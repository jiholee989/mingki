"""AI 작업 기록: 도구 호출(TOOL_START · TOOL_END)과 상품별 판단(DECISION). 실제 Spring · LLM 없이 확인한다."""

import pytest

from app.schemas import ProductAssessment
from app.spring import SpringError
from app.tools.base import recording
from app.tools.local import LocalTools
from tests.test_graph import DsrReasoner
from tests.test_server import FakeSpring, in_order, started


class Recorder:
    def __init__(self):
        self.calls = []

    def tool_started(self, node, tool, args):
        self.calls.append(("start", node, tool, args))

    def tool_finished(self, node, tool, *, ok, ms, summary=None, error=None):
        self.calls.append(("end", node, tool, ok, summary, error))


class Tools:
    is_local = True

    def get_products(self, status=None):
        return [{"productId": "P001"}, {"productId": "P002"}]

    def get_product_documents(self, ids):
        return {"documents": [{"productId": i} for i in ids], "data_gaps": []}

    def broken(self):
        raise TimeoutError("MCP 응답 없음")


def records(spring, type_):
    return [body for kind, name, body in spring.calls if kind == "event" and name == type_]


# ---------- 도구 호출 감싸기 ----------

def test_recording_reports_start_end_and_summary():
    rec = Recorder()
    belt = recording(Tools(), rec, "product_impact_agent")
    assert len(belt.get_products()) == 2
    belt.get_product_documents(["P001", "P002", "P003"])
    assert rec.calls == [
        ("start", "product_impact_agent", "get_products", {}),
        ("end", "product_impact_agent", "get_products", True, "2건", None),
        ("start", "product_impact_agent", "get_product_documents", {"args": ["3개"]}),  # ID 목록은 개수로
        ("end", "product_impact_agent", "get_product_documents", True, "documents 3건, data_gaps 0건", None),
    ]
    assert belt.is_local


def test_recording_reports_failure_and_raises_the_same_error():
    rec = Recorder()
    with pytest.raises(TimeoutError):
        recording(Tools(), rec, "requirement_agent").broken()
    assert rec.calls[-1] == ("end", "requirement_agent", "broken", False, None, "MCP 응답 없음")


def test_without_recorder_tools_are_used_as_is():
    tools = Tools()
    assert recording(tools, None, "apply") is tools


# ---------- 백엔드로 가는 기록 ----------

def test_run_records_tool_calls_and_one_decision_per_product():
    _, spring, _ = started()
    tools = [(b["node"], b["tool"]) for b in records(spring, "TOOL_END")]
    assert tools == [("requirement_agent", "diff_versions"), ("requirement_agent", "get_regulation_context"),
                     ("product_impact_agent", "get_products"), ("product_impact_agent", "get_product_rules"),
                     ("product_impact_agent", "get_product_documents")]
    assert all(b["ok"] and b["ms"] >= 0 for b in records(spring, "TOOL_END"))
    assert in_order([f"{n}:{b.get('tool') or b.get('node')}" for k, n, b in spring.calls if k == "event"],
                    ["STEP:requirement_agent", "TOOL_START:diff_versions", "TOOL_END:diff_versions",
                     "STEP:product_impact_agent", "TOOL_START:get_products", "DECISION:product_impact_agent"])
    decisions = {b["productId"]: b for b in records(spring, "DECISION")}
    assert set(decisions) == {"P001", "P002", "P003"}
    assert decisions["P003"]["model"]["impact"] == decisions["P003"]["final"]["impact"] == "keep"
    assert decisions["P001"]["checks"] == []


def test_decision_shows_what_the_code_check_changed():
    """실제 실행의 P004(R037, 이미 30%)와 P007(R060 개월 규칙)을 모델 판단과 최종 판단으로 나눠 남긴다."""
    class RealMistakes(DsrReasoner):
        def product_impacts(self, requirements, products, rules, *args):
            picks = {"P004": ["R037"], "P007": ["R060", "R056"]}
            return [ProductAssessment(requirement_id="REQ-8", product_id=pid, target_rule_ids=rids, evidence_rule_ids=rids,
                                      scope="시행일 이후 신규 신청", applicability="all", impact="change_required",
                                      reason="DSR 한도 변경") for pid, rids in picks.items()]
    _, spring, _ = started(tools=LocalTools(), reasoner=RealMistakes())
    decisions = {b["productId"]: b for b in records(spring, "DECISION")}
    p004, p007 = decisions["P004"], decisions["P007"]
    assert (p004["model"]["impact"], p004["model"]["targetRuleIds"]) == ("change_required", ["R037"])
    assert (p004["final"]["impact"], p004["final"]["targetRuleIds"]) == ("keep", [])
    assert "R037" in p004["checks"][0] and "이미 개정 한도" in p004["checks"][0]
    assert p007["final"] == {"impact": "change_required", "targetRuleIds": ["R056"]}
    assert any("R060" in note for note in p007["checks"])
    assert decisions["P001"]["model"] is None  # 모델이 판단하지 않은 상품은 판단 없음으로 남긴다


def test_record_failure_does_not_fail_the_run():
    class RecordsRejected(FakeSpring):
        def event(self, type_, payload=None):
            if type_ in ("TOOL_START", "TOOL_END", "DECISION"):
                raise SpringError("기록 저장 실패 (500)")
            super().event(type_, payload)
    _, spring, _ = started(spring=RecordsRejected())
    assert spring.kinds()[-1] == "APPROVAL_REQUIRED:REVIEW"
    assert not records(spring, "FAILED")
