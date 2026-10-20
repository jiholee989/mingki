"""값·단위·근거 검사와 재작성의 요청 반영 검토. 항목당 최대 두 번 작성한다."""

from app.schemas import Event
from app.validation import validate_proposal
from app.nodes.proposal import changed_fields, CONTENT_FIELDS


def make_verify(reasoner):
    def verify(state):
        proposals, checked, failed = [], 0, 0
        baselines = state.get("revision_baselines", {})
        for item in state["proposals"]:
            if item.status != "pending" or item.verification != "pending":
                proposals.append(item)
                continue
            proposal = item.model_copy(deep=True)
            baseline = baselines.get(item.id)
            errors = [item.generation_error] if item.generation_error else validate_proposal(state, item, baseline)
            if baseline and not errors:
                if not changed_fields(baseline, item):
                    errors.append("재작성 결과에 본문 변경이 없습니다")
                else:
                    req = next(r for r in state["requirements"] if r.id == item.requirement_id)
                    try:
                        result = reasoner.check_revision({"requirement": req.model_dump(mode="json"),
                            "previous_proposal": baseline.model_dump(mode="json"),
                            "comment": baseline.review_comment, "candidate": item.model_dump(mode="json")})
                        if not result.feedback_addressed or not result.mandatory_preserved:
                            errors.append("수정 요청·필수 변경 검토 실패: " + result.reason)
                    except ValueError as exc:
                        errors.append(str(exc))
            proposal.verification = "failed" if errors else "passed"
            proposal.generation_error = "; ".join(errors) if errors else None
            proposal.changed_fields = changed_fields(baseline, item) if baseline and not errors else []
            if errors and item.attempt >= 2 and baseline:
                # 실패한 새 본문을 기존 승인 가능한 제안처럼 보여주지 않는다.
                for name in CONTENT_FIELDS:
                    setattr(proposal, name, getattr(baseline.model_copy(deep=True), name))
            proposals.append(proposal)
            checked += 1
            failed += bool(errors)
        return {"proposals": proposals,
                "events": [Event(node="verify", message=f"제안 {checked}건 검사 / 보완 필요 {failed}건")]}
    return verify


def route_after_verify(state):
    return "proposal_agent" if any(p.verification == "failed" and p.attempt < 2 and p.status == "pending"
                                   for p in state["proposals"]) else "review"
