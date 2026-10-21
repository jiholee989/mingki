"""상품별 변경 제안 채점: Agent 결과를 eval/expected_proposals.yaml과 비교한다.

입력은 백엔드 계약(docs/BACKEND_API.md 10.2) 형식의 JSON이다. 셋 다 받는다.
  - Agent → Spring 콜백 본문   {"items": [...]}
  - 화면 조회 응답              {"task": ..., "proposals": [...]}   (latest: true 인 현재 회차만 채점)
  - 제안 배열                   [...]
latest 표시가 없으면 proposalKey마다 round가 가장 큰 행을 쓴다.

실행 (레포 루트에서):
    uv run --with pyyaml python eval/score_proposals.py 결과.json
    uv run --with pyyaml python eval/score_proposals.py 결과.json --json      # 기계용 출력
화면 조회 응답은 예를 들어 다음처럼 받는다:
    curl -s -H "Authorization: Bearer $TOKEN" localhost:8080/api/ai/tasks/{id}/proposals > 결과.json

핵심 지표가 하나라도 목표에 못 미치면 종료 코드 1. 가산 항목(후속 작업 등)은 종료 코드에 영향이 없다.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

EXPECTED = Path(__file__).parent / "expected_proposals.yaml"
_REG_URI = re.compile(r"reg://([a-z0-9-]+)/v\d+/([0-9a-z-]+)")
_FOLLOW_UP_HINTS = ("문구", "화면", "설명서", "번역", "안내")
COUNT_METRICS = ("함정 오판", "정답에 없는 변경")  # 건수 지표, 목표 0


def load_proposals(data) -> list[dict]:
    rows = data.get("items", data.get("proposals")) if isinstance(data, dict) else data
    if rows is None:
        raise ValueError("제안 목록을 찾을 수 없습니다 (items · proposals · 배열 중 하나)")
    if any("latest" in r for r in rows):
        return [r for r in rows if r.get("latest")]
    best: dict[str, dict] = {}
    for r in rows:
        key = r.get("proposalKey") or f"{r.get('productId')}:{r.get('ruleKey') or r.get('ruleId')}"
        if key not in best or (r.get("round") or 0) > (best[key].get("round") or 0):
            best[key] = r
    return list(best.values())


def _same_value(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def _bases(rows: list[dict]) -> set[str]:
    return {f"{rid}/{aid}" for r in rows for rid, aid in _REG_URI.findall(r.get("basis") or "")}


def product_impact(rows: list[dict]) -> str | None:
    impacts = {r.get("impact") for r in rows}
    for impact in ("change_required", "needs_check", "keep"):
        if impact in impacts:
            return impact
    return None


def score(proposals: list[dict], expected: dict) -> dict:
    by_product = defaultdict(list)
    for p in proposals:
        by_product[p.get("productId")].append(p)
    must_not = {m["rule_id"]: m for m in expected["must_not"]}
    eff = expected["effective_date"]

    products, metrics = [], defaultdict(lambda: [0, 0])  # 이름 → [맞음, 전체]
    for e in expected["products"]:
        pid, rows = e["product_id"], by_product.get(e["product_id"], [])
        got = product_impact(rows)
        issues = []
        ok_impact = got == e["impact"]
        metrics["판정 정확도"][1] += 1
        metrics["판정 정확도"][0] += ok_impact
        if not rows:
            issues.append("제안 없음 (빠진 상품)")
        elif not ok_impact:
            issues.append(f"판정: 정답 {e['impact']}, 결과 {got}")

        if e["impact"] == "change_required":
            # 기존 규칙은 rule_id로, 새 규칙(rule_id 없음)은 rule_id가 비어 있는 변경 제안으로 찾는다 (rule_key 이름은 보지 않음)
            target = next((r for r in rows if r.get("ruleId") == e["rule_id"] and r.get("impact") == "change_required"), None)
            metrics["변경 대상 recall"][1] += 1
            metrics["변경 대상 recall"][0] += target is not None
            if target is None:
                issues.append(f"{e['rule_id'] or '새 규칙'} 변경 제안 없음")
            else:
                want = e["proposed"]
                ok_value = _same_value(target.get("proposedValue"), want["value"]) and target.get("unit") == want["unit"]
                metrics["값 · 단위 정확도"][1] += 1
                metrics["값 · 단위 정확도"][0] += ok_value
                if not ok_value:
                    issues.append(f"값 · 단위: 정답 {want['value']} {want['unit']}, 결과 {target.get('proposedValue')} {target.get('unit')}")
                ok_date = target.get("effectiveDate") == eff and bool((target.get("transition") or "").strip())
                metrics["날짜 · 경과조치"][1] += 1
                metrics["날짜 · 경과조치"][0] += ok_date
                if not ok_date:
                    issues.append(f"날짜 · 경과조치: effectiveDate={target.get('effectiveDate')}, transition={'있음' if target.get('transition') else '없음'}")
        elif e.get("basis_required"):
            ok_basis = bool(_bases(rows) & set(e["basis_any"]))
            metrics["keep · needs_check 근거"][1] += 1
            metrics["keep · needs_check 근거"][0] += ok_basis
            if rows and not ok_basis:
                issues.append(f"근거: {', '.join(e['basis_any'])} 중 하나여야 함, 결과 {sorted(_bases(rows)) or '없음'}")
        products.append({"product_id": pid, "expected": e["impact"], "got": got, "ok": not issues, "issues": issues})

    traps = [
        {"rule_id": p.get("ruleId"), "product_id": p.get("productId"), "reason": must_not[p.get("ruleId")]["reason"],
         "trap": bool(must_not[p.get("ruleId")].get("trap"))}
        for p in proposals if p.get("impact") == "change_required" and p.get("ruleId") in must_not
    ]
    # 함정 목록에 없더라도 정답에 없는 변경은 반영되면 엉뚱한 값이 DB에 들어간다. 새 규칙은 (상품, rule_id 없음)으로 맞춘다
    expected_changes = {(e["product_id"], e["rule_id"]) for e in expected["products"] if e["impact"] == "change_required"}
    extra_changes = [
        {"rule_id": p.get("ruleId"), "product_id": p.get("productId"), "rule_key": p.get("ruleKey"),
         "change": f"{p.get('currentValue')} → {p.get('proposedValue')} {p.get('unit')}"}
        for p in proposals if p.get("impact") == "change_required"
        and (p.get("productId"), p.get("ruleId")) not in expected_changes and p.get("ruleId") not in must_not
    ]
    unknown = sorted({p.get("productId") for p in proposals} - {e["product_id"] for e in expected["products"]})

    bonus = []
    for b in expected.get("bonus", {}).get("follow_up", []):
        items = [f for r in by_product.get(b["product_id"], []) for f in (r.get("followUp") or [])]
        hints = [str(h) for h in b.get("keywords") or _FOLLOW_UP_HINTS]  # YAML은 65 같은 키워드를 숫자로 읽는다
        hit = any(any(h in f for h in hints) for f in items)
        bonus.append({"product_id": b["product_id"], "item": b["item"], "hit": hit})

    core = {name: {"ok": ok, "total": total} for name, (ok, total) in metrics.items()}
    core["함정 오판"] = {"ok": len(traps), "total": 0}
    core["정답에 없는 변경"] = {"ok": len(extra_changes), "total": 0}
    passed = (all(v["ok"] == v["total"] for k, v in core.items() if k not in COUNT_METRICS)
              and not traps and not extra_changes and not unknown)
    extra = [b["item"] for b in expected.get("bonus", {}).get("extra", [])]
    return {"scenario": expected["scenario"], "passed": passed, "not_scored": extra, "core": core, "products": products,
            "traps": traps, "extra_changes": extra_changes, "unknown_products": unknown, "bonus_follow_up": bonus}


def print_report(result: dict) -> None:
    print(f"시나리오: {result['scenario']}  →  {'통과' if result['passed'] else '미통과'}\n")
    print("[핵심 지표]")
    for name, v in result["core"].items():
        if name in COUNT_METRICS:
            print(f"  {name:20} {v['ok']}건 (목표 0)")
        else:
            print(f"  {name:20} {v['ok']}/{v['total']}")
    print("\n[상품별]")
    for p in result["products"]:
        mark = "✓" if p["ok"] else "✗"
        print(f"  {mark} {p['product_id']}  정답 {p['expected']:16} 결과 {str(p['got']):16} {' / '.join(p['issues'])}")
    if result["traps"]:
        print("\n[함정 · 대상 아님에 낸 변경 제안]")
        for t in result["traps"]:
            print(f"  ✗ {t['rule_id']} ({t['product_id']}) {'[함정] ' if t['trap'] else ''}{t['reason']}")
    if result["extra_changes"]:
        print("\n[정답에 없는 변경 제안] 반영하면 바뀌면 안 되는 규칙이 바뀐다")
        for x in result["extra_changes"]:
            print(f"  ✗ {x['rule_id'] or '새 규칙'} ({x['product_id']}) {x['rule_key']} {x['change']}")
    if result["unknown_products"]:
        print(f"\n[정답지에 없는 상품] {', '.join(result['unknown_products'])}")
    hits = sum(b["hit"] for b in result["bonus_follow_up"])
    print(f"\n[가산: 후속 작업] {hits}/{len(result['bonus_follow_up'])}  (문구 · 화면 · 설명서 언급 여부만 봄. 내용은 사람이 확인)")
    for b in result["bonus_follow_up"]:
        print(f"  {'✓' if b['hit'] else '·'} {b['product_id']}  {b['item']}")
    print("\n채점하지 않음 (사람이 확인): 계약 영향(별도 응답)")
    for item in result["not_scored"]:
        print(f"  · {item}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("result", help="제안 JSON 파일 (- 이면 표준 입력)")
    ap.add_argument("--expected", default=str(EXPECTED), help="정답 YAML (기본 eval/expected_proposals.yaml)")
    ap.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.result == "-" else Path(args.result).read_text(encoding="utf-8")
    expected = yaml.safe_load(Path(args.expected).read_text(encoding="utf-8"))
    result = score(load_proposals(json.loads(raw)), expected)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
