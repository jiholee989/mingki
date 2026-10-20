from langgraph.types import interrupt
from app.schemas import Approval, Event


def confirm_requirements(state):
    decision = interrupt(
        {
            "type": "confirm_requirements",
            "requirements": [r.model_dump(mode="json") for r in state["requirements"]],
            "change_specs": [s.model_dump(mode="json") for s in state["change_specs"]],
        }
    )
    validate_confirmation(state, decision)
    action = decision["action"]
    reqs = state["requirements"]
    keys = set(decision.get("confirmed_req_keys", [r.id for r in reqs]))
    excluded = set(decision.get("excluded_spec_keys", []))
    approved = action == "approve" and bool(keys)
    update = {
        "approvals": [
            Approval(
                stage="requirements", approved=approved, comment=decision.get("comment")
            )
        ],
        "events": [
            Event(
                node="confirm_requirements",
                message="분석·수정 대상 확정" if approved else "분석 보류",
            )
        ],
    }
    if approved:
        update["requirements"] = [r for r in reqs if r.id in keys]
        update["change_specs"] = [
            s
            for s in state["change_specs"]
            if s.requirement_id in keys and s.id not in excluded
        ]
    return update


def route_after_confirm(state):
    return "test_agent" if state["approvals"][-1].approved else "report"


def validate_confirmation(state, decision):
    if not isinstance(decision, dict):
        raise ValueError("승인 결정은 객체여야 합니다")
    action = decision.get("action")
    if action not in ("approve", "reject"):
        raise ValueError("첫 검토는 approve 또는 reject입니다")
    reqs = state["requirements"]
    keys = set(decision.get("confirmed_req_keys", [r.id for r in reqs]))
    excluded = set(decision.get("excluded_spec_keys", []))
    if not keys <= {r.id for r in reqs} or not excluded <= {
        s.id for s in state["change_specs"]
    }:
        raise ValueError("이 작업에 없는 요건/영향 위치입니다")
