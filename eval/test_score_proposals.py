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


# ---------- 2단계 시나리오 · 정답지와 데이터 일치 ----------

SCENARIOS = {p.name: p for p in sorted(Path(__file__).parent.glob("expected_proposals*.yaml"))}


def load_expected(name):
    return yaml.safe_load(SCENARIOS[name].read_text(encoding="utf-8"))


def perfect_from(expected):
    """정답지에서 만점 답안을 만든다 (근거는 basis_any 첫 항목)."""
    rows = []
    for e in expected["products"]:
        rid, aid = e["basis_any"][0].split("/", 1)
        row = {"productId": e["product_id"], "ruleId": e["rule_id"], "impact": e["impact"],
               "basis": f"reg://{rid}/v9/{aid}", "reason": e.get("reason", "기준 충족"), "followUp": []}
        if e["impact"] == "change_required":
            row.update(proposedValue=e["proposed"]["value"], unit=e["proposed"]["unit"],
                       effectiveDate=expected["effective_date"], transition=expected["transition"])
        rows.append(row)
    return rows


@pytest.mark.parametrize("name", ["expected_proposals.senior-age.yaml", "expected_proposals.senior-explanation.yaml"])
def test_stage2_perfect_answer_passes(name):
    assert score(perfect_from(load_expected(name)), load_expected(name))["passed"]


def test_senior_age_traps():
    exp = load_expected("expected_proposals.senior-age.yaml")
    rows = perfect_from(exp) + [
        {"productId": "P001", "ruleId": "R008", "impact": "change_required", "proposedValue": "60", "unit": "age"},
        {"productId": "P002", "ruleId": "R029", "impact": "change_required", "proposedValue": "60", "unit": "age"},
    ]
    r = score(rows, exp)
    assert sorted(t["rule_id"] for t in r["traps"]) == ["R008", "R029"] and not r["passed"]


def test_new_rule_is_scored_without_rule_id_or_key_name():
    exp = load_expected("expected_proposals.senior-explanation.yaml")
    rows = perfect_from(exp)
    by_pid(rows, "P001")["ruleKey"] = "ELDERLY_EXPLAIN_CHECK"  # 이름은 달라도 정답
    assert score(rows, exp)["passed"]
    by_pid(rows, "P003").update(proposedValue="false")  # 값이 틀리면 오답
    rows = [r for r in rows if r["productId"] != "P004"]  # 빠진 상품
    r = score(rows, exp)
    assert r["core"]["값 · 단위 정확도"]["ok"] == r["core"]["값 · 단위 정확도"]["total"] - 1
    assert r["core"]["변경 대상 recall"]["ok"] == r["core"]["변경 대상 recall"]["total"] - 1


def test_explanation_record_trap():
    exp = load_expected("expected_proposals.senior-explanation.yaml")
    rows = perfect_from(exp) + [{"productId": "P001", "ruleId": "R025", "impact": "change_required", "proposedValue": "5", "unit": "years"}]
    assert [t["rule_id"] for t in score(rows, exp)["traps"]] == ["R025"]


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_expected_matches_data(name):
    exp = load_expected(name)
    data = ROOT / "data" / "business"
    rules = {r["rule_id"]: r for r in json.loads((data / "product_rules.json").read_text(encoding="utf-8"))}
    products = {p["product_id"] for p in json.loads((data / "products.json").read_text(encoding="utf-8"))}
    contracts = {c["contract_id"] for c in json.loads((data / "loan_contracts.json").read_text(encoding="utf-8"))}
    regs = ROOT / "data" / "regulations"

    assert {e["product_id"] for e in exp["products"]} == products, "모든 상품에 판정이 있어야 함"
    for e in exp["products"]:
        if e["rule_id"]:
            r = rules[e["rule_id"]]
            assert r["product_id"] == e["product_id"] and r["effective_to"] is None, e
            if "current" in e:
                assert (r["value"], r["unit"]) == (e["current"]["value"], e["current"]["unit"]), e
        for b in e["basis_any"]:
            rid, aid = b.split("/", 1)
            heads = "".join(p.read_text(encoding="utf-8") for p in (regs / rid).glob("v*.md"))
            num, _, sub = aid.removeprefix("supp-").partition("-")
            label = ("부칙 " if aid.startswith("supp-") else "") + f"제{num}조" + (f"의{sub}" if sub else "")
            assert f"### {label}(" in heads, f"{name}: 근거 조항 없음 {b}"
    for m in exp["must_not"]:
        assert m["rule_id"] in rules, m
    for group in exp.get("bonus", {}).get("contracts", {}).values():
        assert set(group) <= contracts
