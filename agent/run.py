"""터미널에서 그래프를 돌려 보는 스크립트. interrupt ①② 마다 사람 결정을 입력받는다.

    uv run python run.py                      # v3 → v4, 단계마다 직접 입력
    uv run python run.py --auto               # 전부 승인으로 끝까지
    uv run python run.py --fail src/batch/limit_job.py=1   # 그 파일 묶음 검증 1회 실패
    uv run python run.py --miss SENIOR_AGE_MONTHS          # 첫 탐색에서 놓침 → 시스템 테스트 → locate 재실행
"""

import argparse

from langgraph.types import Command

from app.graph import build_graph
from app.tools.mock import MockTools


def ask(prompt: str, choices: str, auto: bool) -> str:
    if auto:
        return choices[0]
    while (answer := input(f"{prompt} [{'/'.join(choices)}] ").strip().lower()) not in choices:
        pass
    return answer


def show_requirements(value: dict) -> None:
    print("\n=== interrupt ① 요건 확정 ===")
    for r in value["requirements"]:
        print(f"- {r['id']}  {r['summary']}  (대상 {r['target']}, 시행 {r['effective_date']})")
        if r["transitional"]:
            print(f"    경과조치: {r['transitional'].splitlines()[0]}")


def show_review(value: dict) -> None:
    print("\n=== interrupt ② 검토 · 승인 ===")
    for s in value["change_specs"]:
        mark = "수정" if s["is_target"] else "제외"
        print(f"- [{mark}] {s['requirement_id']:9} {s['file']}:{s['line']} {s['symbol']} — {s['reason']}")
    print("\n패치:")
    for p in value["patches"]:
        print(f"- {p['status']:12} {p['bundle_id']} (round {p['round']})")
    if value["verification_failed"]:
        print(f"\n검증 실패(기본 차단): {value['verification_failed']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", default="v3")
    parser.add_argument("--new", default="v4")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--fail", action="append", default=[], metavar="FILE=N")
    parser.add_argument("--miss", action="append", default=[], metavar="SYMBOL")
    args = parser.parse_args()

    tools = MockTools(
        patch_failures={f: int(n) for f, n in (x.split("=") for x in args.fail)},
        hidden_on_first_search=set(args.miss),
    )
    graph = build_graph(tools)
    config = {"configurable": {"thread_id": "cli"}}
    out = graph.invoke(
        {"task_id": "CLI", "regulation_id": "credit-loan-ops", "old_version": args.old, "new_version": args.new}, config
    )

    seen = 0
    while True:
        for e in out["events"][seen:]:
            print(f"  · {e.node}: {e.message}")
        seen = len(out["events"])
        if "__interrupt__" not in out:
            break
        value = out["__interrupt__"][0].value
        if value["type"] == "confirm_requirements":
            show_requirements(value)
            choice = ask("요건을 확정할까요? a=확정 r=반려", "ar", args.auto)
            decision = {"action": "approve" if choice == "a" else "reject"}
        else:
            show_review(value)
            choice = ask("a=승인 r=거절 e=패치 수정", "are", args.auto)
            if choice == "e":
                bundle_id = input("수정할 bundle_id: ").strip()
                decision = {"action": "edit", "edited_patches": [{"bundle_id": bundle_id, "diff": input("새 diff: ")}]}
            else:
                decision = {"action": "approve" if choice == "a" else "reject"}
        out = graph.invoke(Command(resume=decision), config)

    result = out["result"]
    print(f"\n=== 결과: {result.summary} ===")
    for sheet in result.change_sheets:
        print(f"\n[{sheet.requirement_id}] {sheet.basis} — 검증 {sheet.verification}")
        for p in sheet.proposals:
            print(f"   {p}")
    for d in result.deliveries:
        print(f"\n{d.kind}: {d.url}")


if __name__ == "__main__":
    main()
