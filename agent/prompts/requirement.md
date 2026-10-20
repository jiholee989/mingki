구·신 조항 비교 결과를 읽고 실질 변경 요건을 반환한다.
숫자뿐 아니라 비교 연산(이하/미만), 의무, 예외, 적용 대상, 삭제도 비교한다.
부칙을 해당 본문 요건의 시행일·경과조치에 연결한다. 단순 문체 변경은 제외한다.
요건 ID는 REQ-{article_id} 형태로 고정하고, 여러 독립 요건이면 구분 접미사를 사용한다.
target은 의미가 드러나는 정책 키이다. article_ref는 원문 URI, 원문은 입력 그대로 사용한다.
부칙(supp-* 조항)은 독립 요건으로 만들지 않는다. 본문 요건의 effective_date/transitional에 연결한다.
하여야 한다→해야 한다, 받지 아니한다→받지 않는다 같은 문체 변경은 items에 넣지 않는다.
수치 변경은 old_value/new_value를 채우고, effective_date는 비교 결과의 effective_from을 기본으로 한다.
target은 코드 검색에 쓸 영문 정책 키다. 예: DSR_LIMIT, SENIOR_AGE. 자연어 설명은 summary에 적는다.
