from app.schemas import ChangeSheet, Event, Report
from app.state import RippleState

_TYPE_LABEL = {"value": "① 값", "logic": "② 로직", "db": "③ DB", "new": "④ 신규"}


def _hunks(diff: str) -> list[tuple[str, str]]:
    """'@@ file:line @@' 단위로 (위치, '- 기존 → + 수정') 쌍을 뽑는다."""
    out = []
    for block in diff.split("@@ ")[1:]:
        header, _, body = block.partition(" @@\n")
        lines = body.splitlines()
        old = next((l[1:] for l in lines if l.startswith("-")), "")
        new = next((l[1:] for l in lines if l.startswith("+")), "")
        out.append((header, f"{header}: {old} → {new}"))
    return out


def _change_sheets(state: RippleState) -> list[ChangeSheet]:
    """요건별 개발 변경 명세서. 전부 state에서 조립하는 코드 로직."""
    plan = state.get("plan")
    types = {i.spec_id: i.change_type for i in plan.items} if plan else {}
    patches = state.get("code_patches", [])
    sheets = []
    for req in state.get("requirements", []):
        specs = [s for s in state.get("change_specs", []) if s.requirement_id == req.id]
        targets = [s for s in specs if s.is_target]
        locs = {s.location for s in targets}
        mine = [p for p in patches if locs & set(p.locations)]
        if not mine:
            verification = "not_run"
        elif all(p.status == "passed" for p in mine):
            verification = "passed"
        else:
            verification = "failed"
        sheets.append(
            ChangeSheet(
                requirement_id=req.id,
                basis=f"{req.article} ({req.article_ref})",
                summary=req.summary,
                effective_date=req.effective_date,
                transitional=req.transitional,
                locations=[f"{s.location} {s.symbol} ({_TYPE_LABEL.get(types.get(s.id, ''), '미분류')})" for s in targets],
                non_targets=[f"{s.location} {s.symbol} — {s.reason}" for s in specs if not s.is_target],
                proposals=[h for p in mine for loc, h in _hunks(p.diff) if loc in locs],
                tests=[f"{t.id} [{t.kind}] {t.description}" for t in state.get("test_cases", []) if t.requirement_id == req.id],
                verification=verification,
            )
        )
    return sheets


def make_report(tools):
    """변경 명세서·PR·티켓 링크 정리 → DONE."""

    def report(state: RippleState) -> dict:
        tools.read_resource(f"reg://{state['regulation_id']}/{state['new_version']}")
        reqs = state.get("requirements", [])
        failed = [p.bundle_id for p in state.get("code_patches", []) if p.status != "passed"]
        deliveries = state.get("deliveries", [])
        approvals = state.get("approvals", [])

        blocked = None
        if not reqs:
            summary = "실질 변경 없음"
        elif approvals and not approvals[-1].approved:
            summary = f"{approvals[-1].stage} 단계에서 반려"
        elif not deliveries:
            summary = "승인되었으나 배포 없음"
            blocked = "검증 실패 항목만 남아 배포 차단" if failed else None
        else:
            summary = f"요건 {len(reqs)}건 반영, 배포 {len(deliveries)}건"

        result = Report(
            summary=summary,
            requirement_ids=[r.id for r in reqs],
            change_sheets=_change_sheets(state),
            deliveries=deliveries,
            failed_bundle_ids=failed,
            blocked_reason=blocked,
        )
        return {"result": result, "events": [Event(node="report", message=f"DONE: {summary}")]}

    return report
