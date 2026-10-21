"""AI 작업 기록 보기: 작업의 진행 이벤트(GET /api/ai/tasks/{id}/events)를 사람이 읽는 줄로 출력한다.

단계 진행(STEP), 도구 호출(TOOL_START · TOOL_END), 상품별 판단(DECISION), 확인 대기 · 종료를 순서대로 보여준다.
도구 호출은 시작과 끝을 한 줄로 합친다. 형식은 docs/BACKEND_API.md 5절.

실행 (레포 루트에서, docker compose up 뒤):
    python3 scripts/trace.py            # 가장 최근 작업
    python3 scripts/trace.py <작업 ID>
필요: python3 (표준 라이브러리만). 백엔드 주소는 BASE (기본 http://localhost:8080)
"""

import json
import os
import re
import sys
import urllib.request

BASE = os.environ.get("BASE", "http://localhost:8080").rstrip("/")
IMPACT = {"change_required": "변경 필요", "keep": "유지", "needs_check": "확인 필요"}
UUID = re.compile(r"\b([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def call(path, token=None, body=None):
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers), timeout=30) as res:
        return json.loads(res.read())


def rules(ids):
    return ", ".join(ids) if ids else "-"


def lines(events):
    started = {}
    for e in events:
        t, p = e["type"], e["payload"] or {}
        if t == "STEP":
            text = p.get("message") or "시작"
            yield f"단계  {p['node']}{' ' + str(p['round']) + '회차' if p.get('round') else ''}: {text}"
        elif t == "TOOL_START" and "node" in p:
            started[(p["node"], p["tool"])] = p.get("args") or {}
        elif t == "TOOL_END" and "node" in p:
            args = started.pop((p["node"], p["tool"]), {})
            shown = ", ".join([*map(str, args.get("args", [])), *(f"{k}={v}" for k, v in args.items() if k != "args")])
            result = (p.get("summary") or "") if p["ok"] else f"실패: {p.get('error')}"
            yield f"도구  {'✓' if p['ok'] else '✗'} {p['tool']}({shown}) {p['ms']}ms  {result}".rstrip()
        elif t in ("TOOL_START", "TOOL_END"):  # 백엔드 대기열 작업 (node 없음)
            state = "시작" if t == "TOOL_START" else ("완료" if p.get("ok") else "재시도" if p.get("retrying") else "실패")
            yield f"큐    {p.get('tool')} {p.get('jobId') or ''} {state} (시도 {p.get('attempt')})"
        elif t == "DECISION":
            model, final = p.get("model"), p["final"]
            before = f"AI {IMPACT.get(model['impact'], model['impact'])} [{rules(model['targetRuleIds'])}]" if model else "AI 판단 없음"
            after = f"최종 {IMPACT.get(final['impact'], final['impact'])} [{rules(final['targetRuleIds'])}]"
            changed = not model or (model["impact"], model["targetRuleIds"]) != (final["impact"], final["targetRuleIds"])
            yield f"판단  {p['productId']}  {before}{' → ' + after if changed else ''}"
            if model and model.get("reason"):
                yield f"        근거: {model['reason']}"
            for note in p.get("checks") or []:
                yield f"        코드 검사: {note}"
        elif t == "APPROVAL_REQUIRED":
            yield "확인  사람 확인 대기"
        elif t in ("DONE", "FAILED"):
            yield f"종료  {p.get('outcome') or p.get('reason')}"
        else:
            yield f"{t}  {json.dumps(p, ensure_ascii=False)}"


def main():
    token = call("/api/auth/login", body={"username": "officer1", "password": "password"})["token"]
    if len(sys.argv) > 1:
        task_id = sys.argv[1]
    else:
        tasks = call("/api/ai/tasks?mine=false", token)
        if not tasks:
            sys.exit("작업이 없습니다")
        task_id = max(tasks, key=lambda t: t["createdAt"])["id"]
    task = call(f"/api/ai/tasks/{task_id}", token)["task"]
    print(f"작업 {task_id}  {task['title']}  ({task['status']})\n")
    for line in lines(call(f"/api/ai/tasks/{task_id}/events?after=0", token)):
        print(UUID.sub(r"\1", line))  # 작업 · 큐 ID는 앞 8자리만


if __name__ == "__main__":
    main()
