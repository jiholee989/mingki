# Rule Ripple — Agent 서버 (담당: 이지호)

> 팀 모노레포(`minkyojung/mingki`)의 `agent/` 폴더. 명령은 이 폴더에서 실행한다.
> mock 도구는 레포 루트 `data/`(규정 v3/v4 · 상품 규칙)를 읽는다. 경로는 `RIPPLE_DATA_DIR`로 바꿀 수 있다.
> 코드 위치는 샘플 레포가 아직 없어 `app/tools/mock.py`의 `_CODE_INDEX`(docs/PROJECT.md 10절 정답지)로 대신한다.
> 정답지는 레포 루트 `eval/` — **Agent 코드에서 읽지 않는다** (테스트에서만 대조).
> Spring 연동 계약은 레포 루트 `docs/BACKEND_API.md` (`/run` · `/resume` · 콜백). 아직 반영 전.

Rule Ripple의 **Agent 서버**. 규정이 바뀌면 개발자가 무엇을·어디서·어떻게 고쳐야 하는지
찾아서 코드 diff · 설정 변경 · 테스트 · Draft PR · 작업 티켓까지 만들어 주는 LangGraph Agent를 구현한다.
도메인은 개인신용대출, 데이터는 전부 시연용 가상 데이터다.

## 팀 구성과 내 범위
- 나(Agent): LangGraph 그래프 전체, 프롬프트, MCP 클라이언트 연결, interrupt/재개, 진행 이벤트, Harness 일부.
- 다른 팀원: MCP 서버 3개(B), 도메인 데이터·샘플 레포·정답지(C), Spring Boot 백엔드(D), Vue + 인프라(E).
- Agent는 DB에 직접 접근하지 않는다. 업무 데이터는 business-mcp → Spring `/internal/**` 경유.
- MCP 서버는 별도 컨테이너. Agent는 HTTP `/mcp`로 호출만 한다. 서버가 준비되기 전까지는 mock 도구로 개발한다.

## 환경 (팀 공통 규칙)
- Python 3.12, 패키지 매니저 **uv** (`pyproject.toml` + `uv.lock` 커밋, `.venv/`·`.env`는 커밋 금지)
- 주요 라이브러리: langgraph, langchain, langchain-openai, pydantic, fastapi, uvicorn, fastmcp, python-dotenv, pytest
- API 키는 `.env`에만. LLM 호출은 개발 중 mock 우선.

## 그래프 (설계 확정본)
```
START → requirement_agent ──(실질 변경 0건)──▶ report
          │
     interrupt ① 요건 확정 (사람)
          │
   ┌──────┴──────┐            같은 superstep에서 병렬, 1번만 실행
 test_agent    locate_agent ◀──────── 시스템 테스트 실패(놓친 위치) 시
 (테스트 고정)     │
              design: plan → worker × 파일 묶음 (Send) → merge
                ▲                                   │
                └── 패치 실패 묶음만 ─── verify (merge에서만 트리거, 묶음별 round ≤ 2)
                                                    │
                                 interrupt ② 검토·승인 (사람이 수정하면 verify 재실행)
                                                    │ 승인 (검증 실패 항목은 기본 차단)
                                               publish → report → END
```

### 노드 책임
| 노드 | 종류 | 하는 일 | 쓸 수 있는 도구 | State 쓰기 |
|---|---|---|---|---|
| requirement_agent | LLM | 신·구 조항 비교 → 요건 구조화(변경 내용, 대상, 시행일, 경과조치). 실질 변경 0건이면 report | diff_versions, search_regulation | requirements |
| confirm_requirements | interrupt ① | 담당자가 요건 확정·수정 | — | requirements, approvals |
| test_agent | LLM | 요건에서 경계값·시행일 전후·시스템 테스트 생성. **고정, design이 수정 불가** | get_file, get_db_schema, get_product_rules | test_cases |
| locate_agent | LLM | 코드·설정·DB 스키마·상품 규칙에서 영향 위치 탐색. 대상 아닌 곳은 "대상 아님 + 이유" 기록 | search_code, get_file, find_usages, get_db_schema, get_product_rules, search_regulation | change_specs |
| plan | LLM 1회 | 위치별 유형(①값 ②로직 ③DB ④신규), 공유 계약(설정 키·함수 시그니처), 파일 묶음, 의존 순서 | get_file, find_usages, get_db_schema | plan, bundles |
| worker (Send) | LLM | 파일 묶음 하나의 패치 작성 (유형별 프롬프트). 같은 파일 위치는 한 worker에 묶음 | get_file, find_usages | code_patches (reducer) |
| merge | 코드 | 샌드박스 하나에 전부 적용, 충돌 묶음만 재작업 | — | code_patches |
| verify | 코드 | check_patch: 패치 적용·문법·테스트(state.test_cases). 패치 실패 → 해당 묶음 plan/worker로, 시스템 테스트 실패 → locate로. 최대 2회 | check_patch | code_patches(검증 결과, round) |
| review | interrupt ② | 명세서·패치 검토, PR·티켓 승인. 사람이 수정했으면 verify 재실행 | — | approvals |
| publish | 코드 | 승인된 항목만 create_draft_pr / create_work_ticket (approval_id + 멱등키 전달) | create_draft_pr, create_work_ticket | deliveries |
| report | 코드 | 변경 명세서·PR·티켓 링크 정리 → DONE | Resource reg://… | result |

### 구현 규칙 (중요)
- test_agent는 locate_agent와 같은 superstep에서 병렬로 **한 번만** 실행. verify를 `add_edge(["test_agent","merge"], "verify")` 같은 join으로 묶지 말 것(재시도 때 test_agent가 다시 안 돌아 verify가 트리거되지 않음). verify는 merge 하나에서만 트리거하고 테스트는 state에서 읽는다.
- 병렬은 유형 단위가 아니라 **파일(모듈) 묶음** 단위. ③ DB 변경이 있으면 먼저 순차 처리.
- interrupt는 fan-out(Send) 바깥에만 둔다.
- 쓰기 도구(create_draft_pr, create_work_ticket)는 **LLM 노드에 절대 바인딩하지 않는다**. 코드 노드(publish)에서만 호출.
- 노드별로 위 표의 도구만 바인딩(최소 권한). → `app/graph.py`의 `NODE_TOOLS`, `ToolBelt`로 강제.
- 틀리면 안 되는 것(diff, 누락 검사, 검증, 마감일 계산)은 코드, 의미 해석만 LLM.
- 구조화 출력은 `with_structured_output(Pydantic)`. OpenAI strict 스키마 제약 때문에 LLM 출력 스키마에 dict 필드·복잡한 기본값을 피한다.
- checkpointer: 개발 중 InMemorySaver, 통합 시 PostgresSaver. thread_id = taskId. (serde는 `app/graph.py`의 `SERDE` 사용)

## MVP 범위
- 유형 ①값 ②로직 + 경과조치(버전이 있는 설정 파일, DB 마이그레이션 없이). ④신규는 명세서·인터페이스·실패하는 테스트까지.
- 시나리오 2개: DSR 0.40 → 0.35, 고령자 65 → 60.
- 경과조치 예시: `config/policy.yaml`에 `SENIOR_AGE: [{value: 65, effective_from: 2020-01-01}, {value: 60, effective_from: 2026-12-01}]`, 코드는 `policy("SENIOR_AGE", as_of=application_date)`.
- 평가 함정(바꾸면 안 됨): `RETIREMENT_AGE = 65`, `LTV_LIMIT = 0.40`. 찾아야 할 어려운 위치: `age > 64`, `SENIOR_AGE_MONTHS = 780`, 하드코딩 `0.4`, 화면 문구 "DSR 40%".

## 진행 상황
- [x] 1~6: schemas, state, tools/mock, nodes 껍데기(LLM 없음), graph, 경로 테스트
- [ ] 7: 노드에 실제 LLM을 하나씩 붙이기 (`prompts/*.md`), MCP 서버가 나오면 mock → `tools/mcp_client.py` 교체 (같은 메서드 이름 유지)
- [ ] `app/api.py` FastAPI 실행·재개 엔드포인트

검증 명령: `uv run pytest -q`
