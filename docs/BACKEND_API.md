# Backend API 계약

Spring Boot 백엔드가 프론트(Vue), Agent(FastAPI), MCP 서버와 주고받는 형태.
설계 근거는 [PROJECT.md](./PROJECT.md), 프론트 쪽 계획은 [FRONTEND_PLAN.md](./FRONTEND_PLAN.md).

> **단순화 흐름(v2)은 [10절](#10-단순화-흐름-계약-v2)이 기준이다.** 5 ~ 7절의 요건 확정 · 패치 · 테스트 · 티켓 · PR은 옛 흐름이며, 새 흐름이 동작한 뒤 정리한다 (10.7).

## 1. 누가 누구를 부르나

```
Vue ──(/api/**, JWT)──▶ Spring ──(/run, /resume)──▶ Agent ──▶ MCP 서버 3개
                          ▲                            │
                          └──(/internal/**, 내부 토큰)──┘   ← Agent 콜백, business-mcp, code-mcp
```

- 공개 포트는 frontend(:80)와 backend(:8080)뿐. Agent · MCP · DB · RabbitMQ는 docker network 안에만 있다.
- `/internal/**`은 `X-Internal-Token` 헤더가 맞아야 통과한다.

## 2. FRONTEND_PLAN.md "백엔드와 확인할 것" 답변

| 질문 | 답 |
|---|---|
| 프론트는 Spring만 호출하나? | 네. Agent · MCP는 직접 호출하지 않는다. |
| 세션 쿠키 vs JWT | JWT (`Authorization: Bearer`). 데모 역할 전환은 계정 두 개로 로그인 (`officer1` / `dev1`, 비밀번호 `password`). |
| 폴링 vs SSE | 둘 다 된다. MVP는 `GET /tasks/{id}` + `GET /tasks/{id}/events?after=` 폴링으로 충분. SSE는 `/stream?access_token=` (EventSource는 헤더를 못 보냄). |
| ① 요건 확정에서 내용 수정이 되나? | 확정 · 보류만. |
| ② "수정함"은 코드 직접 수정인가? | MVP는 코멘트로 수정 요청 (`REQUEST_CHANGES`). Agent가 반영하고 verify를 다시 돈다. |
| 검증 실패 패치의 publish 차단 예외? | 없음. 서버가 409로 막는다. 해당 위치를 `excludedSpecKeys`로 빼고 승인하거나 수정 요청한다. |
| 규정 파일 형식 | `.md` / `.markdown` / `.txt`, UTF-8, 파일당 1MB 이하. |
| 작업 티켓은 어디에 생기나? | 백엔드 `work_tickets` 테이블 (Jira 대신). 링크는 `/tickets/{id}`, 참조는 `RR-{id}`. |
| 명세서 출력 형식 | `GET /tasks/{id}/report`의 `report.markdown`. 화면 렌더링 + 다운로드. |
| history 모드 SPA fallback | frontend 컨테이너(nginx)의 `try_files $uri /index.html`로 처리. Spring은 `/api`만 담당. |

## 3. 인증 · 역할

| 역할 | 누구 | 할 수 있는 것 |
|---|---|---|
| `OFFICER` | 준법감시 · 상품기획 담당자 | 규정 업로드, ① 요건 확정 |
| `DEVELOPER` | 개발자 | 규정 업로드, ② 검토 · 승인 |

조회는 로그인한 사람 모두 가능. 역할이 다르면 403.

```http
POST /api/auth/login   {"username":"officer1","password":"password"}
→ {"token":"…","userId":1,"username":"officer1","displayName":"김준법","role":"OFFICER"}
GET  /api/auth/me
```

## 4. 작업 상태

FRONTEND_PLAN.md 작업 상태 표와 같은 이름을 쓴다.

```
EXTRACTING ─▶ WAITING_REQUIREMENT_APPROVAL ─(확정)─▶ LOCATING ─▶ DESIGNING ─▶ VERIFYING ─▶ WAITING_REVIEW ─(승인)─▶ PUBLISHING ─▶ DONE
     │                    │                                          ▲            │              │
     └▶ NO_CHANGE         └(전부 보류)▶ HELD                          └── 재시도 ──┘              ├(거절)▶ REJECTED
                                                                     ▲                          └(수정 요청)▶ DESIGNING
                                                                                  어디서든 오류 ▶ FAILED
```

단순화 흐름([SIMPLIFICATION.md](./SIMPLIFICATION.md))에서는 요건 확정 없이 `EXTRACTING ─▶ LOCATING`으로 바로 간다. 두 흐름 모두 허용한다.

`GET /tasks/{id}`의 `pendingAction`이 지금 사람이 할 일을 알려준다 (`{step, role, path}` 또는 `null`).
라우터 가드는 이 값과 `status`만 보면 된다.

## 5. 공개 API (`/api/ai/tasks`)

에러는 항상 `{"error":"CONFLICT","message":"…"}` 형태.
400 입력 오류 · 401 미인증 · 403 역할 · 404 없음 · 409 상태 충돌 · 413 파일 크기.

| 프론트 함수 | Method · Path | 요청 | 응답 |
|---|---|---|---|
| `createTask(files)` | `POST /api/ai/tasks` | multipart: `oldFile`, `newFile`, `title?`, `oldVersion?`(기본 v3), `newVersion?`(기본 v4) | **202** `{taskId, status}` |
| `listTasks()` | `GET /api/ai/tasks?mine=false` | `mine=true`면 내가 만든 것만 | `TaskSummary[]` |
| `getTask(id)` | `GET /api/ai/tasks/{id}` | | `{task, errorMessage, maxVerifyRounds, documents, pendingAction, counts, approvals, deliveries}` |
| `getRequirements(id)` | `GET /api/ai/tasks/{id}/requirements` | | `{task, documents, requirements[]}` — 요건마다 `oldText` · `newText` (신·구 원문) |
| `approveRequirements(id, d)` | `POST /api/ai/tasks/{id}/requirements/approval` | `{decisions:[{requirementId, decision:"CONFIRMED"\|"HELD"}], comment?}` — **모든 요건**에 결정 필요 | `Approval` |
| `getChangeSpecs(id)` | `GET /api/ai/tasks/{id}/change-specs` | | `{task, targets[], nonTargets[]}` — 대상 아님도 `reason` 포함 |
| `getPatches(id)` | `GET /api/ai/tasks/{id}/patches` | | `{task, maxVerifyRounds, latestRound, passed, failed, pending, canApprove, patches[], testCases[]}` — `patches`는 회차 전체, 현재 것은 `latest:true` |
| `reviewPatches(id, d)` | `POST /api/ai/tasks/{id}/review` | `{decision:"APPROVE"\|"REJECT"\|"REQUEST_CHANGES", comment?, excludedSpecKeys?}` — 수정 요청은 comment 필수 | `Approval` |
| `getReport(id)` | `GET /api/ai/tasks/{id}/report` | | `{task, report, deliveries[]}` |
| `getEvaluation(id)` | `GET /api/ai/tasks/{id}/evaluation` | | `{task, evaluation}` |
| (폴링) | `GET /api/ai/tasks/{id}/events?after={seq}` | | `{seq, type, payload, createdAt}[]` |
| (SSE) | `GET /api/ai/tasks/{id}/stream?access_token={jwt}` | `Last-Event-ID` 또는 `?after=` | `event: {type}` / `data: {seq,type,payload}` |
| `resetDemo()` | `POST /api/demo/reset` | | `{tasks, jobs, workTickets, products, productRules, loanContracts}` — 작업 기록을 지우고 업무 데이터를 `data/business` JSON으로 되돌린다. 계정은 남긴다. `DEMO_RESET_ENABLED=false`면 404 |

### 승인 규칙 (서버가 검사)

| 단계 | 누가 | 언제 | 검사 |
|---|---|---|---|
| ① 요건 확정 | OFFICER | `WAITING_REQUIREMENT_APPROVAL` | 모든 요건에 CONFIRMED/HELD. 하나라도 확정 → `LOCATING`, 전부 보류 → `HELD` |
| ② 검토 · 승인 | DEVELOPER | `WAITING_REVIEW` | APPROVE: 제외하지 않은 현재 패치가 **전부 PASSED**여야 함 (아니면 409). `canApprove`가 같은 판단을 미리 알려준다 |

### 주요 객체

```jsonc
// Requirement
{"id":1,"reqKey":"R1","summary":"고령자 기준 만 65세 → 만 60세","target":"개인신용대출 전 상품",
 "effectiveDate":"2026-12-01","transitional":"시행일 이후 신청분부터, 기존 계약은 종전 기준",
 "articleRef":"제15조","oldText":"…","newText":"…","status":"PROPOSED","detail":{}}

// ChangeSpec
{"id":3,"specKey":"S3","reqKey":"R1","locationKind":"CODE","filePath":"loan/pricing.py",
 "symbol":"SENIOR_AGE_MONTHS","lineNo":12,"snippet":"SENIOR_AGE_MONTHS = 780",
 "changeType":"VALUE","target":true,"reason":"월 단위로 표현된 같은 기준 (65×12)","bundle":"pricing","detail":{}}
// 대상 아님: "target":false, "changeType":null, "reason":"소득 추정용 은퇴 나이, 고령자 기준과 무관"

// Patch
{"id":7,"bundle":"eligibility","round":2,"specKeys":["S1","S4"],"filePath":"loan/eligibility.py",
 "diff":"--- a/…\n+++ b/…","verifyStatus":"PASSED","verifyLog":"…","failureKind":null,"latest":true,"detail":{}}

// Approval — ① 요건 확정은 요청 값 그대로 CONFIRMED(하나라도 확정) · HELD(전부 보류)
{"id":1,"step":"REQUIREMENTS","decision":"CONFIRMED","approverId":1,
 "approver":{"userId":1,"username":"officer1","displayName":"김준법","role":"OFFICER"},"comment":"R2 보류",
 "payload":{"decisions":[{"requirementId":1,"reqKey":"R1","decision":"CONFIRMED"},…],"confirmedReqKeys":["R1"]},
 "createdAt":"…"}
// ② 검토 · 승인은 step "REVIEW", decision APPROVE · REJECT · REQUEST_CHANGES
```

`changeType`: `VALUE`(①) · `LOGIC`(②) · `DB`(③) · `NEW`(④).
`locationKind`: `CODE` · `CONFIG` · `DB` · `PRODUCT` · `DOC` · `UI`.

### 진행 이벤트 `type`

| type | payload | 화면 |
|---|---|---|
| `STEP` | `{node, round?, message?}` | 단계 표시. `node=verify`면 `round`회차 |
| `APPROVAL_REQUIRED` | `{step:"REQUIREMENTS"\|"REVIEW", summary?}` | 승인 화면으로 이동 버튼 |
| `RESUMED` | `{step, decision, by, approvalId}` | |
| `TOOL_START` / `TOOL_END` | `{tool, attempt?, ok?, retrying?, dead?, error?}` | 큐 재시도 표시 |
| `TOKEN` | `{text}` | (선택) 스트리밍 |
| `STATUS` | `{status}` | |
| `DONE` | `{outcome:"DONE"\|"NO_CHANGE"\|"HELD"\|"REJECTED"}` | 종료 |
| `FAILED` | `{reason}` | 오류 화면 |

## 6. Agent ↔ Spring

### Spring → Agent

둘 다 바로 202를 돌려주고, 실제 작업은 백그라운드에서 한다.

```http
POST {AGENT_BASE_URL}/run
{"taskId","threadId","title","documents":[{"side":"OLD","versionLabel":"v3","filename","sha256"},…],
 "callbackBaseUrl":"http://backend:8080/internal/tasks/{taskId}"}

POST {AGENT_BASE_URL}/resume
{"taskId","threadId","step":"REQUIREMENTS"|"REVIEW","decision","approvalId","comment","payload","callbackBaseUrl"}
```

`decision`: REQUIREMENTS면 `CONFIRMED` · `HELD`, REVIEW면 `APPROVE` · `REJECT` · `REQUEST_CHANGES`.

`/resume`의 payload
- REQUIREMENTS: `{decisions:[{requirementId, reqKey, decision}], confirmedReqKeys:[…]}`
- REVIEW: `{excludedSpecKeys:[…], approvedPatchIds:[…]}` (APPROVE일 때만 approvedPatchIds)

### Agent → Spring (`{callbackBaseUrl}` 아래)

| Method · Path | 언제 | 본문 |
|---|---|---|
| `GET /documents` | 시작 | → `[{side, versionLabel, filename, sha256, content}]` |
| `GET ` (빈 경로) | 아무 때 | → `{id, title, status, currentNode, verifyRound, threadId}` |
| `GET /approvals` | 재개 후 | → interrupt 기록 |
| `POST /events` | 노드 진입마다 | `{type, payload}` — 위 이벤트 표 |
| `PUT /requirements` | requirement_agent | `{items:[{reqKey, summary, target, effectiveDate, transitional, articleRef, oldText, newText, detail}]}` — EXTRACTING에서만, 전체 교체 |
| `PUT /change-specs` | locate_agent | `{items:[{specKey, reqKey, locationKind, filePath, symbol, lineNo, snippet, changeType, target, reason, bundle, detail}]}` — specKey upsert |
| `POST /test-cases` | test_agent | `{items:[{testKey, reqKey, name, kind:"BOUNDARY"\|"EFFECTIVE_DATE"\|"SYSTEM"\|"UNIT", code, detail}]}` — **한 번만**, 두 번째는 409 |
| `PUT /patches` | design · verify | `{items:[{bundle, round, filePath, specKeys, diff, verifyStatus, verifyLog, failureKind, detail}]}` — (bundle, round, filePath) upsert. verify 결과만 보낼 땐 diff 생략 |
| `PUT /report` | report | `{markdown, summary, …}` 자유 형식 |
| `PUT /evaluation` | 평가 스크립트 | `{locate:{recall, precision}, trapErrors, verifyPassRate:{round1, round2}, keywordBaseline:{…}, elapsedSec}` |

**순서 규칙**
1. 노드에 들어갈 때 `STEP {node}` → 상태가 자동으로 바뀐다 (`requirement_agent`→EXTRACTING, `test_agent`·`locate_agent`→LOCATING, `plan`·`worker`·`merge`·`design_agent`→DESIGNING, `verify`→VERIFYING, `publish`→PUBLISHING).
2. interrupt 직전에 산출물을 저장하고 `APPROVAL_REQUIRED {step}`을 보낸다.
3. 실질 변경 0건이면 `PUT /report` 후 `DONE {outcome:"NO_CHANGE"}`.
4. 끝나면 `PUT /report` 후 `DONE {outcome}`. 오류는 `FAILED {reason}`.
5. 위 4절 그림에 없는 전이는 409. `WAITING_*`에서 나가는 전이는 승인 API만 한다 (Agent는 `FAILED`만 가능). 종료 상태는 같은 outcome의 `DONE`만 받는다.
6. 산출물 저장 가능 상태 (그 밖에는 409)

| 경로 | 상태 |
|---|---|
| `PUT /requirements` | EXTRACTING |
| `PUT /change-specs` | LOCATING · DESIGNING · VERIFYING |
| `POST /test-cases` | LOCATING |
| `PUT /patches` | DESIGNING · VERIFYING (검토 대기부터 고정) |

## 7. 쓰기 도구 (승인 필요)

`create_draft_pr` · `create_work_ticket`은 서버가 다시 검증한다. 그래프의 interrupt만 믿지 않는다.

```http
POST /internal/work-tickets      ← business-mcp create_work_ticket
{"taskId","approvalId","idempotencyKey":"{taskId}:ticket:S1","title","description","type":"CODE"|"CONFIG"|"DB"|"DOC"|"TEST","targetRef","specKeys":["S1"],"assignee"}

POST /internal/jobs              ← code-mcp create_draft_pr
{"taskId","type":"CREATE_DRAFT_PR","approvalId","idempotencyKey":"{taskId}:pr:{bundle}","payload":{"branch","specKeys":[…]}}

→ 202 {"jobId","status":"QUEUED","duplicate":false}
```

검증 (실패 시 403/409)
1. `approvalId`가 같은 작업의 REVIEW/APPROVE 기록
2. 그 작업의 **가장 최근** REVIEW 결정 (이후 수정 요청 · 거절로 뒤집히지 않음)
3. 작업 상태가 `PUBLISHING`
4. `specKeys`가 승인 때 제외한 위치가 아님

같은 `idempotencyKey`로 다시 오면 새로 만들지 않고 기존 `jobId`를 `duplicate:true`로 돌려준다.
publish 노드는 `GET /internal/jobs/{jobId}`로 `DONE`/`DEAD`를 기다린 뒤 report로 간다.

## 8. 큐 (가산점)

```
rr.jobs (direct) ─ job ──▶ rr.jobs.q ──▶ JobWorker ─ 성공 ─▶ DONE
                                             └ 실패 ─▶ rr.jobs.retry (TTL 3초) ─▶ rr.jobs.q   (최대 3회)
                                                        └ 3회 실패 ─▶ rr.jobs.dlq  (DEAD)
```

- 처리 중 `TOOL_START` / `TOOL_END {ok, attempt, retrying, dead}` 이벤트가 화면으로 간다.
- 시연용으로 `JOB_FAILURE_RATE`(기본 0.3) 확률로 일부러 실패한다. `0`이면 항상 성공.
- RabbitMQ 콘솔 http://localhost:15672 (guest/guest)에서 retry · DLQ 큐를 보여줄 수 있다.

## 9. business-mcp 읽기 도구

| 도구 | Spring |
|---|---|
| `get_product_rules(key?)` | `GET /internal/product-rules?key=ELIGIBLE_MIN_AGE` (key 없으면 전체) |
| | `GET /internal/products`, `GET /internal/products/{productId}/rules` |
| `get_db_schema()` | `GET /internal/db/schema` |
| (경과조치 판단) | `GET /internal/contracts/impact?ageFrom=60&ageTo=64&appliedBefore=2026-12-01` |

데이터와 스키마는 [data/business/README.md](../data/business/README.md)를 따른다. 기동할 때 `data/business/*.json`을 읽어 비어 있는 테이블에만 넣는다.

```jsonc
// GET /internal/product-rules — effectiveTo가 null이면 현재 유효
{"ruleId":"R010","productId":"P002","ruleKey":"ELIGIBLE_MIN_AGE","value":"65","unit":"age",
 "effectiveFrom":"2024-01-01","effectiveTo":null}

// GET /internal/contracts/impact?ageFrom=60&ageTo=64&appliedBefore=2026-12-01
{"ageFrom":60,"ageTo":64,"total":2,"byProduct":{"P001":2},"appliedBefore":"2026-12-01","grandfathered":2,
 "contracts":[{"contractId":"C0002","productId":"P001","status":"ACTIVE","appliedAt":"2025-06-11",
               "ageAtApplication":62,"grandfathered":true}, …]}
```

- `unit`: `ratio` · `percent_point` · `krw` · `age` · `score` · `bool`
- 경과조치는 기존 행을 `effectiveTo = 2026-11-30`으로 닫고 `effectiveFrom = 2026-12-01` 행을 추가한다.
- `contracts/impact`의 나이는 `birth_date`와 `applied_at`으로 계산한 신청일 기준 만 나이다. `REJECTED`와 만기 지난 계약은 세지 않는다. `appliedBefore`보다 먼저 신청한 건이 `grandfathered`(종전 기준 유지)다.

시드의 규칙 키는 시나리오 대상과 함정을 같이 담는다.

| rule_id | 키 · 값 | 판단 | 이유 |
|---|---|---|---|
| R001, R011 | `DSR_LIMIT 0.40` | 변경 대상 | 제8조 40% → 35% |
| R010 | P002 `ELIGIBLE_MIN_AGE 65` | 변경 대상 | 제15조 고령자 기준. 키에 SENIOR가 없다 |
| R015 | P003 `DSR_LIMIT 0.35` | 대상 아님 | 상품 기준이 이미 신 기준 이하 |
| R007, R018 | `MORTGAGE_LTV_LIMIT 0.40` | 함정 | 같은 0.40이지만 LTV(제10조) |
| R008 | `INCOME_EST_RETIREMENT_AGE 65` | 함정 | 같은 65지만 소득 추정용 정년(제7조) |
| R005, R013, R019 | `SENIOR_RATE_DISCOUNT 0.3` | 대상 아님 | 우대 폭은 그대로, 적용 대상만 넓어짐 |

## 10. 단순화 흐름 계약 (v2)

기준: [SIMPLIFICATION.md](./SIMPLIFICATION.md) v2. 요청 · 응답 예시는 [`docs/contracts/`](./contracts/)에 있고, 각 영역 테스트가 같은 파일을 읽는다.

### 10.1 상태 · 노드

```
EXTRACTING ─▶ LOCATING ─▶ DESIGNING ⇄ VERIFYING ─▶ WAITING_REVIEW ─(APPROVE)─▶ PUBLISHING ─▶ DONE
     │            │                                       └(REJECT)▶ REJECTED
     └▶ NO_CHANGE ┘ (전 상품 유지)                    어디서든 오류 ▶ FAILED
```

| 노드 (`STEP {node}`) | 상태 |
|---|---|
| `requirement_agent` | `EXTRACTING` |
| `impact_agent` (`product_impact_agent`도 받음) | `LOCATING` |
| `proposal_agent` | `DESIGNING` |
| `verify` (`round` 포함) | `VERIFYING` |
| interrupt 직전 `APPROVAL_REQUIRED {step:"REVIEW"}` | `WAITING_REVIEW` |
| `apply` | `PUBLISHING` |
| `report` 뒤 `DONE {outcome}` | `DONE` · `NO_CHANGE` · `REJECTED` |

- `WAITING_REQUIREMENT_APPROVAL` · `HELD`는 쓰지 않는다.
- 역할 검사는 없다. 로그인한 사용자 누구나 확인할 수 있다.

### 10.2 제안 (`rule_proposals`)

제안 1건 = 상품 1개 × 규칙 1개. 새 규칙(제15조의2 등)도 상품마다 1건이다.

| 필드 | 형식 | 규칙 |
|---|---|---|
| `proposalKey` | 문자열 | Agent가 정한다. 작업 안에서 고유 (권장: `{productId}:{ruleKey}`) |
| `reqKey` | 문자열 | 근거 요건 |
| `productId` | `P001` | 필수 |
| `ruleId` | `R001` \| null | 기존 규칙 변경 · 유지면 필수, 새 규칙이면 null |
| `ruleKey` | 문자열 | `change_required`면 필수 |
| `impact` | `change_required` \| `keep` \| `needs_check` | 필수 |
| `current` · `proposed` | 문자열 | 화면용 글 ("DSR 한도 40%") |
| `unit` | `ratio` · `percent` · … | `change_required`면 필수. 기존 규칙의 단위를 바꾸지 않는다 |
| `currentValue` · `proposedValue` | 문자열 | `change_required`면 `proposedValue` 필수, 기존 규칙이면 `currentValue`도 필수 |
| `effectiveDate` | `YYYY-MM-DD` | `change_required`면 필수 |
| `basis` | 문자열 | 근거 조항 (`reg://credit-loan-ops/v4/8`) |
| `reason` | 문자열 | 필수 (`keep` · `needs_check`는 왜 그런지) |
| `transition` | 문자열 | 경과조치 |
| `followUp` | 문자열 배열 | 후속 작업 (화면 문구 · 심사 절차 · 설명서) |
| `round` | 1 이상 | 작성 회차 |
| `verifyStatus` · `verifyLog` | `PENDING` \| `PASSED` \| `FAILED` | 근거 검사 결과 |

**Agent → Spring** `PUT {callbackBaseUrl}/proposals` `{items:[…]}` ([예시](./contracts/proposals.put.json))
- `(proposalKey, round)` 기준 upsert. 근거 검사 결과만 보낼 때도 같은 항목을 보낸다.
- `DESIGNING` · `VERIFYING`에서만 받는다. `WAITING_REVIEW`부터 고정 (사용자가 본 제안과 반영할 제안이 같아야 한다).

**화면** `GET /api/ai/tasks/{id}/proposals`
- `{task, maxVerifyRounds, latestRound, canApprove, proposals[]}`
- `proposals`는 회차 전체이고 현재 것은 `latest:true`. 서버가 `decision`(`APPLY` · `EXCLUDE` · null)과 반영 결과 `apply {jobId, status, closedRuleId, newRuleId}`를 붙인다.
- 현재 제안 = 제안 묶음(`reqKey` × `productId`)마다 가장 높은 `round`의 행. 재작성 회차에서 빠진 규칙 행은 이전 회차에 남지만 현재 제안이 아니다 (키마다 최고 회차를 고르면 1회차에만 있던 `FAILED` 행이 `canApprove`를 영원히 막는다).
- `canApprove`: `WAITING_REVIEW` + 현재 `change_required` 제안이 1건 이상 + 모두 `PASSED`.

### 10.3 사용자 확인

`POST /api/ai/tasks/{id}/review` ([예시](./contracts/review.post.json))

```json
{"decision": "APPROVE", "excludedProposalKeys": ["P005:DSR_LIMIT"], "comment": "P005는 화면 문구 정비 후 반영"}
```

| 결정 | 검사 | 결과 |
|---|---|---|
| `APPROVE` | `canApprove`(아니면 409). 제외 키는 현재 `change_required` 제안이어야 함(400). 제외하고 남는 게 없으면 400 (REJECT로 보낸다) | `PUBLISHING`. 기록 payload `{approvedProposalKeys, excludedProposalKeys}` |
| `REJECT` | | `REJECTED` |

- 수정 요청(`REQUEST_CHANGES`)은 없다.
- 작업 상세(`GET /api/ai/tasks/{id}`)의 `pendingAction.role`은 항상 null이고, `counts.proposals`(현재 회차 제안 수)가 붙는다.
- Agent 재개: `POST /resume {step:"REVIEW", decision, approvalId, payload}` — payload는 위 기록과 같다. Agent는 그래프를 돌리기 전에 거부할 수 있다: 검토 대기 중인 thread가 아니면(없거나 이미 끝남) 409, `approvedProposalKeys ∪ excludedProposalKeys`가 Agent가 보낸 현재 `change_required` 키와 다르거나 APPROVE에 `approvalId`가 없으면 400. 202 뒤에는 `apply` → `report` → `DONE` 또는 `FAILED`가 콜백으로 온다.

### 10.4 반영 (쓰기 도구 · 승인 필요)

business-mcp `apply_rule_version(task_id, approval_id, proposal_key, idempotency_key)` → Spring:

```http
POST /internal/product-rules/versions
{"taskId", "approvalId", "proposalKey", "idempotencyKey": "{taskId}:apply:{proposalKey}"}

→ 202 {"jobId", "status": "QUEUED", "duplicate": false}
```

**Agent는 값을 보내지 않는다.** 서버가 `rule_proposals`의 현재 제안에서 지금 값 · 제안 값 · 단위 · 시행일을 꺼낸다. 사용자가 확인한 값과 다른 값은 들어갈 수 없다.

접수 검사 (실패 시 403 · 409)
1. `approvalId`가 이 작업의 REVIEW/APPROVE 기록이고, 가장 최근 REVIEW 결정이다 (403)
2. 작업 상태가 `PUBLISHING`이다 (409)
3. `proposalKey`가 `approvedProposalKeys`에 있고, 현재 제안이 `change_required` · `PASSED`다 (403)
4. 기존 규칙이면 그 행이 지금 유효하고 값이 `currentValue`와 같다. 새 규칙이면 같은 상품 · 규칙 키의 유효한 행이 없다. 아니면 409 "이미 바뀐 규칙". 값은 **숫자로 비교**한다 (`0.4` = `0.40`)
5. 같은 `idempotencyKey`면 새로 만들지 않고 기존 `jobId`를 `duplicate:true`로 돌려준다

대기열 작업 `APPLY_RULE_VERSION` (8절 큐 · 재시도 · DLQ 그대로)
- 행을 잠그고 4번을 다시 검사한다. 다르면 **재시도하지 않고 바로 `DEAD`** (`lastError` = "이미 바뀐 규칙"). 다시 해도 결과가 같기 때문이다.
- 기존 행: `effective_to = effectiveDate - 1일`
- 새 행: `rule_id` = 기존 최대 번호 다음(`R083`부터), `value = proposedValue`, `unit`, `effective_from = effectiveDate`, `effective_to = null`
- 새 규칙은 닫는 행 없이 새 행만 추가한다.
- 결과 `GET /internal/jobs/{jobId}` → `{status, result: {proposalKey, productId, closedRuleId, newRuleId, effectiveFrom}}` ([예시](./contracts/apply.job.json)). 새 규칙이면 `closedRuleId: null`.
- 전달 기록(`deliveries`)에 `RULE_VERSION`으로 남긴다.
- 일반 큐 API `POST /internal/jobs`는 `APPLY_RULE_VERSION`을 받지 않는다 (400). 제안 · 지금 값 검사를 건너뛰지 못하게 반영은 이 API로만 받는다.

Agent `apply` 노드: 승인된 제안마다 한 번씩 호출하고 `/internal/jobs/{jobId}`가 `DONE` · `DEAD`가 될 때까지 기다린다. 모두 `DONE`이면 `DONE {outcome:"DONE"}`, 하나라도 `DEAD`면 `FAILED {reason}`.

### 10.5 business-mcp 읽기 (보강)

| Spring | 추가 |
|---|---|
| `GET /internal/products` | `?status=ON_SALE\|SALE_ENDED` |
| `GET /internal/product-rules` | `?productId=`, `?asOf=YYYY-MM-DD` — 그날 유효한 행만 (`effectiveFrom ≤ asOf`, `effectiveTo`가 null이거나 `≥ asOf`) |
| `GET /internal/product-rules/keys` (신규) | `?asOf=` (기본 오늘) → `[{ruleKey, units, productIds, activeRows, closedRows, upcomingRows}]`. #23 `list_rule_keys` 모양에 `upcomingRows`(아직 시작 전인 행, 반영 직후 생김)를 더했다. `productIds`는 `asOf`에 유효한 행이 있는 상품 ([예시](./contracts/rule-keys.get.json)) |
| `GET /internal/contracts/impact` | `?dsrFrom=&dsrTo=` — `dsr_at_approval`이 (dsrFrom, dsrTo] 안. 나이 조건과 함께 주면 둘 다 만족. 계약마다 `dsrAtApproval` · `repaymentType` · `maturityDate` · `extensionCount` · `maturesAfterEffective`(만기 ≥ `appliedBefore`) 추가. 연장 사례(C0006)는 만기일시 · 연장 이력으로 Agent가 판단한다 ([예시](./contracts/contract-impact.get.json)) |

**"지금 유효"는 `effectiveTo == null`이 아니다.** 반영하면 기존 행은 `effective_to = 2026-11-30`(오늘은 아직 유효), 새 행은 `effective_from = 2026-12-01`(오늘은 아직 아님, `effectiveTo` null)이 된다. 유효 여부는 `asOf`로 판단한다.

### 10.6 계약 영향 저장 · 조회

- Agent: `PUT {callbackBaseUrl}/contract-impacts` `{items:[{contractId, reqKey, reason, grandfathered, maturesAfterEffective}]}` — 전체 교체, `LOCATING` ~ `VERIFYING`.
- 화면: `GET /api/ai/tasks/{id}/contract-impacts` → `{task, items}`. 계약 값은 바꾸지 않는다.

### 10.7 정리 예정 (옛 흐름)

새 흐름이 끝까지 동작하면 지운다: `/requirements/approval`, `/change-specs`, `/patches`, `/test-cases`, `/internal/work-tickets`, 큐 작업 `CREATE_DRAFT_PR` · `CREATE_TICKET`, `REQUEST_CHANGES`, 역할(`OFFICER` · `DEVELOPER`) 검사.
