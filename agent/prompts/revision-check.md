수정 제안이 사용자의 의견을 실제 본문에 반영했는지 검토한다. 문구 차이나 반영 설명만 믿지 않는다.
comment, previous_proposal, candidate, requirement와 regulation_context의 실제 조항·부칙을 대조한다. documents와 data_gaps를 함께 확인하며 조회하지 않은 계약의 과거 기준을 추정하지 않는다.
feedback_addressed: 사용자가 요청한 추가·삭제·범위·문구 변경이 실제 추천 본문/actions/optional_actions/precautions에 반영되었는가.
mandatory_preserved: 필수 값 변경·원문 단위·시행일·경과조치·조건부 적용 범위를 유지했는가. 필수 변경 '대신' 새로운 기능을 제안하면 false다.
반영 불가 사유만 적거나 같은 내용을 다르게 요약한 응답은 feedback_addressed=false다.
reason은 미반영 항목·위반을 구체적인 한 문장으로 설명한다. 제공된 근거 외 정책을 만들지 않는다.
의견에 여러 요청이 있으면 각각 실제 필드의 문장과 대조한다. 한 항목의 표현만 달라졌다고 전체 의견을 반영했다고 판정하지 않는다. reason에는 충족한 본문 근거 또는 빠진 항목을 구체적으로 적는다.
신청일 기준 경과조치를 계약일 기준으로 바꾸거나, 기존 계약 연장을 누락하거나, "종전 기준"을 자료 없이 모든 거래의 40% 등으로 단정하면 mandatory_preserved=false다.
scope/conditions와 본문이 충돌하면 필수 적용 범위 보존으로 인정하지 않는다. 범위 재판단 요청인데 scope가 그대로이고 설명만 수정 완료라면 feedback_addressed=false이며 영향 재분석 필요를 reason에 명시한다.
반영 불가·추가 자료 필요라는 정직한 설명은 수정 완료와 구분한다. 실제 요청을 충족하지 못했다면 feedback_addressed=false로 두되, reason에 재작성 반복으로 해결할 수 없는 원문 충돌/자료 부족/영향 재분석 필요 중 해당 사유를 설명한다.

사용자가 결과물·위치를 지정하면 그 위치에 실제 결과가 있어야 한다.
예: "고객 안내 한 문장을 추가 제안으로 써줘"인데 optional_actions에 기존의 일반적인 매뉴얼·고객 대응 조치만 있고 actions에만 안내 문구가 있으면 feedback_addressed=false다.
"문구를 추가한다"는 계획은 문구 자체를 요청한 의견의 이행이 아니다.
