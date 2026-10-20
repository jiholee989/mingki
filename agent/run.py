"""demo=고정 규칙, llm=실제 모델+로컬 자료, live=실제 모델+MCP."""

import argparse
import logging
import uuid
from pathlib import Path
from dotenv import load_dotenv


def ask(prompt, choices, auto):
    if auto:
        return choices[0]
    while True:
        answer = input(prompt + " ").strip().lower()
        if answer in choices:
            return answer


def main():
    parser = argparse.ArgumentParser(
        description="규정 근거·영향 분석 → 사람 확인 → 수정안·검증"
    )
    parser.add_argument("--mode", choices=("demo", "llm", "live"), default="demo")
    parser.add_argument("--regulation", default="credit-loan-ops")
    parser.add_argument("--old", default="v3")
    parser.add_argument("--new", default="v4")
    parser.add_argument(
        "--auto", action="store_true", help="demo/llm 모드에서 두 검토 자동 진행"
    )
    parser.add_argument(
        "--publish", action="store_true", help="최종 승인 후 외부 PR·티켓 요청"
    )
    parser.add_argument("--approval-id", type=int, help="Spring이 발급한 최종 승인 ID")
    args = parser.parse_args()
    if args.mode == "live" and args.auto:
        parser.error("live 모드에서는 검토를 직접 진행하세요")
    if args.publish and (
        args.mode != "live" or not args.approval_id or args.approval_id < 1
    ):
        parser.error("발행에는 live 모드와 Spring의 --approval-id가 필요합니다")
    # CLI는 이 프로젝트의 설정을 사용한다. 셸에 남은 다른 프로젝트 키와 섞지 않는다.
    load_dotenv(Path(__file__).with_name(".env"), override=True)
    from app.graph import build_graph
    from app.runner import AgentRunner, DecisionError

    if args.mode in ("llm", "live"):
        from app.llm import LlmReasoner

        reasoner = LlmReasoner()
        logger = logging.getLogger("app.llm")
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[LLM] %(message)s"))
        logger.addHandler(handler)
        if args.mode == "live":
            from app.tools.mcp_client import McpTools

            mcp_logger = logging.getLogger("app.tools.mcp_client")
            mcp_logger.setLevel(logging.INFO)
            mcp_handler = logging.StreamHandler()
            mcp_handler.setFormatter(logging.Formatter("[MCP] %(message)s"))
            mcp_logger.addHandler(mcp_handler)
            mcp_logger.propagate = False
            tools = McpTools()
            print("[LIVE] 실제 LLM + MCP 서버 조회·검증. 외부 발행은 별도 승인.", flush=True)
        else:
            from app.tools.mock import MockTools

            tools = MockTools()
            print(
                "[LLM] 실제 모델 + 로컬 샘플 자료. MCP 연결·실제 검증·외부 발행 없음.",
                flush=True,
            )
    else:
        from app.demo import DemoReasoner
        from app.tools.mock import MockTools

        reasoner, tools = DemoReasoner(), MockTools()
        print("[DEMO] 샘플 데이터·고정 규칙 사용. 실제 코드 검증·외부 발행 없음.")
    try:
        runner = AgentRunner(build_graph(tools, reasoner))
        task_id = f"CLI-{uuid.uuid4().hex[:8]}"
        out = runner.start(task_id, args.regulation, args.old, args.new)
        seen = 0
        while True:
            for event in out.get("events", [])[seen:]:
                print(f"  · {event.node}: {event.message}")
            seen = len(out.get("events", []))
            if "__interrupt__" not in out:
                break
            value = out["__interrupt__"][0].value
            if value["type"] == "confirm_requirements":
                print("\n① 변경 근거·영향 위치 검토")
                for req in value["requirements"]:
                    print(
                        f"- {req['id']} {req['summary']} | 근거 {req['article_ref']} | 시행 {req['effective_date']}"
                    )
                for spec in value["change_specs"]:
                    label = "확인 필요" if spec["needs_review"] else "대상" if spec["is_target"] else "비대상"
                    line = spec["line"] or ("신규" if spec["kind"] == "new" else "미확인")
                    print(
                        f"  [{label}] {spec['file']}:{line} {spec['symbol']}: {spec['reason']}"
                    )
                    if spec["before"] or spec["after"]:
                        print(f"    변경 전: {spec['before']} → 변경 후: {spec['after']}")
                choice = ask(
                    "수정 대상을 확정할까요? a=확정 r=보류", ("a", "r"), args.auto
                )
                decision = {"action": "approve" if choice == "a" else "reject"}
            else:
                print("\n② 수정안·검증 결과 검토")
                for patch in value["patches"]:
                    print(
                        f"- {patch['bundle_id']} [{patch['status']}]\n{patch['proposal']}\n{patch['diff']}"
                    )
                    for error in patch.get("errors", []):
                        print(f"  수정안 확인 필요: {error}")
                for error in value["system_errors"]:
                    print(f"  확인 필요: {error}")
                choice = ask(
                    "a=검토 완료 r=거절 c=수정 요청", ("a", "r", "c"), args.auto
                )
                decision = {
                    "action": {"a": "approve", "r": "reject", "c": "request_changes"}[
                        choice
                    ],
                    "publish": args.publish,
                    "approval_id": args.approval_id,
                }
                if choice == "c":
                    decision["comment"] = input("수정 요청 내용: ").strip()
                if (
                    choice == "a"
                    and not value["demo"]
                    and (value["verification_failed"] or value["system_errors"])
                ):
                    print("검증 미통과: 수정 요청 또는 거절을 선택하세요.")
                    continue
            try:
                out = runner.resume(task_id, decision)
            except DecisionError as exc:
                if args.auto:
                    raise SystemExit(f"자동 진행 중단: {exc}") from None
                print(f"결정을 반영하지 못했습니다: {exc}")
        print(f"\n[{out['result'].status}] {out['result'].summary}")
        if out["result"].blocked_reason:
            print(out["result"].blocked_reason)
    finally:
        tools.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if getattr(exc, "status_code", None) == 401:
            raise SystemExit(
                "OpenAI 인증 실패(401): agent/.env의 OPENAI_API_KEY와 프로젝트 권한을 확인하세요."
            ) from None
        raise
