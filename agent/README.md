# Rule Ripple Agent

규정 변경 근거와 시스템 영향 위치를 먼저 보여주고, 사람이 대상을 확정한 뒤 수정안을 만든다.

```text
requirement_agent → locate_agent → confirm_requirements (첫 승인)
→ test_agent → design_agent → verify → review (최종 검토)
                   ↑ 실패 로그로 재작성 ─┘        ↓
                                   publish → report
```

- `test_agent`의 테스트는 재작업 중 고정한다.
- 수정안은 파일별로 순차 작성한다. 병렬 worker·DB 단계 스케줄러는 사용하지 않는다.
- 첫 검토에서 요건별 확정·보류, 영향 위치 제외가 가능하다.
- LLM은 실질 변경 여부와 변경 전후 동작 차이를 함께 작성한다. 문체만 바뀐 후보는 제외한다.
- 코드 검색 없이 탐색을 끝내지 않는다. 본문 미조회·변경 전후 설명 부족 후보는 `확인 필요`로 표시한다.
- `확인 필요` 후보는 수정안 생성 대상에서 제외한다. 의미상 관련성은 첫 승인에서 사람이 함께 확인한다.
- 최종 검토는 승인·거절·코멘트 수정 요청이다. 최종 제외는 수정 요청으로 보내 재검증해야 한다.
- DB/상품 규칙/신규 모듈은 자동 패치 대신 작업 티켓 명세로 처리한다.

## 실행

`agent/`에서 실행한다. Python 3.12, uv를 사용한다.

```bash
uv sync
uv run python run.py --auto
uv run python run.py
uv run pytest -q
```

기본 `demo` 모드는 로컬 시연 규정·상품 JSON과 미리 작성한 코드 위치 목록을 사용한다.
`DemoReasoner`의 판단은 고정 규칙이다. 실제 패치/테스트는 실행하지 않고 `unverified`로 표시한다.
외부 PR·티켓을 생성하지 않는다. 최종 상태 `DEMO`는 실제 검증 성공을 뜻하지 않는다.

## MCP 없이 실제 LLM 확인

`agent/.env`에 `OPENAI_API_KEY`, `OPENAI_MODEL`을 설정한다. MCP URL은 이 모드에서 사용하지 않는다.
CLI는 현재 작업 디렉터리와 관계없이 `run.py` 옆의 `.env`를 읽고, 같은 이름의 기존 환경변수보다 우선한다.

```bash
uv run python run.py --mode llm
# 사람 확인도 자동으로 진행하며 끝까지 확인
uv run python run.py --mode llm --auto
```

| 모드 | 판단 | 자료 조회 | 실제 검증·발행 |
|---|---|---|---|
| `demo` | 고정 시연 규칙 | 로컬 샘플 | 수행 안 함 |
| `llm` | 실제 LLM API | 로컬 샘플 | 수행 안 함 |
| `live` | 실제 LLM API | MCP 서버 | 검증 가능, 발행은 별도 승인 |

`llm` 모드에서도 모델이 조회 도구와 인자를 선택한다. 도구 실행만 로컬 `MockTools`가 담당한다.
규정·상품은 샘플 파일, 코드는 미리 작성한 위치와 snippet 목록이다. 실제 저장소 분석은 아니다.
테스트·수정안은 모델이 생성하지만 실행하지 않는다. 결과는 `LLM_PREVIEW`, 코드 패치는 `unverified`로 표시한다.
`[LLM] 요청/조회` 로그로 모델 호출과 도구 선택을 확인할 수 있다. 실제 API 사용량이 발생한다.

## 실제 LLM + MCP

`.env.example`을 참고해 `agent/.env`를 준비하고 MCP 서버 3개를 별도로 실행한다.
모델은 환경 변수로 지정하며, 설정이 없으면 demo로 자동 대체하지 않고 오류로 알린다.

```bash
uv run python run.py --mode live
```

호스트에서 Agent를 실행한다면 루트에서 먼저 다음 명령으로 MCP와 의존 서비스를 올린다.
로컬 포트는 127.0.0.1에만 공개하고, 기본 compose의 내부 통신 설정은 유지한다.

```bash
# 저장소 루트
docker compose -f docker-compose.yml -f docker-compose.agent-local.yml up -d --build regulation-mcp code-mcp business-mcp
# 이후 agent/에서 실행
uv run python run.py --mode live
```

`agent/.env`의 MCP URL은 `.env.example`의 localhost:8001/8002/8003을 사용한다.
Spring은 business-mcp의 상품 조회 때문에 필요하다. 이 명령으로 Agent의 HTTP API까지 연결되지는 않는다.

- `LlmReasoner`: 프롬프트와 구조화 출력으로 요건/테스트/수정안을 만든다.
- 영향 탐색에서는 모델이 MCP의 도구 설명을 읽고 읽기 도구와 인자를 선택한다.
- 같은 원문이 조회 파일에서 유일하게 확인되면 모델의 줄 번호를 보정한다.
- 위치·원문이 확인되지 않거나 중복되면 `확인 필요`로 표시하고 수정 대상에서 제외한다.
- `[LLM]`은 모델 판단·요청, `[MCP]`는 실제 MCP 서버의 도구·Resource 호출 로그다.
  `diff_versions`와 `check_patch`처럼 그래프가 직접 호출하는 도구도 MCP 로그에 표시한다.
- 조회 오류는 모델에 돌려준다. 탐색은 최대 8턴, 같은 도구 3회(파일 본문 8개), 모델 요청 timeout 120초다.
- 문맥 한도는 문자 수 기준이다. 큰 도구 결과는 범위를 줄여 재조회하도록 한다.
- 실제 모델 호출의 품질/호환성과 MCP 서버 동작은 이 저장소의 오프라인 테스트로 보장하지 않는다.
- 모델 출력은 JSON Schema로 형식을 제한하고, 영향 위치는 요건별로 정리한다.
- 코드 후보 본문을 보충 조회하고, 실제 코드를 읽지 않거나 함수 인자가 맞지 않는 생성 테스트는 명세로 보류한다.
- 생성 테스트는 로컬 Agent 프로세스에서 실행하지 않는다. code-mcp의 격리 환경에서 실행해야 한다.

기본 live 실행도 발행 없이 검토까지만 진행한다. 실제 발행을 요청하려면 Spring의 유효한 승인 ID가 필요하다.

```bash
uv run python run.py --mode live --publish --approval-id 42
```

숫자 42는 예시다. Agent가 승인 ID를 발급하지 않으며, 최종 권한은 백엔드가 다시 검사한다.

## 파일 역할

| 파일 | 역할 |
|---|---|
| `run.py` | CLI, demo/llm/live 선택 |
| `app/graph.py`, `app/state.py` | 실행 순서와 작업 상태 |
| `app/nodes/` | 단계별 처리, 승인·검증·발행 통제 |
| `app/reasoning.py`, `app/llm.py` | 모델 인터페이스와 실제 LLM 연결 |
| `app/demo.py`, `app/tools/mock.py` | 시연 전용 판단·도구 |
| `app/tools/base.py`, `app/tools/mcp_client.py` | 도구 권한 제한과 MCP 연결 |
| `app/backend.py`, `app/runner.py` | Spring 계약 변환과 공통 실행기 |
| `prompts/` | 모델 지시문 |

## MCP 담당자와 맞출 계약

기존 도구 이름과 업무 데이터 camelCase 응답을 유지했다. 아래 추가 조건을 확인해야 한다.

1. `get_file(path)`는 파일 본문 문자열 또는 `{content: "..."}`를 반환한다.
2. `search_code`/`find_usages`는 `file`, `line`, `snippet`이 있는 후보를 반환한다.
3. 코드 patch는 현재 MCP 계약인 `@@ file:line @@` 블록과 `-기존/+변경` 행을 사용한다.
   일반 Git unified diff와 다르다. 적용/검증/PR 생성 도구가 같은 형식을 사용해야 한다.
4. `check_patch`는 `results[{bundle_id, ok, errors}]`, `system{ok, errors}`,
   `tests{executed: 실제 실행한 테스트 수}`를 반환해야 한다.
   `generated`는 실행 증거가 아니다. 생성 테스트는 수정 전 실패·수정 후 통과도 확인한다. 실행 수가 없거나 0이면 발행을 차단한다.
5. 쓰기 도구는 기존 `task_id`, `approval_id`, `idempotency_key`, `spec_keys`를 받고
   `{jobId, status, duplicate?, branch?, url?}`를 반환한다.
6. MCP 서버 소스는 루트 `mcp/`에 있다. 코드 조회 대상은 `mcp/sample_repo`이며, 업무 조회는 Spring을 사용한다.

## 백엔드 연결 지점 (HTTP 서버는 아직 연결하지 않음)

`AgentRunner`를 FastAPI의 백그라운드 작업에서 호출하면 같은 그래프를 재사용할 수 있다.

```python
runner = AgentRunner(build_graph(tools, reasoner, checkpointer=checkpointer), on_update=save_update)
runner.start_backend(RunRequest.model_validate(body), regulation_id=registered_regulation_id)
runner.resume_backend(ResumeRequest.model_validate(body))
```

- `/run`의 문서 정보에는 본문이 없다. 향후 API가 callbackBaseUrl의 `/documents`에서 원문을 읽고
  규정 MCP에 작업별로 등록/연결한 뒤, 실제 `regulation_id`를 Runner에 전달해야 한다.
  업로드된 문서를 무시하고 고정 v3/v4를 읽으면 안 된다.
- `backend.py`의 payload 함수가 요건/위치/테스트/패치를 Spring 형식으로 변환한다.
- `on_update(node, delta)`는 노드 완료마다 결과 저장·이벤트 중계에 사용할 콜백이다.
  `STEP` → 산출물 저장 → `APPROVAL_REQUIRED` 순서로 HTTP 어댑터를 작성한다.
  승인 대기는 Runner 반환의 `__interrupt__`에서 확인한다.
- 요건 저장은 EXTRACTING일 때, 영향 위치는 첫 승인 전에 저장한다.
  첫 승인 화면도 `/change-specs`를 조회해야 한다. 프론트/백엔드 소스는 수정하지 않았다.
- `APPROVE + excludedSpecKeys`는 현재 백엔드가 허용하지만 이 Agent는 거부한다.
  제외하려면 REQUEST_CHANGES로 보내 재검증하고 **새 승인**을 받아야 한다.
- ticket_only 명세는 코드 패치 PASSED 행으로 저장하지 않는다.
  티켓만 있는 작업의 승인 허용은 백엔드 담당자와 별도로 맞춰야 한다.
- `QUEUED`는 접수다. 실제 완료/URL은 향후 HTTP 어댑터에서 `/internal/jobs/{jobId}`를 조회해 갱신한다.
- 메모리 체크포인터는 개발용이다. 서버 배포 시 DB 체크포인터를 주입하고,
  task/thread별 분산 잠금·작업 재전달·이벤트 멱등성을 구현한다.
- `NO_CHANGE/HELD/REJECTED/DONE`은 기존 종료 상태로 매핑할 수 있다.
  `DEMO/LLM_PREVIEW/READY/QUEUED/BLOCKED`를 무조건 `DONE` 이벤트로 보내면 안 된다.

## 테스트 범위

외부 LLM/MCP/Spring 호출 없이 승인 순서·발행 차단·계약 변환·도구 선택 루프를 검사한다.
임시 테스트 폴더의 간단한 DSR 코드를 실제로 패치하고 pytest를 실행하는 검증도 포함한다.
이때 모델과 MCP 전송은 테스트 대역이며, 운영 시스템을 수정하지 않는다.
