"""그래프에서 사용하는 모델 인터페이스와 구조화 출력."""

from typing import Protocol
from pydantic import BaseModel
from app.schemas import Requirement, ProductAssessment, ProductDraft, RevisionCheck


class RequirementJudgment(BaseModel):
    """바뀐 본문 조항 하나에 대한 모델 판단. 요건의 개수 · 번호 · 조항 · 원문은 코드가 정한다."""
    is_material: bool
    summary: str
    target: str
    behavior_change: str
    old_value: str | None
    new_value: str | None


class BehaviorOutput(BaseModel):
    behavior_change: str


class ProductAssessmentsOutput(BaseModel):
    items: list[ProductAssessment]


class Reasoner(Protocol):
    def requirements(self, diff: dict) -> list[Requirement]: ...
    def product_impacts(self, requirements, products, rules, regulation_context=None, documents=None, data_gaps=None) -> list[ProductAssessment]: ...
    def draft_product(self, context: dict) -> ProductDraft: ...
    def check_revision(self, context: dict) -> RevisionCheck: ...
