"""상품별 제안·부분 검토·버전 충돌을 외부 API 없이 검증한다."""
import copy
import subprocess
import sys

import pytest
from app.backend import ResumeRequest, product_proposals_payload
from app.graph import NODE_TOOLS, build_graph
from app.runner import AgentRunner, DecisionError
from app.schemas import ProductDraft, ProductAssessment, Requirement, RuleChange, RevisionCheck
from app.tools.local import LocalTools
from app.cli import select_proposals, review_command


class DsrReasoner:
    """외부 API 없이 검토 상태 전이를 확인하는 테스트 대역."""
    def __init__(self):
        self.contexts = []

    def requirements(self, diff):
        source = next(c for c in diff["changes"] if c["article_id"] == "8")
        return [Requirement(id="REQ-8", article_id="8", article="제8조",
                            article_ref=source["new_uri"], change="modified", summary="DSR 40%에서 35%로",
                            target="DSR_LIMIT", old_value="0.40", new_value="0.35")]

    def product_impacts(self, requirements, products, rules, regulation_context=None, documents=None, data_gaps=None):
        result = []
        for req in requirements:
            for p in products:
                ids = [r["ruleId"] for r in rules if r["productId"] == p["productId"] and r["ruleKey"] == "DSR_LIMIT"]
                keep = p["productId"] == "P003"
                result.append(ProductAssessment(requirement_id=req.id, product_id=p["productId"],
                    target_rule_ids=[] if keep else ids, evidence_rule_ids=ids,
                    scope="시행일 이후 신규 신청", applicability="all",
                    impact="no_change" if keep else "change_required", reason="테스트 자료의 DSR 비교"))
        return result

    def draft_product(self, context):
        self.contexts.append(copy.deepcopy(context))
        actions = ["신규 신청에 개정 기준 적용"]
        if context.get("comment"):
            actions.append(f"{context['comment']} (검토 {context['previous_proposal']['version']}차)")
        return ProductDraft(recommendation="DSR 35%로 변경", actions=actions, precautions=["경과조치 확인"],
                            changes=[RuleChange(**row) for row in context["mandatory_changes"]])

    def check_revision(self, context):
        return RevisionCheck(feedback_addressed=True, mandatory_preserved=True, reason="요청 반영 확인")


class ThreeProductTools(LocalTools):
    """검토 상태 전이 테스트는 최초 3개 상품으로 작게 유지한다."""
    def get_products(self):
        return super().get_products()[:3]

    def get_product_rules(self, *args, **kwargs):
        return [row for row in super().get_product_rules(*args, **kwargs) if int(row["ruleId"][1:]) <= 19]


def start(reasoner=None):
    reasoner = reasoner or DsrReasoner()
    tools = ThreeProductTools()
    runner = AgentRunner(build_graph(tools, reasoner))
    return runner, runner.start("T1", "credit-loan-ops"), reasoner, tools


def decision(proposal, action="approve", **extra):
    return {"proposal_id": proposal.id, "version": proposal.version, "action": action, **extra}


def test_only_review_after_proposals_without_code_or_write_tools():
    _, out, reasoner, tools = start()
    assert out["__interrupt__"][0].value["type"] == "product_review"
    assert len(out["proposals"]) == 2 and len(reasoner.contexts) == 2
    assert {p.id for p in out["proposals"]} == {"REQ-8:P001", "REQ-8:P002"}
    assert all(p.article_ref == "reg://credit-loan-ops/v4/8" for p in out["proposals"])
    assert "R001 DSR_LIMIT=0.40" in out["proposals"][0].current
    assert tools.called("get_products") and tools.called("get_product_rules")
    for tool in ("get_file", "search_code", "check_patch", "create_draft_pr", "create_work_ticket"):
        assert not tools.called(tool)
    assert set(sum((list(v) for v in NODE_TOOLS.values()), [])) == {"diff_versions", "get_regulation_context", "get_products", "get_product_rules", "get_product_documents"}


def test_partial_approval_stays_in_review_without_new_generation():
    runner, out, reasoner, _ = start()
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0])]})
    assert [p.status for p in out["proposals"]] == ["approved", "pending"]
    assert out["__interrupt__"] and len(reasoner.contexts) == 2
    assert len(out["review_history"]) == 1


def test_revision_only_selected_preserves_approved_and_supports_repeat():
    runner, out, reasoner, _ = start()
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0])]})
    approved = out["proposals"][0].model_dump()
    for version in (2, 3):
        out = runner.resume("T1", {"decisions": [decision(out["proposals"][1], "request_changes", comment="적용 시점을 구분해 주세요")]})
        assert out["proposals"][0].model_dump() == approved
        assert out["proposals"][1].version == version
        assert out["proposals"][1].status == "pending"
        assert reasoner.contexts[-1]["comment"] == "적용 시점을 구분해 주세요"
    assert len(reasoner.contexts) == 4
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][1])], "finish": True})
    assert out["result"].status == "APPROVED"


def test_edit_revokes_approval_and_requires_new_version_approval():
    runner, out, reasoner, _ = start()
    out = runner.resume("T1", {"decisions": [decision(p) for p in out["proposals"]]})
    assert out["__interrupt__"]  # 완료 전에는 승인 항목도 다시 열 수 있다.
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0], "edit", edits={"recommendation": "신규 신청에만 변경 기준 적용", "actions": ["시행일로 신청 구분"]})]})
    a, b = out["proposals"]
    assert (a.version, a.status, a.human_edited) == (2, "pending", True)
    assert b.status == "approved" and b.version == 1
    assert len(reasoner.contexts) == 2
    assert out["review_history"][0].snapshot.version == 1
    assert out["review_history"][0].snapshot.status == "approved"
    out = runner.resume("T1", {"decisions": [decision(a)], "finish": True})
    assert out["result"].approved_count == 2


@pytest.mark.parametrize("bad", [
    {"proposal_id": "unknown", "version": 1, "action": "approve"},
    {"proposal_id": "REQ-8:P002", "version": 2, "action": "approve"},
    {"proposal_id": "REQ-8:P002", "version": 1, "action": "request_changes", "comment": " "},
    {"proposal_id": "REQ-8:P002", "version": 1, "action": "edit", "edits": {"product_id": "P003"}},
    {"proposal_id": "REQ-8:P002", "version": 1, "action": "edit", "edits": {"recommendation": " "}},
])
def test_bad_batch_is_atomic_and_checkpoint_can_retry(bad):
    runner, out, _, _ = start()
    before = [p.model_dump() for p in out["proposals"]]
    with pytest.raises(DecisionError):
        runner.resume("T1", {"decisions": [decision(out["proposals"][0]), bad]})
    snapshot = runner.graph.get_state(runner.config("T1")).values
    assert [p.model_dump() for p in snapshot["proposals"]] == before
    out = runner.resume("T1", {"decisions": [decision(p) for p in out["proposals"]], "finish": True})
    assert out["result"].status == "APPROVED"


def test_duplicate_ids_finish_and_wrong_task_stage_rejected():
    runner, out, _, _ = start()
    item = decision(out["proposals"][0])
    for command in ({"decisions": [item, item]}, {"finish": True}, {}):
        with pytest.raises(DecisionError):
            runner.resume("T1", command)
    with pytest.raises(DecisionError):
        runner.resume("T1", {"decisions": [item]}, task_id="other")
    with pytest.raises(DecisionError):
        runner.resume("T1", {"decisions": [item]}, step="REQUIREMENTS")
    with pytest.raises(ValueError):
        runner.start("T1", "credit-loan-ops")


@pytest.mark.parametrize("actions, expected", [(["approve", "reject"], "PARTIALLY_APPROVED"), (["reject", "reject"], "REJECTED")])
def test_final_status_and_completed_thread_cannot_resume(actions, expected):
    runner, out, _, _ = start()
    out = runner.resume("T1", {"decisions": [decision(p, a) for p, a in zip(out["proposals"], actions)], "finish": True})
    assert out["result"].status == expected and out["result"].mode == "llm"
    assert len(out["result"].unchanged) == 1
    with pytest.raises(DecisionError):
        runner.resume("T1", {"finish": True})


def test_no_requirements_and_no_affected_products_skip_review():
    class Empty(DsrReasoner):
        def requirements(self, diff):
            return []
    assert start(Empty())[1]["result"].status == "NO_CHANGE"
    class Unchanged(DsrReasoner):
        def product_impacts(self, *args):
            return [r.model_copy(update={"impact": "no_change"}) for r in super().product_impacts(*args)]
    assert start(Unchanged())[1]["result"].status == "NO_ACTION"


@pytest.mark.parametrize("kind", ["missing", "duplicate", "wrong_rule"])
def test_uncertain_impacts_are_deferred_not_silently_excluded(kind):
    class Uncertain(DsrReasoner):
        def product_impacts(self, *args):
            rows = super().product_impacts(*args)
            if kind == "missing":
                return rows[1:]
            if kind == "duplicate":
                return rows + [rows[0]]
            rows[0] = rows[0].model_copy(update={"target_rule_ids": ["R015"]})
            return rows
    out = start(Uncertain())[1]
    assert out["proposals"][0].impact == "needs_review"
    assert not out["proposals"][0].target_rule_ids
    assert "R015" not in out["proposals"][0].current


def test_generation_failure_blocks_approval_and_manual_edit_recovers():
    class Broken(DsrReasoner):
        def draft_product(self, context):
            raise ValueError("invalid model output")
    runner, out, _, _ = start(Broken())
    with pytest.raises(DecisionError):
        runner.resume("T1", {"decisions": [decision(out["proposals"][0])]})
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0], "edit", edits={"recommendation": "DSR 상한 조정", "actions": ["0.40에서 0.35로 변경"]})]})
    assert out["proposals"][0].generation_error is None
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0])]})
    assert out["proposals"][0].status == "approved"


def test_backend_contract_and_camel_case_payload():
    runner, out, _, _ = start()
    payload = product_proposals_payload(out["proposals"])
    assert payload["items"][0]["proposalKey"] == "REQ-8:P001"
    assert payload["items"][0]["version"] == 1
    request = ResumeRequest.model_validate({"taskId": "T1", "threadId": "T1", "step": "REVIEW", "payload": {"decisions": [decision(p) for p in out["proposals"]], "finish": True}})
    assert runner.resume_backend(request)["result"].status == "APPROVED"
    with pytest.raises(ValueError):
        ResumeRequest(taskId="T1", threadId="T1", step="REQUIREMENTS").to_decision()


def test_cli_selectors_edits_and_removed_demo_mode():
    _, out, _, _ = start()
    proposals = [p.model_dump(mode="json") for p in out["proposals"]]
    assert len(select_proposals("1,P001,2", proposals)) == 2
    assert review_command("p P002", proposals)["decisions"][0]["proposal_id"] == "REQ-8:P002"
    answers = iter(["수정안", "항목1|항목2", "", "-", "메모"])
    command = review_command("e 1", proposals, lambda _: next(answers))
    assert command["decisions"][0]["edits"]["precautions"] == []
    assert not command["finish"]
    for bad in ("p", "p 9", "a 1", "f 2", "e 1,2"):
        with pytest.raises(ValueError):
            review_command(bad, proposals)
    result = subprocess.run([sys.executable, "run.py", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "{llm,live}" in result.stdout and "demo" not in result.stdout
    removed = subprocess.run([sys.executable, "run.py", "--mode", "demo"], capture_output=True, text=True)
    assert removed.returncode != 0


def test_one_batch_approves_one_and_regenerates_another():
    runner, out, reasoner, _ = start()
    out = runner.resume("T1", {"decisions": [
        decision(out["proposals"][0]),
        decision(out["proposals"][1], "request_changes", comment="신규와 기존 구분"),
    ]})
    assert [(p.status, p.version) for p in out["proposals"]] == [("approved", 1), ("pending", 2)]
    assert len(reasoner.contexts) == 3
    assert reasoner.contexts[-1]["product"]["productId"] == "P002"
    assert len(out["review_history"]) == 2


def test_scope_and_transitions_reach_proposal_model():
    _, out, reasoner, _ = start()
    context = reasoner.contexts[0]
    articles = {a["article_id"]: a for a in context["regulation_context"] if a["regulation_id"] == "credit-loan-ops"}
    assert "모든 개인신용대출" in articles["3"]["text"]
    assert "종전의 규정" in out["proposals"][0].transitional
    assert "기간을 연장" in out["proposals"][0].transitional
    assert context["requirement"]["effective_date"] == "2026-12-01"


def test_unsupported_no_change_is_kept_for_review():
    class Unsupported(DsrReasoner):
        def product_impacts(self, *args):
            return [row.model_copy(update={"impact": "no_change", "target_rule_ids": [], "evidence_rule_ids": []})
                    for row in super().product_impacts(*args)]
    out = start(Unsupported())[1]
    assert len(out["proposals"]) == 3
    assert all(p.impact == "needs_review" for p in out["proposals"])


def test_policy_key_difference_alone_does_not_override_semantic_judgment():
    class DifferentPolicy(DsrReasoner):
        def requirements(self, diff):
            return [row.model_copy(update={"target": "DEBT_SERVICE_RATIO"}) for row in super().requirements(diff)]
    out = start(DifferentPolicy())[1]
    assert len(out["proposals"]) == 2
    assert all(p.impact == "change_required" for p in out["proposals"])


def test_unchanged_revision_retries_then_blocks_approval_and_keeps_previous_body():
    class Unchanged(DsrReasoner):
        def draft_product(self, context):
            self.contexts.append(copy.deepcopy(context))
            return ProductDraft(recommendation="DSR 35%로 변경", actions=["신규 신청에 개정 기준 적용"], precautions=["경과조치 확인"], changes=[RuleChange(**row) for row in context["mandatory_changes"]])
    runner, out, reasoner, _ = start(Unchanged())
    original = out["proposals"][0]
    approved = out["proposals"][1]
    out = runner.resume("T1", {"decisions": [decision(approved)]})
    out = runner.resume("T1", {"decisions": [decision(original, "request_changes", comment="기존 신청은 제외해 주세요")]})
    revised = out["proposals"][0]
    assert revised.generation_error and "본문 변경이 없습니다" in revised.generation_error
    assert revised.actions == original.actions
    assert revised.recommendation == original.recommendation
    assert revised.changed_fields == []
    assert reasoner.contexts[-1]["validation_errors"]
    assert len(reasoner.contexts) == 4  # 초기 두 항목 + 선택한 항목의 두 시도
    assert out["proposals"][1].status == "approved"
    with pytest.raises(DecisionError):
        runner.resume("T1", {"decisions": [decision(revised)]})
    out = runner.resume("T1", {"decisions": [decision(revised, "edit", edits={"actions": ["시행일 이후 신규 신청에만 적용"]})]})
    assert out["proposals"][0].generation_error is None
    assert out["proposals"][0].changed_fields == ["actions"]


def test_unchanged_first_attempt_can_recover_on_retry():
    class Retry(DsrReasoner):
        def draft_product(self, context):
            draft = super().draft_product({**context, "comment": ""})
            if context.get("validation_errors"):
                draft.actions = ["신규 신청만 적용하고 기존 신청과 연장은 종전 기준 유지"]
            return draft
    runner, out, _, _ = start(Retry())
    out = runner.resume("T1", {"decisions": [decision(out["proposals"][0], "request_changes", comment="기존 신청 제외")]})
    revised = out["proposals"][0]
    assert revised.generation_error is None
    assert revised.changed_fields == ["actions"]
    assert "기존 신청" in revised.actions[0]


def test_spacing_and_reordering_alone_are_not_body_changes():
    from app.nodes.proposal import changed_fields
    before = ProductDraft(recommendation="DSR 35%", actions=["a", "b"], precautions=["경과 조치"])
    after = ProductDraft(recommendation=" DSR  35% ", actions=["b", "a"], precautions=["경과조치"])
    assert changed_fields(before, after) == []


def test_review_screen_shows_request_response_and_changed_fields(capsys):
    from app.cli import show_details
    _, out, _, _ = start()
    proposal = out["proposals"][0].model_copy(update={
        "review_comment": "기존 신청 제외", "revision_response": "수행 항목에 기존 신청 제외 추가",
        "changed_fields": ["actions"], "version": 2,
    })
    show_details(proposal.model_dump(mode="json"))
    text = capsys.readouterr().out
    assert "요청 의견: 기존 신청 제외" in text
    assert "반영 설명: 수행 항목에 기존 신청 제외 추가" in text
    assert "변경된 항목: 필수 조치" in text


def test_document_evidence_allows_keep_without_invented_rule():
    class DocumentReasoner(DsrReasoner):
        def product_impacts(self, *args):
            rows = super().product_impacts(*args)
            rows[0] = rows[0].model_copy(update={"impact": "no_change", "target_rule_ids": [], "evidence_rule_ids": [], "document_refs": ["product-doc://P001"]})
            return rows
    out = start(DocumentReasoner())[1]
    assert not any(p.product_id == "P001" for p in out["proposals"])
    assert next(i for i in out["product_impacts"] if i.product_id == "P001").document_refs == ["product-doc://P001"]


def test_another_products_document_cannot_support_keep():
    class WrongDocument(DsrReasoner):
        def product_impacts(self, *args):
            rows = super().product_impacts(*args)
            rows[0] = rows[0].model_copy(update={"impact": "no_change", "target_rule_ids": [], "evidence_rule_ids": [], "document_refs": ["product-doc://P002"]})
            return rows
    out = start(WrongDocument())[1]
    assert out["proposals"][0].impact == "needs_review"
    assert not out["proposals"][0].document_refs


def test_article_filter_preserves_context_and_rejects_unknown_article():
    class Capture(DsrReasoner):
        def requirements(self, diff):
            self.diff = diff
            return super().requirements(diff)
    reasoner = Capture()
    runner = AgentRunner(build_graph(ThreeProductTools(), reasoner))
    out = runner.start("filtered", "credit-loan-ops", article_ids=["8"])
    assert {c["article_id"] for c in reasoner.diff["changes"] if not c["article_id"].startswith("supp-")} == {"8"}
    assert out["snapshot_date"] == "2026-11-30"
    assert any(a["regulation_id"] == "dsr-management" for a in reasoner.diff["regulation_context"])
    with pytest.raises(ValueError, match="없는 조항"):
        runner.start("bad-filter", "credit-loan-ops", article_ids=["999"])
