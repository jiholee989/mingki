"""가짜 MCP 도구.

- 규정(regulation-mcp)·상품 규칙(business-mcp): 레포 루트 data/ 의 실제 시연 데이터를 읽는다.
- 코드(code-mcp): 샘플 레포가 아직 없어서 docs/PROJECT.md 10절 정답지 기준 임시 인덱스를 쓴다.

실제 MCP 클라이언트(mcp_client.py)도 같은 메서드 이름·반환 형태를 따르면 그대로 교체된다.
테스트 시나리오(실패 주입)는 생성자 옵션으로 만든다.
"""

from pathlib import Path
from typing import Any

from app.data import DATA_DIR, load_business, load_regulation

# TODO(C 샘플 레포): 레포가 올라오면 실제 파일 검색으로 교체
_CODE_INDEX: dict[str, list[dict]] = {
    "DSR_LIMIT": [
        {"file": "config/policy.yaml", "line": 3, "symbol": "DSR_LIMIT", "snippet": "DSR_LIMIT: 0.40", "kind": "config"},
        # 중간: 한도 배치의 하드코딩
        {"file": "src/batch/limit_job.py", "line": 12, "symbol": "recalc_limits", "snippet": "if dsr > 0.4:", "kind": "code"},
        # 중간: 화면 문구
        {"file": "frontend/src/views/LoanApply.vue", "line": 48, "symbol": "dsr_notice", "snippet": "DSR 40% 이하만 신청 가능합니다", "kind": "ui"},
        {"file": "src/loan/ltv.py", "line": 5, "symbol": "LTV_LIMIT", "snippet": "LTV_LIMIT = 0.40", "kind": "code"},  # 함정: 같은 값, 다른 의미
    ],
    "SENIOR_AGE": [
        {"file": "config/policy.yaml", "line": 7, "symbol": "SENIOR_AGE", "snippet": "SENIOR_AGE: 65", "kind": "config"},
        # 쉬움
        {"file": "src/loan/eligibility.py", "line": 21, "symbol": "is_senior", "snippet": "return age >= 65", "kind": "code"},
        # 어려움: 단위가 다름
        {"file": "src/loan/eligibility.py", "line": 8, "symbol": "SENIOR_AGE_MONTHS", "snippet": "SENIOR_AGE_MONTHS = 780", "kind": "code"},
        # 중간: 표현이 다름
        {"file": "src/loan/rate.py", "line": 34, "symbol": "senior_discount", "snippet": "if age > 64:", "kind": "code"},
        {"file": "src/loan/income.py", "line": 3, "symbol": "RETIREMENT_AGE", "snippet": "RETIREMENT_AGE = 65", "kind": "code"},  # 함정: 소득 추정용
    ],
}

WRITE_TOOLS = frozenset({"create_draft_pr", "create_work_ticket"})


class ToolBelt:
    """허용된 도구만 노출하는 래퍼 (노드별 최소 권한)."""

    def __init__(self, source: Any, names: frozenset[str]):
        self._source = source
        self.names = names

    def __getattr__(self, name: str):
        if name not in self.names:
            raise PermissionError(f"tool '{name}' is not bound to this node")
        return getattr(self._source, name)


class MockTools:
    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        hidden_on_first_search: set[str] | None = None,
        patch_failures: dict[str, int] | None = None,
    ):
        """
        data_dir: 규정·업무 데이터 폴더 (기본: 레포 루트 data/)
        hidden_on_first_search: 첫 search_code에서 빠뜨릴 symbol (시스템 테스트 실패 → locate 재실행 시나리오)
        patch_failures: {file: n} 해당 파일 묶음을 처음 n번 check_patch에서 실패시킴
        """
        self.data_dir = Path(data_dir)
        self._hidden = set(hidden_on_first_search or ())
        self._searched: set[str] = set()
        self._patch_failures = dict(patch_failures or {})
        self.calls: list[tuple[str, dict]] = []

    def subset(self, *names: str) -> ToolBelt:
        return ToolBelt(self, frozenset(names))

    def _log(self, name: str, **kwargs) -> None:
        self.calls.append((name, kwargs))

    def called(self, name: str) -> list[dict]:
        return [kw for n, kw in self.calls if n == name]

    # ---------- 규정 (regulation-mcp) ----------
    def diff_versions(self, regulation_id: str, old_version: str, new_version: str) -> dict:
        """원문 기준 결정적 diff. 바뀐 조항만 돌려준다 (자구 수정 포함 — 실질 여부 판단은 Agent 몫)."""
        self._log("diff_versions", regulation_id=regulation_id, old_version=old_version, new_version=new_version)
        old = load_regulation(regulation_id, old_version, self.data_dir)
        new = load_regulation(regulation_id, new_version, self.data_dir)
        changes = []
        for aid in dict.fromkeys([*old["articles"], *new["articles"]]):
            o, n = old["articles"].get(aid), new["articles"].get(aid)
            if o and n and o["text"] == n["text"]:
                continue
            changes.append({
                "article_id": aid,
                "title": (n or o)["title"],
                "change": "added" if o is None else "removed" if n is None else "modified",
                "old_text": o["text"] if o else None,
                "new_text": n["text"] if n else None,
            })
        return {
            "regulation_id": regulation_id,
            "old_version": old_version,
            "new_version": new_version,
            "effective_from": new["meta"].get("effective_from"),
            "changes": changes,
        }

    def search_regulation(self, query: str, regulation_id: str = "credit-loan-ops", version: str = "v4") -> list[dict]:
        self._log("search_regulation", query=query)
        reg = load_regulation(regulation_id, version, self.data_dir)
        return [
            {"uri": f"reg://{regulation_id}/{version}/{aid}", "article_id": aid, **a}
            for aid, a in reg["articles"].items()
            if query in a["title"] or query in a["text"]
        ]

    def read_resource(self, uri: str) -> str:
        """reg://{regulation_id}/{version}[/{article_id}]"""
        self._log("read_resource", uri=uri)
        regulation_id, version, *rest = uri.removeprefix("reg://").split("/")
        reg = load_regulation(regulation_id, version, self.data_dir)
        if rest:
            return reg["articles"][rest[0]]["text"]
        return reg["meta"]["title"]

    # ---------- 코드 (code-mcp) ----------
    def search_code(self, query: str) -> list[dict]:
        self._log("search_code", query=query)
        hits = []
        for key, entries in _CODE_INDEX.items():
            for e in entries:
                if query in (key, e["symbol"]):
                    hits.append(dict(e))
        first_time = query not in self._searched
        self._searched.add(query)
        if first_time:
            hits = [h for h in hits if h["symbol"] not in self._hidden]
        return hits

    def get_file(self, path: str) -> str:
        self._log("get_file", path=path)
        lines = [e["snippet"] for es in _CODE_INDEX.values() for e in es if e["file"] == path]
        return "\n".join(lines)

    def find_usages(self, symbol: str) -> list[dict]:
        self._log("find_usages", symbol=symbol)
        return [dict(e) for es in _CODE_INDEX.values() for e in es if e["symbol"] == symbol]

    # ---------- 업무 (business-mcp → Spring /internal/**) ----------
    def get_db_schema(self, table: str | None = None) -> dict:
        self._log("get_db_schema", table=table)
        schema = {
            name: sorted({k for row in load_business(name, self.data_dir) for k in row})
            for name in ("products", "product_rules", "loan_contracts")
        }
        return schema if table is None else {table: schema.get(table, [])}

    def get_product_rules(self, rule_key: str | None = None, product_id: str | None = None) -> list[dict]:
        """규칙 행 + 상품명·설명. (상품 정보를 같이 줄지는 business-mcp(B)와 확정 필요)"""
        self._log("get_product_rules", rule_key=rule_key, product_id=product_id)
        products = {p["product_id"]: p for p in load_business("products", self.data_dir)}
        return [
            {**r, "product_name": products[r["product_id"]]["name"],
             "product_description": products[r["product_id"]]["description"]}
            for r in load_business("product_rules", self.data_dir)
            if (rule_key is None or r["rule_key"] == rule_key) and (product_id is None or r["product_id"] == product_id)
        ]

    # ---------- 검증 (code-mcp 샌드박스) ----------
    def check_patch(self, patches: list[dict], test_cases: list[dict]) -> dict:
        """샌드박스에 패치 적용 → 문법 → 테스트. 묶음별 결과 + 시스템 테스트 결과."""
        self._log("check_patch", patches=patches, test_cases=test_cases)
        results = []
        for p in patches:
            file = p["files"][0]
            if self._patch_failures.get(file, 0) > 0:
                self._patch_failures[file] -= 1
                results.append({"bundle_id": p["bundle_id"], "ok": False, "errors": [f"{file}: 경계값 테스트 실패"]})
            else:
                results.append({"bundle_id": p["bundle_id"], "ok": True, "errors": []})

        covered = {loc for p in patches for loc in p["locations"]}
        missed = [
            f"{e['file']}:{e['line']}:{e['symbol']}"
            for es in _CODE_INDEX.values()
            for e in es
            if e["symbol"] in self._hidden and f"{e['file']}:{e['line']}" not in covered
        ]
        return {"results": results, "system": {"ok": not missed, "missed_locations": missed}}

    # ---------- 쓰기 (코드 노드 publish 전용) ----------
    def create_draft_pr(self, title: str, patches: list[dict], approval_id: str, idempotency_key: str) -> dict:
        self._log("create_draft_pr", title=title, patches=patches, approval_id=approval_id, idempotency_key=idempotency_key)
        return {"url": "https://git.example.com/loan-core/pull/101"}

    def create_work_ticket(self, title: str, body: str, approval_id: str, idempotency_key: str) -> dict:
        self._log("create_work_ticket", title=title, body=body, approval_id=approval_id, idempotency_key=idempotency_key)
        return {"url": "https://jira.example.com/browse/RR-7"}
