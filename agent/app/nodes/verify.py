from app.nodes.design import MAX_ROUND, _retryable
from app.schemas import Event
from app.state import RippleState


def make_verify(tools):
    """check_patch로 적용·문법·테스트(state.test_cases). merge에서만 트리거된다."""

    def verify(state: RippleState) -> dict:
        patches = state.get("code_patches", [])
        res = tools.check_patch(
            patches=[p.model_dump(mode="json") for p in patches],
            test_cases=[t.model_dump(mode="json") for t in state.get("test_cases", [])],
        )
        by_id = {r["bundle_id"]: r for r in res["results"]}

        updated = []
        for p in patches:
            r = by_id.get(p.bundle_id, {"ok": False, "errors": ["검증 결과 없음"]})
            if p.status == "conflict" or not r["ok"]:
                errors = p.errors if p.status == "conflict" else r["errors"]
                updated.append(p.model_copy(update={"status": "patch_failed", "round": p.round + 1, "errors": errors}))
            else:
                updated.append(p.model_copy(update={"status": "passed", "errors": []}))

        missed = res["system"]["missed_locations"]
        failed = [p.bundle_id for p in updated if p.status == "patch_failed"]
        return {
            "code_patches": updated,
            "missed_locations": missed,
            "events": [Event(node="verify", message=f"실패 묶음 {len(failed)}개, 놓친 위치 {len(missed)}곳")],
        }

    return verify


def route_after_verify(state: RippleState) -> str:
    if state.get("human_edit_pending"):
        return "review"  # 사람이 고친 패치는 자동 재작업 없이 다시 검토로
    if state.get("missed_locations") and state.get("locate_round", 0) < MAX_ROUND:
        return "locate_agent"
    if any(_retryable(p) for p in state.get("code_patches", [])):
        return "plan"
    return "review"
