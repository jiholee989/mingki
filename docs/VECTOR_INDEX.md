# Vector DB 설계

`regulation-mcp`가 제공하는 규정 · 상품 문서 검색을 정리합니다. 평가표의 **rag-mcp 역할 = regulation-mcp**입니다.

구현: `mcp/regulation-mcp/regulation_mcp/search.py` (검색), `product_docs.py` (상품 문서 읽기)

## 1. 결정 사항

| 항목 | 선택 | 이유 |
|---|---|---|
| 검색 대상 | 규정(`data/regulations/*/v*.md`) + 상품 문서(`data/product-docs/P000.md`) | 숫자 규칙은 business-mcp로 DB에서 정확히 조회하고, 절차 · 문구처럼 숫자로 표현되지 않는 정보는 문서 검색으로 찾음 |
| 제공 위치 | regulation-mcp 하나 (컬렉션 2개) | Vector DB를 한 곳에 둠. business-mcp는 Spring DB 조회만 |
| 규정 검색 범위 | `regulation_id` 생략 시 **모든 규정의 최신 버전** | 같은 개념이 여러 규정에 흩어져 있음 (DSR 한도는 운영기준, 산정 방법 · 예외는 DSR 관리기준) |
| 검색 방식 | **의미 + 키워드(BM25) 혼합** | 의미 검색은 바꿔 쓴 질문에 강하고, 키워드는 숫자 · 조항 표현("100분의 5")에 강함 (5절) |
| 저장소 | Chroma, regulation-mcp 프로세스 안(메모리) | 조각이 120개 정도라 별도 서버가 필요 없음. 컨테이너에 마운트된 폴더만 보므로 정답 노출 범위도 그대로 |
| 임베딩 | OpenAI `text-embedding-3-small` (`EMBEDDING_MODEL`로 변경) | 팀이 이미 OpenAI 키를 씀. 한국어 품질 |
| 색인 시점 | 첫 검색 때, 그리고 원본 파일 내용이 바뀌었을 때만 | 무작위 변형 평가에서 폴더(`REGULATIONS_DIR`, `PRODUCT_DOCS_DIR`)만 바꿔 끼우면 다시 색인 |
| 대체 수단 | 키가 없거나 임베딩 호출 실패 시 BM25만 | 키 없는 로컬 개발 · 테스트, 네트워크 장애 |

## 2. 색인 대상과 조각

| 컬렉션 | 원본 | 조각 | 임베딩 · BM25 텍스트 | 필터 키 |
|---|---|---|---|---|
| `regulations` | `data/regulations/{id}/v{N}.md` 모든 버전 | 조항 1개 | `{규정 제목} > {제N조}({조항 제목})\n본문` | `{regulation_id}/{version}` |
| `product_docs` | `data/product-docs/P000.md` | `##` 섹션 1개 | `{상품명} > {섹션 제목}\n본문` | `product_id` |

**색인하지 않는 것**: 각 폴더의 `README.md`, `docs/`, `eval/`. 정답과 판단 근거가 들어 있습니다. 파일 이름 규칙(`{id}/v{N}.md`, `P000.md`)과 경로 검사로 구조적으로 막혀 있습니다.

## 3. 검색 방식

1. **키워드**: BM25. 한글은 단어 + 글자 bigram, 영문 · 숫자는 그대로(`dsr`, `40%`, `100`) 토큰으로 씁니다. 형태소 분석기 없이도 조사가 붙은 단어를 찾습니다.
2. **의미**: 질의를 임베딩해 Chroma에서 코사인 유사도로 후보를 찾습니다(필터 안에서 최대 `max(k × 4, 20)`개).
3. **혼합**: 두 점수를 후보 안에서 각각 0~1로 정규화하고 `0.5 × 의미 + 0.5 × 키워드`로 합칩니다(`HYBRID_ALPHA`). 비중은 기본값 0.5를 그대로 씁니다. 평가셋에 맞춰 조정하지 않았습니다.

## 4. 도구

```
search_regulation(query, regulation_id=None, version=None)
  -> [{ uri, regulation_id, version, article_id, title, text }]   관련도 순 최대 5개 (SEARCH_TOP_K)

search_product_docs(query, product_id=None)
  -> [{ uri, product_id, name, section, text, updated_at }]       관련도 순 최대 5개

get_product_doc(product_id)
  -> { uri, product_id, name, updated_at, sections: [{ uri, section, text }] }
```

- `search_regulation`의 위치 인자 호출 `(query, regulation_id, version)`은 이전과 같이 동작합니다. 결과에 `regulation_id`, `version`이 추가됐습니다.
- `version`만 주고 `regulation_id`를 생략하면 오류입니다.
- 링크: 규정 `reg://{regulation_id}/{version}/{article_id}`, 상품 문서 `doc://{product_id}#{섹션 번호}`.

## 5. 평가

`eval/retrieval.yaml` — 규정 질의 28개(기본 12 · 바꿔 쓴 질의 6 · 규정 사이에서 골라야 하는 질의 6 · 숫자 · 조항 표현 4), 상품 문서 질의 10개.

```
uv run --project mcp/regulation-mcp --with pyyaml python eval/run_retrieval.py
```

| 검색 | 규정 recall@3 | 바꿔 쓴 질의 | 숫자 · 조항 | 상품 문서 recall@3 | 함정 1위 |
|---|---|---|---|---|---|
| 키워드 (BM25) | 23/28 (82%) | 2/6 | 4/4 | 10/10 | 1 |
| 의미 (Vector) | 22/28 (79%) | 4/6 | 1/4 | 8/10 | 1 |
| **혼합 (채택)** | **25/28 (89%)** | **4/6** | **4/4** | **10/10** | **0** |

2026-10-20 측정. 혼합 비중 비교(같은 평가셋): 0.3 → 86%, **0.5 → 89%**, 0.7 → 82%. 기본값 0.5가 가장 좋아 그대로 씁니다.

참고: 처음에는 순위 합산(RRF)으로 섞었는데 79%로 키워드보다 낮았습니다. 바꿔 쓴 질의에서 BM25의 엉뚱한 순위가 의미 검색의 정답을 밀어냈기 때문입니다. 점수 정규화 가중합으로 바꿨습니다.

놓친 질의: Q14 "벌이에 비해 빚 갚는 돈이 얼마까지 허용되나", Q17 "돈 빌린 뒤 마음이 바뀌어 없던 일로 할 수 있는 기간", Q20 "마이너스통장 DSR 계산할 때 기준 금액".

`not_top1`은 같은 숫자 · 같은 단어 때문에 엉뚱한 조항이 1위로 나오는 경우(예: "녹취해야 하는 고령 고객 나이"에 운영기준 제15조 고령자 정의)를 잡습니다.
