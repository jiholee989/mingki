"""검토 화면은 요약으로 유지하고 상세 조회는 모델을 호출하지 않는다."""

from difflib import ndiff

from app.validation import approval_problem, validate_feedback


CONTENT_LABELS = {"recommendation": "제안 요약", "actions": "필수 조치",
                  "optional_actions": "추가 제안", "precautions": "주의", "changes": "규칙 값"}
REVIEW_HELP = "v 3 상세 | k 유지 근거 | p 1,3 승인 | r 2 제외 | c 2 재작성 | e 2 직접 수정 | a 전체 검토 완료 | f 완료 | ? 도움말"


def blocked_proposals(proposals):
    return [(n, p, problem) for n, p in enumerate(proposals, 1)
            if p["status"] == "pending" and (problem := approval_problem(p))]


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
        raise ValueError(REVIEW_HELP)
    if action == "a" and selector:
        raise ValueError("일부 승인은 p 번호를 사용하세요")
    if action in ("p", "c", "e") and not selector:
        raise ValueError("대상 번호 또는 상품 ID를 입력하세요")
    selected = select_proposals(selector, proposals) if selector else [p for p in proposals if p["status"] == "pending"]
    if action == "p":
        selected = [p for p in selected if p["status"] != "approved"]
        if not selected:
            raise ValueError("선택한 제안은 이미 승인됐습니다. a로 남은 항목을 검토하거나 f로 완료하세요")
    if action == "a" and (blocked := blocked_proposals(proposals)):
        print(f"전체 검토 완료 예정 · 승인 {len(selected) - len(blocked)}건 · 승인 불가 항목 제외 {len(blocked)}건")
        for number, p, problem in blocked:
            print(f"  제외 예정: {number}번 {p['product_id']} — {problem}")
        answer = read("위 항목을 제외하고 나머지를 승인해 종료할까요? [y/N]: ").strip().lower()
        if answer not in ("y", "yes", "예", "네"):
            raise ValueError("전체 검토 완료를 취소했습니다. 상태는 변경되지 않았습니다. c 번호 재작성 / e 번호 직접 수정 / r 번호 제외")
        reasons = {p["id"]: problem for _, p, problem in blocked}
        return {"decisions": [{"proposal_id": p["id"], "version": p["version"],
                               "action": "reject" if p["id"] in reasons else "approve",
                               "comment": "전체 검토 완료 시 제외: " + reasons[p["id"]] if p["id"] in reasons else ""}
                              for p in selected], "finish": True}
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
        status = "제외" if p["status"] == "rejected" else "검증 실패" if p.get("generation_error") or p.get("verification") == "failed" else "확인 필요" if p["impact"] == "needs_review" else "대기"
        if p["status"] == "pending" and not p.get("generation_error"):
            if p.get("revision_outcome") == "cannot_apply":
                status = "요청 반영 불가 · 기존본"
            elif p.get("revision_outcome") == "needs_clarification":
                status = "의견 보완 필요 · 기존본"
        print(f"{number} | {p['product_id']} {brief(p['product_name'], 14)} | {brief(targets, 22)} | {brief(values, 27)} | {brief(p.get('scope', ''), 24)} | {status} v{p['version']}")
    if all(p["status"] in ("approved", "rejected") for p in proposals):
        print("모든 항목 검토 완료. f를 입력하면 종료합니다.")
    blocked = blocked_proposals(proposals)
    if blocked:
        print("승인 불가: " + ", ".join(f"{n}번 {p['product_id']}" for n, p, _ in blocked))
        print("a를 입력하면 승인 불가 항목의 제외 여부를 확인하고 나머지 승인·종료를 함께 처리합니다.")
    print(REVIEW_HELP)


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
        label = "미반영 사유" if p.get("revision_outcome") in ("cannot_apply", "needs_clarification", "failed") else "반영 설명"
        print(label + ": " + p["revision_response"])
    if p.get("changed_fields"):
        print("변경된 항목: " + ", ".join(CONTENT_LABELS[n] for n in p["changed_fields"]))
    if p.get("generation_error"):
        print("검증 실패: " + p["generation_error"])


def show_unchanged(items):
    for item in items:
        print(f"{item['product_id']} / {item['requirement_id']}: {item['reason']} / {item['scope']}")


def show_review_changes(previous, proposals, decisions):
    """선택한 항목의 실제 변경만 출력한다. 생성 실패 후보를 적용된 변경처럼 표시하지 않는다."""
    selected = {d["proposal_id"] for d in decisions if d["action"] in ("request_changes", "edit")}
    before = {p["id"]: p for p in previous}
    for number, proposal in enumerate(proposals, 1):
        p = proposal.model_dump(mode="json")
        if p["id"] not in selected:
            continue
        old = before[p["id"]]
        print(f"\n변경 결과 · {number}번 {p['product_id']} {p['product_name']} · v{old['version']} → v{p['version']}")
        print("요청 의견: " + (p["review_comment"] or "직접 편집"))
        if p.get("revision_outcome") in ("cannot_apply", "needs_clarification"):
            outcome = "반영 불가" if p["revision_outcome"] == "cannot_apply" else "추가 확인 필요"
            print(outcome + " · 요청은 반영하지 않았으며 이전 본문을 유지했습니다.")
            print("사유: " + p["revision_response"])
            print("기존 본문 검증: " + ("통과" if p["verification"] == "passed" else "실패 · 승인 불가"))
            print(f"c {number} 의견 보완 / v {number} 기존 본문 확인")
            continue
        if p["verification"] != "passed" or p.get("generation_error"):
            print("재작성 실패 · 이전 본문 유지 · 승인 불가")
            print("사유: " + (p.get("generation_error") or "검증을 통과하지 못했습니다"))
            print(f"c {number} 구체적인 의견으로 재작성 / e {number} 직접 수정 / v {number} 현재 본문 확인")
            continue
        print("검증 통과 · 아래 변경 내용을 확인한 뒤 승인하세요.")
        if p.get("revision_response"):
            print("반영 설명: " + p["revision_response"])
        changed = False
        for field, label in CONTENT_LABELS.items():
            if old.get(field) == p.get(field):
                continue
            changed = True
            print(label + ":")
            if isinstance(p[field], list):
                def lines(values):
                    return [f"{v['rule_id']} {v['rule_key']}: {v['current_value']} → {v['proposed_value']} ({v['unit']})"
                            if isinstance(v, dict) else v for v in values]
                for line in ndiff(lines(old.get(field, [])), lines(p[field])):
                    if line.startswith(("- ", "+ ")):
                        print("  " + line)
            else:
                print("  - " + str(old.get(field, "")))
                print("  + " + p[field])
        if not changed:
            print("본문 변경 없음")
        print(f"적용 범위(유지): {p['scope']}")
        print("적용 대상·예외 판단 변경이 필요하면 문구 수정만으로 해결되지 않습니다.")
