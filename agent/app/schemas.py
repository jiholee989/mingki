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
    old_value: str | None = None
    new_value: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    effective_date: date | None = None
    transitional: str | None = None


class TestCase(BaseModel):
    __test__ = False
    id: str
    requirement_id: str
    kind: Literal["boundary", "effective_date", "system", "unit"]
    description: str
    inputs: str
    expected: str
    code: str | None = Field(
        default=None, description="격리된 code-mcp에서 실행할 pytest 소스"
    )


class ChangeSpec(BaseModel):
    id: str
    requirement_id: str
    file: str
    line: int = Field(ge=0)
    symbol: str
    snippet: str
    kind: Literal["config", "code", "db", "product_rule", "ui", "new"]
    is_target: bool
    reason: str

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


class PatchResult(BaseModel):
    bundle_id: str
    files: list[str]
    spec_ids: list[str]
    locations: list[str]
    diff: str
    proposal: str = ""
    status: Literal[
        "pending", "passed", "patch_failed", "unverified", "ticket_only"
    ] = "pending"
    round: int = Field(default=1, ge=1, description="작성 회차. 실패 횟수와 구분한다")
    errors: list[str] = Field(default_factory=list)


class Approval(BaseModel):
    stage: Literal["requirements", "review"]
    approved: bool
    approval_id: int | None = None
    comment: str | None = None


class Delivery(BaseModel):
    kind: Literal["draft_pr", "work_ticket"]
    job_id: str
    status: str
    idempotency_key: str
    duplicate: bool = False
    branch: str | None = None
    url: str | None = None


class ChangeSheet(BaseModel):
    requirement_id: str
    basis: str
    summary: str
    effective_date: date | None = None
    transitional: str | None = None
    locations: list[str]
    non_targets: list[str]
    proposals: list[str]
    tests: list[str]
    verification: Literal["passed", "failed", "not_run"]


class Report(BaseModel):
    status: Literal[
        "DONE",
        "NO_CHANGE",
        "HELD",
        "REJECTED",
        "BLOCKED",
        "QUEUED",
        "READY",
        "DEMO",
        "LLM_PREVIEW",
    ]
    summary: str
    requirement_ids: list[str] = Field(default_factory=list)
    change_sheets: list[ChangeSheet] = Field(default_factory=list)
    deliveries: list[Delivery] = Field(default_factory=list)
    failed_bundle_ids: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None


class Event(BaseModel):
    node: str
    message: str
