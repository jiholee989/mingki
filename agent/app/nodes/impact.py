"""로컬 또는 MCP에서 상품·규칙을 읽고 법령 요건별 영향을 정리한다. 중간 승인은 없다."""

from collections import defaultdict
from app.schemas import Event, ProductImpact, ProductAssessment
from app.data import active_rules
from app.tools.base import recorder_of, recording
from app.validation import change_problem, exemption_needs_customer_data, ground_conditions, condition_errors


def code_checks(model_reason, reason):
    """코드 검사가 모델 이유 뒤에 " / "로 덧붙인 메모. 모델 판단이 없으면 최종 이유 전체."""
    if model_reason is None:
        return [reason]
    return [note for note in reason[len(model_reason):].split(" / ") if note.strip()]


def make_product_impact_agent(tools, reasoner):
    def product_impact_agent(state, config=None):
        recorder = recorder_of(config)
        belt = recording(tools, recorder, "product_impact_agent")
        products = belt.get_products()
        rules = active_rules(belt.get_product_rules(as_of=state["snapshot_date"]), state["snapshot_date"])
        ids = [p["productId"] for p in products]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("조회된 상품이 없거나 상품 ID가 중복되었습니다")
        known = {p["productId"]: p for p in products}
        document_result = belt.get_product_documents(ids)
        documents = document_result["documents"]
        data_gaps = [*state.get("data_gaps", []), *document_result["data_gaps"]]
        document_refs = defaultdict(set)
        for doc in documents:
            if doc["productId"] not in known:
                raise ValueError("상품 문서의 상품 ID가 조회 결과와 다릅니다")
            document_refs[doc["productId"]].add(doc["uri"])
        by_product = defaultdict(dict)
        for rule in rules:
            if rule["productId"] not in known:
                raise ValueError("상품 규칙의 상품 ID를 확인할 수 없습니다")
            by_product[rule["productId"]][rule["ruleId"]] = rule
        candidates = defaultdict(list)
        req_ids = {r.id for r in state["requirements"]}
        for item in reasoner.product_impacts(state["requirements"], products, rules, state["regulation_context"], documents, data_gaps):
            if item.product_id not in known or item.requirement_id not in req_ids:
                continue  # 모델이 만든 상품·요건은 산출물에 넣지 않는다.
            candidates[(item.requirement_id, item.product_id)].append(item)
        impacts = []
        for req in state["requirements"]:
            for product in products:
                pid = product["productId"]
                rows = candidates[(req.id, pid)]
                if len(rows) == 1:
                    row = rows[0].model_copy(deep=True)
                    ground_conditions(row, {**{a["uri"]: a["text"] for a in state["regulation_context"]},
                        **{d["uri"]: d["content"] for d in documents if d["productId"] == pid}})
                    target_ids = list(dict.fromkeys(row.target_rule_ids))
                    evidence_ids = list(dict.fromkeys(row.evidence_rule_ids))
                    refs = list(dict.fromkeys(row.document_refs))
                    valid = all(rid in by_product[pid] for rid in target_ids + evidence_ids) and all(ref in document_refs[pid] for ref in refs)
                    impact = row.impact if valid else "needs_review"
                    reason = row.reason if valid else row.reason + " / 다른 상품 또는 미조회 규칙·문서 근거: 확인 필요"
                    target_ids = [rid for rid in target_ids if rid in by_product[pid]]
                    evidence_ids = [rid for rid in evidence_ids if rid in by_product[pid]]
                    refs = [ref for ref in refs if ref in document_refs[pid]]
                    if impact == "change_required":
                        # 고른 규칙이 말이 되는지 본다 (이미 기준 충족 · 다른 성격의 규칙 · 판매 중단). 걸린 규칙은 근거로만 남긴다
                        problems = {rid: p for rid in target_ids if (p := change_problem(req, by_product[pid][rid], product))}
                        if problems:
                            target_ids = [rid for rid in target_ids if rid not in problems]
                            evidence_ids = list(dict.fromkeys(evidence_ids + list(problems)))
                            reason += " / " + "; ".join(note for _, note in problems.values())
                            if not target_ids:
                                impact = "no_change" if all(v == "no_change" for v, _ in problems.values()) else "needs_review"
                    if impact == "no_change" and not evidence_ids and not refs:
                        impact = "needs_review"
                        reason += " / 유지·적용 제외를 뒷받침할 규칙·문서 근거 없음: 추가 확인"
                else:
                    target_ids, evidence_ids, refs, impact = [], [], [], "needs_review"
                    reason = "상품별 영향 판단이 누락되었거나 중복되어 추가 확인이 필요합니다"
                scope = row.scope if len(rows) == 1 else "적용 범위 추가 확인"
                applicability = row.applicability if len(rows) == 1 else "unknown"
                conditions = row.conditions if len(rows) == 1 else []
                if impact == "no_change" and exemption_needs_customer_data(req, list(by_product[pid].values())):
                    impact, applicability, target_ids = "needs_review", "unknown", []
                    reason += " / 차주별 DSR 예외 한도 충족 여부를 확인할 자료가 없어 전체 면제를 확정하지 않음"
                sources = {**{a["uri"]: a["text"] for a in state["regulation_context"]},
                           **{d["uri"]: d["content"] for d in documents if d["productId"] == pid}}
                probe = ProductAssessment(requirement_id=req.id, product_id=pid, impact=impact, reason=reason,
                                          applicability=applicability, conditions=conditions)
                if condition_errors(probe, sources):
                    evidence_ids = list(dict.fromkeys(evidence_ids + target_ids))
                    target_ids, conditions, impact, applicability = [], [], "needs_review", "unknown"
                    scope = "적용 조건·원문 근거 추가 확인"
                    reason += " / 적용 조건의 인용 근거가 확인되지 않아 수치 변경을 확정하지 않음"
                if impact == "no_change":
                    target_ids = []
                    if applicability in ("conditional", "unknown"):
                        impact = "needs_review"
                        reason += " / 조건부 예외·적용 범위를 확인해야 하므로 무조건 유지로 확정하지 않음"
                relevant = [by_product[pid][rid] for rid in target_ids]
                current = "; ".join(f"{r['ruleId']} {r['ruleKey']}={r['value']} ({r['unit']})" for r in relevant)
                impacts.append(ProductImpact(
                    id=f"{req.id}:{pid}", requirement_id=req.id, product_id=pid,
                    product_name=product["name"], impact=impact, target_rule_ids=target_ids, evidence_rule_ids=evidence_ids,
                    scope=scope, applicability=applicability, conditions=conditions,
                    document_refs=refs, reason=reason, current=current or "관련 상품 규칙이 특정되지 않음: 상품·업무 절차 확인 필요",
                ))
                if hasattr(recorder, "decided"):
                    # 모델 판단(rows[0])과 코드 검사 뒤 최종 판단을 함께 남긴다
                    model = rows[0] if len(rows) == 1 else None
                    recorder.decided("product_impact_agent", req.id, pid, model, impact, target_ids,
                                     code_checks(model.reason if model else None, reason))
        return {"products": products, "product_rules": rules, "product_impacts": impacts,
                "product_documents": documents, "data_gaps": data_gaps,
                "events": [Event(node="product_impact_agent", message=f"상품 {len(products)}개 × 변경 요건 {len(state['requirements'])}개 영향 분석 / 유효 규칙 {len(rules)}개 / 문서 {len(documents)}개")]}
    return product_impact_agent


def route_after_impact(state):
    return "proposal_agent" if any(i.impact != "no_change" for i in state["product_impacts"]) else "report"
