#!/usr/bin/env bash
# 실행 중인 스택(docker compose up)으로 시연 흐름을 처음부터 끝까지 한 번 돌린다.
#   로그인 → 규정 v3 · v4 업로드 → 확인 대기 → 변경 제안 전부 반영 → 완료
# 사용: scripts/smoke.sh [--reset]
#   --reset  시작 전에 POST /api/demo/reset 으로 작업 기록 · 업무 데이터를 처음 상태로 되돌린다
# 필요: curl, python3. 백엔드 주소는 BASE (기본 http://localhost:8080)
set -euo pipefail

BASE="${BASE:-http://localhost:8080}"
TIMEOUT="${TIMEOUT:-300}"
REG_DIR="$(cd "$(dirname "$0")/.." && pwd)/data/regulations/credit-loan-ops"

json() { python3 -c "import json, sys; d = json.load(sys.stdin); $1"; }
api() { curl -sS --fail-with-body -H "Authorization: Bearer $TOKEN" "$@"; }

# 상태가 바뀔 때마다 한 줄 출력하고, 인자로 받은 상태 중 하나가 되면 그 상태를 돌려준다
wait_for() {
  local until="$1" last="" status started=$SECONDS
  while (( SECONDS - started < TIMEOUT )); do
    status=$(api "$BASE/api/ai/tasks/$TASK" | json 'print(d["task"]["status"])')
    [[ "$status" != "$last" ]] && echo "  $(( SECONDS - started ))s  $status" >&2 && last="$status"
    [[ " $until " == *" $status "* ]] && echo "$status" && return 0
    sleep 2
  done
  echo "TIMEOUT" && return 0
}

fail() {
  echo "실패: $1" >&2
  api "$BASE/api/ai/tasks/$TASK" | json 'print("  errorMessage:", d.get("errorMessage"))' >&2 || true
  exit 1
}

TOKEN=$(curl -sS --fail-with-body -H 'Content-Type: application/json' \
  -d '{"username":"officer1","password":"password"}' "$BASE/api/auth/login" | json 'print(d["token"])')
echo "로그인 완료"

if [[ "${1:-}" == "--reset" ]]; then
  api -X POST "$BASE/api/demo/reset" | json 'print("초기화 완료:", d)'
fi

TASK=$(api -F "oldFile=@$REG_DIR/v3.md" -F "newFile=@$REG_DIR/v4.md" "$BASE/api/ai/tasks" | json 'print(d["taskId"])')
echo "업로드 완료: 작업 $TASK"

STATUS=$(wait_for "WAITING_REVIEW DONE NO_CHANGE REJECTED FAILED")
[[ "$STATUS" == "WAITING_REVIEW" ]] || fail "확인 대기 전에 $STATUS"

api "$BASE/api/ai/tasks/$TASK/proposals" | json '
cur = [p for p in d["proposals"] if p["latest"]]
print("제안 %d건 (작성 %s회차, canApprove=%s)" % (len(cur), d["latestRound"], d["canApprove"]))
for p in cur:
    if p["impact"] == "change_required":
        value = "%s → %s %s" % (p["currentValue"], p["proposedValue"], p["unit"])
    else:
        value = p["reason"]
    print("  %-16s %s %s  %s  [%s]" % (p["impact"], p["productId"], p.get("productName") or "", value, p["verifyStatus"]))
    if p["verifyStatus"] == "FAILED" and p["verifyLog"]:
        print("                   검사: %s" % p["verifyLog"])
sys.stdout.flush()
if not d["canApprove"]:
    sys.exit("반영할 수 없습니다 (변경 제안이 없거나 검사를 통과하지 못한 제안이 있음)")
'

api -H 'Content-Type: application/json' -d '{"decision":"APPROVE","comment":"smoke"}' \
  "$BASE/api/ai/tasks/$TASK/review" > /dev/null
echo "전부 반영으로 확인"

STATUS=$(wait_for "DONE REJECTED FAILED")
[[ "$STATUS" == "DONE" ]] || fail "반영 뒤 $STATUS"

api "$BASE/api/ai/tasks/$TASK/proposals" | json '
for p in d["proposals"]:
    if p["latest"] and p["apply"]:
        a = p["apply"]
        print("  %-22s %-5s %s → %s" % (p["proposalKey"], a["status"], a["closedRuleId"] or "-", a["newRuleId"]))
'
echo "완료: 작업 $TASK"
