from langgraph.types import interrupt
from app.schemas import Approval, Event


def review(state):
    patches = state.get("code_patches", [])
    decision = interrupt(
        {
            "type": "review",
            "demo": state.get("demo", False),
            "change_specs": [s.model_dump(mode="json") for s in state["change_specs"]],
            "patches": [p.model_dump(mode="json") for p in patches],
            "verification_failed": [
                p.bundle_id
                for p in patches
                if p.status not in ("passed", "ticket_only")
            ],
            "system_errors": state.get("system_errors", []),
        }
    )
    validate_review(state, decision)
    action = decision["action"]
    excluded = set(decision.get("excluded_spec_keys", []))
    if action == "request_changes":
        return {
            "review_decision": decision,
            "revision_comment": decision["comment"],
            "retry_count": 0,
            "change_specs": [s for s in state["change_specs"] if s.id not in excluded],
            "events": [Event(node="review", message="수정 요청 → 재작성·재검증")],
        }
    return {
        "review_decision": decision,
        "approvals": [
            Approval(
                stage="review",
                approved=action == "approve",
                approval_id=decision.get("approval_id"),
                comment=decision.get("comment"),
            )
        ],
        "events": [
            Event(node="review", message="승인" if action == "approve" else "거절")
        ],
    }


def route_after_review(state):
    action = state["review_decision"]["action"]
    if action == "request_changes":
        return "design_agent"
    if action == "approve" and state["review_decision"].get("publish", True):
        return "publish"
    return "report"


def validate_review(state, decision):
    if not isinstance(decision, dict):
        raise ValueError("승인 결정은 객체여야 합니다")
    action = decision.get("action")
    if action not in ("approve", "reject", "request_changes"):
        raise ValueError("최종 검토는 approve/reject/request_changes입니다")
    excluded = set(decision.get("excluded_spec_keys", []))
    if excluded and action != "request_changes":
        raise ValueError(
            "수정 대상을 제외하려면 request_changes로 재작성·재검증해야 합니다"
        )
    if not excluded <= {s.id for s in state["change_specs"]}:
        raise ValueError("이 작업에 없는 영향 위치입니다")
    if action == "request_changes" and not (decision.get("comment") or "").strip():
        raise ValueError("수정 요청에는 comment가 필요합니다")
    if action == "approve" and not state.get("demo"):
        patches = state.get("code_patches", [])
        if (
            not patches
            or state.get("system_errors")
            or any(p.status not in ("passed", "ticket_only") for p in patches)
        ):
            raise ValueError("미검증 또는 실패한 수정안은 승인할 수 없습니다")
        aid = decision.get("approval_id")
        if decision.get("publish", True) and (type(aid) is not int or aid < 1):
            raise ValueError("Spring이 발급한 approval_id가 필요합니다")
