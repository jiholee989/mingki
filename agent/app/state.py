import operator
from typing import Annotated, TypedDict

from app.schemas import (
    Approval,
    Bundle,
    ChangeSpec,
    Delivery,
    Event,
    PatchResult,
    Plan,
    Report,
    Requirement,
    TestCase,
)


def merge_patches(left: list[PatchResult] | None, right: list[PatchResult] | None) -> list[PatchResult]:
    """bundle_id 기준 upsert. 병렬 worker 결과와 verify 갱신을 모두 받는다."""
    merged = {p.bundle_id: p for p in left or []}
    for p in right or []:
        merged[p.bundle_id] = p
    return list(merged.values())


class RippleState(TypedDict, total=False):
    # 입력
    task_id: str
    regulation_id: str
    old_version: str
    new_version: str

    # 요건 · 테스트 · 위치
    requirements: list[Requirement]
    test_cases: list[TestCase]  # test_agent만 쓴다. design 쪽은 읽기만.
    change_specs: list[ChangeSpec]
    locate_round: int
    missed_locations: list[str]  # verify가 시스템 테스트 실패 시 채움

    # 설계 · 패치
    plan: Plan
    bundles: list[Bundle]
    pending_bundle_ids: list[str]  # 이번에 worker로 보낼 묶음
    code_patches: Annotated[list[PatchResult], merge_patches]

    # 사람 · 배포 · 결과
    approvals: Annotated[list[Approval], operator.add]
    review_decision: dict  # interrupt ② 재개 값 (LLM 출력 아님)
    human_edit_pending: bool
    deliveries: list[Delivery]
    result: Report
    events: Annotated[list[Event], operator.add]
