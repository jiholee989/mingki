"""Spring 어댑터: 콜백 순서 · 제안 펼치기 · 확인 번역 · 종료 상태 · 인증. 실제 Spring · LLM 없이 확인한다."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.bridge import flatten, proposal_keys, review_decision
from app.data import DATA_DIR
from app.graph import build_graph
from app.runner import AgentRunner
from app.server import create_app
from app.spring import SpringClient
from tests.test_graph import DsrReasoner, ThreeProductTools

TOKEN = "test-token"
CALLBACK = "http://backend:8080/internal/tasks/T1"
HEADERS = {"X-Internal-Token": TOKEN}
CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def sha(version):
    return hashlib.sha256((DATA_DIR / "regulations" / "credit-loan-ops" / f"{version}.md").read_bytes()).hexdigest()


class FakeSpring:
    """SpringClient 대역. 받은 콜백을 순서대로 기록한다."""

    def __init__(self, docs=None):
        self.calls = []
        self.docs = docs or [{"side": "OLD", "versionLabel": "v3", "sha256": sha("v3")},
                             {"side": "NEW", "versionLabel": "v4", "sha256": sha("v4")}]

    def documents(self):
        return self.docs

    def event(self, type_, payload=None):
        self.calls.append(("event", type_, payload or {}))

    def put(self, path, body):
        self.calls.append(("put", path, body))

    def post(self, path, body):
        self.calls.append(("post", path, body))

    def close(self):
        pass

    def kinds(self):
        out = []
        for kind, name, body in self.calls:
            if kind == "event" and name == "STEP":
                out.append(f"STEP:{body['node']}")
            elif kind == "event":
                out.append(f"{name}:{body.get('step') or body.get('outcome') or ''}")
            else:
                out.append(f"{kind.upper()} {name}")
        return out

    def puts(self, path):
        return [b for k, n, b in self.calls if k == "put" and n == path]


def in_order(kinds, expected):
    it = iter(kinds)
    return all(any(k == e for k in it) for e in expected)


def client(runner, spring):
    app = create_app(runner, submit=lambda fn, *args: fn(*args), spring_factory=lambda url: spring, token=TOKEN)
    return TestClient(app)


def runner():
    return AgentRunner(build_graph(ThreeProductTools(), DsrReasoner()))


def run_body():
    return {"taskId": "T1", "threadId": "T1", "title": "개인신용대출 운영기준 v3 → v4",
            "documents": [{"side": "OLD", "versionLabel": "v3", "filename": "v3.md", "sha256": sha("v3")},
                          {"side": "NEW", "versionLabel": "v4", "filename": "v4.md", "sha256": sha("v4")}],
            "callbackBaseUrl": CALLBACK}


def resume_body(decision, approved=(), excluded=(), comment=None):
    return {"taskId": "T1", "threadId": "T1", "step": "REVIEW", "decision": decision, "approvalId": 7,
            "comment": comment, "callbackBaseUrl": CALLBACK,
            "payload": {"approvedProposalKeys": list(approved), "excludedProposalKeys": list(excluded)}}


def started(spring=None):
    spring = spring or FakeSpring()
    r = runner()
    api = client(r, spring)
    assert api.post("/run", json=run_body(), headers=HEADERS).status_code == 202
    return api, spring


# ---------- 콜백 순서 · 제안 펼치기 ----------

def test_run_reports_each_node_and_waits_for_review():
    api, spring = started()
    kinds = spring.kinds()
    assert in_order(kinds, ["STEP:requirement_agent", "PUT requirements", "STEP:product_impact_agent",
                            "STEP:proposal_agent", "PUT proposals", "STEP:verify", "PUT proposals",
                            "APPROVAL_REQUIRED:REVIEW"])
    verify = next(b for k, n, b in spring.calls if k == "event" and b.get("node") == "verify")
    assert verify["round"] == 1
    reqs = spring.puts("requirements")[0]["items"]
    assert [r["reqKey"] for r in reqs] == ["REQ-8"]


def test_proposals_are_one_row_per_product_rule_including_keep():
    api, spring = started()
    rows = {r["proposalKey"]: r for r in spring.puts("proposals")[-1]["items"]}
    assert set(rows) == {"P001:DSR_LIMIT", "P002:DSR_LIMIT", "P003:REQ-8"}
    p001 = rows["P001:DSR_LIMIT"]
    assert (p001["impact"], p001["ruleId"], p001["unit"], p001["currentValue"], p001["proposedValue"]) == \
        ("change_required", "R001", "ratio", "0.40", "0.35")
    assert p001["effectiveDate"] == "2026-12-01" and p001["round"] == 1 and p001["verifyStatus"] == "PASSED"
    assert p001["followUp"] and p001["reason"]
    keep = rows["P003:REQ-8"]
    assert (keep["impact"], keep["ruleId"], keep["verifyStatus"]) == ("keep", "R015", "PASSED")
    # 제안 작성 직후(검사 전)는 PENDING
    assert spring.puts("proposals")[0]["items"][0]["verifyStatus"] == "PENDING"


# docs/BACKEND_API.md 10.2 · docs/contracts/proposals.put.json 의 필드. 바뀌면 백엔드 ProposalsTest 와 같이 고친다.
CONTRACT_FIELDS = {"proposalKey", "reqKey", "productId", "ruleId", "ruleKey", "impact", "current", "proposed", "unit",
                   "currentValue", "proposedValue", "effectiveDate", "basis", "reason", "transition", "followUp",
                   "round", "verifyStatus", "verifyLog"}


def test_rows_match_contract_field_set():
    api, spring = started()
    for row in spring.puts("proposals")[-1]["items"]:
        assert set(row) == CONTRACT_FIELDS, row["proposalKey"]
    if (CONTRACTS / "proposals.put.json").exists():
        assert set(json.loads((CONTRACTS / "proposals.put.json").read_text())["items"][0]) == CONTRACT_FIELDS


# ---------- 확인 (10.3) ----------

def test_approve_with_exclusion_finishes_and_reports_done():
    api, spring = started()
    spring.calls.clear()
    res = api.post("/resume", json=resume_body("APPROVE", approved=["P001:DSR_LIMIT"], excluded=["P002:DSR_LIMIT"]),
                   headers=HEADERS)
    assert res.status_code == 202
    assert spring.kinds()[-2:] == ["PUT report", "DONE:DONE"]
    report = spring.puts("report")[0]
    assert report["status"] == "PARTIALLY_APPROVED"
    assert {p["product_id"]: p["status"] for p in report["proposals"]} == {"P001": "approved", "P002": "rejected"}
    assert report["markdown"].startswith("# Rule Ripple")


def test_reject_ends_rejected():
    api, spring = started()
    spring.calls.clear()
    api.post("/resume", json=resume_body("REJECT", comment="보류"), headers=HEADERS)
    assert spring.kinds()[-1] == "DONE:REJECTED"


def test_review_translation_maps_backend_keys_to_agent_decisions():
    r = runner()
    r.start("T1", "credit-loan-ops")
    proposals = r.current_proposals("T1")
    assert [proposal_keys(p) for p in proposals] == [["P001:DSR_LIMIT"], ["P002:DSR_LIMIT"]]
    cmd = review_decision(proposals, "APPROVE", {"approvedProposalKeys": ["P002:DSR_LIMIT"]}, "ok")
    assert cmd["finish"] is True
    assert [(d["proposal_id"], d["action"], d["version"]) for d in cmd["decisions"]] == \
        [("REQ-8:P001", "reject", 1), ("REQ-8:P002", "approve", 1)]
    with pytest.raises(ValueError):
        review_decision(proposals, "REQUEST_CHANGES", {})


def test_resume_rejects_other_steps_and_bad_decisions():
    api, spring = started()
    body = resume_body("APPROVE")
    assert api.post("/resume", json={**body, "step": "REQUIREMENTS"}, headers=HEADERS).status_code == 400
    assert api.post("/resume", json={**body, "decision": "REQUEST_CHANGES"}, headers=HEADERS).status_code == 400


# ---------- 종료 · 실패 · 인증 ----------

def test_no_requirements_ends_no_change_without_review():
    class NoChange(DsrReasoner):
        def requirements(self, diff):
            return []

    spring = FakeSpring()
    client(AgentRunner(build_graph(ThreeProductTools(), NoChange())), spring).post("/run", json=run_body(), headers=HEADERS)
    assert spring.kinds()[-1] == "DONE:NO_CHANGE"
    assert not any(k.startswith("APPROVAL_REQUIRED") for k in spring.kinds())


def test_document_mismatch_is_reported_as_failure():
    spring = FakeSpring(docs=[{"side": "NEW", "versionLabel": "v4", "sha256": "0" * 64}])
    client(runner(), spring).post("/run", json=run_body(), headers=HEADERS)
    kind, name, body = spring.calls[-1]
    assert name == "FAILED" and "원문" in body["reason"]


def test_rejects_wrong_token_and_missing_callback():
    api = client(runner(), FakeSpring())
    assert api.post("/run", json=run_body(), headers={"X-Internal-Token": "x"}).status_code == 401
    assert api.post("/run", json={**run_body(), "callbackBaseUrl": None}, headers=HEADERS).status_code == 400


def test_spring_client_urls_and_token():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers["X-Internal-Token"]))
        return httpx.Response(200, json={"status": "DONE"})

    spring = SpringClient(CALLBACK, token=TOKEN, transport=httpx.MockTransport(handler))
    spring.event("STEP", {"node": "verify"})
    spring.put("proposals", {"items": []})
    spring.job("J1")
    assert seen == [("POST", f"{CALLBACK}/events", TOKEN), ("PUT", f"{CALLBACK}/proposals", TOKEN),
                    ("GET", "http://backend:8080/internal/jobs/J1", TOKEN)]
