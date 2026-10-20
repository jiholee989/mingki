"""법령 변경 → 상품별 제안 → 부분 승인·직접 수정·재작성. 실제 업무 변경은 하지 않는다."""

import argparse
import logging
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.cli import select_proposals, review_command, show_review, show_details, show_unchanged


def configure_log(name, prefix, verbose=False):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO if verbose else logging.WARNING)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(f"[{prefix}] %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False


def main():
    parser = argparse.ArgumentParser(description="법령 변경 → 상품별 변경 제안 → 부분 승인·수정 요청")
    parser.add_argument("--mode", choices=("llm", "live"), default="llm", help="자료 출처: llm=로컬 샘플(기본), live=MCP·백엔드. 둘 다 실제 LLM 사용")
    parser.add_argument("--regulation", default="credit-loan-ops")
    parser.add_argument("--article", action="append", default=[], help="분석할 변경 조항 ID. 예: --article 8 (여러 번 지정 가능)")
    parser.add_argument("--old", default="v3")
    parser.add_argument("--new", default="v4")
    parser.add_argument("--verbose", action="store_true", help="LLM·MCP 요청 로그 표시")
    args = parser.parse_args()
    # 자료 경로 등 환경 설정을 읽은 뒤 Agent 모듈을 불러온다.
    load_dotenv(Path(__file__).with_name(".env"), override=True)
    from app.graph import build_graph
    from app.runner import AgentRunner, DecisionError
    from app.llm import LlmReasoner
    reasoner = LlmReasoner()
    configure_log("app.llm", "LLM", args.verbose)
    if args.mode == "live":
        from app.tools.mcp_client import McpTools
        configure_log("app.tools.mcp_client", "MCP", args.verbose)
        tools = McpTools()
        print("[LIVE] 실제 LLM + 규정·업무 MCP. 상품 변경 제안만 작성합니다.", flush=True)
    else:
        from app.tools.local import LocalTools
        tools = LocalTools()
        print("[LLM] 실제 LLM + 로컬 규정·상품 샘플. MCP 사용 없음.", flush=True)
    try:
        if args.mode == "live":
            tools.check_connection()
        runner = AgentRunner(build_graph(tools, reasoner))
        task_id = f"CLI-{uuid.uuid4().hex[:8]}"
        out = runner.start(task_id, args.regulation, args.old, args.new, article_ids=args.article)
        seen = 0
        while True:
            for event in out.get("events", [])[seen:]:
                print(f"  · {event.node}: {event.message}")
            seen = len(out.get("events", []))
            if "__interrupt__" not in out:
                break
            value = out["__interrupt__"][0].value
            show_review(value)
            while True:
                try:
                    command = input("검토 명령: ").strip()
                    if command.startswith("v "):
                        for proposal in select_proposals(command[2:], value["proposals"]):
                            show_details(proposal)
                        continue
                    if command == "k":
                        show_unchanged(value["unchanged"])
                        continue
                    decision = review_command(command, value["proposals"])
                    out = runner.resume(task_id, decision)
                    break
                except (DecisionError, ValueError) as exc:
                    print(f"결정을 반영하지 못했습니다: {exc}")
        print(f"\n[{out['result'].status}] {out['result'].summary}")
        print("제안서 검토 결과입니다. 실제 상품·DB·코드 변경이나 외부 발행은 수행하지 않았습니다.")
    finally:
        tools.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if getattr(exc, "status_code", None) == 401:
            raise SystemExit("LLM 인증 실패: agent/.env의 API 키와 권한을 확인하세요.") from None
        raise
