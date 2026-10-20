# Rule Ripple Agent

법령 개정을 분석해 상품별 변경 제안을 만들고, 검증 후 사람이 검토한다.

```text
요건 분석 → 상품 영향 판단 → 제안 작성 → 검증 → 사람 검토
                              ↑ 보완·수정 요청 ┘       ├─ CLI: 보고서
                                                     └─ 백엔드 승인: apply → 보고서
```

## 실행

`agent/.env`에 `OPENAI_API_KEY`와 `OPENAI_MODEL`을 설정하고 `agent/`에서 실행한다.
설정 예시는 `.env.example`을 참고한다. CLI는 이 `.env`를 기존 환경변수보다 우선한다.

```bash
uv sync
uv run python run.py --article 8                 # LLM + 로컬 자료, DSR 변경
uv run python run.py                             # 전체 변경 조항
uv run python run.py --mode live --article 8      # LLM + 규정·업무 MCP
uv run pytest -q
```

두 모드 모두 실제 LLM을 사용한다. 기본값은 `llm`이다.
로컬 자료는 `data/`의 규정·상품 규칙·상품 문서이며, `live`는 MCP가 반환한 자료만 사용한다.
MCP 주소는 `REGULATION_MCP_URL`, `BUSINESS_MCP_URL`로 설정한다.
규칙은 개정 시행일 전날에 유효한 행을 사용한다. `--verbose`로 요청 로그를 확인한다.

## 검토

| 명령 | 기능 |
|---|---|
| `v 3` / `k` | 제안 상세 / 유지 판단 근거 |
| `p 1,3` / `r 2` | 선택 승인 / 제외 |
| `c 2` / `e 2` | 구체적 의견으로 재작성 / 문구 직접 수정 |
| `a` / `f` | 남은 항목 승인 후 완료 / 검토 완료 |

승인 항목은 숨기고 번호는 유지한다. 수정한 항목만 새 버전으로 검토한다.
검증은 값·단위·시행일·출처·인용문을 검사하고, 실패한 항목은 한 번 보완한다.
법령의 적용 범위와 예외 판단은 사람이 근거와 함께 확인한다.
CLI 승인만으로 실제 DB를 변경하지 않는다.

## 백엔드 반영 연결

- `AgentRunner.resume_backend()`는 `APPROVE`와 승인·제외 목록을 내부 검토 결정으로 변환한다.
- `rule_proposals_payload()`는 제안을 상품 × 규칙 행으로 변환한다. 반영 키는 `상품ID:규칙키`다.
- `apply`는 검증·승인된 규칙에 `apply_rule_version(task_id, approval_id, proposal_key, idempotency_key)`을 호출한다. 변경 값은 보내지 않는다.
- 멱등키는 `{task_id}:apply:{proposal_key}`로 고정한다. 작업 ID와 결과는 보고서에 남긴다.
- 큐 접수 후 `QUEUED`·`RUNNING`·`RETRYING`을 조회하며, 전부 `DONE`일 때만 완료다. `DEAD`·시간 초과·조회 실패는 `FAILED`다.
- 완료 조회는 `build_graph(..., job_reader=spring.job)`로 연결한다. `spring.job`은 `GET /internal/jobs/{jobId}`를 호출하는 백엔드 어댑터 함수다. 기본 대기는 60초, 조회 간격은 1초다.

실제 반영에는 백엔드에 저장된 제안·유효한 승인 ID·MCP 쓰기 도구·작업 조회 연결이 모두 필요하다.
현재 확인한 main의 MCP에는 `apply_rule_version`이 아직 없다. Agent 노드는 구현됐으며, 해당 도구와 백엔드 반영 API 배포 후 실제 반영을 검증해야 한다.
HTTP 서버·콜백·Postgres 체크포인터는 별도 어댑터와 연결한다. 기본 체크포인터는 메모리다.

## 파일

| 위치 | 기능 |
|---|---|
| `run.py`, `app/cli.py` | CLI 실행·검토 화면 |
| `app/graph.py`, `app/state.py`, `app/runner.py` | 그래프·상태·시작·재개 |
| `app/nodes/` | 요건·영향·제안·검증·검토·반영·보고 |
| `app/llm.py`, `prompts/` | 구조화된 LLM 호출 |
| `app/validation.py` | 제안·입력 검증 |
| `app/tools/` | 로컬 자료·MCP 조회 및 반영 호출 |
| `app/backend.py`, `app/schemas.py` | 백엔드 변환·데이터 모델 |
