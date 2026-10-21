"""모델이 고른 조회(Lookup)를 하네스가 실행한다.

모델은 무엇을 왜 볼지 고르고, 실행 · 제한 · 기록은 코드가 한다.
- 조회 전용 도구만 (get_article · search_regulation, 노드 권한은 graph.NODE_TOOLS)
- 요건 하나에 최대 MAX_LOOKUPS개, 검색은 결과 MAX_SEARCH_HITS개까지
- 버전은 시행일 기준으로 고른 다른 규정 목록(related)의 것만. 그 밖의 규정 · 버전은 쓰지 않는다
- 실패는 작업을 멈추지 않고 자료 없음(data_gaps)으로 남긴다
"""

MAX_LOOKUPS = 5
MAX_SEARCH_HITS = 3


def run_lookups(tools, lookups, related, known_uris):
    """고른 조회를 실행해 새로 본 조항과 자료 없음 목록을 돌려준다. known_uris: 이미 문맥에 있는 조항."""
    versions = {r["regulation_id"]: r["version"] for r in related}
    seen, articles, gaps = set(known_uris), [], []
    for lookup in lookups[:MAX_LOOKUPS]:
        try:
            if lookup.tool == "get_article":
                if lookup.regulation_id not in versions or not lookup.article_id:
                    gaps.append(f"조회 건너뜀: get_article {lookup.regulation_id}/{lookup.article_id} — 볼 수 있는 규정 · 조항이 아님")
                    continue
                version = versions[lookup.regulation_id]
                found = [{**tools.get_article(lookup.regulation_id, version, lookup.article_id),
                          "regulation_id": lookup.regulation_id, "version": version}]
            else:
                if not lookup.query:
                    gaps.append("조회 건너뜀: search_regulation 질문 없음")
                    continue
                if lookup.regulation_id in versions:
                    hits = tools.search_regulation(lookup.query, lookup.regulation_id, versions[lookup.regulation_id])
                else:
                    hits = tools.search_regulation(lookup.query)
                found = [h for h in hits if versions.get(h.get("regulation_id")) == h.get("version")][:MAX_SEARCH_HITS]
        except Exception as exc:  # 조회 실패는 판단 자료가 줄어들 뿐 작업을 멈추지 않는다
            gaps.append(f"조회 실패: {lookup.tool} — {exc}"[:200])
            continue
        for article in found:
            if article["uri"] not in seen:
                seen.add(article["uri"])
                articles.append(article)
    return articles, gaps
