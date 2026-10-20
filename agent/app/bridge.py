"""그래프 실행을 Spring 콜백으로 옮긴다. 계약은 docs/BACKEND_API.md 10절.

노드에 들어갈 때 STEP, 노드가 끝나면 산출물 저장, interrupt 에서 APPROVAL_REQUIRED, 끝나면 리포트 뒤 DONE.

Agent 와 백엔드는 제안 단위가 다르다. Agent 는 상품 × 요건 1건에 규칙 변경 여러 개(changes)를 담고,
백엔드는 상품 × 규칙 1행이다. 여기서 펼친다. 유지 판정(no_change)은 Agent 에서 제안이 아니지만
백엔드는 모든 상품에 행 하나를 요구해서 keep 행으로 보낸다.

사람 확인은 1번이다 (SIMPLIFICATION v2). 백엔드의 APPROVE + 제외 목록을 Agent 의 제안별 approve · reject 로
바꾸고 finish 로 검토를 끝낸다. 수정 요청 · 직접 편집은 백엔드 경로에서 쓰지 않는다.
"""

import logging

from app.backend import requirements_payload

log = logging.getLogger(__name__)

# Agent 판정 → 백엔드 · 정답지 판정
IMPACTS = {"change_required": "change_required", "no_change": "keep", "needs_review": "needs_check"}
VERIFY = {"pending": "PENDING", "passed": "PASSED", "failed": "FAILED"}
# Agent 리포트 상태 → 백엔드 DONE outcome. 없으면 종료 상태가 아니라서 FAILED
OUTCOMES = {"NO_CHANGE": "NO_CHANGE", "NO_ACTION": "NO_CHANGE", "APPROVED": "DONE",
            "PARTIALLY_APPROVED": "DONE", "REJECTED": "REJECTED"}


def proposal_keys(proposal):
    """Agent 제안 하나가 백엔드에서 차지하는 행의 키. 규칙 변경이 있으면 규칙마다, 없으면 요건 하나."""
    if proposal.impact == "change_required" and proposal.changes:
        return [f"{proposal.product_id}:{c.rule_key}" for c in proposal.changes]
    return [f"{proposal.product_id}:{proposal.requirement_id}"]


def flatten(proposal):
    """Agent 제안 1건 → 백엔드 제안 행들 (docs/contracts/proposals.put.json 모양)."""
    base = {
        "reqKey": proposal.requirement_id,
        "productId": proposal.product_id,
        "current": proposal.current,
        "proposed": proposal.recommendation,
        "effectiveDate": proposal.effective_date.isoformat() if proposal.effective_date else None,
        "basis": proposal.article_ref,
        "reason": proposal.reason,
        "transition": proposal.transitional,
        "followUp": [*proposal.actions, *proposal.optional_actions],
        "round": proposal.attempt,
        "verifyStatus": VERIFY[proposal.verification],
        "verifyLog": proposal.generation_error,
    }
    if proposal.impact == "change_required" and proposal.changes:
        return [{**base, "proposalKey": f"{proposal.product_id}:{c.rule_key}", "ruleId": c.rule_id,
                 "ruleKey": c.rule_key, "impact": "change_required", "unit": c.unit,
                 "currentValue": c.current_value, "proposedValue": c.proposed_value}
                for c in proposal.changes]
    return [{**base, "proposalKey": f"{proposal.product_id}:{proposal.requirement_id}", "ruleId": None,
             "ruleKey": None, "impact": "needs_check", "unit": None, "currentValue": None, "proposedValue": None}]


def keep_row(impact, round_):
    """유지 판정은 Agent 제안이 아니라서 영향 판단에서 행을 만든다. 근거 검사 대상이 아니라 PASSED.

    유지는 바꿀 규칙이 없어서 target_rule_ids 가 비어 있다. 근거 규칙이 하나면 그것을 ruleId 로 둔다.
    """
    evidence = list(dict.fromkeys(impact.evidence_rule_ids))
    return {"proposalKey": f"{impact.product_id}:{impact.requirement_id}", "reqKey": impact.requirement_id,
            "productId": impact.product_id, "ruleId": evidence[0] if len(evidence) == 1 else None,
            "ruleKey": None, "impact": "keep", "current": impact.current, "proposed": None, "unit": None,
            "currentValue": None, "proposedValue": None, "effectiveDate": None, "basis": None,
            "reason": impact.reason, "transition": None, "followUp": [], "round": round_,
            "verifyStatus": "PASSED", "verifyLog": None}


def review_decision(proposals, decision, payload, comment=None):
    """백엔드 확인(10.3) → Agent 검토 명령. 반영으로 고른 행이 하나라도 있는 제안만 approve, 나머지는 reject."""
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError("decision 은 APPROVE | REJECT 입니다")
    approved = set(payload.get("approvedProposalKeys") or []) if decision == "APPROVE" else set()
    decisions = []
    for p in proposals:
        if p.status != "pending":
            continue
        action = "approve" if any(k in approved for k in proposal_keys(p)) else "reject"
        decisions.append({"proposal_id": p.id, "version": p.version, "action": action, "comment": comment or ""})
    return {"decisions": decisions, "finish": True}


class SpringBridge:
    def __init__(self, spring):
        self.spring = spring
        self.round = 0
        self.keep_rows = []

    # ---------- 노드 ----------

    def node_started(self, node):
        if node == "review":
            return
        payload = {"node": node}
        if node == "proposal_agent":
            self.round += 1
        if node == "verify":
            payload["round"] = self.round
        self.spring.event("STEP", payload)

    def node_updated(self, node, delta):
        if node == "requirement_agent":
            self.spring.put("requirements", requirements_payload(delta["requirements"]))
        elif node == "product_impact_agent":
            self.keep_rows = [i for i in delta["product_impacts"] if i.impact == "no_change"]
        elif node in ("proposal_agent", "verify"):
            items = [row for p in delta["proposals"] for row in flatten(p)]
            items += [keep_row(i, self.round) for i in self.keep_rows]
            self.spring.put("proposals", {"items": items})
        message = _message(delta)
        if message and node != "review":
            self.spring.event("STEP", {"node": node, "message": message})

    # ---------- 멈춤 · 종료 ----------

    def finish(self, out):
        if out.get("__interrupt__"):
            self.spring.event("APPROVAL_REQUIRED", {"step": "REVIEW"})
            return
        result = out["result"]
        self.spring.put("report", report_payload(result))
        outcome = OUTCOMES.get(result.status)
        if outcome:
            self.spring.event("DONE", {"outcome": outcome})
        else:
            self.spring.event("FAILED", {"reason": f"종료 상태가 아닙니다: {result.status} ({result.summary})"})

    def fail(self, exc):
        log.exception("Agent 실행 실패")
        try:
            self.spring.event("FAILED", {"reason": f"Agent 실행 실패: {exc}"})
        except Exception:
            log.exception("FAILED 이벤트 전송 실패")


def _message(delta):
    events = delta.get("events") or []
    return events[-1].message if events else None


def report_payload(result):
    data = result.model_dump(mode="json")
    lines = ["# Rule Ripple 상품 변경 제안서", "", f"**{result.status}** · {result.summary}"]
    for p in result.proposals:
        mark = {"approved": "반영", "rejected": "제외"}.get(p.status, p.status)
        lines += ["", f"## {p.product_name} ({p.product_id}) — {mark}", "",
                  f"- 근거: {p.article_ref}", f"- 현재: {p.current}", f"- 제안: {p.recommendation}"]
        lines += [f"- {c.rule_id} {c.rule_key}: {c.current_value} → {c.proposed_value} ({c.unit})" for c in p.changes]
        lines += [f"- 조치: {a}" for a in p.actions]
    if result.unchanged:
        lines += ["", "## 유지", ""]
        lines += [f"- {i.product_name} ({i.product_id}): {i.reason}" for i in result.unchanged]
    return {"markdown": "\n".join(lines), **data}
