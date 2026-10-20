from collections import defaultdict
from app.patches import validate_diff
from app.reasoning import Draft
from app.schemas import Event, PatchResult

MAX_ROUND = 2
TICKET_KINDS = {"db", "product_rule", "new"}


def file_content(result):
    if isinstance(result, str):
        return result
    if isinstance(result, dict) and isinstance(result.get("content"), str):
        return result["content"]
    raise ValueError("get_file은 문자열 또는 {content: 문자열}을 반환해야 합니다")


def make_design_agent(tools, reasoner):
    def design_agent(state):
        grouped = defaultdict(list)
        for spec in state["change_specs"]:
            if spec.is_target:
                grouped[spec.file].append(spec)
        previous = {p.bundle_id: p for p in state.get("code_patches", [])}
        round_ = state.get("design_round", 0) + 1
        patches = []
        for path, specs in grouped.items():
            bid = f"B:{path}"
            old = previous.get(bid)
            if (
                old
                and old.status in ("passed", "ticket_only")
                and not state.get("revision_comment")
                and not state.get("system_errors")
            ):
                patches.append(old)
                continue
            ticket = any(s.kind in TICKET_KINDS for s in specs)
            content = None if ticket else file_content(tools.get_file(path))
            context = {
                "requirements": [
                    r.model_dump(mode="json") for r in state["requirements"]
                ],
                "specs": [
                    {**s.model_dump(mode="json"), "location": s.location} for s in specs
                ],
                "file": path,
                "content": content,
                "ticket_only": ticket,
                "tests": [t.model_dump(mode="json") for t in state["test_cases"]],
                "previous_diff": old.diff if old else None,
                "errors": [
                    *(old.errors if old else []),
                    *state.get("system_errors", []),
                ],
                "comment": state.get("revision_comment", ""),
            }
            draft, errors = Draft(diff="", proposal=""), []
            try:
                draft = reasoner.draft(context)
                if not ticket and not reasoner.is_demo:
                    validate_diff(draft.diff, specs)
            except ValueError as exc:
                errors = [f"수정안 생성 오류: {exc}"]
            patches.append(
                PatchResult(
                    bundle_id=bid,
                    files=[path],
                    spec_ids=[s.id for s in specs],
                    locations=sorted({s.location for s in specs}),
                    diff=draft.diff,
                    proposal=draft.proposal,
                    status="patch_failed"
                    if errors
                    else "ticket_only"
                    if ticket
                    else "pending",
                    round=round_,
                    errors=errors,
                )
            )
        return {
            "code_patches": patches,
            "design_round": round_,
            "retry_count": state.get("retry_count", 0) + 1,
            "revision_comment": "",
            "blocked_reason": None,
            "events": [
                Event(
                    node="design_agent", message=f"{round_}회차 수정안 {len(patches)}개"
                )
            ],
        }

    return design_agent
