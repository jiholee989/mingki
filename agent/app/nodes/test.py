import json
import math
from datetime import timedelta

from app.schemas import Event, Requirement, TestCase
from app.state import RippleState


def _is_ratio(v: str) -> bool:
    return "." in v


def _value_cases(req: Requirement) -> list[TestCase]:
    """경계값 + 시행일 전후 + 시스템 테스트. 값은 요건에서 계산한다 (eval/fixtures/applicants.json과 같은 지점)."""
    old, new, eff = req.old_value, req.new_value, req.effective_date
    after = (eff + timedelta(days=4)).isoformat() if eff else None
    cases = []

    if _is_ratio(new):
        # "초과할 수 없다": 신 한도 정확히는 허용, 신·구 사이는 거절
        mid = f"{math.floor((float(old) + float(new)) * 50) / 100:.2f}"  # 신·구 중간, 내림
        points = [(new, "APPROVE"), (mid, "REJECT")]
        field, sys_point, sys_expected = "dsr", mid, "REJECT (신청 · 심사 · 한도 배치 전부)"
    else:
        # "N세 이상": N-1은 아님, N은 해당, 종전 기준값도 해당
        n, o = int(new), int(old)
        points = [(str(n - 1), "false"), (str(n), "true"), (str(o), "true")]
        between = str((n + o) // 2)
        field, sys_point, sys_expected = "age", between, "true (신청 API 전체 흐름에서 고령자 처리)"

    for value, expected in points:
        cases.append(TestCase(
            id=f"{req.id}-B-{value}", requirement_id=req.id, kind="boundary",
            description=f"{req.target} 경계값 {field}={value}",
            inputs=json.dumps({field: value, "applied_at": after}), expected=expected,
        ))
    if eff:
        for label, d, expected in (("before", eff - timedelta(days=1), old), ("on", eff, new)):
            cases.append(TestCase(
                id=f"{req.id}-D-{label}", requirement_id=req.id, kind="effective_date",
                description=f"시행일 {label} 신청 ({d.isoformat()}) → {req.target}={expected}",
                inputs=json.dumps({field: sys_point, "applied_at": d.isoformat()}), expected=expected,
            ))
    cases.append(TestCase(
        id=f"{req.id}-SYS", requirement_id=req.id, kind="system",
        description=f"{req.target} 관련 전 구간 일관성 (놓친 위치 탐지)",
        inputs=json.dumps({field: sys_point, "applied_at": after}), expected=sys_expected,
    ))
    return cases


def _new_obligation_cases(req: Requirement) -> list[TestCase]:
    """④ 신규: 구현이 없으므로 일부러 실패하는 테스트(명세 역할)만 만든다."""
    return [TestCase(
        id=f"{req.id}-U-1", requirement_id=req.id, kind="unit",
        description=f"{req.article}: 확인을 마치지 않으면 계약 체결 불가",
        inputs=json.dumps({"explanation_confirmed": False}),
        expected="체결 거부 (현재 미구현 → 실패가 정상)",
    )]


def make_test_agent(tools):
    """요건 → 경계값 · 시행일 전후 · 시스템 테스트. 한 번만 실행되고 design은 수정할 수 없다."""

    def test_agent(state: RippleState) -> dict:
        cases: list[TestCase] = []
        for req in state["requirements"]:
            tools.get_product_rules(req.target)
            cases += _new_obligation_cases(req) if req.change == "added" else _value_cases(req)
        return {
            "test_cases": cases,
            "events": [Event(node="test_agent", message=f"테스트 {len(cases)}건 고정")],
        }

    return test_agent
