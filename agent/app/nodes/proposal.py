"""신규 제안 또는 선택한 항목만 작성한다. 검증 실패 재시도는 같은 버전에서 수행한다."""

from app.schemas import Event, ProductProposal, RuleChange
from app.validation import expected_value, new_rule_change, normalize

CONTENT_FIELDS = ("recommendation", "actions", "optional_actions", "precautions", "changes")


def changed_fields(before, after):
    def normalized(value):
        if isinstance(value, list):
            return sorted(str(v.model_dump()) if hasattr(v, "model_dump") else normalize(v) for v in value)
        return normalize(value)
    return [name for name in CONTENT_FIELDS if normalized(getattr(before, name)) != normalized(getattr(after, name))]


def make_proposal_agent(reasoner):
    def proposal_agent(state):
        previous = {p.id: p for p in state.get("proposals", [])}
        baselines = dict(state.get("revision_baselines", {}))
        requirements = {r.id: r for r in state["requirements"]}
        products = {p["productId"]: p for p in state["products"]}
        proposals, generated = [], 0
        for impact in state["product_impacts"]:
            if impact.impact == "no_change":
                continue
            old = previous.get(impact.id)
            retry = old and old.verification == "failed" and old.attempt < 2 and old.status == "pending"
            requested = old and old.status == "revision_requested"
            if old and not retry and not requested:
                proposals.append(old)
                continue
            if requested:
                baselines[impact.id] = old.model_copy(deep=True)
            baseline = baselines.get(impact.id)
            req = requirements[impact.requirement_id]
            rules = [r for r in state["product_rules"] if r["productId"] == impact.product_id]
            contract = [{"rule_id": r["ruleId"], "rule_key": r["ruleKey"], "current_value": r["value"],
                         "proposed_value": expected_value(req, r["unit"]), "unit": r["unit"]}
                        for r in rules if r["ruleId"] in impact.target_rule_ids]
            if impact.impact == "change_required" and not impact.target_rule_ids and req.change == "added":
                contract = [new_rule_change(req)]  # 새로 생긴 의무: 바꿀 기존 규칙이 없으니 새 규칙을 더한다
            context = {"requirement": req.model_dump(mode="json"), "regulation_context": state["regulation_context"],
                       "product": products[impact.product_id], "rules": rules,
                       "documents": [d for d in state.get("product_documents", []) if d["productId"] == impact.product_id],
                       "data_gaps": state.get("data_gaps", []), "impact": impact.model_dump(mode="json"),
                       "mandatory_changes": contract, "previous_proposal": baseline.model_dump(mode="json") if baseline else None,
                       "comment": baseline.review_comment if baseline else "",
                       "validation_errors": [old.generation_error] if retry else [],
                       "previous_attempt": old.model_dump(mode="json") if retry else None}
            error, response = None, ""
            try:
                draft = reasoner.draft_product(context)
                content = {name: getattr(draft, name) for name in CONTENT_FIELDS}
                response = getattr(draft, "revision_response", "")
            except ValueError as exc:
                error = str(exc)
                content = {name: getattr(baseline, name) for name in CONTENT_FIELDS} if baseline else {
                    "recommendation": "제안 작성 실패: 상세에서 원인을 확인하세요", "actions": [],
                    "optional_actions": [], "precautions": [],
                    "changes": [RuleChange(**c) for c in contract if c["proposed_value"] is not None]}
            proposals.append(ProductProposal(
                id=impact.id, product_id=impact.product_id, product_name=impact.product_name,
                requirement_id=req.id, article_ref=req.article_ref, impact=impact.impact,
                target_rule_ids=impact.target_rule_ids, evidence_rule_ids=impact.evidence_rule_ids,
                current=impact.current, reason=impact.reason, scope=impact.scope,
                applicability=impact.applicability, conditions=impact.conditions,
                effective_date=req.effective_date, transitional=req.transitional, **content,
                version=old.version if retry else old.version + 1 if old else 1,
                attempt=old.attempt + 1 if retry else 1,
                review_comment=baseline.review_comment if baseline else "", document_refs=impact.document_refs,
                basis_refs=impact.basis_refs,
                generation_error=error, revision_response=response,
            ))
            generated += 1
        return {"proposals": proposals, "revision_baselines": baselines, "review_finish": False,
                "events": [Event(node="proposal_agent", message=f"제안 {generated}건 작성 → 검증")]}
    return proposal_agent
