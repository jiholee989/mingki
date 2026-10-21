"""실패 제안이 섞인 전체 완료와 HTTP 승인 경계를 실제 모델·DB 없이 확인한다."""

import pytest

from app.cli import review_command, show_review
from app.schemas import RevisionCheck
from test_graph import DsrReasoner, ThreeProductTools, decision, start
from tests.test_apply import QueueTools
from tests.test_server import HEADERS, resume_body, started


class UnmetFeedback(DsrReasoner):
    def check_revision(self, context):
        return RevisionCheck(feedback_addressed=False, mandatory_preserved=True, reason="고객 안내 문장이 없음")


def failed_revision():
    runner, out, reasoner, _ = start(UnmetFeedback())
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0], "request_changes", comment="고객 안내 문장 추가")]})
    assert out["proposals"][0].verification == "failed"
    return runner, out, reasoner


def test_all_completion_can_explicitly_exclude_failure_and_finish_once(capsys):
    runner, out, reasoner = failed_revision()
    generated = len(reasoner.contexts)
    command = review_command("a", out["__interrupt__"][0].value["proposals"], lambda _: "y")
    out = runner.resume("T1", command)
    assert out["result"].status == "PARTIALLY_APPROVED"
    assert [p.status for p in out["proposals"]] == ["rejected", "approved"]
    assert len(reasoner.contexts) == generated
    assert "고객 안내 문장이 없음" in out["review_history"][-2].comment
    text = capsys.readouterr().out
    assert "승인 1건" in text and "제외 1건" in text and "1번 P001" in text


@pytest.mark.parametrize("answer", ["", "n"])
def test_cancelled_completion_keeps_every_proposal_and_review_history(answer):
    runner, out, _ = failed_revision()
    before = [p.model_dump() for p in runner.current_proposals("T1")]
    history = list(out["review_history"])
    with pytest.raises(ValueError, match="취소"):
        review_command("a", out["__interrupt__"][0].value["proposals"], lambda _: answer)
    assert [p.model_dump() for p in runner.current_proposals("T1")] == before
    assert runner.graph.get_state(runner.config("T1")).values["review_history"] == history


def test_individual_approval_reports_failed_product_and_reason():
    runner, out, _ = failed_revision()
    with pytest.raises(ValueError, match="1번 P001 승인 불가:.*고객 안내 문장이 없음"):
        runner.resume("T1", review_command("p 1", out["__interrupt__"][0].value["proposals"]))


def test_already_approved_hidden_selection_does_not_add_review_records():
    runner, out, _, _ = start()
    command = review_command("p 1", out["__interrupt__"][0].value["proposals"])
    out = runner.resume("T1", command)
    with pytest.raises(ValueError, match="이미 승인"):
        review_command("p 1", out["__interrupt__"][0].value["proposals"])
    assert len(out["review_history"]) == 1
    out = runner.resume("T1", review_command("a", out["__interrupt__"][0].value["proposals"]))
    assert out["result"].status == "APPROVED"


def test_completion_preserves_prior_approvals_when_only_failed_item_remains():
    runner, out, _ = failed_revision()
    out = runner.resume("T1", review_command("p 2", out["__interrupt__"][0].value["proposals"]))
    approved = out["proposals"][1].model_dump()
    out = runner.resume("T1", review_command("a", out["__interrupt__"][0].value["proposals"], lambda _: "y"))
    assert out["result"].status == "PARTIALLY_APPROVED"
    assert out["proposals"][0].status == "rejected"
    assert out["proposals"][1].model_dump() == approved


def test_rejected_failure_is_displayed_as_excluded(capsys):
    runner, out, _ = failed_revision()
    out = runner.resume("T1", review_command("r 1", out["__interrupt__"][0].value["proposals"]))
    show_review(out["__interrupt__"][0].value)
    row = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("1 |"))
    assert "제외 v2" in row and "검증 실패" not in row


def test_cli_failed_revision_help_and_completion_in_one_session(monkeypatch, capsys):
    import run
    import app.llm
    import app.tools.local

    monkeypatch.setattr(run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.llm, "LlmReasoner", UnmetFeedback)
    monkeypatch.setattr(app.tools.local, "LocalTools", ThreeProductTools)
    monkeypatch.setattr("sys.argv", ["run.py", "--article", "8"])
    answers = iter(["c 1", "고객 안내 문장 추가", "?", "a", "y"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    run.main()
    text = capsys.readouterr().out
    assert "승인 불가: 1번 P001" in text
    assert "제외 예정: 1번 P001" in text
    assert "[PARTIALLY_APPROVED]" in text
    assert "결정을 반영하지 못했습니다" not in text


class FailedP001(DsrReasoner):
    def draft_product(self, context):
        if context["product"]["productId"] == "P001":
            raise ValueError("P001 모델 요청 실패")
        return super().draft_product(context)


class EmptyBodyP001(DsrReasoner):
    def draft_product(self, context):
        draft = super().draft_product(context)
        if context["product"]["productId"] == "P001":
            draft.recommendation = ""
            draft.actions = []
        return draft


def test_empty_failed_body_can_be_excluded_without_allowing_approval():
    runner, out, _, _ = start(EmptyBodyP001())
    proposals = out["__interrupt__"][0].value["proposals"]
    with pytest.raises(ValueError, match="제안 본문 없음"):
        runner.resume("T1", review_command("p 1", proposals))
    out = runner.resume("T1", review_command("a", proposals, lambda _: "y"))
    assert out["result"].status == "PARTIALLY_APPROVED"
    assert [p.status for p in out["proposals"]] == ["rejected", "approved"]


def test_agent_http_reject_can_finish_even_when_failed_body_is_empty():
    api, spring, tools = started(tools=QueueTools(), reasoner=EmptyBodyP001())
    spring.calls.clear()
    response = api.post("/resume", json=resume_body("REJECT"), headers=HEADERS)
    assert response.status_code == 202 and spring.kinds()[-1] == "DONE:REJECTED"
    assert tools.requests == []


def test_agent_http_rejects_failed_approval_before_acceptance_and_allows_exclusion():
    api, spring, tools = started(tools=QueueTools(), reasoner=FailedP001())
    spring.calls.clear()
    bad = resume_body("APPROVE", approved=["P001:DSR_LIMIT", "P002:DSR_LIMIT"])
    response = api.post("/resume", json=bad, headers=HEADERS)
    assert response.status_code == 400
    assert "P001:DSR_LIMIT" in response.json()["detail"]
    assert "P001 모델 요청 실패" in response.json()["detail"]
    assert tools.requests == [] and spring.calls == []
    # Agent 어댑터 경계 검증이다. 실제 Spring의 canApprove 정책 검증은 포함하지 않는다.
    good = resume_body("APPROVE", approved=["P002:DSR_LIMIT"], excluded=["P001:DSR_LIMIT"])
    response = api.post("/resume", json=good, headers=HEADERS)
    assert response.status_code == 202 and spring.kinds()[-1] == "DONE:DONE"
    assert [r["proposal_key"] for r in tools.requests] == ["P002:DSR_LIMIT"]
