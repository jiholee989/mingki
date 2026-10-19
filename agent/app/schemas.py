"""팀 공유 계약 스키마.

LLM 구조화 출력(`with_structured_output`)에도 쓰이므로 OpenAI strict 스키마 제약을 지킨다.
- dict 필드 금지 (자유 형식 값은 JSON 문자열로)
- 복잡한 기본값 금지 (기본값은 None / 빈 리스트 / 단순 리터럴만)
"""

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field

# ---------- 요건 ----------
class Requirement(BaseModel):
    id: str = Field(description="reqKey. 조항 기준으로 고정: REQ-8, REQ-15-2")
    article_id: str = Field(description="data/regulations 조항 ID. 예: 8, 15-2")
    article: str = Field(description="조항 표기. 예: 제15조의2(고령자 설명 확인)")
    article_ref: str = Field(description="신 원문 Resource URI. 예: reg://credit-loan-ops/v4/15")
    change: Literal["modified", "added"] = Field(description="modified=기존 조항 변경, added=신설(④ 신규 의무)")
    summary: str = Field(description="변경 내용 한 줄 요약")
    target: str = Field(description="변경 대상 정책 키. 예: DSR_LIMIT, SENIOR_AGE")
    old_value: str | None = None
    new_value: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    effective_date: date | None = None
    transitional: str | None = Field(default=None, description="경과조치 설명 (부칙 원문)")

# ---------- 테스트 ----------
class TestCase(BaseModel):
    __test__ = False  # pytest 수집 대상 아님

    id: str
    requirement_id: str
    kind: Literal["boundary", "effective_date", "system", "unit"]
    description: str
    inputs: str = Field(description="입력값 JSON 문자열")
    expected: str


# ---------- 영향 위치 ----------
class ChangeSpec(BaseModel):
    id: str
    requirement_id: str
    file: str
    line: int
    symbol: str
    snippet: str
    kind: Literal["config", "code", "db", "product_rule", "ui", "new"]
    is_target: bool
    reason: str = Field(description="대상/대상 아님 판단 이유")

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"

# ---------- 설계 ----------
ChangeType = Literal["value", "logic", "db", "new"]  # ①값 ②로직 ③DB ④신규

class PlanItem(BaseModel):
    spec_id: str
    change_type: ChangeType

class Contract(BaseModel):
    name: str
    kind: Literal["config_key", "function_signature"]
    definition: str


class Bundle(BaseModel):
    """worker 하나가 맡는 파일(모듈) 묶음. 같은 파일의 위치는 반드시 한 묶음."""

    id: str
    files: list[str]
    spec_ids: list[str]
    change_type: ChangeType
    stage: int = Field(description="의존 순서. ③DB 변경은 0, 나머지는 1")


class Plan(BaseModel):
    items: list[PlanItem]
    contracts: list[Contract]
    bundles: list[Bundle]


# ---------- 패치 ----------
PatchStatus = Literal["pending", "merged", "conflict", "passed", "patch_failed"]


class PatchResult(BaseModel):
    bundle_id: str
    files: list[str]
    locations: list[str] = Field(description="이 패치가 다루는 file:line 목록")
    diff: str
    status: PatchStatus = "pending"
    round: int = Field(default=0, description="검증 실패 횟수 (최대 2)")
    errors: list[str] = []
    human_edited: bool = False


# ---------- 승인 · 배포 · 결과 ----------
class Approval(BaseModel):
    stage: Literal["requirements", "review"]
    approved: bool
    approval_id: str | None = None
    comment: str | None = None


class Delivery(BaseModel):
    kind: Literal["draft_pr", "work_ticket"]
    url: str
    idempotency_key: str


class ChangeSheet(BaseModel):
    """변경 1건당 개발 변경 명세서 (핵심 결과물)."""

    requirement_id: str
    basis: str = Field(description="근거 조항 + 원문 링크")
    summary: str
    effective_date: date | None = None
    transitional: str | None = None
    locations: list[str] = Field(description="수정 대상 file:line symbol (유형)")
    non_targets: list[str] = Field(description="대상 아님 file:line symbol — 이유")
    proposals: list[str] = Field(description="수정안 (diff 요약)")
    tests: list[str]
    verification: Literal["passed", "failed", "not_run"]


class Report(BaseModel):
    status: Literal["DONE"] = "DONE"
    summary: str
    requirement_ids: list[str] = []
    change_sheets: list[ChangeSheet] = []
    deliveries: list[Delivery] = []
    failed_bundle_ids: list[str] = []
    blocked_reason: str | None = None


class Event(BaseModel):
    """진행 이벤트 (프론트 진행 표시용)."""

    node: str
    message: str
