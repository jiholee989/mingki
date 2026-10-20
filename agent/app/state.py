import operator
from typing import Annotated, TypedDict
from app.schemas import (
    Approval,
    ChangeSpec,
    Delivery,
    Event,
    PatchResult,
    Report,
    Requirement,
    TestCase,
)


class RippleState(TypedDict, total=False):
    task_id: str
    regulation_id: str
    old_version: str
    new_version: str
    requirements: list[Requirement]
    change_specs: list[ChangeSpec]
    test_cases: list[TestCase]
    code_patches: list[PatchResult]
    design_round: int
    retry_count: int
    system_errors: list[str]
    review_decision: dict
    revision_comment: str
    blocked_reason: str | None
    demo: bool
    llm_used: bool
    approvals: Annotated[list[Approval], operator.add]
    events: Annotated[list[Event], operator.add]
    deliveries: list[Delivery]
    result: Report
