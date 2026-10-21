"""재작성 실제 반환·변경 출력·실패 설명을 외부 호출 없이 확인한다."""

from app.cli import show_review_changes
from app.schemas import RevisionCheck
from test_graph import DsrReasoner, ThreeProductTools, decision, start


def test_revision_diff_shows_only_selected_product_and_changed_lines(capsys):
    runner, out, _, _ = start()
    previous = out["__interrupt__"][0].value["proposals"]
    decisions = [decision(out["proposals"][0], "request_changes", comment="기존 신청 제외 문구 추가")]
    out = runner.resume("T1", {"decisions": decisions})
    show_review_changes(previous, out["proposals"], decisions)
    text = capsys.readouterr().out
    assert "1번 P001" in text and "v1 → v2" in text
    assert "+ 기존 신청 제외 문구 추가" in text
    assert "검증 통과" in text and "P002" not in text
    assert "- 신규 신청에 개정 기준 적용" not in text  # 유지한 조치는 변경으로 출력하지 않는다.


def test_failed_revision_does_not_claim_candidate_was_applied(capsys):
    class FailedRevision(DsrReasoner):
        def draft_product(self, context):
            draft = super().draft_product(context)
            if context.get("comment"):
                from app.schemas import ProductRevision
                return ProductRevision(**draft.model_dump(), revision_response="요청을 모두 반영했습니다")
            return draft

        def check_revision(self, context):
            return RevisionCheck(feedback_addressed=False, mandatory_preserved=True, reason="고객 안내 문장이 없음")

    runner, out, _, _ = start(FailedRevision())
    original = out["proposals"][0]
    previous = out["__interrupt__"][0].value["proposals"]
    decisions = [decision(original, "request_changes", comment="고객 안내 문장 추가")]
    out = runner.resume("T1", {"decisions": decisions})
    revised = out["proposals"][0]
    assert revised.actions == original.actions
    assert "이전 본문을 유지" in revised.revision_response
    assert "모두 반영했습니다" not in revised.revision_response
    show_review_changes(previous, out["proposals"], decisions)
    text = capsys.readouterr().out
    assert "재작성 실패 · 이전 본문 유지 · 승인 불가" in text
    assert "고객 안내 문장이 없음" in text
    assert "검증 통과" not in text and "  + " not in text


def test_revision_checker_receives_supplementary_sources_and_only_own_documents():
    class Capture(DsrReasoner):
        def check_revision(self, context):
            self.checked = context
            return super().check_revision(context)

    runner, out, reasoner, _ = start(Capture())
    runner.resume("T1", {"decisions": [decision(out["proposals"][0], "request_changes", comment="경과조치 안내 추가")]})
    context = reasoner.checked
    assert any(a["article_id"] == "supp-2" and "신청" in a["text"] for a in context["regulation_context"])
    assert context["documents"]
    assert all(d["productId"] == "P001" for d in context["documents"])
    assert "data_gaps" in context


def test_cli_automatically_prints_revision_without_details_command(monkeypatch, capsys):
    import run
    import app.llm
    import app.tools.local

    monkeypatch.setattr(run, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.llm, "LlmReasoner", DsrReasoner)
    monkeypatch.setattr(app.tools.local, "LocalTools", ThreeProductTools)
    monkeypatch.setattr("sys.argv", ["run.py", "--article", "8"])
    answers = iter(["c 1", "기존 신청 제외 안내 추가", "a"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    run.main()
    text = capsys.readouterr().out
    assert "선택한 제안을 수정·검증하고 있습니다" in text
    assert "변경 결과 · 1번 P001" in text
    assert "+ 기존 신청 제외 안내 추가" in text
    assert "[APPROVED]" in text


def test_cannot_apply_is_visible_and_preserves_original_validation(capsys):
    class Cannot(DsrReasoner):
        def draft_product(self, context):
            if context.get("comment"):
                from app.schemas import ProductRevision
                old = context["previous_proposal"]
                return ProductRevision(**{k: old[k] for k in ("recommendation", "actions", "optional_actions", "precautions", "changes")},
                                       revision_outcome="cannot_apply", revision_response="원문과 충돌하므로 반영할 수 없습니다")
            return super().draft_product(context)

    runner, out, _, _ = start(Cannot())
    previous = out["__interrupt__"][0].value["proposals"]
    decisions = [decision(out["proposals"][0], "request_changes", comment="DSR 40%로 유지해줘")]
    out = runner.resume("T1", {"decisions": decisions})
    show_review_changes(previous, out["proposals"], decisions)
    text = capsys.readouterr().out
    assert "반영 불가 · 요청은 반영하지 않았으며 이전 본문을 유지" in text
    assert "기존 본문 검증: 통과" in text
    assert "아래 변경 내용을 확인" not in text
    assert "  + " not in text


def test_new_rule_change_is_named_instead_of_none(capsys):
    """새 규칙(rule_id · current_value 없음)은 None 대신 '새 규칙' · '없음'으로 보인다 (show_details와 같은 표시)."""
    from types import SimpleNamespace

    change = {"rule_id": None, "rule_key": "SENIOR_DISCLOSURE_CHECK", "current_value": None, "proposed_value": "true", "unit": "bool"}
    old = {"id": "REQ-15-2:P002", "version": 1, "recommendation": "설명 확인 절차 추가", "actions": ["절차 추가"],
           "optional_actions": [], "precautions": [], "changes": []}
    new = {**old, "version": 2, "product_id": "P002", "product_name": "리플 시니어 든든대출", "review_comment": "규칙으로 추가",
           "revision_outcome": "revised", "verification": "passed", "generation_error": None, "revision_response": "",
           "scope": "고령자 신규 계약", "changes": [change]}
    show_review_changes([old], [SimpleNamespace(model_dump=lambda mode=None: new)],
                        [{"proposal_id": old["id"], "action": "request_changes"}])
    text = capsys.readouterr().out
    assert "+ 새 규칙 SENIOR_DISCLOSURE_CHECK: 없음 → true (bool)" in text
    assert "None" not in text
