from app.schemas import ProductReport, Event


def make_report():
    def report(state):
        proposals = state.get("proposals", [])
        approved = sum(p.status == "approved" for p in proposals)
        rejected = sum(p.status == "rejected" for p in proposals)
        if state.get("apply_error"):
            status, summary = "FAILED", "상품 규칙 반영 실패: " + state["apply_error"]
        elif state.get("apply_approval"):
            results = state.get("apply_results", [])
            if results and all(item.status == "DONE" for item in results):
                status, summary = "DONE", f"상품 규칙 {len(results)}건 반영 완료"
            else:
                status, summary = "FAILED", "상품 규칙 반영 완료를 확인하지 못했습니다"
        elif not state.get("requirements"):
            status, summary = "NO_CHANGE", "실질적인 법령 변경 없음"
        elif not proposals:
            status, summary = "NO_ACTION", "상품별 영향 검토 결과 변경 제안 없음"
        elif approved + rejected < len(proposals):
            status, summary = "IN_REVIEW", "검토 미완료 항목 있음"
        elif approved == len(proposals):
            status, summary = "APPROVED", f"상품 변경 제안 {approved}건 승인"
        elif approved:
            status, summary = "PARTIALLY_APPROVED", f"제안 {approved}건 승인 / {rejected}건 제외"
        else:
            status, summary = "REJECTED", "모든 제안 제외"
        mode = state["mode"]
        return {"result": ProductReport(status=status, mode=mode, summary=summary,
                    proposals=proposals, unchanged=[i for i in state.get("product_impacts", []) if i.impact == "no_change"],
                    approved_count=approved, rejected_count=rejected,
                    apply_results=state.get("apply_results", []), apply_error=state.get("apply_error")),
                "events": [Event(node="report", message=summary if state.get("apply_approval") else summary + " (제안서 검토 결과이며 실제 상품 변경 아님)")]}
    return report
