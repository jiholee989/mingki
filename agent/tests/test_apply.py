"""실제 DB 쓰기 없이 승인 경계·멱등키·큐 완료·실패를 확인한다."""
import pytest
from app.backend import ResumeRequest, proposal_rows
from app.bridge import review_decision
from app.graph import build_graph
from app.nodes.apply import make_apply
from app.runner import AgentRunner, DecisionError
from app.schemas import ApplyApproval, RuleChange
from test_graph import DsrReasoner, ThreeProductTools, start, decision


class QueueTools(ThreeProductTools):
    is_local = False

    def __init__(self):
        super().__init__()
        self.requests = []

    def apply_rule_version(self, **kwargs):
        self.requests.append(kwargs)
        return {"jobId": kwargs["proposal_key"], "status": "QUEUED", "duplicate": False}


def completed(job_id):
    return {"id": job_id, "taskId": "T1", "status": "DONE", "type": "APPLY_RULE_VERSION",
            "result": {"proposalKey": job_id, "productId": job_id.split(":")[0], "newRuleId": "R083"}}


def request(approved=None, excluded=None, **kwargs):
    return ResumeRequest(taskId="T1", threadId="T1", step="REVIEW", decision="APPROVE", approvalId=12,
                         payload={"approvedProposalKeys": approved or ["P001:DSR_LIMIT"],
                                  "excludedProposalKeys": excluded if excluded is not None else ["P002:DSR_LIMIT"]}, **kwargs)


def running(job_reader=completed):
    tools = QueueTools()
    runner = AgentRunner(build_graph(tools, DsrReasoner(), job_reader=job_reader, poll_interval=.001))
    out = runner.start("T1", "credit-loan-ops")
    return runner, out, tools


def test_backend_approval_applies_only_selected_rule_and_waits_for_done():
    reads = []
    def job(job_id):
        reads.append(job_id)
        return {"status": "RETRYING"} if len(reads) == 1 else completed(job_id)
    runner, _, tools = running(job)
    out = runner.resume_backend(request())
    assert out["result"].status == "DONE"
    assert tools.requests == [{"task_id": "T1", "approval_id": 12, "proposal_key": "P001:DSR_LIMIT",
                               "idempotency_key": "T1:apply:P001:DSR_LIMIT"}]
    assert len(reads) == 2
    assert [r.status for r in out["result"].apply_results] == ["DONE"]
    assert [p.status for p in out["proposals"]] == ["approved", "rejected"]


def test_all_jobs_must_complete():
    runner, _, tools = running()
    out = runner.resume_backend(request(["P001:DSR_LIMIT", "P002:DSR_LIMIT"], []))
    assert len(tools.requests) == 2
    assert len(out["result"].apply_results) == 2 and out["result"].status == "DONE"


@pytest.mark.parametrize("job", [
    lambda _: {"status": "DEAD", "lastError": "이미 바뀐 규칙"},
    lambda _: {"status": "DONE", "result": {"proposalKey": "wrong", "productId": "P001"}},
    lambda _: {"status": "UNKNOWN"},
    lambda _: {**completed("P001:DSR_LIMIT"), "taskId": "OTHER"},
])
def test_dead_or_wrong_job_never_reports_done(job):
    runner, _, _ = running(job)
    result = runner.resume_backend(request())["result"]
    assert result.status == "FAILED" and result.apply_error


def test_timeout_keeps_job_for_later_reconciliation():
    _, out, _ = running()
    out["proposals"][0].status = "approved"
    out["apply_approval"] = ApplyApproval(approval_id=12, proposal_keys=["P001:DSR_LIMIT"])
    time = [0.0]
    def sleep(seconds):
        time[0] += seconds
    node = make_apply(QueueTools(), lambda _: {"status": "RUNNING"}, timeout=2, poll_interval=1,
                      clock=lambda: time[0], sleep=sleep)
    delta = node(out)
    assert delta["apply_results"][0].status == "TIMEOUT"
    assert delta["apply_results"][0].job_id and delta["apply_error"]


def test_missing_reader_never_submits_write():
    runner, _, tools = running(None)
    result = runner.resume_backend(request())["result"]
    assert result.status == "FAILED" and "job_reader" in result.apply_error
    assert tools.requests == []


def test_cli_approval_and_backend_rejection_never_submit_write():
    runner, out, tools = running()
    out = runner.resume("T1", {"decisions": [decision(p) for p in out["proposals"]], "finish": True})
    assert out["result"].status == "APPROVED" and tools.requests == []
    runner, _, tools = running()
    result = runner.resume_backend(ResumeRequest(taskId="T1", threadId="T1", step="REVIEW", decision="REJECT"))["result"]
    assert result.status == "REJECTED" and tools.requests == []


@pytest.mark.parametrize("change", [
    {"approval_id": None}, {"task_id": "OTHER"},
    {"payload": {"approvedProposalKeys": ["UNKNOWN"], "excludedProposalKeys": []}},
    {"payload": {"approvedProposalKeys": ["P001:DSR_LIMIT", "P001:DSR_LIMIT"], "excludedProposalKeys": ["P002:DSR_LIMIT"]}},
    {"payload": {"approvedProposalKeys": ["P001:DSR_LIMIT"], "excludedProposalKeys": []}},
])
def test_bad_backend_approval_is_rejected_before_checkpoint_or_write(change):
    runner, out, tools = running()
    bad = request().model_copy(update=change)
    with pytest.raises(DecisionError):
        runner.resume_backend(bad)
    assert tools.requests == []
    assert runner.graph.get_state(runner.config("T1")).values["proposals"][0].status == "pending"


def test_rule_export_and_rule_level_exclusion_within_one_proposal():
    runner, out, tools = running()
    # 두 번째 상품은 별도 행이다. 첫 번째 상품에 두 번째 규칙 행을 추가해 경계 변환만 확인한다.
    p = out["proposals"][0].model_copy(deep=True)
    p.changes.append(RuleChange(rule_id="R2", rule_key="OTHER_DSR", current_value="0.4", proposed_value="0.35", unit="ratio"))
    req = request(["P001:DSR_LIMIT"], ["P001:OTHER_DSR", "P002:DSR_LIMIT"])
    command = review_decision([p, out["proposals"][1]], req.decision, req.payload, approval_id=req.approval_id)
    assert command["apply_approval"]["proposal_keys"] == ["P001:DSR_LIMIT"]
    assert command["decisions"][0]["action"] == "approve"
    rows = proposal_rows(p)
    assert [row["proposalKey"] for row in rows] == ["P001:DSR_LIMIT", "P001:OTHER_DSR"]
    assert rows[0]["currentValue"] == "0.40" and rows[0]["verifyStatus"] == "PASSED"


def test_replay_reuses_idempotency_key():
    _, out, _ = running()
    out["proposals"][0].status = "approved"
    out["apply_approval"] = ApplyApproval(approval_id=12, proposal_keys=["P001:DSR_LIMIT"])
    tools = QueueTools()
    node = make_apply(tools, completed)
    assert node(out)["apply_error"] is None
    assert node(out)["apply_error"] is None
    assert tools.requests[0] == tools.requests[1]


def test_local_source_cannot_apply_even_with_approval_metadata():
    _, out, _, tools = start()
    out["proposals"][0].status = "approved"
    out["apply_approval"] = ApplyApproval(approval_id=12, proposal_keys=["P001:DSR_LIMIT"])
    delta = make_apply(tools, completed)(out)
    assert "MCP" in delta["apply_error"] and not delta["apply_results"]


def test_one_rejected_submission_does_not_skip_the_others():
    runner, out, tools = running()

    def submit(**kw):
        tools.requests.append(kw)
        if kw["proposal_key"] == "P001:DSR_LIMIT":
            raise RuntimeError("백엔드 409 ERROR: 이미 바뀐 규칙: R001 값이 0.40이 아니라 0.38입니다")
        return {"jobId": kw["proposal_key"]}
    tools.apply_rule_version = submit
    result = runner.resume_backend(request(["P001:DSR_LIMIT", "P002:DSR_LIMIT"], []))["result"]
    assert result.status == "FAILED"
    assert [(r.proposal_key, r.status) for r in result.apply_results] == [("P001:DSR_LIMIT", "FAILED"), ("P002:DSR_LIMIT", "DONE")]
    assert "이미 바뀐 규칙" in result.apply_results[0].error and "P002" not in result.apply_error


def test_transient_read_errors_are_retried_then_given_up():
    reads = []

    def flaky(job_id):
        reads.append(job_id)
        if len(reads) <= 2:
            raise RuntimeError("503 Service Unavailable")
        return completed(job_id)
    runner, _, _ = running(flaky)
    assert runner.resume_backend(request())["result"].status == "DONE" and len(reads) == 3

    def down(job_id):
        raise RuntimeError("503 Service Unavailable")
    runner, _, _ = running(down)
    result = runner.resume_backend(request())["result"]
    assert result.status == "FAILED" and "조회 실패" in result.apply_error
    assert result.apply_results[0].status == "QUEUED" and result.apply_results[0].job_id   # 접수된 작업은 기록에 남는다


def test_write_failure_keeps_already_queued_job_and_reports_failed():
    runner, out, tools = running()
    def submit(**kw):
        tools.requests.append(kw)
        if len(tools.requests) == 2:
            raise RuntimeError("두 번째 요청 연결 실패")
        return {"jobId": kw["proposal_key"]}
    tools.apply_rule_version = submit
    result = runner.resume_backend(request(["P001:DSR_LIMIT", "P002:DSR_LIMIT"], []))["result"]
    assert result.status == "FAILED"
    first, second = result.apply_results
    assert (first.job_id, first.status) == ("P001:DSR_LIMIT", "DONE")      # 접수된 작업은 끝까지 확인한다
    assert (second.job_id, second.status) == (None, "FAILED") and "연결 실패" in second.error
    assert "연결 실패" in result.apply_error and "P001" not in result.apply_error


def test_mcp_write_contract_over_real_protocol_without_database():
    from fastmcp import FastMCP
    from app.tools.mcp_client import McpTools
    server, observed = FastMCP("apply-contract"), []
    @server.tool
    def apply_rule_version(task_id: str, approval_id: int, proposal_key: str, idempotency_key: str) -> dict:
        observed.append((task_id, approval_id, proposal_key, idempotency_key))
        return {"jobId": proposal_key, "status": "QUEUED", "duplicate": False}
    _, state, _ = running()
    state["proposals"][0].status = "approved"
    state["apply_approval"] = ApplyApproval(approval_id=12, proposal_keys=["P001:DSR_LIMIT"])
    tools = McpTools({"business": server})
    try:
        delta = make_apply(tools, completed)(state)
        assert delta["apply_error"] is None
        assert delta["apply_results"][0].status == "DONE"
        assert observed == [("T1", 12, "P001:DSR_LIMIT", "T1:apply:P001:DSR_LIMIT")]
    finally:
        tools.close()


def test_missing_mcp_write_tool_is_failure_without_http_write_fallback():
    from fastmcp import FastMCP
    from app.tools.mcp_client import McpTools
    _, state, _ = running()
    state["proposals"][0].status = "approved"
    state["apply_approval"] = ApplyApproval(approval_id=12, proposal_keys=["P001:DSR_LIMIT"])
    reads = []
    tools = McpTools({"business": FastMCP("no-apply-tool")})
    try:
        delta = make_apply(tools, lambda job: reads.append(job))(state)
        assert delta["apply_error"] and not reads
        assert all(r.status == "FAILED" and r.job_id is None for r in delta["apply_results"])
    finally:
        tools.close()
