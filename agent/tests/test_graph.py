"""경로 테스트. 규정·상품 규칙은 레포 루트 data/의 실제 시연 데이터를 쓴다.

기대값 출처: eval/answer_key.md (Agent 코드는 eval/을 읽지 않는다 — 테스트에서만 대조),
docs/PROJECT.md 10절 정답지(코드 위치 — 샘플 레포가 나오기 전까지 mock 인덱스).
"""

import shutil

import pytest
from langgraph.types import Command

from app.data import DATA_DIR
from app.graph import LLM_NODES, NODE_TOOLS, build_graph
from app.tools.mock import WRITE_TOOLS, MockTools

INPUT = {"task_id": "T-1", "regulation_id": "credit-loan-ops", "old_version": "v3", "new_version": "v4"}
CFG = {"configurable": {"thread_id": "T-1"}}
BUNDLE_FILES = [
    "config/policy.yaml", "db/product_rules", "src/batch/limit_job.py", "frontend/src/views/LoanApply.vue",
    "src/loan/eligibility.py", "src/loan/rate.py", "src/loan/senior_explanation.py",
]


def start(tools, input=INPUT):
    graph = build_graph(tools)
    return graph, graph.invoke(input, CFG)


def resume(graph, value):
    return graph.invoke(Command(resume=value), CFG)


def run_to_end(tools):
    graph, _ = start(tools)
    resume(graph, {"action": "approve"})
    return resume(graph, {"action": "approve"})


def interrupt_type(out):
    return out["__interrupt__"][0].value["type"]


def nodes(out):
    return [e.node for e in out["events"]]


def workers(out):
    return [e.message for e in out["events"] if e.node == "worker"]


# ---------- 데이터 기반 판단 ----------
def test_requirements_from_real_regulation_diff():
    graph, out = start(MockTools())
    reqs = {r["id"]: r for r in out["__interrupt__"][0].value["requirements"]}
    # 실질 변경 3건. 제6·17·18·19조 자구 수정은 제외
    assert set(reqs) == {"REQ-8", "REQ-15", "REQ-15-2"}
    assert (reqs["REQ-8"]["old_value"], reqs["REQ-8"]["new_value"]) == ("0.40", "0.35")
    assert (reqs["REQ-15"]["old_value"], reqs["REQ-15"]["new_value"]) == ("65", "60")
    assert reqs["REQ-15-2"]["change"] == "added"
    assert all(r["effective_date"] == "2026-12-01" for r in reqs.values())
    # 경과조치: 부칙 제2조는 제8조·제15조에, 부칙 제3조는 제15조의2에
    assert "부칙 제2조" in reqs["REQ-8"]["transitional"] and "부칙 제2조" in reqs["REQ-15"]["transitional"]
    assert "부칙 제3조" in reqs["REQ-15-2"]["transitional"]
    assert reqs["REQ-15"]["article_ref"] == "reg://credit-loan-ops/v4/15"


def test_product_rules_match_data_answer_key():
    out = run_to_end(MockTools())
    rules = {s.symbol.split()[0]: s for s in out["change_specs"] if s.kind == "product_rule"}
    assert {k for k, s in rules.items() if s.is_target} == {"R001", "R011", "R010"}
    # 함정과 대상 아님은 이유와 함께 남는다
    for rid in ("R015", "R007", "R018", "R008", "R005", "R013", "R019"):
        assert not rules[rid].is_target and rules[rid].reason
    assert "이미 신 기준" in rules["R015"].reason


def test_code_answer_key_locations_and_traps():
    out = run_to_end(MockTools())
    code = {s.symbol: s for s in out["change_specs"] if s.kind in ("config", "code", "ui")}
    must = {"is_senior", "senior_discount", "SENIOR_AGE_MONTHS", "SENIOR_AGE", "DSR_LIMIT", "recalc_limits", "dsr_notice"}
    assert {k for k, s in code.items() if s.is_target} == must
    assert {k for k, s in code.items() if not s.is_target} == {"RETIREMENT_AGE", "LTV_LIMIT"}
    patched = {f for p in out["code_patches"] for f in p.files}
    assert "src/loan/income.py" not in patched and "src/loan/ltv.py" not in patched


def test_new_obligation_gets_interface_and_failing_test():
    """④ 신규(제15조의2): MVP는 명세서 · 인터페이스 · 실패하는 테스트까지."""
    out = run_to_end(MockTools())
    spec = next(s for s in out["change_specs"] if s.requirement_id == "REQ-15-2")
    assert spec.kind == "new" and spec.is_target
    bundle = next(b for b in out["bundles"] if b.files == ["src/loan/senior_explanation.py"])
    assert bundle.change_type == "new"
    assert any(c.name == "confirm_senior_explanation" for c in out["plan"].contracts)
    tests = [t for t in out["test_cases"] if t.requirement_id == "REQ-15-2"]
    assert [t.kind for t in tests] == ["unit"] and "실패가 정상" in tests[0].expected


def test_boundary_tests_match_applicant_fixtures():
    """test_agent가 만든 경계값이 eval/fixtures/applicants.json의 경계 지점과 같다."""
    out = run_to_end(MockTools())
    bounds = {t.id for t in out["test_cases"] if t.kind == "boundary"}
    assert {"REQ-15-B-59", "REQ-15-B-60", "REQ-15-B-65"} <= bounds  # A01 / A02 / A04
    assert {"REQ-8-B-0.35", "REQ-8-B-0.37"} <= bounds  # A08 허용 / A07 거절
    sys15 = next(t for t in out["test_cases"] if t.id == "REQ-15-SYS")
    assert '"age": "62"' in sys15.inputs  # A03


def test_versioned_config_not_overwritten():
    """경과조치: 설정값을 덮어쓰지 않고 시행일 버전을 추가한다."""
    out = run_to_end(MockTools())
    policy = next(p for p in out["code_patches"] if p.files == ["config/policy.yaml"])
    assert "{value: 65}, {value: 60, effective_from: 2026-12-01}" in policy.diff
    rules = next(p for p in out["code_patches"] if p.files == ["db/product_rules"])
    assert "effective_to=2026-11-30" in rules.diff


# ---------- 경로 ----------
def test_happy_path():
    tools = MockTools()
    graph, out = start(tools)
    assert interrupt_type(out) == "confirm_requirements"

    out = resume(graph, {"action": "approve"})
    assert interrupt_type(out) == "review"
    assert out["__interrupt__"][0].value["verification_failed"] == []

    out = resume(graph, {"action": "approve"})
    assert out["result"].status == "DONE"
    assert {d.kind for d in out["deliveries"]} == {"draft_pr", "work_ticket"}
    assert nodes(out).count("test_agent") == 1
    assert nodes(out).count("verify") == 1
    assert sorted(f for b in out["bundles"] for f in b.files) == sorted(BUNDLE_FILES)

    # 같은 파일의 위치는 한 묶음
    elig = next(p for p in out["code_patches"] if p.files == ["src/loan/eligibility.py"])
    assert len(elig.locations) == 2

    # 멱등키 · approval_id 전달
    pr = tools.called("create_draft_pr")[0]
    assert pr["approval_id"] and pr["idempotency_key"].startswith("T-1:")


def test_no_substantive_change_goes_to_report(tmp_path):
    """자구 수정만 있는 개정이면 요건 0건 → 바로 report."""
    reg = tmp_path / "regulations" / "credit-loan-ops"
    reg.mkdir(parents=True)
    v3 = (DATA_DIR / "regulations" / "credit-loan-ops" / "v3.md").read_text(encoding="utf-8")
    shutil.copy(DATA_DIR / "regulations" / "credit-loan-ops" / "v3.md", reg / "v3.md")
    (reg / "v3-1.md").write_text(v3.replace("하여야 한다", "해야 한다"), encoding="utf-8")

    graph, out = start(MockTools(data_dir=tmp_path), {**INPUT, "new_version": "v3-1"})
    assert "__interrupt__" not in out
    assert nodes(out) == ["requirement_agent", "report"]
    assert out["result"].summary == "실질 변경 없음"


def test_patch_failure_reworks_only_failed_bundle():
    tools = MockTools(patch_failures={"src/batch/limit_job.py": 1})
    graph, out = start(tools)
    out = resume(graph, {"action": "approve"})
    assert interrupt_type(out) == "review"
    assert out["__interrupt__"][0].value["verification_failed"] == []

    assert len(workers(out)) == len(BUNDLE_FILES) + 1  # 전체 + 실패 묶음 1개 재작업
    assert workers(out)[-1] == "B:src/batch/limit_job.py 패치 작성 (round 1)"
    assert nodes(out).count("verify") == 2
    assert nodes(out).count("test_agent") == 1


def test_system_test_failure_reruns_locate():
    tools = MockTools(hidden_on_first_search={"SENIOR_AGE_MONTHS"})
    graph, out = start(tools)
    out = resume(graph, {"action": "approve"})
    assert interrupt_type(out) == "review"

    assert nodes(out).count("locate_agent") == 2
    assert nodes(out).count("test_agent") == 1
    assert "SENIOR_AGE_MONTHS" in {s.symbol for s in out["change_specs"]}
    # 놓친 위치가 있던 묶음(eligibility.py)만 다시 작업
    assert workers(out)[len(BUNDLE_FILES):] == ["B:src/loan/eligibility.py 패치 작성 (round 0)"]
    assert out["missed_locations"] == []


def test_two_failures_block_publish():
    tools = MockTools(patch_failures={"src/batch/limit_job.py": 2})
    graph, out = start(tools)
    out = resume(graph, {"action": "approve"})
    review = out["__interrupt__"][0].value
    assert review["verification_failed"] == ["B:src/batch/limit_job.py"]
    assert nodes(out).count("verify") == 2

    out = resume(graph, {"action": "approve"})
    # 실패 묶음은 PR에서 빠진다
    pr_files = {f for p in tools.called("create_draft_pr")[0]["patches"] for f in p["files"]}
    assert "src/batch/limit_job.py" not in pr_files
    assert out["result"].failed_bundle_ids == ["B:src/batch/limit_job.py"]


def test_all_failed_blocks_publish_entirely():
    tools = MockTools(patch_failures={f: 2 for f in BUNDLE_FILES})
    graph, out = start(tools)
    out = resume(graph, {"action": "approve"})
    assert len(out["__interrupt__"][0].value["verification_failed"]) == len(BUNDLE_FILES)

    out = resume(graph, {"action": "approve"})
    assert tools.called("create_draft_pr") == []
    assert tools.called("create_work_ticket") == []
    assert out["result"].blocked_reason


def test_review_reject_skips_publish():
    tools = MockTools()
    graph, out = start(tools)
    resume(graph, {"action": "approve"})
    out = resume(graph, {"action": "reject", "comment": "문구 확인 필요"})
    assert "publish" not in nodes(out)
    assert tools.called("create_draft_pr") == []
    assert out["result"].summary == "review 단계에서 반려"


def test_requirement_reject_skips_everything():
    graph, out = start(MockTools())
    out = resume(graph, {"action": "reject"})
    assert nodes(out) == ["requirement_agent", "confirm_requirements", "report"]


def test_human_edit_reruns_verify_then_review():
    tools = MockTools()
    graph, out = start(tools)
    resume(graph, {"action": "approve"})
    out = resume(graph, {"action": "edit", "edited_patches": [{"bundle_id": "B:src/batch/limit_job.py", "diff": "manual"}]})
    assert interrupt_type(out) == "review"
    assert nodes(out).count("verify") == 2
    edited = next(p for p in out["code_patches"] if p.bundle_id == "B:src/batch/limit_job.py")
    assert edited.human_edited and edited.status == "passed"

    out = resume(graph, {"action": "approve"})
    assert out["result"].status == "DONE"


# ---------- 명세서 ----------
def test_change_sheet_per_requirement():
    out = run_to_end(MockTools())
    sheets = {s.requirement_id: s for s in out["result"].change_sheets}
    senior = sheets["REQ-15"]
    assert senior.basis == "제15조(고령자 기준) (reg://credit-loan-ops/v4/15)"
    assert senior.transitional and senior.effective_date
    assert any("is_senior (② 로직)" in loc for loc in senior.locations)
    assert any("ELIGIBLE_MIN_AGE" in loc for loc in senior.locations)
    assert any("INCOME_EST_RETIREMENT_AGE" in n for n in senior.non_targets)
    assert {t.split()[1] for t in senior.tests} == {"[boundary]", "[effective_date]", "[system]"}
    assert senior.verification == "passed"
    # 같은 파일(policy.yaml)을 공유해도 수정안은 요건별로 나뉜다
    assert all("DSR" not in p for p in senior.proposals)
    assert any("SENIOR_AGE" in p for p in senior.proposals)


def test_change_sheet_marks_failed_verification():
    out = run_to_end(MockTools(patch_failures={"src/batch/limit_job.py": 2}))
    status = {s.requirement_id: s.verification for s in out["result"].change_sheets}
    assert status == {"REQ-8": "failed", "REQ-15": "passed", "REQ-15-2": "passed"}


# ---------- 권한 ----------
@pytest.mark.parametrize("node", sorted(LLM_NODES))
def test_write_tools_never_bound_to_llm_nodes(node):
    assert not WRITE_TOOLS & set(NODE_TOOLS[node])


def test_toolbelt_enforces_least_privilege():
    belt = MockTools().subset(*NODE_TOOLS["worker"])
    with pytest.raises(PermissionError):
        belt.create_draft_pr
