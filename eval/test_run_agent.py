"""run_agent.py 의 집계 테스트 (서버 없이).  실행: uv run --with pyyaml --with pytest pytest eval -q"""

import json
from pathlib import Path

import yaml

from run_agent import summarize
from score_proposals import EXPECTED

FIXTURES = Path(__file__).parent / "fixtures"
E = yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_summary_counts_passed_runs_and_products():
    runs = [
        {"status": "WAITING_REVIEW", "seconds": 60, "response": load("proposals.perfect.json")},
        {"status": "WAITING_REVIEW", "seconds": 63, "response": load("proposals.run-2026-10-21.json")},
        {"status": "FAILED", "seconds": 2, "error": "Agent 호출 실패"},
    ]
    s = summarize(runs, E)
    assert s["scored"] == 2 and s["passed"] == 1
    assert s["average"]["판정 정확도"] == (10.0, 12.0)  # (12 + 8) / 2
    assert s["average"]["정답에 없는 변경"] == (0.5, 0.0)
    assert s["per_product"]["P001"] == 2 and s["per_product"]["P010"] == 1
    assert s["rows"][2]["result"] is None and s["rows"][2]["status"] == "FAILED"


def test_summary_without_scored_runs():
    s = summarize([{"status": "TIMEOUT", "seconds": 300}], E)
    assert s["scored"] == 0 and s["passed"] == 0 and s["average"] == {}
