"""저장된 실행 결과를 다시 채점해 요건별로 요약한다. LLM 없이 정답지만 읽으므로 같은 파일이면 같은 숫자가 나온다.

run_agent.py 가 남긴 결과 JSON(화면 조회 응답 + run)을 받는다. 실행 (레포 루트에서):
    uv run --with pyyaml python eval/summarize_results.py eval/baseline/20261021-170231-all-*.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_agent  # noqa: E402


def main(paths):
    runs = []
    for path in paths:
        saved = json.loads(Path(path).read_text(encoding="utf-8"))
        run = dict(saved["run"])
        run["response"] = {"proposals": saved["proposals"]}
        runs.append(run)
    for expected, req_key in run_agent.scenarios("all"):
        summary = run_agent.summarize(runs, expected, req_key)
        run_agent.print_summary(summary, expected["scenario"] + f" ({req_key})")
        wrong = sorted({p["product_id"] for r in summary["rows"] if r["result"] for p in r["result"]["products"] if not p["ok"]})
        if wrong:
            print("  한 번이라도 틀린 상품: " + " · ".join(wrong))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
