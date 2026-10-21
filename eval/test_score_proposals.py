"""score_proposals.py 테스트.  실행: uv run --with pyyaml --with pytest pytest eval -q"""

import copy
import json
from pathlib import Path

import pytest
import yaml

from score_proposals import EXPECTED, load_proposals, score

ROOT = Path(__file__).resolve().parents[1]
E = yaml.safe_load(EXPECTED.read_text(encoding="utf-8"))
PERFECT = json.loads((Path(__file__).parent / "fixtures" / "proposals.perfect.json").read_text(encoding="utf-8"))


def items():
    return copy.deepcopy(PERFECT["items"])


def by_pid(rows, pid):
    return next(r for r in rows if r["productId"] == pid)


def test_perfect_answer_passes():
    r = score(load_proposals(PERFECT), E)
    assert r["passed"]
    assert r["core"]["판정 정확도"] == {"ok": 12, "total": 12}
    assert r["core"]["변경 대상 recall"] == {"ok": 6, "total": 6}
    assert r["core"]["keep · needs_check 근거"] == {"ok": 4, "total": 4}
    assert all(b["hit"] for b in r["bonus_follow_up"])


def test_contract_example_is_partial():
    data = json.loads((ROOT / "docs/contracts/proposals.put.json").read_text(encoding="utf-8"))
    r = score(load_proposals(data), E)
    assert not r["passed"]
    missing = [p["product_id"] for p in r["products"] if "제안 없음 (빠진 상품)" in p["issues"]]
    assert len(missing) == 12 - 4


def test_unit_mistake_fails_value_metric():
    rows = items()
    p5 = by_pid(rows, "P005")
    p5.update(proposedValue="0.35", unit="ratio")
    r = score(rows, E)
    assert r["core"]["값 · 단위 정확도"] == {"ok": 5, "total": 6}
    assert not r["passed"]


def test_trap_change_is_counted():
    rows = items() + [{"productId": "P001", "ruleId": "R007", "ruleKey": "MORTGAGE_LTV_LIMIT", "impact": "change_required",
                       "proposedValue": "0.35", "unit": "ratio", "effectiveDate": "2026-12-01"}]
    r = score(rows, E)
    assert [t["rule_id"] for t in r["traps"]] == ["R007"] and r["traps"][0]["trap"]
    assert r["core"]["판정 정확도"]["ok"] == 12  # 상품 판정은 맞지만
    assert not r["passed"]  # 함정 오판으로 미통과


def test_wrong_verdict_and_missing_transition():
    rows = items()
    by_pid(rows, "P012").update(impact="change_required", proposedValue="0.35", effectiveDate="2026-12-01")
    by_pid(rows, "P001")["transition"] = None
    r = score(rows, E)
    assert r["core"]["판정 정확도"]["ok"] == 11
    assert r["core"]["날짜 · 경과조치"] == {"ok": 5, "total": 6}
    assert any(t["rule_id"] == "R079" for t in r["traps"])


def test_keep_with_wrong_basis():
    rows = items()
    by_pid(rows, "P009")["basis"] = "reg://credit-loan-ops/v4/8"
    r = score(rows, E)
    assert r["core"]["keep · needs_check 근거"] == {"ok": 3, "total": 4}


def test_screen_response_uses_latest_round_only():
    rows = items()
    old = copy.deepcopy(by_pid(rows, "P005"))
    old.update(round=1, proposedValue="0.35", latest=False)
    for r in rows:
        r["latest"] = True
    r = score(load_proposals({"task": {}, "proposals": rows + [old]}), E)
    assert r["passed"]


def test_without_latest_flag_uses_highest_round():
    rows = items()
    old = copy.deepcopy(by_pid(rows, "P005"))
    old.update(round=1, proposedValue="0.35")
    assert score(load_proposals(rows + [old]), E)["passed"]


def test_unknown_product_fails():
    rows = items() + [{"productId": "P999", "impact": "keep"}]
    r = score(rows, E)
    assert r["unknown_products"] == ["P999"] and not r["passed"]


def test_rejects_unknown_shape():
    with pytest.raises(ValueError):
        load_proposals({"data": []})
