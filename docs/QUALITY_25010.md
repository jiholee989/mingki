# ISO/IEC 25010 품질 특성별 아키텍처 설계 근거

Capstone 평가표 "아키텍처 설계 — ISO/IEC 25010 품질평가를 고려한 아키텍처 설계"에 대한 답이다.
품질 특성마다 **무엇이 위험이었고, 어떻게 설계했고, 코드 · 문서 어디에 있으며, 어떻게 확인했는지**를 적는다.
전체 흐름은 [PROJECT.md](./PROJECT.md) · [SIMPLIFICATION.md](./SIMPLIFICATION.md), 인터페이스는 [BACKEND_API.md](./BACKEND_API.md)를 따른다.

ISO/IEC 25010:2023의 특성 9개를 쓴다. 2011판 이름이 다른 것은 괄호에 적었다.

| 영역 | 담당 | 이 문서에서 |
|---|---|---|
| 백엔드(Spring) · 전체 구조 | C | 작성함 |
| Agent(LangGraph) | A | 백엔드가 확인한 사실만 적음. 담당이 보완 |
| MCP 서버 3개 | B | 같음 |
| 데이터 · 평가 | E | 작성함 (2.1 정답지 · 채점 줄, 2.7 데이터 줄, 2.9 계약 영향 줄, 4 · 5절 숫자) |
| 프론트 | D | 비어 있음 |

## 0. 한눈에 보기

| 특성 | 핵심 설계 결정 | 근거 위치 |
|---|---|---|
| 기능 적합성 | 정답지 기반 채점으로 "맞게 판단했는가"를 수치로 측정 | `eval/score_proposals.py`, `expected_proposals*.yaml` |
| 성능 효율성 | 긴 작업은 202 + 비동기, 결과는 폴링 · SSE, 무거운 반영은 큐 | `TaskController`, `JobWorker`, `AgentDispatcher` |
| 호환성 | 영역 간 인터페이스를 계약 문서 + 예시 JSON으로 고정, 모든 영역 테스트가 같은 파일을 읽음 | `BACKEND_API.md` 10절, `docs/contracts/` |
| 상호작용 능력(사용성) | 사람 확인 1번, 제안마다 반영 · 제외, 화면이 계산하지 않도록 서버가 `canApprove` · `pendingAction` 제공 | `TaskDtos` |
| 신뢰성 | 멱등키 · 재시도 · DLQ, 같은 트랜잭션 커밋, DB 체크포인터, "다시 시도" 복구, 시연 리셋 | `RuleVersionService`, `JobWorker`, `agent/app/checkpoint.py`, `/retry` |
| 보안성 | JWT 공개 API · 내부 토큰 `/internal/**`, 쓰기 도구는 승인 기록을 서버가 재검증, Agent는 값을 보내지 않음, 정답지는 Agent 접근 범위 밖 | `SecurityConfig`, `ApprovalGuard`, `RuleVersionService` |
| 유지보수성 | 영역별 폴더 · 담당, 계약 테스트, CI, 판단 로직을 DB 없이 테스트 가능한 순수 클래스로 분리 | `BusinessQueries`, `Proposals`, `RuleVersions`, `.github/workflows/ci.yml` |
| 이식성 | docker compose 한 번으로 전체, 설정은 환경 변수, 시드는 JSON 파일 | `docker-compose.yml`, `BusinessDataLoader` |
| 안전성 | 업무 데이터는 사람이 확인한 제안만, 지금 값이 바뀌었으면 거절, 기존 행은 지우지 않고 종료일로 닫음 | `RuleVersions.problem`, `RuleVersionService.apply` |

## 1. 시스템 구조와 신뢰 경계

```
사용자(브라우저) ──(/api/**, JWT)──▶ Spring 백엔드 ──(/run · /resume · /continue)──▶ Agent(FastAPI + LangGraph)
                                        ▲                                                │
                                        └────(/internal/**, X-Internal-Token)────────────┤  콜백 · business-mcp
                                                                                         ▼
                                                    regulation-mcp ◀── Agent ──▶ business-mcp ──▶ Spring /internal
```

- Agent · MCP는 docker network 안에서만 불린다. 밖으로 열린 건 백엔드(8080)와 개발 편의용 DB · RabbitMQ 포트다. 호스트에서 Agent를 띄울 때는 `docker-compose.agent-local.yml`로 MCP 포트를 127.0.0.1에만 연다.
- **업무 규칙은 Spring 한 곳에만 있다.** MCP는 Spring `/internal/**`을 감싸고, Agent는 MCP를 통해서만 업무 데이터를 본다. 그래서 "무엇이 허용되는가"를 고칠 때 한 곳만 고친다.
- 정답지(`eval/`)는 어느 컨테이너에도 마운트되지 않는다. Agent가 읽을 수 있는 건 규정 원문 · 상품 문서 · Spring 응답뿐이다 (`docker-compose.yml`의 마운트 목록).

## 2. 품질 특성별 설계

형식: **위험 → 설계 → 위치 → 확인**.

### 2.1 기능 적합성 (Functional suitability)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| LLM이 그럴듯하지만 틀린 제안을 냄 | 정답지와 자동 비교. 판정 12/12, 변경 대상 recall, 값 · 단위, 날짜 · 경과조치, 함정 오판 0건을 핵심 지표로 두고 하나라도 미달이면 실패 | `eval/score_proposals.py`, `eval/expected_proposals*.yaml` (DSR · 고령자 · 설명 확인 3개 시나리오) | 실제 LLM 실행에서 12개 상품 중 11개 일치 (#35, 다른 1건은 4절 P006). 채점기 테스트 18개 |
| 같은 숫자 · 다른 의미(LTV 0.40, 정년 65), 단위가 다른 규칙(percent 35), 종료된 옛 행 | 함정을 데이터에 심고 정답지 `must_not`으로 채점. 유효 여부는 `effectiveTo == null`이 아니라 날짜(`asOf`)로 판단 | `data/business/product_rules.json`, `ProductRule.isValidOn`, business-mcp `as_of` | `BusinessQueriesTest.validityFollowsDatesNotMissingEndDate`, #23 리뷰에서 발견해 양쪽 수정 |
| 제안이 근거 없이 나옴 | Agent 근거 검사: 인용 조항이 실제 diff에 있는지, 지금 값이 조회 결과와 같은지, 단위 변환(35% → ratio 0.35 / percent 35) | `agent/app/validation.py` | Agent 테스트 122개. 정답지는 검사에 쓰지 않는다 (SIMPLIFICATION 4절) |
| 판단을 못 하는 경우를 "맞음"으로 포장 | 세 번째 판정 `needs_check`. 자료가 없으면 지어내지 않고 추가 확인으로 낸다 | `Proposals.IMPACTS`, `product_impact_agent` | 정답지에 `needs_check` 정답 포함 (DSR P010, 설명 확인 P009) |
| 정답지가 데이터와 어긋나 채점이 틀림 (데이터를 늘리거나 고칠 때) | 정답지의 상품 · 규칙 ID · 지금 값 · 단위 · 근거 조항 · 계약 ID를 실제 데이터와 대조하는 테스트. 모든 상품에 판정이 있는지도 검사 | `eval/test_score_proposals.py` `test_expected_matches_data` | 시나리오 3개 모두 통과 (#44). 정답지 YAML의 쉼표로 이유가 잘리던 버그도 #42에서 고침 |
| 새 규칙(제15조의2)처럼 규칙 이름을 Agent가 알 수 없음 | 새 규칙은 `rule_key` 이름을 채점하지 않고 값 · 단위 · 시행일로 채점 | `score_proposals.py` (`ruleId: null` 매칭) | `test_new_rule_is_scored_without_rule_id_or_key_name` (#44) |
| 한 시나리오(v3 → v4 DSR)에만 맞춘 판단 | 시나리오마다 정답지를 따로 두고(`--expected`), Agent는 `AGENT_ARTICLE_IDS`로 조항 하나씩 실행. 상품 12개 · 규칙 82개 · 규정 4개로 데이터를 늘려 같은 숫자 · 다른 이름 · 다른 단위가 섞이게 함 | `eval/answer_key.md` 시나리오 표, `data/` (#19) | DSR 11/12 (#35). 고령자 · 설명 확인은 M3 |

### 2.2 성능 효율성 (Performance efficiency)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 규정 분석이 수십 초 ~ 수 분. 요청 스레드를 붙잡으면 화면이 멈춤 | 업로드 · 확인은 **202를 바로 돌려주고** Agent 호출은 트랜잭션 커밋 뒤 `@Async`로. 진행은 `GET /events?after=` 폴링 또는 SSE | `AgentDispatcher`, `TaskController.stream`, `SseBroadcaster` | #35: 업로드 → 39초 뒤 확인 대기. 그동안 API는 응답 |
| 반영(DB 쓰기)이 외부 상태에 따라 느리거나 실패 | RabbitMQ 큐 작업 `APPLY_RULE_VERSION`. 접수와 처리를 분리하고 워커가 하나씩 처리(prefetch 1) | `JobPublisher`, `JobWorker`, `RabbitConfig` | 실패 주입 50%에서 6건 반영 완료 (#35) |
| LLM이 상품 수백 개를 한 번에 읽음 | 조회 도구에 필터(`status`, `productId`, `asOf`)와 규칙 키 집계(`/product-rules/keys`)를 두어 필요한 것만 읽게 함 | `InternalBusinessController`, business-mcp `list_rule_keys` | #23 · #25 |
| 규정 검색이 원문 전체를 LLM에 넣음 | 조항 단위 색인 + 의미 · 키워드 혼합 검색, 상위 5개만 | regulation-mcp `search.py`, [VECTOR_INDEX.md](./VECTOR_INDEX.md) | 혼합 검색 recall@3 89%, 함정 1위 0건 (VECTOR_INDEX 측정표) |
| 체크포인터 DB 연결이 요청마다 열림 | 연결 풀 1개 고정, 끊기면 재연결 | `agent/app/checkpoint.py` (#34) | 코드 확인, DB 재시작 실험은 안 함 |

### 2.3 호환성 (Compatibility)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 영역 5개(백엔드 · Agent · MCP · 프론트 · 데이터)가 각자 인터페이스를 상상해 구현 | **계약 먼저.** 인터페이스는 `BACKEND_API.md` 10절에 PR로 올리고 쓰는 쪽이 승인한 뒤 구현. 요청 · 응답 예시는 `docs/contracts/*.json` 한 벌 | `docs/contracts/` 7개 | 백엔드 `BusinessQueriesTest` · `ProposalsTest`, MCP `test_server.py`, 채점기가 **같은 파일**을 읽는다. 어긋나면 어느 쪽 테스트든 실패 |
| Agent와 백엔드의 제안 단위가 다름(상품 × 요건 vs 상품 × 규칙) | 어댑터가 펼친다. 유지 판정은 `keep` 행으로 보내 "모든 상품에 판정 1개" 규칙을 지킴 | `agent/app/backend.py` `rule_proposals_payload` | `test_server.py` |
| 응답 키 표기(camelCase)와 데이터 파일(snake_case)이 다름 | DB 컬럼 · JSON 파일은 snake_case, API는 camelCase로 고정. 변환은 로더 한 곳 | `BusinessDataLoader` | 시드 로더 테스트 |
| 옛 흐름(코드 패치)과 새 흐름(상품 규칙)이 한동안 공존 | 같은 상태 이름을 재사용하고 새 전이(`EXTRACTING → LOCATING`, `LOCATING → NO_CHANGE`)만 추가해 두 흐름을 함께 돌렸다. 새 흐름이 끝까지 동작한 뒤 옛 흐름을 한 번에 지웠다 (V7, 10.7) | `TaskStatus.agentCanMoveTo`, `V7__drop_old_flow.sql` | `TaskStatusTest` |

### 2.4 상호작용 능력 (Interaction capability, 2011: 사용성)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 사람이 할 일을 화면이 추측해야 함 | 서버가 `pendingAction {step, path}`와 `canApprove`를 계산해서 준다. 화면은 상태와 이 값만 본다 | `TaskDtos.PendingAction`, `Proposals.canApprove` | `GET /api/ai/tasks/{id}` 응답 예시 |
| 확인이 여러 단계면 사용자가 지침 | 사람 확인은 **1번**. 제안마다 반영 / 제외만 고른다 (팀 결정, SIMPLIFICATION 결정 사항) | `TaskService.reviewProposals` | #28 |
| 왜 이런 판단인지 모름 | 제안마다 근거 조항(`basis`), 이유(`reason`), 경과조치(`transition`), 후속 작업(`followUp`)을 함께 저장 | `rule_proposals` V4 | 계약 10.2 |
| 진행 상황을 모름 | 노드마다 `STEP {node, message}` 이벤트, 회차(`round`) 포함 | `TaskEventService` | 계약 10.1 이벤트 표 (#43) |

### 2.5 신뢰성 (Reliability)

가장 많이 투자한 특성이다. 실제 장애를 일으켜 확인했다.

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 큐 메시지 중복 전달로 같은 반영이 두 번 | 멱등키 `{taskId}:apply:{proposalKey}`. 같은 키면 새로 만들지 않고 기존 작업을 돌려줌(`duplicate: true`). 키가 같은데 내용이 다르면 409 | `JobPublisher.publish`, `RuleVersionService.enqueue` | `RuleVersionServiceTest` (#33) |
| 워커가 반영 뒤 · 작업 완료 기록 전에 죽음 | 규칙 행 · 전달 기록 · 작업 `DONE`을 **한 트랜잭션**에 커밋 | `RuleVersionService.apply` | #33 |
| 일시 장애 vs 다시 해도 같은 실패 | 일시 실패는 3초 뒤 최대 3회 재시도 → DLQ. "이미 바뀐 규칙"처럼 영구 실패는 `PermanentJobFailure`로 재시도 없이 DEAD | `JobWorker`, `PermanentJobFailure` | `JobWorkerTest` 3개. 실패 주입 50%에서 2 · 3회차 성공 (#29) |
| Agent 프로세스가 승인 대기 중 죽음 | LangGraph 체크포인터를 Postgres에. 재시작 뒤 같은 `threadId`로 재개 | `agent/app/checkpoint.py` | #30: 검토 대기 중 재시작 → 수정 요청 → 거절까지 이어짐 |
| Agent가 업로드 직후 · 승인 직후 · 반영 도중 죽음 | "다시 시도" `POST /api/ai/tasks/{id}/retry`. Agent `/continue`를 먼저 보내고 409면 저장된 승인으로 `/resume`, 그것도 없으면 `/run`. FAILED였던 작업은 멈춘 자리로 되돌림 | `TaskController.retryTask`, `AgentClient.continueTask` | #39: 세 경우 모두 `kill -9` 후 복구. 반영 도중 죽은 경우 큐 작업이 같은 멱등키로 재사용돼 건수 그대로 |
| 반영 일부만 실패 | 한 건이 접수에서 거절돼도 나머지는 계속하고, 어느 건이 왜 실패했는지 결과에 남김. 최종은 FAILED | `agent/app/nodes/apply.py` (#34) | `test_apply.py` |
| 시드가 반쯤 들어감 | 로더 트랜잭션이 파싱 오류(checked 예외)에도 롤백 | `BusinessDataLoader` `rollbackFor = Exception.class` | 오타 필드 JSON으로 확인 (#6) |
| 실행할 때마다 결과가 달라야 함(반영 뒤 두 번째 실행은 "변경 없음") | 시연 리셋 `POST /api/demo/reset`: 작업 기록 삭제 + 업무 데이터를 JSON 시드로 복원 | `DemoResetService` | #25, #35에서 82행 복원 확인 |
| Agent 상태 전이가 뒤죽박죽 | Agent 이벤트는 `agentCanMoveTo` 표에 있는 전이만 허용(409). 확인 대기 뒤 제안은 고정 | `TaskStatus`, `AgentResultService.lockIn` | `TaskStatusTest` 11개 |
| 콜백 순서가 계약과 다름 | 어댑터가 노드 시작 · 완료 · interrupt · 종료를 정해진 순서로 보냄 | `agent/app/bridge.py` | `agent/tests/test_server.py` 11개 (가짜 Spring) |

### 2.6 보안성 (Security)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 아무나 작업을 만들고 확인함 | 공개 API는 JWT(`Authorization: Bearer`, 480분). 401 · 403도 `{error, message}` 형식 | `SecurityConfig`, `JwtAuthFilter` | 로그인 없이 리셋 → 401 (#25) |
| Agent · MCP가 공개 API를 거치지 않고 아무거나 바꿈 | `/internal/**`은 `X-Internal-Token`이 있어야 한다. backend 포트가 호스트에 열려 있어 네트워크로는 막지 않으므로 토큰이 유일한 경계다. 기본 토큰이면 Agent가 기동 때 경고 | `InternalTokenFilter`, `agent/app/server.py` | 토큰 없이 `/internal/**` → 401 |
| LLM이 "승인됐다"고 주장하며 쓰기 도구를 부름 | 쓰기 도구는 **승인 기록 ID를 받아 서버가 다시 검증**: 같은 작업의 REVIEW/APPROVE인지, 가장 최근 결정인지, 작업이 PUBLISHING인지, 그 제안이 반영으로 골라졌는지 | `ApprovalGuard`, `RuleVersionService.enqueue` | `RuleVersionServiceTest`, 반영으로 고르지 않은 제안 → 403 (#29) |
| LLM이 확인받은 값과 다른 값을 반영 | **Agent는 값을 보내지 않는다.** 서버가 저장된 제안 행에서 지금 값 · 제안 값 · 단위 · 시행일을 꺼낸다 | `RuleVersionService` | 계약 10.4 |
| 일반 큐 API로 검사를 우회 | 큐에 작업을 넣는 일반 API를 두지 않는다. 반영은 `/internal/product-rules/versions`로만 받고 `/internal/jobs`는 조회만 한다 | `JobController`, `InternalBusinessController` | #29, `POST /internal/jobs` → 405 |
| 쓰기 도구가 분석 노드에 노출 | 노드마다 도구 부분집합만 줌. `apply_rule_version`은 `apply` 노드에만 | `agent/app/graph.py` `NODE_TOOLS`, `ToolBelt` | Agent 테스트 |
| 정답 힌트가 Agent 입력에 섞임 | 정답 · 근거 조항 컬럼(`source`, `note`)을 DB에서 제거. `eval/`은 어느 컨테이너에도 마운트 안 함. 규정 `applies_to`는 큰 범위만 | #4 · #6 · #40, `docker-compose.yml` | 로더가 JSON의 `source` · `note`만 무시하고 다른 모르는 필드는 기동 오류 |
| MCP가 받은 ID로 다른 경로에 닿음 | `task_id` · `job_id`는 UUID 형식만, `product_id`는 영숫자만 | business-mcp `_uuid`, regulation-mcp 범위 검사 | MCP 테스트 (#31, #23) |
| 업로드 파일로 서버를 망가뜨림 | `.md` · `.txt`만, 1MB 이하, UTF-8 | `TaskService.readText` | |

### 2.7 유지보수성 (Maintainability)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 판단 로직이 컨트롤러 · DB에 섞여 테스트하기 어려움 | 계산 · 규칙을 DB 없이 테스트하는 순수 클래스로 분리 | `BusinessQueries`(조회 계산), `Proposals`(제안 규칙), `RuleVersions`(반영 판단) | 단위 테스트 53개(백엔드) |
| 팀원 5명이 같은 파일을 고쳐 충돌 | 영역별 폴더 담당(`agent/` A, `mcp/` B, `backend/` C, `frontend/` D, `data/` · `eval/` E, `docs/` PM). 남의 폴더는 그 사람 브랜치로 PR | SIMPLIFICATION 10절 | 어댑터 PR을 Agent 브랜치 위에 올려 A가 리뷰 (#30) |
| 깨진 채 머지 | PR마다 백엔드 · Agent · MCP 2개 · 프론트 테스트 (GitHub Actions) | `.github/workflows/ci.yml` (#38) | 작업 5개 통과 |
| 결정이 슬랙에 흩어짐 | 결정은 `SIMPLIFICATION.md` PR로 확정. 문서에 없는 결정은 미확정. 열린 질문은 11절 | SIMPLIFICATION 10 · 11절 | v1 → v2 → v2.1 변경 이력 |
| 스키마 변경 이력이 없음 | Flyway V1 ~ V7. 공유 DB 뒤로는 V1을 고치지 않고 새 버전으로 | `backend/src/main/resources/db/migration/` | 기존 DB에 V3 ~ V5 적용 확인. V7은 옛 흐름 · 새 흐름 데이터를 섞은 DB 사본에서 적용 · 스키마 검증 통과 |
| 규정이 바뀔 때마다 코드를 고침 | 규정 원문 · 상품 규칙 · 상품 문서를 데이터(`data/`)로 두고, 정책값은 시행일 버전 행으로 관리. 규정 파일 형식은 테스트로 고정 | `data/regulations/README.md`, `product_rules (effective_from, effective_to)`, regulation-mcp `test_data_format.py` | M1 · M2가 규정 파일만으로 동작 (#35) |
| 안 쓰는 코드가 남아 혼란 | 옛 흐름 API · 테이블 · 큐 작업 · 역할을 10.7 목록으로 두고, 새 흐름이 끝까지 동작한 뒤 한 PR로 지웠다. MCP 쪽 code-mcp도 같이 지웠다 (#48) | `BACKEND_API.md` 10.7 | 엔티티 4개 · 테이블 5개 · 엔드포인트 8개 삭제 |

### 2.8 이식성 (Portability)

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| 개발자마다 환경이 달라 안 돌아감 | `docker compose up --build` 한 번으로 postgres · rabbitmq · backend · MCP 2개 · Agent(#49). 호스트에서 Agent를 띄울 때는 `docker-compose.agent-local.yml`로 MCP 포트를 열어 연결. 설정은 전부 환경 변수(`DB_HOST`, `AGENT_BASE_URL`, `JOB_FAILURE_RATE`, `AGENT_MODE` …) | `docker-compose.yml`, `backend/README.md` 환경 변수 표, `agent/README.md` | #25에서 backend 이미지 빌드 · 기동 · 시드 확인, #35에서 Docker 스택 전체 실행 |
| 데이터가 DB에만 있어 옮기기 어려움 | 업무 데이터의 원천은 `data/business/*.json` 하나. 기동 때 빈 테이블에 넣고, 리셋으로 되돌림 | `BusinessDataLoader` | |
| 로컬 개발이 컨테이너 없이 안 됨 | 백엔드는 `./gradlew bootRun`, Agent는 `llm` 모드(로컬 자료) · `live` 모드(MCP)로 선택 | README | |
| Agent 실행 환경 고정 | Python 3.12 · uv · `uv.lock`, JDK 21 · Gradle wrapper 8.10 | `pyproject.toml`, `gradle/wrapper` | CI가 같은 조합으로 실행 |

### 2.9 안전성 (Safety, 2023 신설)

업무 데이터(상품 규칙)를 자동으로 바꾸는 시스템이라, "잘못 바꾸지 않는 것"이 가장 중요한 특성이다.

| 위험 | 설계 | 위치 | 확인 |
|---|---|---|---|
| LLM 제안이 확인 없이 반영됨 | 사람이 제안마다 반영 / 제외를 고르고, 근거 검사를 통과한 변경 제안만 승인 가능(`canApprove`) | `TaskService.reviewProposals` | 검사 실패 제안이 있으면 409 |
| 두 작업이 같은 규칙을 동시에 바꿈 | 접수 때와 워커에서 "지금 값이 제안 당시 값과 같은가"를 두 번 검사(숫자 비교). 다르면 409 "이미 바뀐 규칙". 워커는 테이블을 잠금 | `RuleVersions.problem`, `RuleVersionService.apply` | `RuleVersionsTest` 7개, 같은 키 재반영 → 409 (#29) |
| 기존 행을 덮어써 이력이 사라짐 | 기존 행은 지우지 않고 `effective_to = 시행일 - 1`로 닫고 새 행(`R083`~)을 추가. 시행일 전 신청분은 종전 값을 봄(경과조치) | `RuleVersionService.apply` | 반영 뒤 R001=0.40(~11-30), R084=0.35(12-01~) |
| 미래 버전이 겹침 | 시행일 뒤에 시작하는 행이 이미 있으면 거절 | `RuleVersions.problem` (#33) | `futureVersionBlocksAnEarlierEffectiveDate` |
| 경과조치 대상 계약이 새 기준으로 심사됨 | 계약 영향 조회가 시행일 전 신청 · 만기가 시행일 이후인 계약을 표시하고, 제안서에 함께 보임. 계약 값은 바꾸지 않음 | `BusinessQueries.contractImpact`, 정답지 `bonus.contracts` | `dsrImpactMatchesContractExample`. 정답: DSR은 시행일 전 신청 9건 · 연장 예정 C0006 · C0068, 고령자는 시행일 전 신청 60 ~ 64세 16건, 설명 확인은 C0092 대상 · C0004 · C0029 대상 아님 (`answer_key.md` 3 ~ 5절). 아직 Agent가 조회 · 저장하지 않아 채점 안 함 (#43) |
| 반영이 반만 되고 멈춤 | 큐 작업 단위가 제안 1건 = 규칙 1행. 실패한 건만 DEAD로 남고 사유가 기록됨 | 계약 10.4 | #34 부분 실패 테스트 |

## 3. 주요 트레이드오프

| 선택 | 대안 | 왜 이쪽인가 |
|---|---|---|
| 코드 패치 대신 **상품 규칙 제안 · 반영** | 코드 diff · 샌드박스 검증 · Draft PR | 검증 가능한 결과물이 더 구체적이고, 사람 확인 1번으로 흐름이 짧다. 샌드박스 실행은 문법 검사 이상을 보장하기 어려웠다 (SIMPLIFICATION 1 ~ 2절) |
| 역할 2개(담당자 · 개발자) 제거 | 역할별 승인 단계 | 확인이 1번이라 역할 구분이 할 일이 없다. 로그인(JWT)은 유지 |
| Agent는 값을 안 보내고 서버가 저장된 제안에서 꺼냄 | Agent가 값을 보냄 | LLM 출력이 쓰기 경로에 직접 닿지 않게 한다. 사용자가 본 값 = 반영되는 값 |
| 유효 여부를 날짜(`asOf`)로 | `effectiveTo == null` | 반영 뒤 기존 행은 종료일이 있어도 오늘은 유효하고, 새 행은 종료일이 없어도 아직 아니다 |
| 영구 실패는 재시도 없이 DEAD | 모두 3회 재시도 | "이미 바뀐 규칙"은 다시 해도 같다. 재시도는 시간만 쓰고 결과를 늦춘다 |
| Vector DB를 regulation-mcp 프로세스 안에(Chroma, 메모리) | pgvector · 별도 서비스 | 조각이 수십 개라 별도 서버가 필요 없고, 컨테이너가 늘지 않는다. 키가 없으면 BM25로 대체 |
| Draft PR · 티켓 기능 삭제 | 실제 GitHub · Jira 연동 | 평가 대상이 아니고 외부 계정이 필요하다. 새 흐름에서 쓰지 않아 코드에서 지웠다 (10.7) |

## 4. 알려진 한계

| 한계 | 영향 | 메모 |
|---|---|---|
| 업로드한 규정 원문을 실제로 분석하지 않고, 등록된 `credit-loan-ops` 원문을 분석한다. 업로드 파일의 sha256이 다르면 FAILED | 임의 규정을 올려 분석할 수 없다 | 업로드 원문을 MCP에 작업별로 등록하는 기능이 없다 |
| Agent 한 프로세스가 thread 단위로 잠근다 | Agent를 여러 개 띄우면 같은 작업이 겹칠 수 있다 | 분산 잠금 없음 (#34) |
| 체크포인터 DB 재연결은 코드로만 확인 | DB 재시작 실험을 안 했다 | |
| 진짜 오류로 DEAD가 된 반영은 다시 시도로 살아나지 않는다 | 작업이 FAILED로 남고, 새로 올려야 한다. Agent 그래프는 이미 끝났고 같은 멱등키는 DEAD 작업을 돌려주기 때문이다 | 시연용 실패 주입으로는 생기지 않는다 (#53). 다시 시도가 실패해도 처음 실패 사유는 `errorMessage`에 남는다 |
| `llm` 모드(MCP 없음)에서 승인하면 반영을 못 해 FAILED로 끝난다 | 개발 흐름에서 불편 | `live` 모드에서는 정상. A 판단 대기 |
| `/internal/**`을 네트워크로 격리하지 않는다 | backend 포트가 열려 있어 내부 토큰이 유일한 경계다 | 운영이라면 `/internal`을 별도 포트나 네트워크로 나눈다 |
| M3(고령자 · 설명 확인) 판단 품질 | 정답지 · 채점기는 있으나 Agent가 아직 통과 못 함 | SIMPLIFICATION 9절 Agent 과제 4개 |
| P006(소액대출) 판정이 정답지(`keep`)와 Agent(`needs_check`)가 다름 | DSR 판정 12개 중 1개 불일치 | 소액 기준(DSR 관리기준 제2조 4호)이 상품이 아니라 차주의 잔액 합계 기준이라 Agent 판단에 근거가 있다. 정답지 조율 중 (A · E, SIMPLIFICATION 11절) |
| 개정 조항과 무관한 규칙을 바꾸는 함정 오판 | 조항 3개를 한 번에 돌린 실행에서 P010 `ESTIMATED_INCOME_RATIO` 0.85를 0.35로 제안 | #35. 채점기 `must_not`으로 잡히는 유형. 근거 검사에서 "개정 조항의 대상 규칙인가" 확인 검토 (A) |
| 채점기 테스트가 CI에 없음 | 정답지를 고쳐도 자동 검사가 안 돎 | `pytest eval` 한 줄 추가 요청 (#42 리뷰) |

## 5. 검증 근거 모음

| 영역 | 자동 테스트 | 실제 실행 기록 |
|---|---|---|
| 백엔드 | 53개 (`./gradlew test`) | #25 · #28 · #29 · #35 · #39 PR 본문 |
| Agent | 122개 (`uv run pytest`) | #27 · #30 · #34 · #35 |
| MCP | regulation 78 · business 55 | #20 · #23 · #31 |
| 채점기 · 정답지 | 18개 (`uv run --with pyyaml --with pytest pytest eval -q`) | #42 · #44. Agent 결과 채점: `eval/score_proposals.py 결과.json [--expected …]` |
| 검색 | 질의 38개 (`eval/run_retrieval.py`) | #20. 규정 recall@3 키워드 82% · 의미 79% · 혼합 89% ([VECTOR_INDEX.md](./VECTOR_INDEX.md)) |
| CI | PR마다 위 전부 (`.github/workflows/ci.yml`) | #38 |
