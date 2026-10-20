"""조회 근거와 필수 변경을 검증한다. 의미 판단을 정답지로 대신하지 않는다."""

import re
from decimal import Decimal, InvalidOperation


def normalize(value):
    return re.sub(r"\s+", "", value).casefold()


def same_value(left, right):
    try:
        return Decimal(left) == Decimal(right)
    except InvalidOperation:
        return left == right


def expected_value(requirement, unit):
    """단일 수치가 명시된 개정 원문만 변환한다. 모호한 계산식은 추측하지 않는다."""
    text = requirement.new_text or ""
    if unit in ("ratio", "percent"):
        found = re.findall(r"(\d+(?:\.\d+)?)\s*%(?!p)", text)
        found += re.findall(r"100\s*분의\s*(\d+(?:\.\d+)?)", text)
        numbers = {Decimal(v) for v in found}
        if len(numbers) == 1:
            value = next(iter(numbers))
            return str(value / 100 if unit == "ratio" else value)
    if unit == "age":
        numbers = set(re.findall(r"만\s*(\d+)\s*세", text))
        if len(numbers) == 1:
            return numbers.pop()
    return None


def source_texts(state, product_id):
    refs = {a["uri"]: a["text"] for a in state["regulation_context"]}
    refs.update({d["uri"]: d["content"] for d in state.get("product_documents", []) if d["productId"] == product_id})
    return refs


def ground_conditions(assessment, sources):
    """인용문이 한 원문에만 실제로 있으면 잘못 붙인 URI를 그 조회 URI로 바로잡는다."""
    for condition in assessment.conditions:
        quote = normalize(condition.quote)
        if len(quote) < 6 or quote in normalize(sources.get(condition.source_ref, "")):
            continue
        matches = [uri for uri, text in sources.items() if quote in normalize(text)]
        if len(matches) == 1:
            condition.source_ref = matches[0]


def condition_errors(assessment, sources):
    errors = []
    if assessment.applicability == "conditional" and not assessment.conditions:
        errors.append("조건부 적용에는 예외 조건과 원문 인용이 필요합니다")
    for condition in assessment.conditions:
        text = sources.get(condition.source_ref, "")
        if "대환" in condition.text and "연장" in condition.quote and "대환" not in condition.quote:
            errors.append("대환 조건을 기간 연장 조항만으로 뒷받침할 수 없습니다. 대환 예외 원문을 인용하세요")
        if not condition.text.strip() or len(normalize(condition.quote)) < 6 or normalize(condition.quote) not in normalize(text):
            errors.append("적용 조건의 출처·인용문이 실제 조회 원문과 다릅니다")
    return errors


def validate_proposal(state, proposal, baseline=None):
    req = next(r for r in state["requirements"] if r.id == proposal.requirement_id)
    rules = {r["ruleId"]: r for r in state["product_rules"] if r["productId"] == proposal.product_id}
    errors = condition_errors(proposal, source_texts(state, proposal.product_id))
    if proposal.article_ref != req.article_ref or proposal.effective_date != req.effective_date:
        errors.append("법령 근거·시행일은 원래 요건과 같아야 합니다")
    if not proposal.scope.strip():
        errors.append("적용 범위를 작성해야 합니다")
    if not proposal.recommendation.strip() or len(proposal.recommendation) > 220:
        errors.append("변경 제안은 220자 이내로 구체적으로 작성하세요")
    for name, limit, width in (("actions", 3, 180), ("optional_actions", 2, 160), ("precautions", 2, 160)):
        values = getattr(proposal, name)
        if len(values) > limit or any(not v.strip() or len(v) > width for v in values):
            errors.append(f"{name}: {limit}개 이하, 항목당 {width}자 이내로 작성하세요")
    if not proposal.actions:
        errors.append("필수 수행 항목이 없습니다")
    ids = [change.rule_id for change in proposal.changes]
    if len(ids) != len(set(ids)):
        errors.append("같은 규칙의 변경이 중복되었습니다")
    if set(ids) != set(proposal.target_rule_ids):
        errors.append("구조화된 값 변경은 변경 대상 규칙과 정확히 일치해야 합니다")
    for change in proposal.changes:
        row = rules.get(change.rule_id)
        if not row:
            errors.append(f"{change.rule_id}: 이 상품의 유효 규칙이 아닙니다")
            continue
        if change.rule_key != row["ruleKey"] or change.unit != row["unit"] or not same_value(change.current_value, row["value"]):
            errors.append(f"{change.rule_id}: 현재 값·키·단위를 조회 결과 그대로 사용하세요")
        expected = expected_value(req, row["unit"])
        if expected is None or not same_value(change.proposed_value, expected):
            errors.append(f"{change.rule_id}: 개정 원문의 값·단위와 다릅니다. 기대 값: {expected or '수치 근거 확인 필요'} ({row['unit']})")
        if same_value(change.current_value, change.proposed_value):
            errors.append(f"{change.rule_id}: 이미 같은 값인 규칙을 변경 대상으로 넣었습니다")
    if baseline and baseline.verification == "passed":
        before = [c.model_dump() for c in baseline.changes]
        after = [c.model_dump() for c in proposal.changes]
        if before != after or proposal.scope != baseline.scope:
            errors.append("재작성은 검증된 필수 값 변경·적용 범위를 유지해야 합니다")
    return list(dict.fromkeys(errors))


def validate_feedback(comment):
    text = normalize(comment).strip(".!?~")
    vague = {"새로운제안", "새로운아이디어", "새제안", "다른제안", "다른제안줘", "다른제안줘봐", "다른제안사항줘봐", "다시", "다시써줘", "수정해줘", "더좋게", "알아서", "바꿔줘"}
    if not text or text in vague:
        raise ValueError("무엇을 바꿀지 구체적으로 적어주세요. 예: 기존 신청은 제외하고 화면 안내 문구를 한 줄 추가해줘")


def exemption_needs_customer_data(requirement, rules):
    """DSR 수치형 예외 한도는 상품 전체 면제를 증명하지 않는다. 정답 ID·상품 목록은 쓰지 않는다."""
    if "DSR" not in (requirement.new_text or "").upper():
        return False
    return any("DSR" in r["ruleKey"].upper() and "EXEMPT" in r["ruleKey"].upper()
               and r["unit"] != "bool" for r in rules)
