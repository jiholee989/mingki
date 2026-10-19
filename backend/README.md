# Rule Ripple — Backend (Spring Boot)

규정 변경 → 개발 변경 설계 Agent 의 백엔드. 레퍼런스 아키텍처에서 **Spring Boot** 상자에 해당한다.

- 공개 API (Vue → Spring): 작업 접수(202) · 조회 · SSE 진행 스트림 · 승인/반려
- 내부 API (`/internal/**`, docker network 전용): Agent 콜백(이벤트·산출물), business-mcp 가 쓰는 업무 조회·변경
- 인증: JWT, 역할 `DEVELOPER` / `LEAD` (PUBLISH 승인은 LEAD 만)
- 큐: RabbitMQ — 티켓 생성·Draft PR·패치 검증을 작업으로 넣고, 실패 시 3초 간격 재시도 3회 → DLQ
- DB: PostgreSQL + Flyway (`src/main/resources/db/migration`)

## 실행

```bash
# 루트에서 (postgres, rabbitmq, backend)
docker compose up --build backend

# 로컬 개발 (postgres/rabbitmq 만 docker 로)
docker compose up -d postgres rabbitmq
cd backend && ./gradlew bootRun        # 또는 gradle bootRun
```

- 헬스: `GET http://localhost:8080/actuator/health`
- RabbitMQ 콘솔: http://localhost:15672 (guest / guest)
- 시드 계정 (비밀번호 모두 `password`): `dev1`, `dev2` (DEVELOPER) / `lead1` (LEAD)

> Gradle wrapper(`gradlew`) 가 없으면 로컬 Gradle 로 `gradle wrapper --gradle-version 8.10` 한 번 실행 후 커밋.

## 공개 API

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{token, role, ...}` |
| GET | `/api/auth/me` | 토큰 확인 |
| POST | `/api/ai/tasks` | `{regulationId, oldVersion, newVersion, question?}` → **202** `{taskId}` |
| GET | `/api/ai/tasks?mine=true` | 내 작업 목록 (LEAD 는 `mine=false` 로 전체) |
| GET | `/api/ai/tasks/{id}` | 상태 + 산출물 + 승인 이력 + 전달 결과 |
| GET | `/api/ai/tasks/{id}/stream` | SSE. `Last-Event-ID` 또는 `?after=seq` 로 놓친 이벤트 재생 |
| POST | `/api/ai/tasks/{id}/approval` | `{step: REVIEW\|PUBLISH, decision: APPROVE\|REJECT, comment?, payload?}` |

모든 `/api/**` 는 `Authorization: Bearer <jwt>`.

### SSE 이벤트

`event:` 이름 = type, `data:` = `{seq, type, payload}`

| type | 의미 | payload 예 |
|---|---|---|
| `STEP` | 노드 진입 | `{step: "locate_agent"}` |
| `TOKEN` | 스트리밍 토큰 | `{text}` |
| `TOOL_START` / `TOOL_END` | 도구 호출 | `{tool, args}` / `{tool, ok, result}` |
| `APPROVAL_REQUIRED` | interrupt | `{step: "REVIEW" \| "PUBLISH", summary}` |
| `RESUMED` | 승인 후 재개 | `{step, by}` |
| `DONE` / `FAILED` | 종료 | `{report}` / `{reason}` |

### 작업 상태

`QUEUED → RUNNING → WAITING_REVIEW → (APPROVE) RUNNING → WAITING_PUBLISH → (APPROVE, LEAD) PUBLISHING → DONE`
반려 시 `REJECTED`, 오류 시 `FAILED`.

## 내부 API (`X-Internal-Token: <INTERNAL_TOKEN>`)

### Agent → Spring (콜백)

| Method | Path | 본문 |
|---|---|---|
| POST | `/internal/tasks/{id}/events` | `{type, payload}` → 저장 후 SSE 중계. `APPROVAL_REQUIRED`/`DONE`/`FAILED` 는 작업 상태도 바꿈 |
| POST | `/internal/tasks/{id}/artifacts` | `{kind: REQUIREMENTS\|CHANGE_SPEC\|CODE_PATCH\|DB_MIGRATION\|TEST_CASE\|VERIFY_RESULT\|REPORT, round, payload}` |
| POST | `/internal/tasks/{id}/deliveries` | `{kind: PR\|TICKET, externalRef, url}` |

### Spring → Agent (AgentClient 가 호출, Agent 쪽에서 구현)

| Method | Path | 본문 |
|---|---|---|
| POST | `{AGENT_BASE_URL}/run` | `{taskId, threadId, regulationId, oldVersion, newVersion, question, callbackUrl}` |
| POST | `{AGENT_BASE_URL}/resume` | `{taskId, threadId, step, decision, payload, callbackUrl}` |

### business-mcp → Spring (업무 조회·변경)

| Method | Path | 설명 |
|---|---|---|
| GET | `/internal/products` | 상품 목록 |
| GET | `/internal/products/{id}/rules` | 상품별 규칙값 (경과조치 이력 포함) |
| GET | `/internal/rules?key=SENIOR_AGE` | 규칙 키로 전 상품 조회 |
| GET | `/internal/contracts/impact?from=60&to=64` | 나이 구간에 걸리는 유효 계약 수 (경과조치 판단) |
| GET | `/internal/db/schema` | 업무 테이블 스키마 요약 (DB 변경 유형 설계용) |
| POST | `/internal/work-tickets` | **변경·승인 필요.** 큐에 넣고 202 `{jobId}` |
| POST | `/internal/products/{id}/rules` | **변경·승인 필요.** `{ruleKey, value, regulationId, regulationArticle, effectiveFrom}` — 종전 행 종료 + 새 행 |

### 큐 (Agent / code-mcp)

| Method | Path | 설명 |
|---|---|---|
| POST | `/internal/jobs` | `{taskId, type: CHECK_PATCH\|CREATE_DRAFT_PR\|CREATE_TICKET, payload}` → 202 |
| GET | `/internal/jobs/{id}` | 상태·시도 횟수·결과 |
| GET | `/internal/jobs?taskId=` | 작업별 큐 이력 |

워커는 `JOB_FAILURE_RATE` (기본 0.3) 확률로 일부러 실패한다. 시연에서 재시도 → DLQ 를 보여주기 위한 것이고, `0` 으로 두면 항상 성공.

## 환경변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | localhost / 5432 / ruleripple / ruleripple / ruleripple | PostgreSQL |
| `RABBIT_HOST` / `RABBIT_PORT` / `RABBIT_USER` / `RABBIT_PASSWORD` | localhost / 5672 / guest / guest | RabbitMQ |
| `AGENT_BASE_URL` | http://agent:8000 | FastAPI Agent |
| `CALLBACK_BASE_URL` | http://backend:8080 | Agent 가 콜백할 Spring 주소 |
| `INTERNAL_TOKEN` | rr-internal-dev-token | `/internal/**` 토큰 |
| `JWT_SECRET` | (시연용) | 32바이트 이상 |
| `JOB_FAILURE_RATE` | 0.3 | 워커 실패 주입 확률 |

## 패키지

```
com.ruleripple.backend
├─ auth/      User, JwtService, JwtAuthFilter, InternalTokenFilter, AuthController
├─ task/      AnalysisTask, TaskEvent, TaskArtifact, Approval, Delivery, TaskService, TaskController, AgentClient, SseBroadcaster
├─ internal/  Product, ProductRule, LoanContract, WorkTicket, InternalEventController, InternalBusinessController
├─ queue/     Job, JobPublisher, JobWorker, JobController
├─ config/    SecurityConfig, RabbitConfig, RestClientConfig, RuleRippleProperties
└─ common/    ApiExceptionHandler
```

## 평가표 대응

| 항목 | 어디서 |
|---|---|
| 아키텍처 — 202 + SSE, `/internal/**` 격리, 업무 규칙 한 곳 | TaskController, InternalTokenFilter, InternalBusinessController |
| Harness — 상태 저장·재개, 진행 이벤트 | analysis_tasks.status, task_events, approval → AgentClient.resume |
| MCP — business-mcp 조회·변경 도구의 데이터 원천 | InternalBusinessController |
| 인증 — 역할 2개, PUBLISH 는 LEAD | SecurityConfig, TaskService.approve |
| 가산점 — 큐, 실패 재시도, DLQ | RabbitConfig, JobPublisher, JobWorker |
