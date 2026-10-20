"""가짜 MCP 도구.

- 규정(regulation-mcp)·상품 규칙(business-mcp): 레포 루트 data/ 의 실제 시연 데이터를 읽는다.
- 코드(code-mcp): 샘플 레포가 아직 없어서 docs/PROJECT.md 10절 정답지 기준 임시 인덱스를 쓴다.

입력 · 출력은 실제 MCP 서버(mcp/README.md, feature/mcp)와 같다. business-mcp는 백엔드 응답 그대로 camelCase.
조회 도구의 메서드 이름과 반환 형태는 MCP 계약을 따른다.
검증은 지원하지 않으며, 쓰기는 외부 호출 없이 가짜 작업 접수 정보만 만든다.
"""

import fnmatch
import re
import uuid
from pathlib import Path

from fastmcp.exceptions import ToolError

from app.data import DATA_DIR, load_business, load_regulation
from app.tools.base import ToolBelt

# TODO(C 샘플 레포): 레포가 올라오면 실제 파일 검색으로 교체
_CODE_INDEX: dict[str, list[dict]] = {
    "DSR_LIMIT": [
        {
            "file": "config/policy.yaml",
            "line": 3,
            "symbol": "DSR_LIMIT",
            "snippet": "DSR_LIMIT: 0.40",
            "kind": "config",
        },
        # 중간: 한도 배치의 하드코딩
        {
            "file": "src/batch/limit_job.py",
            "line": 12,
            "symbol": "recalc_limits",
            "snippet": "if dsr > 0.4:",
            "kind": "code",
        },
        # 중간: 화면 문구
        {
            "file": "frontend/src/views/LoanApply.vue",
            "line": 48,
            "symbol": "dsr_notice",
            "snippet": "DSR 40% 이하만 신청 가능합니다",
            "kind": "ui",
        },
        {
            "file": "src/loan/ltv.py",
            "line": 5,
            "symbol": "LTV_LIMIT",
            "snippet": "LTV_LIMIT = 0.40",
            "kind": "code",
        },  # 함정: 같은 값, 다른 의미
    ],
    "SENIOR_AGE": [
        {
            "file": "config/policy.yaml",
            "line": 7,
            "symbol": "SENIOR_AGE",
            "snippet": "SENIOR_AGE: 65",
            "kind": "config",
        },
        # 쉬움
        {
            "file": "src/loan/eligibility.py",
            "line": 21,
            "symbol": "is_senior",
            "snippet": "return age >= 65",
            "kind": "code",
        },
        # 어려움: 단위가 다름
        {
            "file": "src/loan/eligibility.py",
            "line": 8,
            "symbol": "SENIOR_AGE_MONTHS",
            "snippet": "SENIOR_AGE_MONTHS = 780",
            "kind": "code",
        },
        # 중간: 표현이 다름
        {
            "file": "src/loan/rate.py",
            "line": 34,
            "symbol": "senior_discount",
            "snippet": "if age > 64:",
            "kind": "code",
        },
        {
            "file": "src/loan/income.py",
            "line": 3,
            "symbol": "RETIREMENT_AGE",
            "snippet": "RETIREMENT_AGE = 65",
            "kind": "code",
        },  # 함정: 소득 추정용
    ],
}


_SQL_TYPE = {
    str: "VARCHAR",
    int: "BIGINT",
    float: "NUMERIC",
    bool: "BOOLEAN",
    list: "VARCHAR",
}


def _camel(row: dict) -> dict:
    return {re.sub(r"_(\w)", lambda m: m[1].upper(), k): v for k, v in row.items()}


class MockTools:
    is_mock = True

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self._jobs: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def subset(self, *names: str) -> ToolBelt:
        return ToolBelt(self, frozenset(names))

    def describe(self, *names):
        import inspect
        from pydantic import create_model

        definitions = []
        for name in names:
            function = getattr(self, name)
            fields = {
                p.name: (
                    p.annotation
                    if p.annotation is not inspect.Parameter.empty
                    else str,
                    p.default if p.default is not inspect.Parameter.empty else ...,
                )
                for p in inspect.signature(function).parameters.values()
            }
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": inspect.getdoc(function) or name,
                        "parameters": create_model(
                            f"Args_{name}", **fields
                        ).model_json_schema(),
                    },
                }
            )
        return definitions

    def close(self):
        pass

    def _log(self, name: str, **kwargs) -> None:
        self.calls.append((name, kwargs))

    def called(self, name: str) -> list[dict]:
        return [kw for n, kw in self.calls if n == name]

    # ---------- 규정 (regulation-mcp) ----------
    def diff_versions(
        self, regulation_id: str, old_version: str, new_version: str
    ) -> dict:
        """원문 기준 결정적 diff. 바뀐 조항만 돌려준다 (자구 수정 포함 — 실질 여부 판단은 Agent 몫)."""
        self._log(
            "diff_versions",
            regulation_id=regulation_id,
            old_version=old_version,
            new_version=new_version,
        )
        old = load_regulation(regulation_id, old_version, self.data_dir)
        new = load_regulation(regulation_id, new_version, self.data_dir)
        changes = []
        for aid in dict.fromkeys([*old["articles"], *new["articles"]]):
            o, n = old["articles"].get(aid), new["articles"].get(aid)
            if o and n and o == n:
                continue
            changes.append(
                {
                    "article_id": aid,
                    "title": (n or o)["title"],
                    "change": "added"
                    if o is None
                    else "removed"
                    if n is None
                    else "modified",
                    "old_text": o["text"] if o else None,
                    "new_text": n["text"] if n else None,
                    "old_uri": f"reg://{regulation_id}/{old_version}/{aid}"
                    if o
                    else None,
                    "new_uri": f"reg://{regulation_id}/{new_version}/{aid}"
                    if n
                    else None,
                }
            )
        return {
            "regulation_id": regulation_id,
            "old_version": old_version,
            "new_version": new_version,
            "effective_from": new["meta"].get("effective_from"),
            "changes": changes,
        }

    def search_regulation(
        self, query: str, regulation_id: str = "credit-loan-ops", version: str = "v4"
    ) -> list[dict]:
        """공백으로 나눈 단어가 모두 제목이나 본문에 있는 조항."""
        self._log("search_regulation", query=query)
        terms = query.split()
        reg = load_regulation(regulation_id, version, self.data_dir)
        return [
            {"uri": f"reg://{regulation_id}/{version}/{aid}", "article_id": aid, **a}
            for aid, a in reg["articles"].items()
            if terms and all(t in a["title"] or t in a["text"] for t in terms)
        ]

    def get_article(self, regulation_id: str, version: str, article_id: str) -> dict:
        self._log(
            "get_article",
            regulation_id=regulation_id,
            version=version,
            article_id=article_id,
        )
        a = load_regulation(regulation_id, version, self.data_dir)["articles"][
            article_id
        ]
        return {
            "uri": f"reg://{regulation_id}/{version}/{article_id}",
            "article_id": article_id,
            **a,
        }

    def list_articles(
        self, regulation_id: str = "credit-loan-ops", version: str = "v4"
    ) -> list[dict]:
        self._log("list_articles", regulation_id=regulation_id, version=version)
        reg = load_regulation(regulation_id, version, self.data_dir)
        return [
            {
                "uri": f"reg://{regulation_id}/{version}/{aid}",
                "article_id": aid,
                "title": a["title"],
            }
            for aid, a in reg["articles"].items()
        ]

    def read_resource(self, uri: str) -> str:
        """MCP Resource reg://{regulation_id}/{version}[/{article_id}] (실제는 client.read_resource)"""
        self._log("read_resource", uri=uri)
        regulation_id, version, *rest = uri.removeprefix("reg://").split("/")
        reg = load_regulation(regulation_id, version, self.data_dir)
        if rest:
            return reg["articles"][rest[0]]["text"]
        return reg["meta"]["title"]

    # ---------- 코드 (code-mcp) ----------
    def search_code(
        self,
        query: str,
        regex: bool = False,
        path_glob: str = "**/*",
        max_results: int = 200,
    ) -> list[dict]:
        """로컬 샘플의 정책 키·symbol·snippet을 문자열/정규식으로 검색한다. 실제 저장소 검색은 아니다."""
        self._log("search_code", query=query, regex=regex, path_glob=path_glob)
        hits = []
        try:
            pattern = re.compile(query) if regex else None
        except re.error as exc:
            raise ToolError(f"정규식 검색 조건을 수정하세요: {exc}") from exc
        for key, entries in _CODE_INDEX.items():
            for e in entries:
                text = f"{key} {e['symbol']} {e['snippet']}"
                matched = (
                    bool(pattern.search(text))
                    if pattern
                    else query.casefold() in text.casefold()
                )
                if matched and fnmatch.fnmatch(e["file"], path_glob):
                    hits.append(dict(e))
        return hits[:max_results]

    def get_file(self, path: str) -> str:
        self._log("get_file", path=path)
        lines = [
            e["snippet"] for es in _CODE_INDEX.values() for e in es if e["file"] == path
        ]
        return "\n".join(lines)

    def find_usages(self, symbol: str) -> list[dict]:
        self._log("find_usages", symbol=symbol)
        return [
            dict(e) for es in _CODE_INDEX.values() for e in es if e["symbol"] == symbol
        ]

    # ---------- 업무 (business-mcp → Spring /internal/**, camelCase) ----------
    def get_products(self) -> list[dict]:
        self._log("get_products")
        return [_camel(p) for p in load_business("products", self.data_dir)]

    def get_product_rules(
        self, rule_key: str | None = None, product_id: str | None = None
    ) -> list[dict]:
        """[{ruleId, productId, ruleKey, value, unit, effectiveFrom, effectiveTo}] — 상품명은 get_products"""
        self._log("get_product_rules", rule_key=rule_key, product_id=product_id)
        return [
            _camel(r)
            for r in load_business("product_rules", self.data_dir)
            if (rule_key is None or r["rule_key"] == rule_key)
            and (product_id is None or r["product_id"] == product_id)
        ]

    def get_db_schema(self) -> list[dict]:
        """[{table, columns: [{name, type, nullable}]}]"""
        self._log("get_db_schema")
        schema = []
        for table in ("products", "product_rules", "loan_contracts"):
            rows = load_business(table, self.data_dir)
            columns = {}
            for row in rows:
                for k, v in row.items():
                    col = columns.setdefault(
                        k, {"name": k, "type": None, "nullable": False}
                    )
                    if v is None:
                        col["nullable"] = True
                    elif col["type"] is None:
                        col["type"] = _SQL_TYPE.get(type(v), "VARCHAR")
            schema.append(
                {
                    "table": table,
                    "columns": [
                        {**c, "type": c["type"] or "VARCHAR"} for c in columns.values()
                    ],
                }
            )
        return schema

    # ---------- 검증 (code-mcp 샌드박스) ----------
    def check_patch(
        self, patches: list[dict], test_cases: list[dict] | None = None
    ) -> dict:
        raise RuntimeError("MockTools는 실제 검증을 수행하지 않습니다")

    # ---------- 쓰기 (코드 노드 publish 전용, 백엔드가 approval_id 재검증) ----------
    def _enqueue(self, approval_id: int | None, idempotency_key: str, **extra) -> dict:
        if not approval_id:
            raise ToolError("백엔드 403 FORBIDDEN: taskId 와 approvalId 가 필요합니다")
        if idempotency_key in self._jobs:
            return {**self._jobs[idempotency_key], "duplicate": True}
        self._jobs[idempotency_key] = {
            "jobId": str(uuid.uuid4()),
            "status": "QUEUED",
            "duplicate": False,
            **extra,
        }
        return self._jobs[idempotency_key]

    def create_draft_pr(
        self,
        task_id: str,
        approval_id: int,
        idempotency_key: str,
        title: str,
        patches: list[dict],
        spec_keys: list[str] | None = None,
    ) -> dict:
        """→ {jobId, status, duplicate, branch, commit}. PR 링크는 GET /internal/jobs/{jobId}"""
        self._log(
            "create_draft_pr",
            task_id=task_id,
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            title=title,
            patches=patches,
            spec_keys=spec_keys or [],
        )
        if not patches:
            raise ToolError("patches가 비어 있습니다")
        branch = "rule-ripple/" + (re.sub(r"[^A-Za-z0-9-]", "", task_id)[:8] or "task")
        return self._enqueue(
            approval_id, idempotency_key, branch=branch, commit=uuid.uuid4().hex
        )

    def create_work_ticket(
        self,
        task_id: str,
        approval_id: int,
        idempotency_key: str,
        title: str,
        description: str | None = None,
        type: str = "CODE",
        target_ref: str | None = None,
        spec_keys: list[str] | None = None,
        assignee: str | None = None,
    ) -> dict:
        """→ {jobId, status, duplicate}"""
        self._log(
            "create_work_ticket",
            task_id=task_id,
            approval_id=approval_id,
            idempotency_key=idempotency_key,
            title=title,
            description=description,
            type=type,
            target_ref=target_ref,
            spec_keys=spec_keys or [],
            assignee=assignee,
        )
        return self._enqueue(approval_id, idempotency_key)
