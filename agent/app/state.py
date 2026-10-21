"""상품 변경 제안 작업의 공통 상태. 승인·수정 이력은 누적한다."""

import operator
from typing import Annotated, Literal, TypedDict
from app.schemas import Event, Requirement, ProductImpact, ProductProposal, ProposalReviewRecord, ProductReport, ApplyApproval, ApplyResult


class RippleState(TypedDict, total=False):
    task_id: str
    regulation_id: str
    old_version: str
    new_version: str
    article_ids: list[str]
    snapshot_date: str
    data_gaps: list[str]
    product_documents: list[dict]
    regulation_context: list[dict]
    requirements: list[Requirement]
    products: list[dict]
    product_rules: list[dict]
    rule_catalog: list[dict]  # 끝나지 않은 규칙 전체 (반영 예정 포함). 새 규칙 이름 재사용 · 중복 방지
    product_impacts: list[ProductImpact]
    proposals: list[ProductProposal]
    revision_baselines: dict[str, ProductProposal]
    review_history: Annotated[list[ProposalReviewRecord], operator.add]
    apply_approval: ApplyApproval | None
    apply_results: list[ApplyResult]
    apply_error: str | None
    review_finish: bool
    events: Annotated[list[Event], operator.add]
    mode: Literal["llm", "live"]
    result: ProductReport
