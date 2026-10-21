# Rule Ripple · MCP 서버

Agent가 쓰는 도구 서버 2개. 흐름은 [docs/SIMPLIFICATION.md](../docs/SIMPLIFICATION.md), 백엔드 계약은 [docs/BACKEND_API.md](../docs/BACKEND_API.md) 9 · 10절, 요청 · 응답 예시는 [docs/contracts/](../docs/contracts/).

| 서버 | 주소 (compose 안) | 볼 수 있는 것 |
|---|---|---|
| regulation-mcp (평가표의 rag-mcp) | `http://regulation-mcp:8001/mcp` | `data/regulations/{id}/v{N}.md` · `data/product-docs/P000.md` 만 |
| business-mcp | `http://business-mcp:8003/mcp` | Spring `/internal/**` 응답 만 |

`eval/` · `docs/` 는 어느 서버도 읽지 못한다. 막는 곳은 두 겹이다.

1. 코드: 모든 경로 입력을 형식으로 먼저 검사한다 (규정은 `{id}/v{N}.md`, 상품 문서는 `P000`, 백엔드 경로에 들어가는 ID는 상품 ID · UUID 형식만).
2. compose: 각 서버에 필요한 폴더만 읽기 전용으로 마운트한다. 컨테이너 안에는 `eval/` · `docs/` 가 아예 없다.

code-mcp(코드 검색 · 패치 검증 · Draft PR)와 `create_work_ticket`은 단순화 계획(v2)에서 빠져 지웠다.

## 실행 · 테스트

```bash
# 전체 (루트에서)
docker compose up --build regulation-mcp business-mcp

# 호스트에서 Agent를 돌릴 때 (포트 8001 · 8003 열기)
docker compose -f docker-compose.yml -f docker-compose.agent-local.yml up -d --build regulation-mcp business-mcp

# 서버 하나 로컬 실행 (각 폴더에서)
cd mcp/business-mcp
uv sync
uv run python -m business_mcp.server        # HTTP :8003/mcp   (--stdio 도 가능)
uv run pytest -q
```

연결 예시 (Agent의 fastmcp Client):

```python
from fastmcp import Client
async with Client("http://business-mcp:8003/mcp") as c:
    rules = (await c.call_tool("get_product_rules", {"rule_key": "DSR_LIMIT", "as_of": "2026-11-30"})).data
```

도구가 실패하면 `ToolError`(MCP `isError`)로 이유 한 줄을 돌려준다. 예: `백엔드 409 CONFLICT: 이미 바뀐 규칙`

## 도구

### regulation-mcp (읽기, 평가표의 rag-mcp 역할)

| 도구 | 입력 | 출력 |
|---|---|---|
| `list_regulations` | (없음) | `[{regulation_id, title, latest_version, applies_to, versions: [{version, effective_from, previous_version, uri}]}]` |
| `diff_versions` | `regulation_id, old_version=None, new_version=None` | `{regulation_id, old_version, new_version, effective_from, changes: [{article_id, title, change, old_text, new_text, old_uri, new_uri}]}` |
| `search_regulation` | `query, regulation_id=None, version=None` | `[{uri, regulation_id, version, article_id, title, text}]` 관련도 순 최대 5개 |
| `search_product_docs` | `query, product_id=None` | `[{uri, product_id, name, section, text, updated_at}]` 관련도 순 최대 5개 |
| `get_product_doc` | `product_id` | `{uri, product_id, name, updated_at, sections: [{uri, section, text}]}` |
| `get_article` | `regulation_id, version, article_id` | `{uri, article_id, title, text}` |
| `list_articles` | `regulation_id, version=None` | `[{uri, article_id, title}]` |
| Resource | `reg://{regulation_id}/{version}/{article_id}` | 조항 원문 (`reg://{id}/{version}` 은 규정 제목) |
| Resource | `doc://{product_id}` | 상품설명서 · 업무 절차 문서 원문 |

- `list_regulations`: 어떤 규정 · 버전이 있는지 모를 때 먼저 부른다. `applies_to`는 frontmatter의 적용 상품 목록이고, 없으면 `null`(정보 없음).
- `diff_versions`: 버전을 생략하면 최신 버전과 그 `previous_version`을 비교한다. 첫 버전이면 오류.
- 규정 파일을 추가 · 수정하면 `uv run pytest tests/test_data_format.py -q` 로 형식을 확인한다 (형식이 틀린 조항은 오류 없이 빠지기 때문).

- `change`: `added` · `removed` · `modified`. 표현만 바뀐 조항도 나온다 (실질 여부는 Agent가 판단).
- 조항 ID: `15`, `15-2`(제15조의2), `supp-2`(부칙 제2조). Agent `app/data.py` 와 같은 규칙.
- 검색 두 도구는 의미 검색(OpenAI `text-embedding-3-small` + 프로세스 안 Chroma)과 키워드 검색(BM25)을 0~1로 정규화해 반반 섞는다. `OPENAI_API_KEY` 가 없거나 임베딩 호출이 실패하면 BM25만 쓴다. 색인 규칙과 평가 결과는 `docs/VECTOR_INDEX.md`.
- `search_regulation` 은 `regulation_id` 를 생략하면 모든 규정의 최신 버전에서 찾는다. 규정마다 같은 말(예: 고령자)을 다르게 정의할 수 있다. 위치 인자 `(query, regulation_id, version)` 호출은 그대로 동작한다.
- 상품 문서는 `data/product-docs/P000.md` 만 읽는다 (`PRODUCT_DOCS_DIR`).

### business-mcp

응답은 백엔드 그대로 (camelCase). 업무 규칙은 Spring 한 곳에만 두고 MCP에서 가공하지 않는다.

| 도구 | 성격 | Spring | 출력 |
|---|---|---|---|
| `get_products` | 읽기 | `GET /internal/products` (+`status` 필터) | `[{productId, name, description, …}]` |
| `get_product_rules` | 읽기 | `GET /internal/product-rules?key=` · `GET /internal/products/{id}/rules` (+`asOf`) | `[{ruleId, productId, ruleKey, value, unit, effectiveFrom, effectiveTo}]` |
| `list_rule_keys` | 읽기 | `GET /internal/product-rules/keys?asOf=` (기본 오늘) | `[{ruleKey, units, productIds, activeRows, closedRows, upcomingRows}]` |
| `get_db_schema` | 읽기 | `GET /internal/db/schema` | `[{table, columns: [{name, type, nullable}]}]` |
| `get_contract_impact` | 읽기 | `GET /internal/contracts/impact` | `{ageFrom, ageTo, total, byProduct, grandfathered?, contracts}` |
| `apply_rule_version` | 쓰기 · 승인 | `POST /internal/product-rules/versions` | `{jobId, status, duplicate}` |
| `get_job` | 읽기 | `GET /internal/jobs/{jobId}` | `{jobId, type, status, attempts, result, lastError}` |

- **유효 여부는 날짜로 판단한다** (`effectiveTo == null` 아님, BACKEND_API 10.5). `as_of`에 유효 = `effectiveFrom ≤ as_of ≤ effectiveTo`(없으면 무한). 반영 직후 기존 행은 종료일이 미래라 아직 유효하고, 새 행은 시작일이 미래라 `upcoming`이다.
- `status` · `asOf`는 백엔드로 넘기고(#25), `get_product_rules`는 같은 조건으로 한 번 더 거른다. 규칙 키 집계는 Spring 한 곳에서 한다.
- **반영 (10.4)**: `apply_rule_version(task_id, approval_id, proposal_key)`는 값을 보내지 않는다. 백엔드가 저장된 제안에서 값을 꺼내므로 사용자가 확인한 값만 들어간다. 멱등키를 생략하면 `{task_id}:apply:{proposal_key}`.
  거절 이유(403 승인 · 409 "이미 바뀐 규칙")는 `ToolError`로 그대로 전달한다. 결과는 `get_job`을 `DONE` · `DEAD`까지 반복 호출해 확인한다 (`DEAD`면 `lastError`).
- `get_job`은 작업 응답에서 `payload` · 멱등키 같은 내부 값을 빼고 상태 · 결과 · 오류만 돌려준다.
- `task_id` · `job_id`는 UUID 형식만 받는다 (URL 경로 우회 방지). 테스트는 `docs/contracts/*.json` 예시를 그대로 읽는다.
- 같은 개념이라도 상품마다 키 이름 · 단위가 다르다 (예: `DSR_LIMIT` 이 `ratio` 0.40 과 `percent` 40 으로 섞여 있음, `MAX_DSR_RATIO`). `list_rule_keys` 의 `units` 로 확인한다.

## 남은 일

- [ ] `get_contract_impact`에 DSR 구간(`dsrFrom` · `dsrTo`) · `maturesAfterEffective` (백엔드 #25에는 있음, M3 경과조치 계약 C0006)
