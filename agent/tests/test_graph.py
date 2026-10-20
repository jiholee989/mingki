"""그래프 경로·발행 차단·Spring/MCP 계약. 외부 API는 호출하지 않는다."""

import copy
import subprocess
import sys

import pytest
from app.backend import (
    ResumeRequest,
    change_specs_payload,
    patches_payload,
    requirements_payload,
)
from app.demo import DemoReasoner
from app.graph import LLM_NODES, NODE_TOOLS, build_graph
from app.reasoning import Draft
from app.runner import AgentRunner
from app.schemas import ChangeSpec, TestCase
from app.tools.base import WRITE_TOOLS
from app.tools.mock import MockTools


def start(tools=None, reasoner=None):
    tools = tools or MockTools()
    runner = AgentRunner(build_graph(tools, reasoner))
    return runner, runner.start("T1", "credit-loan-ops"), tools


def test_first_approval_includes_evidence_and_locations_before_any_design():
    runner, out, tools = start()
    value = out["__interrupt__"][0].value
    assert value["type"] == "confirm_requirements"
    assert len(value["requirements"]) == 3 and len(value["change_specs"]) == 21
    assert all(r["article_ref"] for r in value["requirements"])
    assert not out.get("code_patches") and not out.get("test_cases")
    assert tools.called("search_code") and not tools.called("check_patch")


def test_demo_never_claims_verification_or_creates_deliveries():
    runner, _, tools = start()
    out = runner.resume("T1", {"action": "approve"})
    assert out["__interrupt__"][0].value["type"] == "review"
    assert {p.status for p in out["code_patches"]} == {"unverified", "ticket_only"}
    assert all(t.code is None for t in out["test_cases"])
    out = runner.resume("T1", {"action": "approve"})
    assert out["result"].status == "DEMO"
    assert not tools.called("create_draft_pr") and not tools.called(
        "create_work_ticket"
    )
    assert not tools.called("check_patch")


def test_rejection_stops_before_design():
    runner, _, tools = start()
    out = runner.resume("T1", {"action": "reject"})
    assert out["result"].status == "HELD"
    assert not out.get("code_patches")


def test_partial_confirmation_and_scope_exclusion():
    runner, out, _ = start()
    excluded = next(s.id for s in out["change_specs"] if s.symbol == "senior_discount")
    out = runner.resume(
        "T1",
        {
            "action": "approve",
            "confirmed_req_keys": ["REQ-15"],
            "excluded_spec_keys": [excluded],
        },
    )
    assert {r.id for r in out["requirements"]} == {"REQ-15"}
    assert all(
        s.requirement_id == "REQ-15" and s.id != excluded for s in out["change_specs"]
    )
    assert all(t.requirement_id == "REQ-15" for t in out["test_cases"])


def test_invalid_confirmation_can_be_retried_without_losing_checkpoint():
    runner, _, _ = start()
    with pytest.raises(ValueError):
        runner.resume("T1", {"action": "approve", "confirmed_req_keys": ["unknown"]})
    out = runner.resume("T1", {"action": "approve"})
    assert out["__interrupt__"][0].value["type"] == "review"


def test_runner_rejects_duplicate_start_wrong_task_and_wrong_stage():
    runner, _, _ = start()
    with pytest.raises(ValueError):
        runner.start("T1", "credit-loan-ops")
    with pytest.raises(ValueError):
        runner.resume("T1", {"action": "approve"}, task_id="other")
    with pytest.raises(ValueError):
        runner.resume("T1", {"action": "approve"}, step="REVIEW")
    with pytest.raises(ValueError):
        runner.resume("missing", {"action": "approve"})


def test_spring_resume_translation():
    runner, _, _ = start()
    req = ResumeRequest.model_validate(
        {
            "taskId": "T1",
            "threadId": "T1",
            "step": "REQUIREMENTS",
            "decision": "CONFIRM",
            "payload": {"confirmedReqKeys": ["REQ-8"]},
        }
    )
    out = runner.resume_backend(req)
    assert {r.id for r in out["requirements"]} == {"REQ-8"}
    assert out["__interrupt__"][0].value["type"] == "review"


class FixtureReasoner(DemoReasoner):
    """외부 모델을 대신하는 고정 응답. 생성 패치의 동작은 실제 pytest로 확인한다."""

    is_demo = False

    def __init__(self, fail_first=False):
        self.contexts = []
        self.fail_first = fail_first

    def requirements(self, diff):
        return [r for r in super().requirements(diff) if r.id == "REQ-8"]

    def locate(self, state, tools):
        return [
            ChangeSpec(
                id="s",
                requirement_id="REQ-8",
                file="loan.py",
                line=1,
                symbol="LIMIT",
                snippet="LIMIT = 0.40",
                kind="code",
                is_target=True,
                reason="DSR 적용",
            )
        ]

    def tests(self, state, tools):
        return [
            TestCase(
                id="dsr",
                requirement_id="REQ-8",
                kind="boundary",
                description="DSR 경계",
                inputs="{}",
                expected="35% 허용, 37% 거절",
                code="from loan import allowed\ndef test_limit():\n    assert allowed(0.35)\n    assert not allowed(0.37)\n",
            )
        ]

    def draft(self, context):
        self.contexts.append(copy.deepcopy(context))
        value = "0.40" if self.fail_first and len(self.contexts) == 1 else "0.35"
        extra = " # 첫 시도" if value == "0.40" else ""
        return Draft(
            diff=f"@@ loan.py:1 @@\n-LIMIT = 0.40\n+LIMIT = {value}{extra}",
            proposal="DSR 한도 변경",
        )


class LocalSandbox(MockTools):
    """테스트 소유 임시 폴더에만 패치를 적용하고 실제 pytest를 실행한다."""

    is_mock = False

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.base = "LIMIT = 0.40\ndef allowed(dsr):\n    return dsr <= LIMIT\n"

    def get_file(self, path):
        return self.base

    def check_patch(self, patches, test_cases):
        self._log("check_patch", patches=patches, test_cases=test_cases)
        root = self.path / f'round-{len(self.called("check_patch"))}'
        root.mkdir()
        added = [
            line[1:] for line in patches[0]["diff"].splitlines() if line.startswith("+")
        ]
        (root / "loan.py").write_text(
            "\n".join(added) + "\n" + "\n".join(self.base.splitlines()[1:]) + "\n"
        )
        (root / "test_policy.py").write_text("\n".join(t["code"] for t in test_cases))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--confcutdir",
                str(root),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
        ok = result.returncode == 0
        return {
            "results": [
                {
                    "bundle_id": patches[0]["bundle_id"],
                    "ok": ok,
                    "errors": [] if ok else [result.stdout],
                }
            ],
            "system": {"ok": ok, "errors": [] if ok else [result.stdout]},
            "tests": {"executed": 1},
        }


def test_actual_patch_and_tests_then_queue_not_done(tmp_path):
    reasoner = FixtureReasoner()
    runner, _, tools = start(LocalSandbox(tmp_path), reasoner)
    out = runner.resume("T1", {"action": "approve"})
    assert out["code_patches"][0].status == "passed"
    assert "LIMIT = 0.40" in reasoner.contexts[0]["content"]
    out = runner.resume("T1", {"action": "approve", "approval_id": 42})
    assert out["result"].status == "QUEUED"  # 접수와 완료를 구분한다.
    assert tools.called("create_draft_pr")[0]["approval_id"] == 42


def test_retry_uses_real_failure_feedback_and_keeps_tests(tmp_path):
    reasoner = FixtureReasoner(fail_first=True)
    runner, _, tools = start(LocalSandbox(tmp_path), reasoner)
    out = runner.resume("T1", {"action": "approve"})
    assert out["code_patches"][0].status == "passed"
    assert len(reasoner.contexts) == 2 and reasoner.contexts[1]["errors"]
    assert reasoner.contexts[0]["previous_diff"] is None
    assert "첫 시도" in reasoner.contexts[1]["previous_diff"]
    assert (
        tools.called("check_patch")[0]["test_cases"]
        == tools.called("check_patch")[1]["test_cases"]
    )
    assert out["code_patches"][0].round == 2


@pytest.mark.parametrize("mode", ["system_failure", "no_execution_count", "no_result"])
def test_unverified_or_system_failure_blocks_approval_and_writes(tmp_path, mode):
    class Broken(LocalSandbox):
        def check_patch(self, patches, test_cases):
            return {
                "results": []
                if mode == "no_result"
                else [{"bundle_id": patches[0]["bundle_id"], "ok": True, "errors": []}],
                "system": {
                    "ok": mode != "system_failure",
                    "errors": ["integration failed"]
                    if mode == "system_failure"
                    else [],
                },
                "tests": {"executed": 0 if mode == "no_execution_count" else 1},
            }

    runner, _, tools = start(Broken(tmp_path), FixtureReasoner())
    out = runner.resume("T1", {"action": "approve"})
    assert out["code_patches"][0].status == "patch_failed"
    with pytest.raises(ValueError, match="미검증"):
        runner.resume("T1", {"action": "approve", "approval_id": 42})
    out = runner.resume("T1", {"action": "reject"})
    assert out["result"].status == "REJECTED" and not tools.called("create_draft_pr")


def test_missing_test_code_is_unverified(tmp_path):
    class NoCode(FixtureReasoner):
        def tests(self, state, tools):
            return [
                t.model_copy(update={"code": None}) for t in super().tests(state, tools)
            ]

    runner, _, tools = start(LocalSandbox(tmp_path), NoCode())
    out = runner.resume("T1", {"action": "approve"})
    assert out["code_patches"][0].status == "unverified"
    assert not tools.called("check_patch")


def test_request_changes_rebuilds_and_reverifies_before_new_approval(tmp_path):
    reasoner = FixtureReasoner()
    runner, _, tools = start(LocalSandbox(tmp_path), reasoner)
    runner.resume("T1", {"action": "approve"})
    out = runner.resume(
        "T1", {"action": "request_changes", "comment": "경계값 설명 보완"}
    )
    assert out["__interrupt__"][0].value["type"] == "review"
    assert reasoner.contexts[-1]["comment"] == "경계값 설명 보완"
    assert len(tools.called("check_patch")) == 2
    assert out["code_patches"][0].round == 2
    assert not tools.called("create_draft_pr")


def test_final_exclusion_requires_reverification(tmp_path):
    runner, _, _ = start(LocalSandbox(tmp_path), FixtureReasoner())
    out = runner.resume("T1", {"action": "approve"})
    with pytest.raises(ValueError, match="재검증"):
        runner.resume(
            "T1",
            {
                "action": "approve",
                "approval_id": 42,
                "excluded_spec_keys": [out["change_specs"][0].id],
            },
        )


def test_backend_payloads_keep_ids_and_one_based_round(tmp_path):
    runner, first, _ = start(LocalSandbox(tmp_path), FixtureReasoner())
    assert requirements_payload(first["requirements"])["items"][0]["reqKey"] == "REQ-8"
    assert (
        change_specs_payload(first["change_specs"])["items"][0]["specKey"] == "SPEC-1"
    )
    out = runner.resume("T1", {"action": "approve"})
    row = patches_payload(out["code_patches"])["items"][0]
    assert (
        row["round"] == 1
        and row["verifyStatus"] == "PASSED"
        and row["specKeys"] == ["SPEC-1"]
    )


@pytest.mark.parametrize("node", sorted(LLM_NODES))
def test_no_write_tools_in_analysis_nodes(node):
    assert not WRITE_TOOLS.intersection(NODE_TOOLS[node])


def test_toolbelt_rejects_write_access():
    belt = MockTools().subset("search_code")
    with pytest.raises(PermissionError):
        belt.create_draft_pr()


def test_streaming_boundary_reports_updates_and_still_resumes():
    updates = []
    runner = AgentRunner(
        build_graph(MockTools()),
        on_update=lambda node, delta: updates.append((node, delta)),
    )
    out = runner.start("stream", "credit-loan-ops")
    assert [name for name, _ in updates] == ["requirement_agent", "locate_agent"]
    assert out["__interrupt__"][0].value["type"] == "confirm_requirements"
    out = runner.resume("stream", {"action": "approve"})
    assert out["__interrupt__"][0].value["type"] == "review"
    out = runner.resume("stream", {"action": "reject"})
    assert out["result"].status == "REJECTED" and updates[-1][0] == "report"


def test_same_location_keeps_multiple_requirement_relations():
    class Shared(DemoReasoner):
        def locate(self, state, tools):
            return [
                ChangeSpec(
                    id="",
                    requirement_id=r.id,
                    file="shared.py",
                    line=1,
                    symbol="check",
                    snippet="check(dsr, age)",
                    kind="code",
                    is_target=True,
                    reason="두 정책을 함께 사용하는 코드",
                )
                for r in state["requirements"]
                if r.change == "modified"
            ]

    _, out, _ = start(reasoner=Shared())
    assert {s.requirement_id for s in out["change_specs"]} == {"REQ-8", "REQ-15"}
    assert len({s.id for s in out["change_specs"]}) == 2


def test_run_payload_uses_document_versions_and_explicit_mcp_registration():
    from app.backend import RunRequest

    request = RunRequest.model_validate(
        {
            "taskId": "backend-task",
            "threadId": "backend-thread",
            "documents": [
                {"side": "OLD", "versionLabel": "v3"},
                {"side": "NEW", "versionLabel": "v4"},
            ],
        }
    )
    runner = AgentRunner(build_graph(MockTools()))
    out = runner.start_backend(request, regulation_id="credit-loan-ops")
    assert out["task_id"] == "backend-task"
    assert out["__interrupt__"][0].value["type"] == "confirm_requirements"
    with pytest.raises(ValueError):
        request.to_input(None)


def test_no_changes_does_not_wait_for_approval():
    class NoChanges(DemoReasoner):
        def requirements(self, diff):
            return []

    _, out, tools = start(reasoner=NoChanges())
    assert out["result"].status == "NO_CHANGE" and "__interrupt__" not in out
    assert not tools.called("search_code")


def test_preview_does_not_require_spring_id_or_write(tmp_path):
    runner, _, tools = start(LocalSandbox(tmp_path), FixtureReasoner())
    runner.resume("T1", {"action": "approve"})
    out = runner.resume("T1", {"action": "approve", "publish": False})
    assert out["result"].status == "READY" and not tools.called("create_draft_pr")


def test_invalid_model_patch_is_repaired_before_sandbox_execution(tmp_path):
    class InvalidFirst(FixtureReasoner):
        def draft(self, context):
            if not self.contexts:
                self.contexts.append(copy.deepcopy(context))
                return Draft(diff="invalid patch", proposal="잘못된 형식")
            return super().draft(context)

    reasoner = InvalidFirst()
    runner, _, tools = start(LocalSandbox(tmp_path), reasoner)
    out = runner.resume("T1", {"action": "approve"})
    assert out["code_patches"][0].status == "passed"
    assert "수정안 생성 오류" in reasoner.contexts[1]["errors"][0]
    assert len(tools.called("check_patch")) == 1


def test_llm_with_local_samples_is_distinct_from_fixed_rule_demo():
    runner, _, tools = start(MockTools(), FixtureReasoner())
    out = runner.resume("T1", {"action": "approve"})
    assert out["llm_used"] and out["demo"]
    assert out["code_patches"][0].status == "unverified"
    assert not tools.called("check_patch")
    out = runner.resume("T1", {"action": "approve", "publish": True})
    assert out["result"].status == "LLM_PREVIEW"
    assert not tools.called("create_draft_pr") and not tools.called(
        "create_work_ticket"
    )


def test_cli_llm_mode_does_not_construct_mcp_client(monkeypatch, capsys):
    import run
    import app.llm
    import app.tools.mcp_client

    monkeypatch.setattr(app.llm, "LlmReasoner", lambda: FixtureReasoner())

    def no_mcp():
        raise AssertionError("LLM 로컬 모드에서 MCP 연결을 시도했습니다")

    monkeypatch.setattr(app.tools.mcp_client, "McpTools", no_mcp)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "llm", "--auto"])
    run.main()
    assert "[LLM_PREVIEW]" in capsys.readouterr().out


def test_cli_uses_project_dotenv_instead_of_stale_shell_key(monkeypatch, tmp_path):
    import os
    import run
    import app.llm

    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=local-test-key\nOPENAI_MODEL=local-test-model\n"
    )
    monkeypatch.setattr(run, "__file__", str(tmp_path / "run.py"))
    monkeypatch.setenv("OPENAI_API_KEY", "stale-shell-key")
    monkeypatch.setenv("OPENAI_MODEL", "stale-shell-model")

    def local_reasoner():
        assert os.environ["OPENAI_API_KEY"] == "local-test-key"
        assert os.environ["OPENAI_MODEL"] == "local-test-model"
        return FixtureReasoner()

    monkeypatch.setattr(app.llm, "LlmReasoner", local_reasoner)
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "llm", "--auto"])
    run.main()


def test_cli_does_not_repeat_approval_when_model_execution_fails(monkeypatch):
    import run
    import app.llm

    class BadTests(FixtureReasoner):
        def tests(self, state, tools):
            raise ValueError("모델 출력 형식 오류")

    monkeypatch.setattr(app.llm, "LlmReasoner", lambda: BadTests())
    monkeypatch.setattr(sys, "argv", ["run.py", "--mode", "llm", "--auto"])
    with pytest.raises(ValueError, match="모델 출력 형식"):
        run.main()


def test_confirming_scope_does_not_turn_uncertain_location_into_patch():
    class Uncertain(DemoReasoner):
        def locate(self, state, tools):
            items = super().locate(state, tools)
            for item in items:
                if item.is_target and item.kind in ("code", "config", "ui"):
                    item.needs_review = True
            return items

    runner, out, _ = start(reasoner=Uncertain())
    uncertain = {s.id for s in out["change_specs"] if s.needs_review}
    assert uncertain
    assert all(not s.is_target for s in out["change_specs"] if s.needs_review)
    out = runner.resume("T1", {"action": "approve"})
    assert all(not uncertain.intersection(p.spec_ids) for p in out["code_patches"])


@pytest.mark.parametrize("decision, action", [("CONFIRMED", "approve"), ("HELD", "reject")])
def test_main_requirement_decision_names(decision, action):
    request = ResumeRequest.model_validate({
        "taskId": "T1", "threadId": "T1", "step": "REQUIREMENTS",
        "decision": decision, "payload": {"confirmedReqKeys": ["REQ-8"]},
    })
    assert request.to_decision()["action"] == action


def test_empty_patch_set_is_not_reported_as_verified():
    from app.nodes.verify import make_verify
    result = make_verify(MockTools())({"code_patches": [], "demo": False})
    assert result["system_errors"]
    assert "검증 완료" not in result["events"][0].message


def test_ticket_only_review_does_not_claim_test_success():
    from app.nodes.verify import make_verify
    from app.schemas import PatchResult
    patch = PatchResult(bundle_id="B:new", files=["new.py"], spec_ids=["S1"], locations=[], diff="", status="ticket_only")
    result = make_verify(MockTools())({"code_patches": [patch], "demo": False})
    assert not result["system_errors"]
    assert "검증 대상 없음" in result["events"][0].message


def test_verified_subset_does_not_hide_missing_confirmed_requirement():
    from app.nodes.verify import make_verify
    from app.schemas import PatchResult
    reqs = DemoReasoner().requirements(MockTools().diff_versions("credit-loan-ops", "v3", "v4"))
    patch = PatchResult(bundle_id="B:new", files=["new.py"], spec_ids=["S1"], locations=[], diff="", status="ticket_only")
    location = ChangeSpec(id="S1", requirement_id=reqs[0].id, file="new.py", line=0, symbol="new", snippet="", kind="new", is_target=True, reason="new")
    result = make_verify(MockTools())({"code_patches": [patch], "requirements": reqs, "change_specs": [location], "demo": False})
    assert any("빠진 확정 요건" in error for error in result["system_errors"])
