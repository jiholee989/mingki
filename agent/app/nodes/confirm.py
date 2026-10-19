from langgraph.types import interrupt

from app.schemas import Approval, Event, Requirement
from app.state import RippleState


def confirm_requirements(state: RippleState) -> dict:
    """interrupt ① 담당자가 요건을 확정·수정한다.

    재개 값: {"action": "approve" | "reject", "requirements": [...수정본, 선택], "comment": str}
    """
    decision = interrupt(
        {
            "type": "confirm_requirements",
            "requirements": [r.model_dump(mode="json") for r in state["requirements"]],
        }
    )
    approved = decision.get("action") == "approve"
    update: dict = {
        "approvals": [Approval(stage="requirements", approved=approved, comment=decision.get("comment"))],
        "events": [Event(node="confirm_requirements", message="요건 확정" if approved else "요건 반려")],
    }
    if approved and decision.get("requirements"):
        update["requirements"] = [Requirement.model_validate(r) for r in decision["requirements"]]
    return update


def route_after_confirm(state: RippleState) -> list[str] | str:
    if state["approvals"][-1].approved:
        return ["test_agent", "locate_agent"]  # 같은 superstep에서 병렬
    return "report"
