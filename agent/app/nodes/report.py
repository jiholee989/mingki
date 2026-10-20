from app.schemas import ChangeSheet, Event, Report


def make_report():
    def report(state):
        patches = state.get("code_patches", [])
        sheets = []
        for req in state.get("requirements", []):
            specs = [
                s for s in state.get("change_specs", []) if s.requirement_id == req.id
            ]
            ids = {s.id for s in specs if s.is_target}
            mine = [p for p in patches if ids.intersection(p.spec_ids)]
            checked = [p for p in mine if p.status != "ticket_only"]
            verification = "not_run"
            if checked and not state.get("demo"):
                verification = (
                    "passed" if all(p.status == "passed" for p in checked) else "failed"
                )
            sheets.append(
                ChangeSheet(
                    requirement_id=req.id,
                    basis=f"{req.article} ({req.article_ref})",
                    summary=req.summary,
                    effective_date=req.effective_date,
                    transitional=req.transitional,
                    locations=[
                        f"{s.location} {s.symbol}" for s in specs if s.is_target
                    ],
                    non_targets=[
                        f"{s.location} {s.symbol}: {s.reason}"
                        for s in specs
                        if not s.is_target
                    ],
                    proposals=[p.proposal or p.diff for p in mine],
                    tests=[
                        f"{t.id}: {t.description}"
                        for t in state.get("test_cases", [])
                        if t.requirement_id == req.id
                    ],
                    verification=verification,
                )
            )
        deliveries = state.get("deliveries", [])
        approvals = state.get("approvals", [])
        reason = state.get("blocked_reason")
        if not state.get("requirements"):
            status, summary = "NO_CHANGE", "실질 변경 없음"
        elif approvals and not approvals[-1].approved:
            status = "HELD" if approvals[-1].stage == "requirements" else "REJECTED"
            summary = "분석 보류" if status == "HELD" else "수정안 거절"
        elif state.get("demo"):
            if state.get("llm_used"):
                status, summary = (
                    "LLM_PREVIEW",
                    "실제 LLM 분석 완료: 로컬 샘플 사용, 실제 검증·외부 발행 없음",
                )
            else:
                status, summary = "DEMO", "시연 완료: 실제 검증·외부 발행 없음"
        elif (
            approvals
            and approvals[-1].stage == "review"
            and approvals[-1].approved
            and not state.get("review_decision", {}).get("publish", True)
        ):
            status, summary = "READY", "검토 완료: 발행 요청 없음"
        elif reason or not deliveries:
            status, summary = "BLOCKED", "발행 미완료"
            reason = reason or "발행할 수정안이 없습니다"
        elif any(d.status != "DONE" for d in deliveries):
            status, summary = "QUEUED", f"발행 {len(deliveries)}건 접수: 완료 확인 필요"
        else:
            status, summary = "DONE", f"발행 {len(deliveries)}건 완료"
        result = Report(
            status=status,
            summary=summary,
            requirement_ids=[r.id for r in state.get("requirements", [])],
            change_sheets=sheets,
            deliveries=deliveries,
            blocked_reason=reason,
            failed_bundle_ids=[
                p.bundle_id
                for p in patches
                if p.status in ("patch_failed", "unverified")
            ],
        )
        return {"result": result, "events": [Event(node="report", message=summary)]}

    return report
