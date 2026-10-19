from app.schemas import Delivery, Event
from app.state import RippleState


def make_publish(tools):
    """승인된 항목만 Draft PR · 작업 티켓 생성. 검증 실패 묶음은 allow_failed 없이는 제외."""

    def publish(state: RippleState) -> dict:
        approval = state["approvals"][-1]
        decision = state.get("review_decision", {})
        allow_failed = decision.get("allow_failed", False)
        eligible = [p for p in state.get("code_patches", []) if p.status == "passed" or allow_failed]
        if not eligible:
            return {"deliveries": [], "events": [Event(node="publish", message="검증 통과 패치 없음 → 배포 차단")]}

        task_id = state["task_id"]
        deliveries = []
        if decision.get("publish_pr", True):
            key = f"{task_id}:{approval.approval_id}:pr"
            out = tools.create_draft_pr(
                title=f"[Rule Ripple] {state['regulation_id']} {state['new_version']} 반영",
                patches=[p.model_dump(mode="json") for p in eligible],
                approval_id=approval.approval_id,
                idempotency_key=key,
            )
            deliveries.append(Delivery(kind="draft_pr", url=out["url"], idempotency_key=key))
        if decision.get("publish_ticket", True):
            key = f"{task_id}:{approval.approval_id}:ticket"
            body = "\n".join(f"- {r.id} {r.summary} (시행 {r.effective_date})" for r in state["requirements"])
            out = tools.create_work_ticket(
                title=f"[Rule Ripple] {state['regulation_id']} 개정 대응",
                body=body,
                approval_id=approval.approval_id,
                idempotency_key=key,
            )
            deliveries.append(Delivery(kind="work_ticket", url=out["url"], idempotency_key=key))
        return {"deliveries": deliveries, "events": [Event(node="publish", message=f"배포 {len(deliveries)}건")]}

    return publish
