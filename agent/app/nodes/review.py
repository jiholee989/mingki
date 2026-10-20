"""제안별 검토. 배치 전체를 검증한 뒤 반영해 일부만 적용되는 일을 막는다."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from langgraph.types import interrupt
from app.schemas import ProductProposal, ProposalReviewRecord, Event, ApplyApproval
from app.nodes.proposal import changed_fields
from app.validation import validate_proposal, validate_feedback


class ProposalEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendation: str | None = None
    actions: list[str] | None = None
    optional_actions: list[str] | None = None
    precautions: list[str] | None = None


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    version: int = Field(ge=1, strict=True)
    action: Literal["approve", "reject", "request_changes", "edit"]
    comment: str = ""
    edits: ProposalEdits | None = None


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[ProposalDecision] = Field(default_factory=list)
    finish: bool = Field(default=False, strict=True)
    apply_approval: ApplyApproval | None = None


def validate_review(state, decision):
    try:
        command = ReviewCommand.model_validate(decision)
    except ValidationError as exc:
        raise ValueError("상품별 결정 형식이 올바르지 않습니다: " + str(exc.errors(include_input=False))) from None
    if not command.decisions and not command.finish:
        raise ValueError("검토할 제안 또는 검토 완료 결정을 지정하세요")
    current = {p.id: p for p in state["proposals"]}
    updated, history, seen = dict(current), [], set()
    for item in command.decisions:
        if item.proposal_id not in current or item.proposal_id in seen:
            raise ValueError("이 작업에 없거나 중복된 제안 ID입니다")
        seen.add(item.proposal_id)
        old = current[item.proposal_id]
        if item.version != old.version:
            raise ValueError(f"오래된 제안 버전입니다: {old.id}의 현재 버전은 {old.version}")
        data = old.model_dump()
        edits = item.edits.model_dump(exclude_unset=True) if item.edits else {}
        if item.action == "edit":
            if not edits:
                raise ValueError("직접 수정할 내용을 입력하세요")
            data.update(edits)
            data.update(version=old.version + 1, human_edited=True, generation_error=None, status="pending")
        elif edits:
            raise ValueError("직접 수정은 edit으로 반영한 뒤 새 버전을 승인하세요")
        elif item.action == "approve":
            if old.verification != "passed" or old.generation_error or not old.recommendation.strip() or not old.actions:
                raise ValueError("생성 오류 또는 수행 항목이 없는 제안은 승인할 수 없습니다")
            data["status"] = "approved"
        elif item.action == "reject":
            data["status"] = "rejected"
        else:
            validate_feedback(item.comment)
            data["status"] = "revision_requested"
        data["review_comment"] = item.comment
        try:
            proposal = ProductProposal.model_validate(data)
        except ValidationError:
            raise ValueError("직접 수정 내용의 형식이 올바르지 않습니다") from None
        if not proposal.recommendation.strip() or any(not a.strip() for a in proposal.actions):
            raise ValueError("제안과 수행 항목은 빈 문자열일 수 없습니다")
        if item.action == "edit":
            errors = validate_proposal(state, proposal)
            if errors:
                raise ValueError("직접 수정 검증 실패: " + "; ".join(errors))
            proposal.verification = "passed"
            proposal.changed_fields = changed_fields(old, proposal)
            proposal.revision_response = "직접 수정: " + (item.comment or "사용자가 제안 본문을 편집했습니다")
        updated[old.id] = proposal
        history.append(ProposalReviewRecord(proposal_id=old.id, version=proposal.version,
                                            action=item.action, comment=item.comment,
                                            snapshot=proposal.model_copy(deep=True)))
    if command.finish and any(p.status not in ("approved", "rejected") for p in updated.values()):
        raise ValueError("검토 대기·수정 요청 항목이 남아 있습니다. 승인 또는 제외 후 완료하세요")
    if command.apply_approval:
        from app.nodes.apply import approved_rows
        if not command.finish:
            raise ValueError("실제 반영은 검토 완료와 함께 요청해야 합니다")
        approved_rows(list(updated.values()), command.apply_approval)
    return [updated[p.id] for p in state["proposals"]], history, command.finish


def review(state):
    decision = interrupt({"type": "product_review",
                          "proposals": [p.model_dump(mode="json") for p in state["proposals"]],
                          "unchanged": [i.model_dump(mode="json") for i in state["product_impacts"] if i.impact == "no_change"]})
    proposals, history, finish = validate_review(state, decision)
    return {"proposals": proposals, "review_history": history, "review_finish": finish,
            "apply_approval": ReviewCommand.model_validate(decision).apply_approval,
            "events": [Event(node="review", message=f"제안 {len(history)}건 검토 반영")]}


def route_after_review(state):
    if any(p.status == "revision_requested" for p in state["proposals"]):
        return "proposal_agent"
    if state.get("review_finish"):
        return "apply" if state.get("apply_approval") else "report"
    return "review"
