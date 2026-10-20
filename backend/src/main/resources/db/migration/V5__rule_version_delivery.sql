-- 상품 규칙 반영(APPLY_RULE_VERSION) 결과를 전달 기록에 남긴다 (docs/BACKEND_API.md 10.4).
ALTER TABLE deliveries DROP CONSTRAINT deliveries_kind_check;
ALTER TABLE deliveries ADD CONSTRAINT deliveries_kind_check CHECK (kind IN ('PR', 'TICKET', 'RULE_VERSION'));
