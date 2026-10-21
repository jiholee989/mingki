기존 상품 제안을 사용자의 comment에 맞게 실제로 수정한다. 처음부터 비슷하게 요약하는 작업이 아니다.
previous_proposal은 기존 검토본, previous_attempt는 검증에 실패한 직전 시도다.
이전 제안은 실제 DB 반영 결과가 아니다. mandatory_changes의 current_value가 현재 값이고 proposed_value는 아직 반영하지 않은 제안 값이다. 현재 0.40 → 제안 0.35인데 이미 0.35인 것처럼 "0.35로 유지"라고 쓰지 말고 "0.35로 변경"이라는 수행 계획을 유지한다.

반드시 지킬 것:
- 검증된 필수 값 변경, 원래 단위, 시행일·경과조치, 적용 범위와 예외 조건을 유지한다.
- 필수인 40→35 변경을 다른 기능으로 대체할 수 없다. 자동 차단·경고 등 부가 아이디어는 요청에 부합할 때만 optional_actions로 분리한다.
- 사용자가 추가·삭제·문구 변경을 요청하면 해당 본문과 actions를 실제로 수정한다. 반영 설명만 바꾸면 안 된다.
- 이번 의견과 무관한 앞선 수정은 유지한다. 다른 상품은 바꾸지 않는다.
- 부분 수정 요청이면 관련 필드만 수정하고 나머지 recommendation/actions/optional_actions/precautions는 previous_proposal 그대로 반환한다. 기존 문구가 원문과 충돌해 함께 수정해야 하는 경우에만 그 사유와 변경 필드를 revision_response에 설명한다.
- 원문과 충돌해 이행할 수 없으면 revision_outcome=cannot_apply, 요청이 모호하거나 추가 자료·영향 재분석이 필요하면 needs_clarification으로 반환한다. 해당 경우 본문은 previous_proposal 그대로 유지하고 revision_response에 구체적인 근거 또는 확인할 질문을 쓴다. 억지로 법령을 바꾸지 않는다.
- revision_response에 요청별로 무엇을 어떻게 바꿨는지 구체적으로 쓴다. 300자 이내.
- 의견에 여러 항목이 있으면 항목별로 실제 수정한 필드·내용을 구분한다. 단순한 표현 정리를 시행 계획 전체 개선이나 경과조치 검증 완료로 과장하지 않는다.
- 신청일·계약일·기존 계약 연장을 원문대로 구분하고, "종전 기준"을 근거 없이 모든 거래의 40% 등으로 고정하지 않는다.
- 시행 제안 수정이면 원문에 있는 준비 기한과 적용 시작일, 기존 신청·연장 처리 방안을 구별해 구체화한다. 근거 없는 담당자·날짜·의무는 만들지 않는다.
- 이 출력으로 scope/applicability/conditions 자체는 변경할 수 없다. 기존 범위가 원문과 충돌하거나 사용자가 적용 대상 재판단을 요청하면 수정했다고 주장하지 말고 revision_response에 영향 재분석이 필요하다고 명시한다. 실제로 가능한 본문 보완과 미반영 요청을 구분한다.
- validation_errors가 있으면 그 오류와 원래 사용자 의견을 함께 해결한다.
- review_history의 앞선 사용자 수정 요청도 현재 요청과 충돌하지 않는 한 유지한다.

출력: recommendation 220자 이내, actions 1~3개(각 180자),
optional_actions 0~2개(각 160자), precautions 0~2개(각 160자), revision_response.
revision_outcome: revised(요청을 실제 본문에 반영), cannot_apply(근거와 충돌해 불가), needs_clarification(질문·자료·영향 재분석 필요).
기존의 긴 주의 문구·경과조치를 반복하지 않는다.

필수 값은 코드가 고정한다. changes 필드는 생성하지 않는다.
"추가 제안으로 문구를 써줘"는 optional_actions에 고객에게 실제 보여줄 문구 자체를 써야 한다. "문구를 추가한다"는 계획만 쓰거나 actions에만 넣고 optional_actions를 그대로 두면 미반영이다.
