"""시연 데이터 전용 규칙. LLM 모드에서는 이 판단을 사용하지 않는다."""

import json
import re
from datetime import date
from app.data import article_label
from app.reasoning import Draft
from app.schemas import ChangeSpec, Requirement, TestCase

_ARTICLE_REF = re.compile(r"제(\d+)조(?:의(\d+))?")
_TARGET_KEYS = {"8": "DSR_LIMIT", "15": "SENIOR_AGE", "15-2": "SENIOR_EXPLANATION"}


def parse_numbers(text: str | None) -> list[str]:
    """'40%' → '0.40', '만 65세' → '65'. 비율은 소수 둘째 자리로 맞춘다."""
    return [
        f"{float(n) / 100:.2f}" if pct else n
        for n, pct in re.findall(r"(\d+(?:\.\d+)?)(%)?", text or "")
    ]


def _referenced_articles(text: str) -> set[str]:
    return {f"{n}-{s}" if s else n for n, s in _ARTICLE_REF.findall(text)}


_NOT_TARGET = {
    "RETIREMENT_AGE": "소득 추정용 정년 가정(제7조)이며 고령자 기준과 무관",
    "LTV_LIMIT": "LTV(제10조)는 DSR과 별개 지표",
}

_TERMS = {"DSR": "DSR", "LTV": "LTV", "RETIREMENT": "정년", "SENIOR": "고령자"}

_NEW_MODULES = {
    "SENIOR_EXPLANATION": (
        "src/loan/senior_explanation.py",
        "confirm_senior_explanation",
    )
}


def _same_value(a: str, b: str | None) -> bool:
    try:
        return b is not None and float(a) == float(b)
    except ValueError:
        return a == b


def _at_most(a: str, b: str | None) -> bool:
    try:
        return b is not None and float(a) <= float(b)
    except ValueError:
        return False


def _rule_terms(rule: dict, product: dict) -> tuple[list[str], bool]:
    """규칙이 가리키는 규정 용어. 키에 단서가 없으면 상품 설명에서 찾는다. (키에서 찾았는지 함께 반환)"""
    tokens = rule["ruleKey"].split("_")
    from_key = [term for token, term in _TERMS.items() if token in tokens]
    if from_key:
        return from_key, True
    text = f"{product['name']} {product['description']}"
    return [term for term in _TERMS.values() if term in text], False


def _rule_specs(
    req: Requirement, rules: list[dict], products: dict[str, dict], find_article
) -> list[ChangeSpec]:
    """상품 규칙 판단. 근거 조항 정보는 입력에 없으므로(정답 분리) 용어 · 값 · 상품 설명으로 판단한다.
    rules · products는 business-mcp 응답 그대로 (camelCase).

    - 대상: 규칙 용어가 바뀐 조항 원문에 나오고, 값이 종전 값과 같다
    - 같은 키인데 값이 이미 신 기준 이하: 대상 아님
    - 용어는 관련 있지만 다른 항목(우대 폭 등): 대상 아님
    - 값만 같고 용어가 다른 조항 소속: 함정, 대상 아님
    """
    req_text = f"{req.old_text or ''} {req.new_text or ''}"
    judged = []
    for rule in rules:
        product = products[rule["productId"]]
        terms, from_key = _rule_terms(rule, product)
        related = [t for t in terms if t in req_text]
        same_value = _same_value(rule["value"], req.old_value)
        if related and same_value:
            judged.append(
                (
                    rule,
                    True,
                    f"'{related[0]}' 규칙 · 종전 값 {req.old_value}"
                    + ("" if from_key else f" ({product['name']} 설명 기준)"),
                )
            )
        elif related and from_key:
            judged.append((rule, False, None))  # 이유는 대상 키를 안 뒤에 정한다
        elif same_value:
            term = terms[0] if terms else None
            where = find_article(term) if term else None
            reason = (
                f"같은 값 {rule['value']}이지만 '{term}' 기준({where})이라 {req.article} 변경과 무관"
                if where
                else f"같은 값 {rule['value']}이지만 {req.article}과 관련 근거 없음"
            )
            judged.append((rule, False, reason))

    target_keys = {rule["ruleKey"] for rule, is_target, _ in judged if is_target}
    specs = []
    for rule, is_target, reason in judged:
        if reason is None:
            if rule["ruleKey"] in target_keys and _at_most(
                rule["value"], req.new_value
            ):
                reason = f"같은 규칙이지만 상품 값 {rule['value']}이 이미 신 기준 {req.new_value} 이하"
            else:
                reason = f"관련 규칙이지만 기준값이 아닌 다른 항목({rule['ruleKey']})이라 직접 대상 아님"
        specs.append(
            ChangeSpec(
                id="",
                requirement_id=req.id,
                file="db/product_rules",
                line=int(rule["ruleId"].lstrip("R")),
                symbol=f"{rule['ruleId']} {rule['productId']}.{rule['ruleKey']}",
                snippet=f"{rule['ruleKey']} = {rule['value']} ({rule['unit']}, {products[rule['productId']]['name']})",
                kind="product_rule",
                is_target=is_target,
                reason=reason,
            )
        )
    return specs


class DemoReasoner:
    is_demo = True

    def requirements(self, diff):
        out = []
        changes = diff["changes"]
        for change in changes:
            aid = change["article_id"]
            if aid.startswith("supp-"):
                continue
            old, new = (
                parse_numbers(change["old_text"]),
                parse_numbers(change["new_text"]),
            )
            if change["change"] == "modified" and old == new:
                continue
            pair = next(((a, b) for a, b in zip(old, new) if a != b), (None, None))
            label = f"{article_label(aid)}({change['title']})"
            supplementary = [
                c["new_text"]
                for c in changes
                if c["article_id"].startswith("supp-")
                and c["new_text"]
                and aid in _referenced_articles(c["new_text"])
            ]
            out.append(
                Requirement(
                    id=f"REQ-{aid}",
                    article_id=aid,
                    article=label,
                    article_ref=change.get("new_uri") or change["old_uri"],
                    change=change["change"],
                    summary=f"{label} {pair[0]} → {pair[1]}"
                    if change["change"] == "modified"
                    else f"{label} {change['change']}",
                    target=_TARGET_KEYS.get(aid, f"ARTICLE_{aid}"),
                    old_value=pair[0],
                    new_value=pair[1],
                    old_text=change["old_text"],
                    new_text=change["new_text"],
                    effective_date=date.fromisoformat(diff["effective_from"])
                    if diff.get("effective_from")
                    else None,
                    transitional="\n".join(supplementary) or None,
                )
            )
        return out

    def locate(self, state, tools):
        out = []
        rules = tools.get_product_rules()
        products = {p["productId"]: p for p in tools.get_products()}

        def find_article(term):
            hits = tools.search_regulation(
                term, state["regulation_id"], state["new_version"]
            )
            return hits[0]["title"] if hits else None

        for req in state["requirements"]:
            if req.change == "added":
                file, symbol = _NEW_MODULES.get(
                    req.target, (f"src/new/{req.target.lower()}.py", req.target.lower())
                )
                out.append(
                    ChangeSpec(
                        id="",
                        requirement_id=req.id,
                        file=file,
                        line=0,
                        symbol=symbol,
                        snippet="(신규 모듈)",
                        kind="new",
                        is_target=True,
                        reason=f"{req.article} 신규 의무",
                    )
                )
                continue
            out.extend(_rule_specs(req, rules, products, find_article))
            for hit in tools.search_code(req.target):
                reason = _NOT_TARGET.get(hit["symbol"])
                out.append(
                    ChangeSpec(
                        id="",
                        requirement_id=req.id,
                        **hit,
                        is_target=reason is None,
                        reason=reason or f"{req.target} 사용 위치 (시연 목록)",
                    )
                )
        return out

    def tests(self, state, tools):
        return [
            TestCase(
                id=f"{r.id}-{kind}",
                requirement_id=r.id,
                kind=kind,
                description=f"{r.summary}: {label}",
                inputs=json.dumps(
                    {"old": r.old_value, "new": r.new_value}, ensure_ascii=False
                ),
                expected="요건과 시행일·경과조치에 맞는 동작 (실행 코드 없는 시연 명세)",
            )
            for r in state["requirements"]
            for kind, label in (
                ("boundary", "경계값"),
                ("effective_date", "시행일 전후"),
                ("system", "관련 경로 일관성"),
            )
        ]

    def draft(self, context):
        reqs = {r["id"]: r for r in context["requirements"]}
        lines = [
            f"{s['location']} {s['symbol']}: {reqs[s['requirement_id']]['summary']}"
            for s in context["specs"]
        ]
        return Draft(
            diff="", proposal="시연용 수정 방향 (실제 패치 아님):\n" + "\n".join(lines)
        )
