"""규정·업무 MCP에서 상품 제안에 필요한 자료만 조회한다.

동기 노드가 전용 이벤트 루프 스레드의 fastmcp Client를 통해 도구를 호출한다.
"""

import asyncio
import logging
import os
import threading
import time
from datetime import date
from typing import Any

from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.tools.base import ToolBelt

logger = logging.getLogger(__name__)

DEFAULT_URLS = {
    "regulation": "http://localhost:8001/mcp",
    "business": "http://localhost:8003/mcp",
}

# 도구 → 서버 (mcp/README.md)
TOOL_SERVER = {
    "list_regulations": "regulation",
    "get_product_doc": "regulation",
    "diff_versions": "regulation",
    "list_articles": "regulation",
    "get_article": "regulation",
    "get_products": "business",
    "get_product_rules": "business",
}


class McpTools:
    is_local = False

    def __init__(self, urls: dict[str, str] | None = None, timeout: float = 120):
        """urls: {"regulation" | "business": "http://…/mcp"} (빠진 것은 환경 변수 · 기본값)"""
        # run.py가 .env를 읽은 뒤 생성하므로 환경변수도 이 시점에 읽는다.
        self.urls = {
            name: os.getenv(f"{name.upper()}_MCP_URL") or default
            for name, default in DEFAULT_URLS.items()
        }
        self.urls.update(urls or {})
        self.timeout = timeout
        self.calls: list[tuple[str, dict]] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="mcp-client"
        )
        self._thread.start()
        self._closed = False

    def subset(self, *names: str) -> ToolBelt:
        return ToolBelt(self, frozenset(names))

    def called(self, name: str) -> list[dict]:
        return [kw for n, kw in self.calls if n == name]

    def _run(self, coro) -> Any:
        if self._closed:
            coro.close()
            raise RuntimeError("MCP 클라이언트가 종료되었습니다")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(self.timeout)
        except TimeoutError:
            future.cancel()
            raise TimeoutError("MCP 요청 제한 시간 초과") from None

    def close(self):
        if not self._closed:

            async def cleanup():
                tasks = [
                    t for t in asyncio.all_tasks() if t is not asyncio.current_task()
                ]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

            self._run(cleanup())
            self._closed = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
            if not self._thread.is_alive():
                self._loop.close()

    async def _call_tool(self, server: str, name: str, args: dict) -> Any:
        async with Client(self.urls[server], timeout=self.timeout) as c:
            res = await c.call_tool(name, args)
        if res.data is not None:
            return res.data
        if res.structured_content is not None:  # 출력 스키마가 없는 도구
            return res.structured_content.get("result", res.structured_content)
        return "".join(getattr(b, "text", "") for b in res.content)

    def call(self, name: str, **kwargs) -> Any:
        args = {k: v for k, v in kwargs.items() if v is not None}
        self.calls.append((name, args))
        server = TOOL_SERVER[name]
        started = time.monotonic()
        logger.info("%s-mcp tool=%s 요청", server, name)
        try:
            result = self._run(self._call_tool(server, name, args))
        except Exception:
            logger.warning("%s-mcp tool=%s 실패", server, name)
            raise
        logger.info("%s-mcp tool=%s 완료 (%.2fs)", server, name, time.monotonic() - started)
        return result

    def check_connection(self):
        """구버전 서버나 잘못된 URL이면 분석을 시작하기 전에 안내한다."""
        async def check():
            for server in self.urls:
                async with Client(self.urls[server], timeout=self.timeout) as client:
                    available = {tool.name for tool in await client.list_tools()}
                required = {name for name, owner in TOOL_SERVER.items() if owner == server}
                missing = required - available
                if missing:
                    raise ValueError(f"{server}-mcp 도구 누락: {', '.join(sorted(missing))}. 최신 main의 MCP 서버를 다시 실행하세요")
        self._run(check())

    def get_regulation_context(self, regulation_id: str, version: str) -> dict:
        catalog = self.list_regulations()
        primary = next((row for row in catalog if row["regulation_id"] == regulation_id), None)
        versions = primary["versions"] if primary else []
        selected = next((v for v in versions if v["version"] == version), None)
        if not selected or not selected.get("effective_from"):
            raise ValueError("조회한 규정 목록에서 분석 버전과 시행일을 확인할 수 없습니다")
        # 분석 대상의 시행일 이후에 개정된 관련 규정은 근거로 사용하지 않는다.
        horizon = date.fromisoformat(selected["effective_from"])
        targets = [(regulation_id, version)]
        gaps = []
        for row in catalog:
            if row["regulation_id"] == regulation_id:
                continue
            candidates = [v for v in row["versions"] if v.get("effective_from")
                          and date.fromisoformat(v["effective_from"]) <= horizon]
            if candidates:
                chosen = max(candidates, key=lambda v: (v["effective_from"], int(v["version"].removeprefix("v"))))
                targets.append((row["regulation_id"], chosen["version"]))
            elif any(not v.get("effective_from") for v in row["versions"]):
                gaps.append(f"{row['regulation_id']}: 시행일이 없어 관련 규정 버전을 선택할 수 없음")
        articles = []
        for rid, selected_version in targets:
            articles.extend({**self.get_article(rid, selected_version, row["article_id"]),
                             "regulation_id": rid, "version": selected_version}
                            for row in self.list_articles(rid, selected_version))
        return {"articles": articles, "data_gaps": gaps}

    def get_product_documents(self, product_ids: list[str]) -> dict:
        documents, gaps = [], []
        for pid in dict.fromkeys(product_ids):
            try:
                doc = self.get_product_doc(pid)
            except ToolError as exc:
                gaps.append(f"{pid}: 상품 문서 조회 실패: {exc}")
                continue
            if doc["product_id"] != pid:
                raise ValueError("MCP 상품 문서의 상품 ID가 요청과 다릅니다")
            sections = [section for section in doc["sections"] if section["text"].strip()]
            if not sections:
                gaps.append(f"{pid}: 상품 문서에 확인 가능한 본문이 없음")
            # 서버가 준 섹션 URI를 유지해 인용·출처 검사가 실제 조회 자료와 일치하게 한다.
            documents.extend({"productId": pid, "uri": section["uri"],
                              "content": f"## {section['section']}\n{section['text']}",
                              "updated_at": doc.get("updated_at")}
                             for section in sections)
        return {"documents": documents, "data_gaps": gaps}

    def __getattr__(self, name: str):
        if name not in TOOL_SERVER:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.call(name, **_bind(name, args, kwargs))


# 노드의 위치 인자를 MCP 요청의 키워드 인자로 바꾼다
_PARAMS = {
    "list_regulations": (),
    "get_product_doc": ("product_id",),
    "diff_versions": ("regulation_id", "old_version", "new_version"),
    "list_articles": ("regulation_id", "version"),
    "get_article": ("regulation_id", "version", "article_id"),
    "get_products": (),
    "get_product_rules": ("rule_key", "product_id", "as_of"),
}


def _bind(name: str, args: tuple, kwargs: dict) -> dict:
    params = _PARAMS[name]
    if len(args) > len(params):
        raise TypeError(f"{name}() 인자가 너무 많습니다: {args}")
    return {**dict(zip(params, args)), **kwargs}
