"""백엔드 대신 가짜 HTTP 응답(MockTransport)을 꽂아서 MCP 도구를 검증한다."""

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from business_mcp import server
from business_mcp.backend import Backend

RULES = [
    {"ruleId": "R010", "productId": "P002", "ruleKey": "ELIGIBLE_MIN_AGE", "value": "65", "unit": "age",
     "effectiveFrom": "2024-01-01", "effectiveTo": None},
    {"ruleId": "R011", "productId": "P002", "ruleKey": "DSR_LIMIT", "value": "0.40", "unit": "ratio",
     "effectiveFrom": "2024-01-01", "effectiveTo": None},
    {"ruleId": "R050", "productId": "P012", "ruleKey": "DSR_LIMIT", "value": "0.45", "unit": "ratio",
     "effectiveFrom": "2020-01-01", "effectiveTo": "2023-12-31"},
    {"ruleId": "R060", "productId": "P007", "ruleKey": "MAX_DSR_RATIO", "value": "40", "unit": "percent",
     "effectiveFrom": "2024-01-01", "effectiveTo": None},
]
# 반영 직후 모습 (BACKEND_API 10.4): 기존 행은 시행일 전날로 닫히고, 새 행은 시행일부터
APPLIED = [
    {"ruleId": "R001", "productId": "P001", "ruleKey": "DSR_LIMIT", "value": "0.40", "unit": "ratio",
     "effectiveFrom": "2024-01-01", "effectiveTo": "2026-11-30"},
    {"ruleId": "R083", "productId": "P001", "ruleKey": "DSR_LIMIT", "value": "0.35", "unit": "ratio",
     "effectiveFrom": "2026-12-01", "effectiveTo": None},
]
CONTRACTS = Path(__file__).resolve().parents[3] / "docs" / "contracts"
PRODUCTS = [
    {"productId": "P001", "name": "리플 직장인 신용대출", "status": "ON_SALE"},
    {"productId": "P012", "name": "리플 직장인 신용대출(구)", "status": "SALE_ENDED"},
]


class FakeSpring:
    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if req.headers.get("X-Internal-Token") != "test-token":
            return httpx.Response(401, json={"error": "UNAUTHORIZED", "message": "internal token"})
        path = req.url.path
        if path == "/internal/product-rules":
            key = req.url.params.get("key")
            return httpx.Response(200, json=[r for r in RULES if key is None or r["ruleKey"] == key])
        if path == "/internal/products":
            return httpx.Response(200, json=PRODUCTS)
        if path in ("/internal/products/P001/rules", "/internal/products/P002/rules"):
            pid = path.split("/")[3]
            return httpx.Response(200, json=[r for r in RULES if r["productId"] == pid])
        if path == "/internal/products/P999/rules":
            return httpx.Response(404, json={"error": "NOT_FOUND", "message": "product not found"})
        if path == "/internal/contracts/impact":
            return httpx.Response(200, json={"ageFrom": int(req.url.params["ageFrom"]), "params": dict(req.url.params)})
        if path == "/internal/work-tickets":
            body = json.loads(req.content)
            if body["approvalId"] != 7:
                return httpx.Response(403, json={"error": "FORBIDDEN", "message": f"존재하지 않는 approvalId: {body['approvalId']}"})
            return httpx.Response(202, json={"jobId": "j-1", "status": "QUEUED", "duplicate": False})
        return httpx.Response(404, json={"error": "NOT_FOUND", "message": "not found"})


@pytest.fixture
def spring(monkeypatch):
    fake = FakeSpring()
    monkeypatch.setattr(server, "backend", Backend("http://spring", "test-token", transport=httpx.MockTransport(fake)))
    return fake


async def call(name, args=None):
    async with Client(server.mcp) as c:
        return (await c.call_tool(name, args or {})).data


async def test_tools_are_registered():
    async with Client(server.mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert names == {"get_products", "get_product_rules", "list_rule_keys", "get_db_schema", "get_contract_impact",
                     "create_work_ticket"}


async def test_sends_internal_token_and_caller(spring):
    await call("get_product_rules")
    assert spring.requests[0].headers["X-Internal-Caller"] == "business-mcp"


async def test_product_rules_pass_backend_response_through(spring):
    rules = await call("get_product_rules", {"rule_key": "DSR_LIMIT"})
    assert rules == [RULES[1], RULES[2]]   # camelCase 그대로, 가공 없음 (종료된 행도 기본으로 포함)
    assert spring.requests[0].url.params["key"] == "DSR_LIMIT"


async def test_product_rules_by_product_filters_key(spring):
    rules = await call("get_product_rules", {"product_id": "P002", "rule_key": "ELIGIBLE_MIN_AGE"})
    assert [r["ruleId"] for r in rules] == ["R010"]


async def test_backend_error_becomes_tool_error(spring):
    with pytest.raises(ToolError, match="404 NOT_FOUND: product not found"):
        await call("get_product_rules", {"product_id": "P999"})


async def test_product_id_cannot_escape_path(spring):
    with pytest.raises(ToolError, match="잘못된 product_id"):
        await call("get_product_rules", {"product_id": "../tasks"})
    assert spring.requests == []


async def test_contract_impact_maps_params_and_omits_none(spring):
    await call("get_contract_impact", {"age_from": 60, "age_to": 64})
    params = spring.requests[0].url.params
    assert params["ageFrom"] == "60" and params["ageTo"] == "64"
    assert "appliedBefore" not in params


async def test_work_ticket_body_matches_backend_contract(spring):
    out = await call("create_work_ticket", {
        "task_id": "t-1", "approval_id": 7, "idempotency_key": "t-1:ticket:S1",
        "title": "고령자 기준 변경", "spec_keys": ["S1"],
    })
    assert out == {"jobId": "j-1", "status": "QUEUED", "duplicate": False}
    body = json.loads(spring.requests[0].content)
    assert body == {
        "taskId": "t-1", "approvalId": 7, "idempotencyKey": "t-1:ticket:S1", "title": "고령자 기준 변경",
        "description": None, "type": "CODE", "targetRef": None, "specKeys": ["S1"], "assignee": None,
    }


async def test_unapproved_ticket_is_rejected_with_backend_reason(spring):
    with pytest.raises(ToolError, match="403 FORBIDDEN: 존재하지 않는 approvalId"):
        await call("create_work_ticket", {"task_id": "t-1", "approval_id": 999, "idempotency_key": "k", "title": "x"})


async def test_backend_down_is_tool_error(monkeypatch):
    def refuse(req):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(server, "backend", Backend("http://spring", "t", transport=httpx.MockTransport(refuse)))
    with pytest.raises(ToolError, match="연결할 수 없습니다"):
        await call("get_products")


async def test_products_filter_by_status(spring):
    assert [p["productId"] for p in await call("get_products", {"status": "ON_SALE"})] == ["P001"]
    assert len(await call("get_products")) == 2


async def test_product_rules_as_of_drops_closed_rows(spring):
    rules = await call("get_product_rules", {"rule_key": "DSR_LIMIT", "as_of": "2026-10-20"})
    assert [r["ruleId"] for r in rules] == ["R011"]
    assert spring.requests[0].url.params["asOf"] == "2026-10-20"   # 계약 10.5


async def test_as_of_after_apply_uses_dates_not_null_end(spring):
    # 리뷰 사례: 반영 직후 R001은 11/30까지 아직 유효, R083은 12/1부터라 아직 시작 전
    RULES.extend(APPLIED)
    try:
        today = await call("get_product_rules", {"product_id": "P001", "as_of": "2026-10-20"})
        effective = await call("get_product_rules", {"product_id": "P001", "as_of": "2026-12-01"})
        last_day = await call("get_product_rules", {"product_id": "P001", "as_of": "2026-11-30"})
    finally:
        del RULES[-len(APPLIED):]
    assert [r["ruleId"] for r in today] == ["R001"]
    assert [r["ruleId"] for r in effective] == ["R083"]
    assert [r["ruleId"] for r in last_day] == ["R001"]   # 종료일 당일까지 유효


async def test_bad_as_of_is_tool_error(spring):
    with pytest.raises(ToolError, match="잘못된 as_of"):
        await call("get_product_rules", {"as_of": "2026/12/01"})


async def test_list_rule_keys_summarizes_keys_units_and_products(spring):
    keys = {k["ruleKey"]: k for k in await call("list_rule_keys", {"as_of": "2026-10-20"})}
    assert keys["DSR_LIMIT"] == {"ruleKey": "DSR_LIMIT", "units": ["ratio"], "productIds": ["P002"],
                                 "activeRows": 1, "closedRows": 1, "upcomingRows": 0}
    # 같은 개념, 다른 키 · 단위도 그대로 드러난다
    assert keys["MAX_DSR_RATIO"]["units"] == ["percent"]
    assert "key" not in spring.requests[0].url.params   # 전체 규칙에서 집계


async def test_list_rule_keys_counts_upcoming_rows_after_apply(spring, monkeypatch):
    monkeypatch.setattr(server, "_today", lambda: date(2026, 10, 20))   # 생략하면 오늘
    RULES.extend(APPLIED)
    try:
        before = {k["ruleKey"]: k for k in await call("list_rule_keys")}["DSR_LIMIT"]
        after = {k["ruleKey"]: k for k in await call("list_rule_keys", {"as_of": "2026-12-01"})}["DSR_LIMIT"]
    finally:
        del RULES[-len(APPLIED):]
    assert (before["activeRows"], before["closedRows"], before["upcomingRows"]) == (2, 1, 1)
    assert before["productIds"] == ["P001", "P002"]
    assert (after["activeRows"], after["closedRows"], after["upcomingRows"]) == (2, 2, 0)


async def test_list_rule_keys_matches_contract_shape(spring):
    # docs/contracts/rule-keys.get.json 의 필드를 모두 낸다 (협업 규칙: 각 영역 테스트가 같은 예시를 읽는다).
    # upcomingRows는 백엔드 92f87d0(계약에 upcomingRows 추가)이 main에 들어오면 계약 파일에도 생긴다.
    contract = json.loads((CONTRACTS / "rule-keys.get.json").read_text(encoding="utf-8"))
    keys = await call("list_rule_keys", {"as_of": "2026-10-20"})
    contract_fields = set().union(*contract)
    assert all(contract_fields <= set(k) for k in keys), contract_fields
    assert all(set(k) <= contract_fields | {"upcomingRows"} for k in keys)
