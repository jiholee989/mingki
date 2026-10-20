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

    def to_decision(self):
        if self.step != "REVIEW" or self.decision != "REVIEW_PROPOSALS":
            raise ValueError("상품별 검토는 step=REVIEW, decision=REVIEW_PROPOSALS를 사용합니다")
        return {"decisions": self.payload.get("decisions", []), "finish": self.payload.get("finish", False)}


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


def product_proposals_payload(items):
    """향후 백엔드 상품 제안 저장 API에 전달할 형식. HTTP 전송은 하지 않는다."""
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
