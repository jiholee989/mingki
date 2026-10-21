변경 요건 하나를 상품들에 적용하기 전에, 판단에 더 필요한 다른 규정 조항을 고른다. 고른 조회는 시스템이 실행해 영향 판단 자료에 더한다.
regulation_context에는 바뀐 규정의 조항만 있다. related_regulations의 규정은 조항 목차(articles: 조항 번호 · 제목)만 있고, 본문은 조회하지 않으면 볼 수 없다.

고르는 기준:
- 적용 대상 · 적용 제외 · 적용 예외, 다른 기준과의 관계, 같은 말의 다른 정의를 확인해야 할 때 고른다.
- 상품 설명이나 규칙의 basisArticles가 가리키는 다른 규정 조항을 확인해야 할 때 고른다.
- 목차 제목으로 조항을 알 수 있으면 get_article(regulation_id, article_id). 번호는 목차에 있는 것만 쓴다. 제목만으로 어느 조항인지 모르면 search_regulation(query, 필요하면 regulation_id).
- 이미 regulation_context에 있는 조항은 고르지 않는다. 더 볼 것이 없으면 빈 목록. 최대 5개.
- reason에는 이 조회로 무엇을 확인하려는지 한 문장으로 쓴다.
