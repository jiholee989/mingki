구·신 조항을 비교하고 본문 변경 후보마다 is_material과 behavior_change를 작성한다.
실질 변경인지 먼저 판정한 뒤 요건을 작성한다. 문체 변경도 후보에 남기되 is_material=false로 한다.

판정 기준:
- 값·비교 연산·계산식·의무·예외·적용 대상·시행일·경과조치가 바뀌어 시스템 동작이 달라지면 is_material=true.
- 표현만 다르고 조건·의무·대상이 같으면 is_material=false, behavior_change="".
- 숫자가 그대로라도 이하→미만, 선택→필수, 의무 신설·삭제는 실질 변경이다.
- behavior_change는 "기존에는 … / 개정 후에는 …"로 실제 동작 차이를 구체적으로 설명한다.
- summary에 '문체 변경 사항 반영' 같은 가상의 개발 작업을 만들지 않는다.

요건 ID는 REQ-{article_id}로 고정하고 독립 요건이면 구분 접미사를 사용한다.
target은 검색용 영문 정책 키, summary는 자연어 설명이다. 원문은 입력 그대로 사용한다.
수치 변경은 old_value/new_value를 채운다.
부칙(supp-*)은 독립 후보로 만들지 않고 본문 요건의 effective_date/transitional에 연결한다.
effective_date는 비교 결과의 effective_from을 기본으로 한다.

changes의 각 본문 조항에 빠짐없이 후보를 작성한다. 제N조의2도 본문 조항이며 supp-*만 부칙이다.
supplementary_changes의 적용례는 본문 신규 의무를 대체하지 않는다. 신규 의무는 해당 added 본문 조항으로 작성한다.
부칙 제2조의 기존 신청·연장 경과조치가 어떤 본문 개정에 적용되는지 transitional에 명시한다.
