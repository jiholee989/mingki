# Rule Ripple

규정이 바뀌면 상품마다 무엇을 바꿔야 하는지 AI가 제안하고, 사람이 확인하면 상품 규칙에 반영한다.
제품 방향은 [docs/SIMPLIFICATION.md](docs/SIMPLIFICATION.md), API는 [docs/BACKEND_API.md](docs/BACKEND_API.md).

## 실행

준비물: Docker Desktop, OpenAI API 키

```bash
cp .env.example .env              # OPENAI_API_KEY 를 넣는다
docker compose up -d --build      # 처음에는 빌드에 몇 분 걸린다
docker compose ps                 # agent 가 healthy 인지 확인
scripts/smoke.sh --reset          # 업로드부터 반영 완료까지 한 번 (약 3분)
```

`scripts/smoke.sh`는 로그인 → 규정 v3 · v4 업로드 → 확인 대기 → 변경 제안 전부 반영 → 완료를 API로 돌리고, 제안과 새로 생긴 규칙 번호를 출력한다. `--reset`은 시작 전에 작업 기록과 업무 데이터를 처음 상태로 되돌린다.

## AI 정확도 측정

```bash
uv run --with pyyaml python eval/run_agent.py --runs 3
```

회차마다 초기화 → 업로드 → 확인 대기까지 돌리고, 제안을 정답지(`eval/expected_proposals.yaml`)와 비교해 점수를 낸다. 반영은 하지 않는다. 회차별 점수 · 평균 · 상품별 정답 횟수를 출력하고, 결과는 `eval/results/`에 저장한다. 실행할 때마다 OpenAI 사용료가 든다.

기본은 바뀐 조항 전부(제8조 DSR 한도 · 제15조 고령자 기준 · 제15조의2 설명 확인 신설)를 한 번에 분석하고, 결과를 요건별로 나눠 정답 파일 3개로 채점한다. 조항 하나만 보려면 `.env`의 `AGENT_ARTICLE_IDS`를 정하고(예: `8`) 정답 파일을 지정한다: `--expected eval/expected_proposals.yaml`.

## 구성

| 서비스 | 하는 일 | 주소 (호스트) |
|---|---|---|
| backend | 로그인 · 작업 API, 반영 대기열 처리 | http://localhost:8080 |
| agent | 요건 추출 → 상품 영향 → 제안 → 근거 검사 → 확인 대기 → 반영 | 내부 전용 |
| regulation-mcp | 규정 조항 비교 · 검색 (평가표의 rag-mcp) | 내부 전용 |
| business-mcp | 상품 · 규칙 · 계약 조회, 상품 규칙 반영 | 내부 전용 |
| postgres | 업무 데이터, 작업 기록, Agent 체크포인트 | localhost:5432 |
| rabbitmq | 반영 대기열 (재시도 · DLQ) | 관리 화면 http://localhost:15672 (guest / guest) |

## 자주 쓰는 명령

| 하려는 일 | 명령 |
|---|---|
| Agent 로그 보기 | `docker compose logs -f agent` |
| AI 작업 기록 보기 (도구 호출 · 상품별 판단 · 코드 검사) | `python3 scripts/trace.py` (가장 최근 작업, 작업 ID를 주면 그 작업) |
| 다시 시연하기 전 초기화 | `scripts/smoke.sh --reset` 또는 `POST /api/demo/reset` |
| 조항 하나만 분석 | `.env`의 `AGENT_ARTICLE_IDS`를 정하고(예: `8`) `docker compose up -d agent` |
| 끄기 | `docker compose down` (DB까지 지우려면 `-v`) |

Agent가 `Exited`이면 `docker compose logs agent`를 본다. 키가 없으면 "OPENAI_MODEL과 OPENAI_API_KEY가 필요합니다"를 남기고 멈춘다.
