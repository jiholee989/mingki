"""Spring 전송 계약 변환. HTTP 호출/DB 접근 없이 테스트할 수 있는 연결 지점."""

from pydantic import BaseModel, ConfigDict, Field

class DocumentInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    side: str
    version_label: str = Field(alias="versionLabel")
    filename: str = ""
    sha256: str = ""


class RunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    thread_id: str = Field(alias="threadId")
    documents: list[DocumentInfo]
    callback_base_url: str | None = Field(default=None, alias="callbackBaseUrl")

    def to_input(self, regulation_id):
        # regulation_id는 업로드 원문을 등록한 MCP의 식별자를 전달받는다.
        versions = {doc.side: doc.version_label for doc in self.documents}
        if (
            set(versions) != {"OLD", "NEW"}
            or len(self.documents) != 2
            or not regulation_id
        ):
            raise ValueError("구·신 문서 정보와 MCP 규정 식별자가 필요합니다")
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "regulation_id": regulation_id,
            "old_version": versions["OLD"],
            "new_version": versions["NEW"],
        }


class ResumeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    thread_id: str = Field(alias="threadId")
    step: str
    decision: str = "REVIEW_PROPOSALS"
    approval_id: int | None = Field(default=None, alias="approvalId")
    comment: str | None = None
    payload: dict = Field(default_factory=dict)

    def to_decision(self, proposals=None):
        if self.step != "REVIEW":
            raise ValueError("상품 제안 검토는 step=REVIEW를 사용합니다")
        if self.decision == "REVIEW_PROPOSALS":
            return {"decisions": self.payload.get("decisions", []), "finish": self.payload.get("finish", False)}
        if self.decision not in ("APPROVE", "REJECT") or proposals is None:
            raise ValueError("검토 결정과 현재 제안이 필요합니다")
        approved = self.payload.get("approvedProposalKeys", [])
        excluded = self.payload.get("excludedProposalKeys", [])
        if not all(isinstance(keys, list) and all(isinstance(k, str) and k for k in keys)
                   and len(keys) == len(set(keys)) for keys in (approved, excluded)):
            raise ValueError("승인·제외 키는 중복 없는 문자열 목록이어야 합니다")
        rows = rule_proposals_payload(proposals)["items"]
        change_keys = {row["proposalKey"] for row in rows if row["impact"] == "change_required"}
        if self.decision == "APPROVE":
            if not approved or set(approved) & set(excluded) or set(approved) | set(excluded) != change_keys:
                raise ValueError("승인·제외 키가 현재 변경 제안과 일치하지 않습니다")
            from app.schemas import ApplyApproval
            approval = ApplyApproval(approval_id=self.approval_id, proposal_keys=approved)
        else:
            if approved:
                raise ValueError("거절 요청에 승인 대상이 포함되어 있습니다")
            approval = None
        decisions = []
        for proposal in proposals:
            keys = {row["proposalKey"] for row in proposal_rows(proposal) if row["impact"] == "change_required"}
            decisions.append({"proposal_id": proposal.id, "version": proposal.version,
                              "action": "approve" if keys & set(approved) else "reject",
                              "comment": self.comment or "백엔드 검토 결정"})
        return {"decisions": decisions, "finish": True,
                "apply_approval": approval.model_dump() if approval else None}


def requirements_payload(items):
    return {
        "items": [
            {
                "reqKey": r.id,
                "summary": r.summary,
                "target": r.target,
                "effectiveDate": r.effective_date.isoformat()
                if r.effective_date
                else None,
                "transitional": r.transitional,
                "articleRef": r.article_ref,
                "oldText": r.old_text,
                "newText": r.new_text,
                "detail": r.model_dump(mode="json"),
            }
            for r in items
        ]
    }


def proposal_rows(proposal):
    """검토 묶음을 백엔드의 상품 × 규칙 행으로 펼친다. 키는 작성 버전이 바뀌어도 유지한다."""
    p = proposal
    rows = []
    for change in p.changes or [None]:
        rows.append({
            "proposalKey": f"{p.product_id}:{change.rule_key}" if change else p.id,
            "reqKey": p.requirement_id, "productId": p.product_id,
            "ruleId": change.rule_id if change else None, "ruleKey": change.rule_key if change else None,
            "impact": "change_required" if change and p.impact == "change_required" else "needs_check",
            "current": p.current, "proposed": p.recommendation,
            "unit": change.unit if change else None,
            "currentValue": change.current_value if change else None,
            "proposedValue": change.proposed_value if change else None,
            "effectiveDate": p.effective_date.isoformat() if p.effective_date else None,
            "basis": p.article_ref, "reason": p.reason, "transition": p.transitional,
            "followUp": p.actions + p.optional_actions, "round": p.attempt,
            "verifyStatus": p.verification.upper(), "verifyLog": p.generation_error,
        })
    return rows


def rule_proposals_payload(items, unchanged=(), rules=()):
    """BACKEND_API 10.2: 유지 판정도 빠짐없이 전송한다. HTTP 전송은 어댑터가 담당한다."""
    rows = [row for proposal in items for row in proposal_rows(proposal)]
    known = {r["ruleId"]: r for r in rules}
    for impact in unchanged:
        evidence = [known[rid] for rid in impact.evidence_rule_ids if rid in known]
        rule = evidence[0] if len(evidence) == 1 else None
        rows.append({"proposalKey": impact.id, "reqKey": impact.requirement_id,
                     "productId": impact.product_id, "ruleId": rule["ruleId"] if rule else None,
                     "ruleKey": rule["ruleKey"] if rule else None, "impact": "keep",
                     "current": impact.current, "proposed": None,
                     "unit": rule["unit"] if rule else None, "currentValue": rule["value"] if rule else None,
                     "proposedValue": None, "effectiveDate": None, "basis": None,
                     "reason": impact.reason, "transition": None, "followUp": [],
                     "round": 1, "verifyStatus": "PASSED", "verifyLog": None})
    keys = [row["proposalKey"] for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("같은 상품·규칙의 제안이 중복되었습니다. 요건을 확인하세요")
    return {"items": rows}


def product_proposals_payload(items):
    """기존 CLI 검토 형식. 백엔드 10.2 저장에는 rule_proposals_payload를 사용한다."""
    return {"items": [{
        "proposalKey": p.id, "reqKey": p.requirement_id,
        "productId": p.product_id, "productName": p.product_name,
        "articleRef": p.article_ref, "impact": p.impact, "targetRuleIds": p.target_rule_ids, "evidenceRuleIds": p.evidence_rule_ids, "documentRefs": p.document_refs,
        "changes": [c.model_dump() for c in p.changes], "scope": p.scope,
        "conditions": [c.model_dump() for c in p.conditions], "verification": p.verification,
        "optionalActions": p.optional_actions, "current": p.current, "reason": p.reason, "proposed": p.recommendation,
        "actions": p.actions, "precautions": p.precautions,
        "effectiveDate": p.effective_date.isoformat() if p.effective_date else None,
        "transitional": p.transitional, "status": p.status, "version": p.version,
        "humanEdited": p.human_edited, "reviewComment": p.review_comment,
        "generationError": p.generation_error,
        "revisionResponse": p.revision_response, "changedFields": p.changed_fields,
    } for p in items]}
