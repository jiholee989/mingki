from app.nodes.design import MAX_ROUND
from app.schemas import Event


def make_verify(tools):
    def verify(state):
        patches = state.get("code_patches", [])
        code = [p for p in patches if p.status != "ticket_only"]
        errors, updated = [], []
        executed = 0
        if state.get("demo"):
            errors = [
                "LLM 분석 확인 모드: 로컬 샘플 사용, 실제 패치·테스트 미실행"
                if state.get("llm_used")
                else "시연 모드: 실제 패치와 테스트를 실행하지 않았습니다"
            ]
            updated = [
                p.model_copy(update={"status": "unverified"}) if p in code else p
                for p in patches
            ]
        elif not code:
            updated = patches
        elif any(p.status == "patch_failed" for p in code):
            # 잘못 생성된 패치를 실행 도구에 보내지 않고 모델에 오류를 돌려준다.
            updated = patches
            errors = [error for p in code for error in p.errors]
        else:
            cases = state.get("test_cases", [])
            covered = {t.requirement_id for t in cases if t.code}
            affected = {
                s.requirement_id
                for s in state["change_specs"]
                if s.is_target and s.id in {i for p in code for i in p.spec_ids}
            }
            if not affected <= covered:
                errors = ["코드 수정 요건마다 실행 가능한 테스트가 필요합니다"]
            else:
                result = tools.check_patch(
                    patches=[p.model_dump(mode="json") for p in code],
                    test_cases=[t.model_dump(mode="json") for t in cases if t.code],
                )
                system = result.get("system", {})
                if system.get("ok") is not True:
                    errors = system.get("errors") or ["시스템 검증 실패"]
                # generated는 실행 증거가 아니다. 실제 실행 수가 없으면 발행을 차단한다.
                executed = result.get("tests", {}).get("executed", 0)
                if (
                    not isinstance(executed, int)
                    or isinstance(executed, bool)
                    or executed < 1
                ):
                    errors = [
                        *errors,
                        "실행한 테스트 수(tests.executed)를 확인할 수 없습니다",
                    ]
                by_id = {r["bundle_id"]: r for r in result.get("results", [])}
                for patch in code:
                    row = by_id.get(patch.bundle_id, {})
                    ok = row.get("ok") is True
                    updated.append(
                        patch.model_copy(
                            update={
                                "status": "passed"
                                if ok and not errors
                                else "patch_failed",
                                "errors": [*row.get("errors", []), *errors]
                                or ([] if ok else ["검증 결과 없음"]),
                            }
                        )
                    )
            if not updated:
                updated = [
                    p.model_copy(update={"status": "unverified", "errors": errors})
                    for p in code
                ]
            updated += [p for p in patches if p.status == "ticket_only"]
        return {
            "code_patches": updated,
            "system_errors": errors,
            "events": [
                Event(
                    node="verify",
                    message=f"테스트 실행 {executed}건 / {'미검증·실패' if errors or any(p.status == 'patch_failed' for p in updated) else '검증 완료'}",
                )
            ],
        }

    return verify


def route_after_verify(state):
    retry = any(p.status == "patch_failed" for p in state.get("code_patches", []))
    return "design_agent" if retry and state["retry_count"] < MAX_ROUND else "review"
