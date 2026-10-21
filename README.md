# Rule Ripple

규정이 바뀌면 상품마다 무엇을 바꿔야 하는지 AI가 근거와 함께 제안하고, 사람이 승인하면 상품 규칙에 반영한다.

제품 방향은 [docs/SIMPLIFICATION.md](docs/SIMPLIFICATION.md), API는 [docs/BACKEND_API.md](docs/BACKEND_API.md)를 참고한다.

## 주요 기능

- 개정 전후 규정을 비교해 변경 요건을 추출한다.
- 상품별로 변경 필요 · 유지 · 추가 확인을 판단하고, 근거 조항과 수정안을 제시한다.
- 담당자가 승인한 제안을 상품 규칙의 새 버전으로 반영한다.

```text
규정 업로드 → 변경 요건 추출 → 상품 영향 분석 → 제안·근거 검사 → 사람 승인 → 반영
```

## 실행

준비물: Docker Desktop, OpenAI API 키

```bash
cp .env.example .env              # OPENAI_API_KEY 입력, OPENAI_MODEL 확인
docker compose up -d --build      # 최초 빌드에 몇 분 소요
docker compose ps                # agent가 healthy인지 확인
scripts/smoke.sh --reset          # 업로드부터 반영까지 시연, 약 3분
```

`scripts/smoke.sh`는 로그인 → 규정 v3·v4 업로드 → 확인 대기 → 변경 제안 전체 반영 → 완료를 API로 실행한다. 제안과 새로 생성된 규칙 번호를 출력한다.

> `--reset`은 시작 전에 작업 기록과 업무 데이터를 초기 상태로 되돌린다.

## AI 정확도 측정

`uv`가 설치된 환경에서 실행한다.

```bash
uv run --with pyyaml python eval/run_agent.py --runs 3
```

회차마다 초기화 → 업로드 → 확인 대기까지 실행하고, 제안을 정답지와 비교한다. 상품 규칙은 반영하지 않는다. 회차별 점수·평균·상품별 정답 횟수를 출력하고, 결과는 `eval/results/`에 저장한다. 실행할 때마다 OpenAI API 사용료가 든다.

기본은 제8조(DSR 한도), 제15조(고령자 기준), 제15조의2(설명 확인 신설)를 함께 분석하고, 요건별 정답 파일 3개로 채점한다.

조항 하나만 평가하려면 `.env`의 `AGENT_ARTICLE_IDS`를 설정하고(예: `8`), Agent를 갱신한 뒤 정답 파일을 지정한다.

```bash
docker compose up -d agent

uv run --with pyyaml python eval/run_agent.py \
  --runs 3 \
  --expected eval/expected_proposals.yaml
```

최종 보고서 기준, DSR 시나리오는 `gpt-5.4-mini`로 3회 측정해 매회 상품 12개를 모두 맞혔다. 전체 조항 통합 평가와는 별도 결과다.

## 구성

| 서비스         | 하는 일                                  | 주소 (호스트)          |
| -------------- | ---------------------------------------- | ---------------------- |
| backend        | 로그인·작업 API, 반영 대기열 처리        | http://localhost:8080  |
| agent          | 요건 추출·영향 분석·제안·근거 검사·반영  | 내부 전용              |
| regulation-mcp | 규정 조항 비교·검색 (평가표의 rag-mcp)   | 내부 전용              |
| business-mcp   | 상품·규칙·계약 조회, 상품 규칙 반영      | 내부 전용              |
| postgres       | 업무 데이터, 작업 기록, Agent 체크포인트 | `localhost:5432`       |
| rabbitmq       | 반영 대기열, 재시도·DLQ                  | http://localhost:15672 |

RabbitMQ 관리 화면의 로컬 기본 계정은 `guest / guest`다.

주요 기술: LangGraph · FastAPI · Spring Boot · FastMCP · PostgreSQL · RabbitMQ · OpenAI · Docker Compose

## 자주 쓰는 명령

| 하려는 일              | 명령                                 |
| ---------------------- | ------------------------------------ |
| Agent 로그 보기        | `docker compose logs -f agent`       |
| 최근 AI 작업 기록 보기 | `python3 scripts/trace.py`           |
| 특정 AI 작업 기록 보기 | `python3 scripts/trace.py <작업 ID>` |
| 초기화 후 다시 시연    | `scripts/smoke.sh --reset`           |
| Agent 설정 변경 적용   | `docker compose up -d agent`         |
| 서비스 종료            | `docker compose down`                |
| DB 볼륨까지 삭제       | `docker compose down -v`             |

AI 작업 기록에서 도구 호출·상품별 판단·코드 검사 내역을 확인한다. 데이터 초기화는 `POST /api/demo/reset`으로도 실행한다.

## 문제 해결

Agent가 `Exited`이면 다음 명령으로 원인을 확인한다.

```bash
docker compose logs agent
```

`OPENAI_MODEL과 OPENAI_API_KEY가 필요합니다`가 나오면 `.env`를 수정하고 다시 실행한다.

```bash
docker compose up -d agent
```
