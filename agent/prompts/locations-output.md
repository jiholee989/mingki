도구 조사 기록에 근거한 ChangeSpec 목록을 반환한다. 추측한 기존 위치는 넣지 않는다.
각 후보는 다음 세 가지로 구분한다.
- 대상: is_target=true, needs_review=false. 요건을 구현하는 관련성이 확인되었음.
- 비대상: is_target=false, needs_review=false. 비슷한 값이지만 다른 의미 등 제외 근거가 있음.
- 확인 필요: is_target=false, needs_review=true. 연관 가능성은 있으나 자료가 부족함.

reason에는 "변경 조항 → 이 코드/규칙의 역할 → 관련/무관한 이유"를 구체적으로 적는다.
대상은 before와 after에 변경 전후 동작·값을 반드시 작성한다. '규정 반영' 같은 일반적인 설명만 쓰지 않는다.
코드 본문 미조회 또는 상품 설명과 규칙 의미를 연결하지 못하면 확인 필요로 남긴다.
코드의 file/line/snippet은 도구 기록과 일치해야 한다.
상품 규칙은 file=db/product_rules, line=ruleId 숫자, symbol=ruleId + productId.ruleKey로 작성한다.
신규 기능 제안은 kind=new이며, 기존 파일을 조회한 것처럼 주장하지 않는다.
같은 위치가 여러 요건에 관련되면 관계를 각각 보존한다.
