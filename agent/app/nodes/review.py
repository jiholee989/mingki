import uuid

from langgraph.types import interrupt

from app.schemas import Approval, Event
from app.state import RippleState


def review(state: RippleState) -> dict:
    """interrupt ② 명세서·패치 검토, PR·티켓 승인.

    재개 값:
      {"action": "approve", "publish_pr": bool, "publish_ticket": bool, "allow_failed": bool}
      {"action": "reject", "comment": str}
      {"action": "edit", "edited_patches": [{"bundle_id": str, "diff": str}]}  → verify 재실행
    """
    patches = state.get("code_patches", [])
    failed = [p.bundle_id for p in patches if p.status != "passed"]
    decision = interrupt(
        {
            "type": "review",
            "change_specs": [s.model_dump(mode="json") for s in state.get("change_specs", [])],
            "patches": [p.model_dump(mode="json") for p in patches],
            "verification_failed": failed,  # 기본 차단 대상
            "missed_locations": state.get("missed_locations", []),
        }
    )
    action = decision.get("action")

    if action == "edit":
        by_id = {p.bundle_id: p for p in patches}
        edited = [
            by_id[e["bundle_id"]].model_copy(update={"diff": e["diff"], "status": "merged", "human_edited": True})
            for e in decision.get("edited_patches", [])
        ]
        return {
            "code_patches": edited,
            "human_edit_pending": True,
            "events": [Event(node="review", message=f"사람 수정 {len(edited)}건 → 재검증")],
        }

    approved = action == "approve"
    return {
        "approvals": [
            Approval(stage="review", approved=approved, approval_id=f"APV-{uuid.uuid4().hex[:12]}",
                     comment=decision.get("comment"))
        ],
        "review_decision": decision,
        "human_edit_pending": False,
        "events": [Event(node="review", message="승인" if approved else "거절")],
    }


def route_after_review(state: RippleState) -> str:
    if state.get("human_edit_pending"):
        return "verify"
    return "publish" if state["approvals"][-1].approved else "report"
