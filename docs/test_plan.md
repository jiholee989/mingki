# 테스트 계획 (Phase 2)

검증 결과서의 기능 테스트 · AI 출력 품질 점검 · 오류 수정 이력을 채우기 위한 기록이다. Phase 2는 `phase1-end` 이후 바뀐 것만 채점하므로, 기능 테스트는 **제안 수정 요청**(SIMPLIFICATION v2.3, BACKEND_API 10.3)과 그에 따라 바뀐 승인 규칙을 대상으로 한다. 검증 ID(TC-xx)는 설계서 STEP 04 인수조건과 같은 번호를 쓴다.

## 1. 계획

| 항목 | 내용 |
|---|---|
| 대상 | `POST /api/ai/tasks/{id}/revisions` · `GET /revisions/{id}` · `POST /review`(승인 규칙 변경) · Agent `/resume` REQUEST_CHANGES · 확인 화면의 수정 요청 입력 · 처리 중 → 확인 복귀 |
| 제외 | 로그인 · 업로드 · 반영 큐(Phase 1에서 검증, `FlowIntegrationTest` 기존 3건). 직접 편집 · 여러 제안 동시 재작성 · 반영 후 되돌리기(범위 밖) |
| 종류 | 기능 테스트 TC 8건 / 평가셋 3개 시나리오 × 상품 12개, 3회 / 실패 유도 TC 2건(TC-04 · TC-07) |
| 통과 기준 | TC 전부 통과. 평가셋은 baseline(`docs/experiments.md`)보다 설명 확인 신설 판정 평균이 오르고 DSR · 고령자가 떨어지지 않음 |
| 환경 | `gpt-5.4-mini`(`OPENAI_MODEL`), 프롬프트 `agent/prompts/`(PR 번호로 표기), 데이터 #19 · #40 · #49, `docker compose up --build` |
| 도구 | 백엔드 `./gradlew test`(단위 + Testcontainers 통합), Agent `uv run pytest -q`, 실제 스택은 `curl` · 화면 수동 확인 + 캡처 |
| 기록 위치 | `docs/experiments.md`(평가셋), `eval/baseline/` · `eval/results/`(결과 JSON), PR 본문(실제 스택 확인), 검증 결과서 |
| 담당 | 백엔드 TC 작성 · 실행 이찬혁, Agent 쪽 결과(TC-02 · 03) 이지호, 화면 TC-08 정민교, 평가셋 · 채점 이서홍 |

## 2. 기능 테스트 (인수조건 → TC)

사용자 스토리는 둘이다. **담당자는 제안 하나에 수정 요청을 보내 AI가 글을 다시 쓰게 할 수 있다.** **담당자는 검사에 실패한 제안을 빼고 나머지를 승인할 수 있다.**

| 검증 ID | 유형 | 인수조건 | 입력 | 기대 결과 | 자동 테스트 | 상태 |
|---|---|---|---|---|---|---|
| TC-01 | 정상 | 수정 요청을 보내면 그 제안만 다시 쓰여 새 버전으로 확인 화면에 돌아온다 | 확인 대기 작업, `{proposalId:"REQ-8:P001", baseVersion:1, comment:"기존 대출을 연장하는 고객은 종전 기준이라는 안내를 조치에 넣어줘"}` | 202 · 작업 DESIGNING → 확인 대기. P001 행 `version:2`, `revisionOutcome:revised`, `changedFields:["actions"]`, 조치에 안내 문구. 다른 상품은 1버전 그대로 | `FlowIntegrationTest.requestChangesRewritesOneProposalAndReturnsToReview` (Agent 콜백은 가짜) | 통과 |
| TC-02 | 예외 | 개정 원문과 충돌하는 요청은 반영하지 않고 사유를 보여 준다 | `comment:"35% 말고 30%로 바꿔줘"` | 확인 대기 복귀. `revisionOutcome:cannot_apply`, 본문은 이전 그대로, `revisionResponse`에 값은 개정 원문 기준이라는 사유. 승인 가능 | Agent `tests/test_observed_regressions.py` (Cannot) · 실제 스택 | Agent 어댑터 뒤 실제 스택 확인 |
| TC-03 | 예외 | 적용 대상을 바꿔 달라는 요청은 재분석이 필요하다고 안내한다 | `comment:"이 상품은 대상이 아니니까 빼줘"` | `revisionOutcome:needs_clarification`, 본문 그대로, `revisionResponse`에 확인할 질문. 승인 또는 제외 가능 | Agent `tests/test_observed_regressions.py` (Clarify) · 실제 스택 | Agent 어댑터 뒤 실제 스택 확인 |
| TC-04 | 오류 (실패 유도) | 무엇을 바꿀지 없는 요청은 받지 않는다 | `comment:"다시 써줘"` | Agent 400 → 작업은 확인 대기로 복귀, `errorMessage`에 "구체적으로 다시 적으세요", `GET /revisions/{id}` `state:rejected`. 제안은 1버전 그대로 승인 가능 | `FlowIntegrationTest.revisionTheAgentRefusesGoesBackToReview` (Agent 400 가짜), Agent `validate_feedback` 테스트 | 통과 |
| TC-05 | 오류 | 잘못된 요청은 접수하지 않는다 | `baseVersion:2`(현재 1) / `proposalId:"REQ-8:P999"` / 유지 판정 `REQ-8:P003` / `comment:" "` | 409 / 400 / 400 / 400. 작업 상태 변화 없음 | `FlowIntegrationTest.revisionRequestChecksProposalVersionAndComment` | 통과 |
| TC-06 | 예외 | 같은 요청을 다시 보내도 두 번 처리하지 않는다 | 같은 `revisionId` 두 번, 세 번째는 내용만 다르게 | 두 번째는 처음 접수와 같은 `revisionId`, Agent 호출 1회. 세 번째는 409. 다시 쓰는 동안 승인 · 추가 수정 요청은 409 | 같은 테스트 + TC-01 안의 409 확인 | 통과 |
| TC-07 | 정상 · 오류 (실패 유도) | 검사에 실패한 제안이 있어도 그것을 빼면 승인할 수 있고, 넣으면 막힌다 | P005 `verifyStatus:FAILED`인 확인 대기. ① 제외 없이 승인 ② P005 제외하고 승인 | ① 409, 응답에 막힌 키 ② 200 → PUBLISHING. 화면 `canApprove:true` | `FlowIntegrationTest.approvalChecksOnlyChosenProposals` | 통과 |
| TC-08 | 정상 (화면) | 수정 요청 뒤 "다시 쓰는 중" 화면이 보이고, 끝나면 확인 화면으로 돌아와 바뀐 부분이 표시된다 | 확인 화면에서 상품 하나에 수정 요청 입력 | 처리 중 화면 → 확인 화면, 해당 상품 카드에 새 제안 문장 · 조치, 반영 설명, 바뀐 칸 강조. 캡처 `TC-08_revision.png` | 수동 (화면) | 프론트 작업 뒤 |

- 자동 테스트는 백엔드 `./gradlew test` 71개(단위 64 · 통합 7)에 들어 있다 (#64). 통합 7개는 Docker 위 실제 Postgres · RabbitMQ로 돌고, Agent만 가짜다.
- 실제 LLM으로 TC-01 ~ 04를 한 바퀴 돌린 결과는 Agent 어댑터 PR이 병합된 뒤 `#64` 본문과 검증 결과서에 남긴다. 캡처 파일명은 `TC-01_revised.png`처럼 TC 번호로 시작한다.

## 3. 평가셋 · 채점

`docs/experiments.md`를 따른다. 평가셋은 정답지 3개(상품 12개 판정 × 3 시나리오), 채점은 `eval/score_proposals.py`, 저장된 결과 재채점은 `eval/summarize_results.py`. 개선 전 값은 10-21 baseline이고, 개선 후는 같은 모델 · 같은 실행 조건(바뀐 조항 전부 한 번에, 3회)으로 잰다.

교재가 요구하는 "답 불가" 문항은 정답지의 유지 · 추가 확인 판정이 맡는다. "실패 유도" 문항은 위 TC-04(모호한 요청) · TC-07(실패 제안 승인 시도)이고, 평가셋에 넣을 실패 유도 문항(규정 본문에 심은 지시문 등)은 데이터 담당과 정한다.

## 4. 실패 분석 · 재검증 순서

1. 고친 내용으로 실패했던 TC · 문항만 먼저 확인
2. 백엔드 `./gradlew test`, Agent `uv run pytest -q` 전체
3. 평가셋 3 시나리오 전체 3회 다시 실행 (다른 문항이 깨지지 않았는지)
4. `docs/experiments.md` 개선 기록 표에 한 줄, 검증 결과서 오류 수정 이력에 한 줄. 되돌린 시도도 적는다
