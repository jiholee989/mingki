# Frontend 작업 계획

Rule Ripple 프론트엔드(Vue 3 + Spring 백엔드)의 작업 순서와 완료 기준.
설계 근거는 [PROJECT.md](./PROJECT.md).

## 원칙

- 백엔드가 바뀌어도 안 바뀌는 것(화면, 상태 흐름, 도메인 개념)과 바뀔 것(API 주소, 응답 필드, 인증, 진행 상황 전달 방식)을 분리한다.
- 바뀔 것은 `src/api/`와 `src/mocks/`에만 둔다. 화면과 store는 `src/domain/` 타입만 본다.
- 백엔드가 완성되기 전에는 MSW mock으로 모든 화면을 먼저 만든다.

## 진행 상황

| # | 작업 | 상태 | 완료 기준 |
|---|---|---|---|
| 1 | 프로젝트 세팅 | ✅ 완료 | `pnpm build` · `lint` · `typecheck` · `test` 통과 |
| 2 | 도메인 타입 | ✅ 완료 | PROJECT.md 2·5절 항목이 전부 `src/domain/` 타입으로 존재 |
| 3 | 가짜 데이터 | ⬜ | 시나리오 2개가 PROJECT.md 10절 정답지 항목을 전부 포함 |
| 4 | API 함수 + mock 서버 | ⬜ | 모든 화면이 쓸 함수가 MSW로 응답하고 상태 전환을 시뮬레이션 |
| 5 | 화면 7개 | ⬜ | 각 화면이 fixture로 렌더링 |
| 6 | 상태별 전환 | ⬜ | 작업 상태 12개 전부 화면 전환, 로딩·빈·오류 화면 포함 |
| 7 | 데모 리허설 | ⬜ | PROJECT.md 10절 5분 데모를 mock으로 끝까지 클릭, 빠진 버튼 없음 |
| 8 | 실서버 연결 | ⬜ | `VITE_USE_MOCK=false`로 같은 화면이 동작 |

## 2. 도메인 타입 (`src/domain/`)

| 타입 | 출처 |
|---|---|
| `AnalysisTask`, `TaskStatus` | PROJECT.md 5절, 아래 상태 목록 |
| `Requirement` (변경 내용, 대상, 시행일, 경과조치, 근거 조항) | 2절, 5절 requirement_agent |
| `ChangeSpec` (위치, 유형 ①~④, 판단 이유, 대상 아님 여부와 이유) | 3절, 5절 locate_agent |
| `CodePatch` (diff, 검증 결과, round) | 5절 design_agent · verify |
| `TestCase` | 5절 test_agent |
| `Approval` | 5절 interrupt ①② |
| `Delivery` (PR · 티켓 링크) | 5절 publish |
| `User`, `Role` (준법감시 · 상품기획 담당자 / 개발자) | 1절 사용자 |

### 작업 상태

| 상태 | 화면 표시 | 사람이 할 일 |
|---|---|---|
| `EXTRACTING` | 요건 추출 중 | 대기 |
| `WAITING_REQUIREMENT_APPROVAL` | 요건 확정 대기 | 담당자: 확정 또는 보류 |
| `LOCATING` | 영향 위치 탐색 · 테스트 생성 중 | 대기 |
| `DESIGNING` | 수정안 생성 중 | 대기 |
| `VERIFYING` | 검증 중 (n회차, 최대 2회) | 대기 |
| `WAITING_REVIEW` | 검토 · 승인 대기 | 개발자: 승인 · 거절 · 수정 |
| `PUBLISHING` | PR · 티켓 생성 중 | 대기 |
| `DONE` | 완료 | 결과 보기 |
| `NO_CHANGE` | 실질 변경 없음 | 종료 |
| `HELD` / `REJECTED` | 보류 · 거절로 종료 | 종료 |
| `FAILED` | 시스템 오류 | 다시 시도 |

## 3. 가짜 데이터 (`src/mocks/fixtures/`)

PROJECT.md 10절 시나리오를 그대로 쓴다.

| 시나리오 | 포함할 것 |
|---|---|
| 고령자 65 → 60 | 요건 1건, 바꿀 곳 4개(`age >= 65`, `age > 64`, `SENIOR_AGE_MONTHS = 780`, 경과조치 분기), 대상 아님 1개(`RETIREMENT_AGE = 65`), diff, 검증 1회차 실패 → 2회차 통과 |
| DSR 0.40 → 0.35 | 요건 1건, 바꿀 곳 3개(`DSR_LIMIT: 0.40`, 하드코딩 `0.4`, 문구 "DSR 40%"), 대상 아님 1개(`LTV_LIMIT = 0.40`), diff, 검증 통과 |

## 4. API 함수 + mock 서버 (`src/api/`, `src/mocks/handlers.ts`)

| 함수 | 용도 | 화면 |
|---|---|---|
| `createTask(files)` | 규정 v3 · v4 업로드, 작업 생성 | 업로드 |
| `listTasks()` / `getTask(id)` | 목록 · 상세 · 현재 상태 | 목록, 진행 상황 |
| `getRequirements(taskId)` | 요건 목록과 신 · 구 원문 | ① 요건 확정 |
| `approveRequirements(taskId, decisions)` | 확정 · 보류 | ① 요건 확정 |
| `getChangeSpecs(taskId)` | 영향 위치, 대상 아님 | 영향 위치 |
| `getPatches(taskId)` | diff, 테스트, 회차별 검증 결과 | ② 검토 · 승인 |
| `reviewPatches(taskId, decision)` | 승인 · 거절 · 수정 요청 | ② 검토 · 승인 |
| `getReport(taskId)` | 명세서, PR · 티켓 링크 | 리포트 |
| `getEvaluation(taskId)` | 키워드 검색 비교, 정답지 점수 | 데모 비교 |

mock은 `createTask` 뒤 시간 흐름으로 상태를 전환하고, interrupt 두 지점에서 멈춘다.

## 5. 화면 7개 (`src/pages/`)

구현 순서는 어려운 것부터.

| 순서 | 화면 | 경로 | 핵심 컴포넌트 | 추가 라이브러리 |
|---|---|---|---|---|
| 1 | ② 검토 · 승인 | `/tasks/:id/review` | Tabs, Badge, Alert, Dialog, Textarea | diff 뷰어 (`diff2html` 또는 `v-code-diff`) |
| 2 | ① 요건 확정 | `/tasks/:id/requirements` | Card, Checkbox, RadioGroup, Tabs | — |
| 3 | 영향 위치 | `/tasks/:id/locations` | Table, Badge, Collapsible, Tooltip | TanStack Table |
| 4 | 진행 상황 | `/tasks/:id` | Badge, Separator, Skeleton | — |
| 5 | 업로드 | `/tasks/new` | Card, Input(file), Progress | — |
| 6 | 리포트 | `/tasks/:id/report` | Card, Table, Button | `markdown-it` |
| 7 | 데모 비교 | `/tasks/:id/evaluation` | Table, Badge, Progress | — |

목록 화면 `/tasks`는 4번과 함께 만든다.

## 6. 상태별 전환

- 라우터 가드: 작업 상태에 따라 허용되는 화면만 진입. 그 외는 진행 상황으로 리다이렉트.
- 역할 가드: ① 요건 확정은 담당자, ② 검토 · 승인은 개발자만.
- 모든 화면에 로딩(Skeleton) · 빈 화면 · 오류 화면.
- 검증 실패 패치는 승인 버튼 비활성. 서버도 막지만 화면에서도 막는다.

## 8. 실서버 연결

백엔드 명세가 확정되면 바꾸는 곳은 세 파일만이어야 한다.

| 파일 | 바뀌는 것 |
|---|---|
| `src/api/client.ts` | 인증 헤더, 에러 형식 |
| `src/api/mappers.ts` | 서버 JSON → 도메인 타입 |
| `src/composables/useTaskPolling.ts` | 폴링 ↔ SSE |

## 백엔드와 확인할 것

| 질문 | 영향 | 프론트 제안 |
|---|---|---|
| 프론트는 Spring만 호출하나? (AI 엔진 직접 호출 없음) | 서버 주소, 인증 | Spring 하나로 통일 |
| 인증: 세션 쿠키 vs JWT | `client.ts` | 데모는 역할 전환 버튼 |
| 진행 상황: 폴링 vs SSE | `useTaskPolling` | MVP는 폴링 |
| ① 요건 확정에서 내용 수정이 되나, 확정 · 보류만인가? | 편집 UI 유무 | 확정 · 보류만 |
| ② "수정함"은 화면에서 코드를 직접 고치는 것인가? | 코드 편집기 유무 | MVP는 코멘트로 수정 요청 |
| 검증 실패 패치의 publish 차단에 예외가 있나? | 예외 승인 UI | 예외 없음 |
| 규정 파일 형식 | 업로드 화면 | 텍스트 · Markdown |
| 작업 티켓은 어디에 생기나? | 링크 대상 | — |
| 명세서 출력 형식 | 다운로드 기능 | 화면 + Markdown |
| history 모드 라우팅 → Spring SPA fallback 필요 | 배포 | 모든 경로 → `index.html` |
