"""실제 MCP 서버 3개(regulation · code · business)에 붙는 도구. MockTools와 메서드 이름 · 반환 형태가 같다.

주소는 docker-compose의 agent 환경 변수 (REGULATION_MCP_URL · CODE_MCP_URL · BUSINESS_MCP_URL).
그래프 노드는 동기 함수라서, 전용 이벤트 루프 스레드에서 fastmcp Client를 돌리고 결과만 기다린다.
도구가 실패하면 fastmcp.exceptions.ToolError(이유 한 줄)가 그대로 올라온다.
"""

import asyncio
import os
import threading
from typing import Any

from fastmcp import Client

from app.tools.base import ToolBelt

DEFAULT_URLS = {
    "regulation": os.getenv("REGULATION_MCP_URL", "http://localhost:8001/mcp"),
    "code": os.getenv("CODE_MCP_URL", "http://localhost:8002/mcp"),
    "business": os.getenv("BUSINESS_MCP_URL", "http://localhost:8003/mcp"),
}

# 도구 → 서버 (mcp/README.md)
TOOL_SERVER = {
    "diff_versions": "regulation",
    "search_regulation": "regulation",
    "get_article": "regulation",
    "list_articles": "regulation",
    "search_code": "code",
    "get_file": "code",
    "find_usages": "code",
    "check_patch": "code",
    "create_draft_pr": "code",
    "get_products": "business",
    "get_product_rules": "business",
    "get_db_schema": "business",
    "get_contract_impact": "business",
    "create_work_ticket": "business",
}


class McpTools:
    is_mock = False

    def __init__(self, urls: dict[str, str] | None = None, timeout: float = 120):
        """urls: {"regulation" | "code" | "business": "http://…/mcp"} (빠진 것은 환경 변수 · 기본값)"""
        self.urls = {**DEFAULT_URLS, **(urls or {})}
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

    def describe(self, *names):
        async def discover():
            definitions = []
            for server in sorted(
                {TOOL_SERVER[n] for n in names if n != "read_resource"}
            ):
                async with Client(self.urls[server], timeout=self.timeout) as client:
                    for tool in await client.list_tools():
                        if tool.name in names:
                            definitions.append(
                                {
                                    "type": "function",
                                    "function": {
                                        "name": tool.name,
                                        "description": tool.description or tool.name,
                                        "parameters": tool.inputSchema,
                                    },
                                }
                            )
            return definitions

        definitions = self._run(discover())
        if "read_resource" in names:
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "read_resource",
                        "description": "검색 결과의 reg:// URI로 규정 원문을 읽는다",
                        "parameters": {
                            "type": "object",
                            "properties": {"uri": {"type": "string"}},
                            "required": ["uri"],
                        },
                    },
                }
            )
        found = {d["function"]["name"] for d in definitions}
        if found != set(names):
            raise ValueError(f"MCP 도구가 없습니다: {set(names)-found}")
        return definitions

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
        return self._run(self._call_tool(TOOL_SERVER[name], name, args))

    def read_resource(self, uri: str) -> str:
        """reg://{regulation_id}/{version}[/{article_id}]"""
        self.calls.append(("read_resource", {"uri": uri}))

        async def read() -> str:
            async with Client(self.urls["regulation"], timeout=self.timeout) as c:
                contents = await c.read_resource(uri)
            return "".join(getattr(b, "text", "") for b in contents)

        return self._run(read())

    def __getattr__(self, name: str):
        if name not in TOOL_SERVER:
            raise AttributeError(name)
        return lambda *args, **kwargs: self.call(name, **_bind(name, args, kwargs))


# 위치 인자로 부르는 노드 코드(예: search_regulation(term, regulation_id, version))를 키워드 인자로 바꾼다
_PARAMS = {
    "diff_versions": ("regulation_id", "old_version", "new_version"),
    "search_regulation": ("query", "regulation_id", "version"),
    "get_article": ("regulation_id", "version", "article_id"),
    "list_articles": ("regulation_id", "version"),
    "search_code": ("query", "regex", "path_glob", "max_results"),
    "get_file": ("path",),
    "find_usages": ("symbol",),
    "check_patch": ("patches", "test_cases"),
    "create_draft_pr": (
        "task_id",
        "approval_id",
        "idempotency_key",
        "title",
        "patches",
        "spec_keys",
    ),
    "get_products": (),
    "get_product_rules": ("rule_key", "product_id"),
    "get_db_schema": (),
    "get_contract_impact": ("age_from", "age_to", "applied_before"),
    "create_work_ticket": (
        "task_id",
        "approval_id",
        "idempotency_key",
        "title",
        "description",
        "type",
        "target_ref",
        "spec_keys",
        "assignee",
    ),
}


def _bind(name: str, args: tuple, kwargs: dict) -> dict:
    params = _PARAMS[name]
    if len(args) > len(params):
        raise TypeError(f"{name}() 인자가 너무 많습니다: {args}")
    return {**dict(zip(params, args)), **kwargs}
