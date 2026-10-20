from fastmcp.exceptions import ToolError
from app.schemas import Delivery, Event


def make_publish(tools):
    def publish(state):
        patches = state.get("code_patches", [])
        approval = state.get("approvals", [])[-1]
        blocked = None
        if state.get("demo") or tools.is_mock:
            blocked = "시연 모드: 외부 PR·티켓을 생성하지 않았습니다"
        elif (
            not approval.approved
            or approval.stage != "review"
            or not approval.approval_id
        ):
            blocked = "유효한 최종 승인이 없습니다"
        elif state.get("system_errors") or any(
            p.status not in ("passed", "ticket_only") for p in patches
        ):
            blocked = "미검증·실패한 수정안은 발행할 수 없습니다"
        if blocked:
            return {
                "deliveries": [],
                "blocked_reason": blocked,
                "events": [Event(node="publish", message=blocked)],
            }
        task_id = state["task_id"]
        code = [p for p in patches if p.status == "passed"]
        deliveries, errors = [], []

        def submit(kind, key, function, **kwargs):
            try:
                out = function(
                    task_id=task_id,
                    approval_id=approval.approval_id,
                    idempotency_key=key,
                    **kwargs,
                )
                deliveries.append(
                    Delivery(
                        kind=kind,
                        job_id=out["jobId"],
                        status=out["status"],
                        idempotency_key=key,
                        duplicate=out.get("duplicate", False),
                        branch=out.get("branch"),
                        url=out.get("url"),
                    )
                )
            except ToolError as exc:
                errors.append(str(exc))

        if code:
            submit(
                "draft_pr",
                f"{task_id}:pr:{approval.approval_id}",
                tools.create_draft_pr,
                title=f"[Rule Ripple] {state['regulation_id']} {state['new_version']}",
                patches=[{"bundle_id": p.bundle_id, "diff": p.diff} for p in code],
                spec_keys=[sid for p in code for sid in p.spec_ids],
            )
        specs = {s.id: s for s in state["change_specs"]}
        for patch in (p for p in patches if p.status == "ticket_only"):
            submit(
                "work_ticket",
                f"{task_id}:ticket:{patch.bundle_id}:{approval.approval_id}",
                tools.create_work_ticket,
                title=f"[Rule Ripple] {patch.files[0]}",
                description=patch.proposal or patch.diff,
                type="DB"
                if any(
                    specs[sid].kind in ("db", "product_rule") for sid in patch.spec_ids
                )
                else "CODE",
                target_ref=patch.files[0],
                spec_keys=patch.spec_ids,
            )
        return {
            "deliveries": deliveries,
            "blocked_reason": "; ".join(errors) or None,
            "events": [
                Event(
                    node="publish",
                    message=f"발행 접수 {len(deliveries)}건"
                    + (" / 일부 실패" if errors else ""),
                )
            ],
        }

    return publish
