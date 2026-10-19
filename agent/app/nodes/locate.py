from app.data import article_label
from app.schemas import ChangeSpec, Event, Requirement
from app.state import RippleState

# LLM이 판단할 자리. 스텁에서는 알려진 코드 함정만 "대상 아님"으로 둔다.
_NOT_TARGET = {
    "RETIREMENT_AGE": "소득 추정용 정년 가정(제7조)이며 고령자 기준과 무관",
    "LTV_LIMIT": "LTV(제10조)는 DSR과 별개 지표",
}

# LLM 자리: 규칙 키 토큰 → 규정 용어
_TERMS = {"DSR": "DSR", "LTV": "LTV", "RETIREMENT": "정년", "SENIOR": "고령자"}

# LLM 자리: ④ 신규 의무를 구현할 모듈 제안
_NEW_MODULES = {"SENIOR_EXPLANATION": ("src/loan/senior_explanation.py", "confirm_senior_explanation")}


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


def _rule_terms(rule: dict) -> tuple[list[str], bool]:
    """규칙이 가리키는 규정 용어. 키에 단서가 없으면 상품 설명에서 찾는다. (키에서 찾았는지 함께 반환)"""
    tokens = rule["rule_key"].split("_")
    from_key = [term for token, term in _TERMS.items() if token in tokens]
    if from_key:
        return from_key, True
    text = f"{rule['product_name']} {rule['product_description']}"
    return [term for term in _TERMS.values() if term in text], False


def _rule_specs(req: Requirement, rules: list[dict], find_article) -> list[ChangeSpec]:
    """상품 규칙 판단. 근거 조항 정보는 입력에 없으므로(정답 분리) 용어 · 값 · 상품 설명으로 판단한다.

    - 대상: 규칙 용어가 바뀐 조항 원문에 나오고, 값이 종전 값과 같다
    - 같은 키인데 값이 이미 신 기준 이하: 대상 아님
    - 용어는 관련 있지만 다른 항목(우대 폭 등): 대상 아님
    - 값만 같고 용어가 다른 조항 소속: 함정, 대상 아님
    """
    req_text = f"{req.old_text or ''} {req.new_text or ''}"
    judged = []
    for rule in rules:
        terms, from_key = _rule_terms(rule)
        related = [t for t in terms if t in req_text]
        same_value = _same_value(rule["value"], req.old_value)
        if related and same_value:
            judged.append((rule, True, f"'{related[0]}' 규칙 · 종전 값 {req.old_value}"
                           + ("" if from_key else f" ({rule['product_name']} 설명 기준)")))
        elif related and from_key:
            judged.append((rule, False, None))  # 이유는 대상 키를 안 뒤에 정한다
        elif same_value:
            term = terms[0] if terms else None
            where = find_article(term) if term else None
            reason = (f"같은 값 {rule['value']}이지만 '{term}' 기준({where})이라 {req.article} 변경과 무관"
                      if where else f"같은 값 {rule['value']}이지만 {req.article}과 관련 근거 없음")
            judged.append((rule, False, reason))

    target_keys = {rule["rule_key"] for rule, is_target, _ in judged if is_target}
    specs = []
    for rule, is_target, reason in judged:
        if reason is None:
            if rule["rule_key"] in target_keys and _at_most(rule["value"], req.new_value):
                reason = f"같은 규칙이지만 상품 값 {rule['value']}이 이미 신 기준 {req.new_value} 이하"
            else:
                reason = f"관련 규칙이지만 기준값이 아닌 다른 항목({rule['rule_key']})이라 직접 대상 아님"
        specs.append(ChangeSpec(
            id="",
            requirement_id=req.id,
            file="db/product_rules",
            line=int(rule["rule_id"].lstrip("R")),
            symbol=f"{rule['rule_id']} {rule['product_id']}.{rule['rule_key']}",
            snippet=f"{rule['rule_key']} = {rule['value']} ({rule['unit']}, {rule['product_name']})",
            kind="product_rule",
            is_target=is_target,
            reason=reason,
        ))
    return specs


def make_locate_agent(tools):
    """코드·설정·DB·상품 규칙에서 영향 위치 탐색. 재실행 시 verify가 준 missed_locations를 힌트로 쓴다."""

    def locate_agent(state: RippleState) -> dict:
        specs = {s.location: s for s in state.get("change_specs", [])}
        reqs = state["requirements"]

        def add(spec: ChangeSpec) -> None:
            if spec.location not in specs:
                specs[spec.location] = spec.model_copy(update={"id": f"SPEC-{len(specs) + 1}"})

        # ④ 신규 의무: 바꿀 기존 위치가 없으니 새 모듈 위치를 만든다
        for req in (r for r in reqs if r.change == "added"):
            file, symbol = _NEW_MODULES.get(req.target, (f"src/new/{req.target.lower()}.py", req.target.lower()))
            add(ChangeSpec(
                id="", requirement_id=req.id, file=file, line=0, symbol=symbol,
                snippet="(신규 모듈)", kind="new", is_target=True,
                reason=f"{req.article} 신규 의무 — 기존 구현 없음",
            ))

        # 상품 규칙 (business-mcp). 함정의 소속 조항은 규정 검색으로 찾는다.
        def find_article(term: str) -> str | None:
            hits = tools.search_regulation(term, state["regulation_id"], state["new_version"])
            return next((f"{article_label(h['article_id'])}({h['title']})" for h in hits
                         if not h["article_id"].startswith("supp-")), None)

        rules = tools.get_product_rules()
        for req in (r for r in reqs if r.change == "modified"):
            for spec in _rule_specs(req, rules, find_article):
                add(spec)

        # 코드 · 설정 (code-mcp). 재실행이면 놓친 위치 힌트도 검색한다.
        queries = [(req, req.target) for req in reqs if req.change == "modified"]
        for hint in state.get("missed_locations", []):  # "file:line:symbol"
            symbol = hint.split(":")[-1]
            req = next((r for r in reqs if r.target in symbol), reqs[0])
            queries.append((req, symbol))
        for req, query in queries:
            for hit in tools.search_code(query):
                reason = _NOT_TARGET.get(hit["symbol"])
                add(ChangeSpec(
                    id="", requirement_id=req.id, file=hit["file"], line=hit["line"], symbol=hit["symbol"],
                    snippet=hit["snippet"], kind=hit["kind"], is_target=reason is None,
                    reason=reason or f"{req.target} 기준값을 사용하는 위치",
                ))

        round_ = state.get("locate_round", 0) + 1
        targets = sum(s.is_target for s in specs.values())
        return {
            "change_specs": list(specs.values()),
            "locate_round": round_,
            "missed_locations": [],
            "events": [
                Event(
                    node="locate_agent",
                    message=f"{round_}회차: 대상 {targets}곳 / 대상 아님 {len(specs) - targets}곳",
                )
            ],
        }

    return locate_agent
