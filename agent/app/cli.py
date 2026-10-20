"""검토 화면은 요약으로 유지하고 상세 조회는 모델을 호출하지 않는다."""

from app.validation import validate_feedback


def select_proposals(text, proposals):
    selected = set()
    for token in text.split(","):
        token = token.strip()
        if token.isdigit():
            number = int(token)
            if not 1 <= number <= len(proposals):
                raise ValueError("표시된 제안 번호를 입력하세요")
            selected.add(proposals[number - 1]["id"])
        else:
            matches = [p for p in proposals if p["id"] == token or p["product_id"] == token]
            if not matches:
                raise ValueError("알 수 없는 제안 번호·상품 ID입니다")
            selected.update(p["id"] for p in matches)
    return [p for p in proposals if p["id"] in selected]


def review_command(text, proposals, read=None):
    read = read or input
    parts = text.strip().split(maxsplit=1)
    if not parts:
        raise ValueError("검토 명령을 입력하세요")
    action, selector = parts[0].lower(), parts[1] if len(parts) == 2 else ""
    if action == "f" and not selector:
        return {"decisions": [], "finish": True}
    if action not in ("a", "p", "r", "c", "e"):
        raise ValueError("상세 v 3 / 승인 p 1,3 / 제외 r 2 / 재작성 c 2 / 직접 수정 e 2 / 완료 f")
    if action == "a" and selector:
        raise ValueError("일부 승인은 p 번호를 사용하세요")
    if action in ("p", "c", "e") and not selector:
        raise ValueError("대상 번호 또는 상품 ID를 입력하세요")
    selected = select_proposals(selector, proposals) if selector else [p for p in proposals if p["status"] == "pending"]
    if action == "e" and len(selected) != 1:
        raise ValueError("직접 수정은 한 제안 번호를 선택하세요")
    comment, edits = "", None
    if action == "c":
        comment = read("무엇을 바꿀까요? (예: 화면 안내 문구 한 줄 추가): ").strip()
        validate_feedback(comment)
    elif action == "e":
        edits = {}
        value = read("제안 요약 (220자 이내, 빈칸=유지): ").strip()
        if value:
            edits["recommendation"] = value
        for key, label in (("actions", "필수 조치 최대 3개"), ("optional_actions", "추가 제안 최대 2개"), ("precautions", "주의 최대 2개")):
            value = read(f"{label} (| 구분, 빈칸=유지, -=비우기): ").strip()
            if value:
                edits[key] = [] if value == "-" else [v.strip() for v in value.split("|")]
        comment = read("수정 메모 (선택): ").strip()
    mapped = {"a": "approve", "p": "approve", "r": "reject", "c": "request_changes", "e": "edit"}[action]
    return {"decisions": [{"proposal_id": p["id"], "version": p["version"], "action": mapped,
                           "comment": comment, **({"edits": edits} if edits is not None else {})} for p in selected],
            "finish": action == "a" or action == "r" and not selector}


def brief(text, width=32):
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def show_review(value):
    proposals = value["proposals"]
    approved = sum(p["status"] == "approved" for p in proposals)
    print(f"\n제안 검토 · 승인 {approved}건 숨김 · 유지 {len(value['unchanged'])}건 · 번호 유지")
    print("번호 | 상품 | 변경 대상 | 현재 → 제안 | 적용 범위 | 상태")
    for number, p in enumerate(proposals, 1):
        if p["status"] == "approved":
            continue
        targets = ",".join(c["rule_key"] for c in p.get("changes", [])) or "절차·자료 확인"
        values = ", ".join(f"{c['current_value']}→{c['proposed_value']} {c['unit']}" for c in p.get("changes", [])) or "상세 확인"
        status = "검증 실패" if p.get("generation_error") else "제외" if p["status"] == "rejected" else "확인 필요" if p["impact"] == "needs_review" else "대기"
        print(f"{number} | {p['product_id']} {brief(p['product_name'], 14)} | {brief(targets, 22)} | {brief(values, 27)} | {brief(p.get('scope', ''), 24)} | {status} v{p['version']}")
    if all(p["status"] in ("approved", "rejected") for p in proposals):
        print("모든 항목 검토 완료. f를 입력하면 종료합니다.")
    print("v 3 상세 | k 유지 근거 | p 1,3 승인 | r 2 제외 | c 2 재작성 | e 2 직접 수정 | a 남은 전체 승인 | f 완료")


def show_details(proposal):
    p = proposal
    print(f"\n{p['product_name']} / {p['requirement_id']} / v{p['version']} [{p['status']}]")
    print(f"근거: {p['article_ref']}\n변경 대상: {', '.join(p['target_rule_ids']) or '수치 변경 없음'}")
    print("판단: " + p["reason"])
    print(f"현재: {p['current']}\n제안: {p['recommendation']}\n범위: {p['scope']}")
    for c in p.get("changes", []):
        print(f"  {c['rule_id']} {c['rule_key']}: {c['current_value']} → {c['proposed_value']} ({c['unit']})")
    for condition in p.get("conditions", []):
        print(f"조건: {condition['text']} ({condition['source_ref']})")
    for field, label in (("actions", "필수 조치"), ("optional_actions", "추가 제안(선택)"), ("precautions", "주의")):
        if p.get(field):
            print(label + ":")
            for item in p[field]:
                print("  - " + item)
    print(f"시행일: {p['effective_date']}\n경과조치: {p['transitional'] or '추가 확인'}")
    if p.get("evidence_rule_ids") or p.get("document_refs"):
        print("참고 근거: " + ", ".join(p.get("evidence_rule_ids", []) + p.get("document_refs", [])))
    if p.get("review_comment"):
        print("요청 의견: " + p["review_comment"])
    if p.get("revision_response"):
        print("반영 설명: " + p["revision_response"])
    if p.get("changed_fields"):
        labels = {"recommendation": "제안 요약", "actions": "필수 조치", "optional_actions": "추가 제안", "precautions": "주의", "changes": "규칙 값"}
        print("변경된 항목: " + ", ".join(labels[n] for n in p["changed_fields"]))
    if p.get("generation_error"):
        print("검증 실패: " + p["generation_error"])


def show_unchanged(items):
    for item in items:
        print(f"{item['product_id']} / {item['requirement_id']}: {item['reason']} / {item['scope']}")
