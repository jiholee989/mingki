"""Agent 내부 계약. Spring/MCP 형식 변환은 경계에서만 처리한다."""

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class Requirement(BaseModel):
    id: str
    article_id: str
    article: str
    article_ref: str
    change: Literal["modified", "added", "removed"]
    summary: str
    target: str
    behavior_change: str = Field(default="", description="변경 전후 시스템 동작의 차이")
    old_value: str | None = None
    new_value: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    effective_date: date | None = None
    transitional: str | None = None


class Event(BaseModel):
    node: str
    message: str


class ScopeCondition(BaseModel):
    text: str
    source_ref: str
    quote: str


class ProductAssessment(BaseModel):
    requirement_id: str
    product_id: str
    reason: str
    target_rule_ids: list[str] = Field(default_factory=list, description="실제로 바꿀 기존 규칙 ID만. 참고한 전체 목록 금지")
    evidence_rule_ids: list[str] = Field(default_factory=list, description="판단에 참고한 규칙 ID")
    document_refs: list[str] = Field(default_factory=list)
    scope: str = Field(default="", description="변경을 적용할 고객·거래 범위")
    applicability: Literal["all", "conditional", "excluded", "unknown"] = "unknown"
    conditions: list[ScopeCondition] = Field(default_factory=list)
    impact: Literal["change_required", "no_change", "needs_review"]


class ProductImpact(ProductAssessment):
    id: str
    product_name: str
    current: str


class RuleChange(BaseModel):
    rule_id: str
    rule_key: str
    current_value: str
    proposed_value: str
    unit: str


class ProposalText(BaseModel):
    recommendation: str = Field(max_length=220)
    actions: list[str] = Field(max_length=3)
    optional_actions: list[str] = Field(default_factory=list, max_length=2)
    precautions: list[str] = Field(max_length=2)


class ProductDraft(ProposalText):
    changes: list[RuleChange] = Field(default_factory=list)


class RevisionText(ProposalText):
    revision_response: str = Field(max_length=300, description="요청별 실제 반영 내용·반영 불가 사유")


class ProductRevision(ProductDraft):
    revision_response: str = Field(max_length=300, description="요청별 실제 반영 내용·반영 불가 사유")


class RevisionCheck(BaseModel):
    feedback_addressed: bool
    mandatory_preserved: bool
    reason: str


class ProductProposal(BaseModel):
    id: str
    product_id: str
    product_name: str
    requirement_id: str
    article_ref: str
    impact: Literal["change_required", "needs_review"]
    target_rule_ids: list[str]
    evidence_rule_ids: list[str]
    current: str
    reason: str
    recommendation: str
    actions: list[str]
    precautions: list[str]
    effective_date: date | None = None
    transitional: str | None = None
    changes: list[RuleChange] = Field(default_factory=list)
    scope: str = ""
    applicability: Literal["all", "conditional", "excluded", "unknown"] = "unknown"
    conditions: list[ScopeCondition] = Field(default_factory=list)
    optional_actions: list[str] = Field(default_factory=list)
    verification: Literal["pending", "passed", "failed"] = "pending"
    attempt: int = 1
    status: Literal["pending", "approved", "rejected", "revision_requested"] = "pending"
    version: int = Field(default=1, ge=1)
    review_comment: str = ""
    human_edited: bool = False
    document_refs: list[str] = Field(default_factory=list)
    generation_error: str | None = None
    revision_response: str = ""
    changed_fields: list[str] = Field(default_factory=list)


class ProposalReviewRecord(BaseModel):
    proposal_id: str
    version: int
    action: Literal["approve", "reject", "request_changes", "edit"]
    comment: str
    snapshot: ProductProposal


class ProductReport(BaseModel):
    status: Literal["NO_CHANGE", "NO_ACTION", "APPROVED", "PARTIALLY_APPROVED", "REJECTED", "IN_REVIEW"]
    mode: Literal["llm", "live"]
    summary: str
    proposals: list[ProductProposal]
    unchanged: list[ProductImpact]
    approved_count: int
    rejected_count: int
