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
     "effectiveFrom": "2024-01-01", "effectiveTo": None, "basisArticles": ["credit-loan-ops/15"]},
    {"ruleId": "R011", "productId": "P002", "ruleKey": "DSR_LIMIT", "value": "0.40", "unit": "ratio",
     "effectiveFrom": "2024-01-01", "effectiveTo": None, "basisArticles": ["credit-loan-ops/8", "dsr-management/8"]},
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
KEYS = json.loads((CONTRACTS / "rule-keys.get.json").read_text(encoding="utf-8"))
APPLY = json.loads((CONTRACTS / "apply.post.json").read_text(encoding="utf-8"))
JOB = json.loads((CONTRACTS / "apply.job.json").read_text(encoding="utf-8"))
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
            status = req.url.params.get("status")
            return httpx.Response(200, json=[p for p in PRODUCTS if status is None or p["status"] == status])
        if path == "/internal/product-rules/keys":
            return httpx.Response(200, json=KEYS)
        if path == "/internal/product-rules/versions":
            body = json.loads(req.content)
            if body["approvalId"] != 12:
                return httpx.Response(403, json={"error": "FORBIDDEN", "message": "최신 REVIEW 승인이 아닙니다"})
            if body["proposalKey"] == "P003:DSR_LIMIT":
                return httpx.Response(409, json={"error": "CONFLICT", "message": "이미 바뀐 규칙"})
            return httpx.Response(202, json=APPLY["response"])
        if path == f"/internal/jobs/{JOB['id']}":
            return httpx.Response(200, json={**JOB, "payload": {"secret": "내부값"}, "idempotencyKey": "k"})
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
                     "create_work_ticket", "apply_rule_version", "get_job"}


async def test_sends_internal_token_and_caller(spring):
    await call("get_product_rules")
    assert spring.requests[0].headers["X-Internal-Caller"] == "business-mcp"


async def test_product_rules_pass_backend_response_through(spring):
    rules = await call("get_product_rules", {"rule_key": "DSR_LIMIT"})
    assert rules == [RULES[1], RULES[2]]   # camelCase 그대로, 가공 없음 (종료된 행도 기본으로 포함)
    assert rules[0]["basisArticles"] == ["credit-loan-ops/8", "dsr-management/8"]   # 근거 조항도 그대로
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


async def test_list_rule_keys_passes_backend_keys_through(spring):
    # 집계는 Spring 한 곳 (GET /internal/product-rules/keys, 10.5). 응답은 계약 예시 그대로
    assert await call("list_rule_keys", {"as_of": "2026-12-01"}) == KEYS
    assert spring.requests[0].url.params["asOf"] == "2026-12-01"


async def test_list_rule_keys_defaults_to_today(spring, monkeypatch):
    monkeypatch.setattr(server, "_today", lambda: date(2026, 10, 20))
    await call("list_rule_keys")
    assert spring.requests[0].url.params["asOf"] == "2026-10-20"


async def test_products_status_is_sent_to_backend(spring):
    await call("get_products", {"status": "SALE_ENDED"})
    assert spring.requests[0].url.params["status"] == "SALE_ENDED"


# ---------- 반영 · 작업 상태 (10.4) ----------

async def test_apply_request_matches_contract(spring):
    req = APPLY["request"]
    out = await call("apply_rule_version", {
        "task_id": req["taskId"], "approval_id": req["approvalId"], "proposal_key": req["proposalKey"]})
    assert out == APPLY["response"]
    sent = spring.requests[0]
    assert sent.method == "POST" and sent.url.path == "/internal/product-rules/versions"
    assert json.loads(sent.content) == req   # 값(지금 값 · 제안 값)은 보내지 않는다. 기본 멱등키 형식도 계약대로


async def test_apply_keeps_given_idempotency_key(spring):
    req = APPLY["request"]
    await call("apply_rule_version", {"task_id": req["taskId"], "approval_id": 12, "proposal_key": "P002:DSR_LIMIT",
                                      "idempotency_key": "retry-1"})
    assert json.loads(spring.requests[0].content)["idempotencyKey"] == "retry-1"


@pytest.mark.parametrize("args, reason", [
    ({"approval_id": 999}, "403 FORBIDDEN: 최신 REVIEW 승인이 아닙니다"),
    ({"proposal_key": "P003:DSR_LIMIT"}, "409 CONFLICT: 이미 바뀐 규칙"),
])
async def test_apply_rejection_reason_reaches_agent(spring, args, reason):
    base = {"task_id": APPLY["request"]["taskId"], "approval_id": 12, "proposal_key": "P001:DSR_LIMIT"}
    with pytest.raises(ToolError, match=reason):
        await call("apply_rule_version", {**base, **args})


@pytest.mark.parametrize("args, reason", [
    ({"task_id": "../tasks"}, "잘못된 task_id"),
    ({"task_id": ""}, "잘못된 task_id"),
    ({"proposal_key": "  "}, "proposal_key가 비어"),
])
async def test_apply_bad_input_never_reaches_backend(spring, args, reason):
    base = {"task_id": APPLY["request"]["taskId"], "approval_id": 12, "proposal_key": "P001:DSR_LIMIT"}
    with pytest.raises(ToolError, match=reason):
        await call("apply_rule_version", {**base, **args})
    assert spring.requests == []


async def test_get_job_returns_status_result_and_error_only(spring):
    job = await call("get_job", {"job_id": JOB["id"]})
    assert job == {"jobId": JOB["id"], "type": "APPLY_RULE_VERSION", "status": "DONE", "attempts": 1,
                   "result": JOB["result"], "lastError": None}   # payload · 멱등키 같은 내부 값은 빼고


@pytest.mark.parametrize("job_id", ["../tasks", "", "4f1c2b8e"])
async def test_get_job_bad_id_never_reaches_backend(spring, job_id):
    with pytest.raises(ToolError, match="잘못된 job_id"):
        await call("get_job", {"job_id": job_id})
    assert spring.requests == []


async def test_get_job_unknown_is_tool_error(spring):
    with pytest.raises(ToolError, match="404"):
        await call("get_job", {"job_id": "00000000-0000-4000-8000-000000000000"})


@pytest.mark.parametrize("response, reason", [
    (httpx.Response(200, text="<html>"), "JSON이 아닙니다"),
    (httpx.Response(200, json=[JOB]), "작업 응답 형식 오류"),
    (httpx.Response(200, json={"id": JOB["id"]}), "작업 응답 형식 오류"),   # status 없음
    (httpx.Response(500, text="boom"), "500"),
])
async def test_unexpected_job_response_is_tool_error(monkeypatch, response, reason):
    _respond(monkeypatch, response)
    with pytest.raises(ToolError, match=reason):
        await call("get_job", {"job_id": JOB["id"]})


async def test_dead_job_shows_last_error(monkeypatch):
    dead = {**JOB, "status": "DEAD", "result": None, "lastError": "이미 바뀐 규칙"}
    _respond(monkeypatch, httpx.Response(200, json=dead))
    job = await call("get_job", {"job_id": JOB["id"]})
    assert (job["status"], job["lastError"], job["result"]) == ("DEAD", "이미 바뀐 규칙", None)


@pytest.mark.parametrize("args, reason", [
    ({"product_id": ""}, "잘못된 product_id"),     # 빈 값이 전체 조회로 새지 않는다
    ({"rule_key": ""}, "rule_key가 비어"),
    ({"as_of": ""}, "잘못된 as_of"),
    ({"as_of": "2026-02-30"}, "잘못된 as_of"),     # 없는 날짜
])
async def test_rule_inputs_are_rejected(spring, args, reason):
    with pytest.raises(ToolError, match=reason):
        await call("get_product_rules", args)
    assert spring.requests == []


def _respond(monkeypatch, response):
    monkeypatch.setattr(server, "backend", Backend("http://spring", "t", transport=httpx.MockTransport(lambda req: response)))


@pytest.mark.parametrize("rule, field", [
    ({**RULES[1], "effectiveFrom": None}, "effectiveFrom"),
    ({**RULES[1], "effectiveTo": "31/12/2026"}, "effectiveTo"),
    ({**RULES[1], "unit": None}, "unit"),
    ({k: v for k, v in RULES[1].items() if k != "ruleKey"}, "ruleKey"),
])
@pytest.mark.parametrize("tool", ["get_product_rules"])
async def test_malformed_rule_from_backend_names_row_and_field(monkeypatch, rule, field, tool):
    _respond(monkeypatch, httpx.Response(200, json=[RULES[0], rule]))
    with pytest.raises(ToolError, match=f"R011의 {field}"):
        await call(tool, {"as_of": "2026-10-20"})


@pytest.mark.parametrize("response, reason", [
    (httpx.Response(200, text="<html>"), "JSON이 아닙니다"),
    (httpx.Response(200, json={"error": "x"}), "목록 형식이 아닙니다"),
    (httpx.Response(500, text="<h1>boom</h1>"), "500"),
])
@pytest.mark.parametrize("tool", ["get_products", "get_product_rules", "list_rule_keys"])
async def test_unexpected_backend_response_is_tool_error(monkeypatch, response, reason, tool):
    _respond(monkeypatch, response)
    with pytest.raises(ToolError, match=reason):
        await call(tool)


async def test_backend_timeout_is_tool_error(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(server, "backend", Backend("http://spring", "t", transport=httpx.MockTransport(slow)))
    with pytest.raises(ToolError, match="연결할 수 없습니다"):
        await call("list_rule_keys")


async def test_malformed_keys_from_backend_is_tool_error(monkeypatch):
    _respond(monkeypatch, httpx.Response(200, json=[{"units": ["ratio"]}]))
    with pytest.raises(ToolError, match="ruleKey가 없는 항목"):
        await call("list_rule_keys")


async def test_empty_rules_give_empty_keys(monkeypatch):
    _respond(monkeypatch, httpx.Response(200, json=[]))
    assert await call("list_rule_keys") == []


@pytest.mark.parametrize("tool, args", [
    ("get_products", {"status": "DELETED"}),
    ("get_contract_impact", {"age_from": "육십"}),
    ("get_products", {"unknown": 1}),
])
async def test_bad_arguments_are_rejected_by_schema(spring, tool, args):
    async with Client(server.mcp) as c:
        r = await c.call_tool(tool, args, raise_on_error=False)
    assert r.is_error
    assert spring.requests == []
