도구 조사 기록에 근거한 ChangeSpec 목록을 반환한다. 추측한 파일은 넣지 않는다.
기존 코드의 file/line/snippet은 도구 기록과 일치해야 한다. 상품 규칙은 file=db/product_rules,
line은 ruleId의 숫자, symbol은 ruleId와 productId.ruleKey를 포함한다.
새 파일 제안은 kind=new로만 표시한다. 같은 위치가 여러 요건에 관련되면 관계를 각각 보존한다.
