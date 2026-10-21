-- 상품 규칙이 따르는 규정 조항 ({regulation_id}/{article_id} JSON 배열). docs/BACKEND_API.md 10.5
-- 정답이 아니라 규칙의 사실 정보다. 비어 있으면 상품 자체 기준이거나 미확인. 시드는 data/business/product_rules.json
ALTER TABLE product_rules ADD COLUMN basis_articles jsonb NOT NULL DEFAULT '[]';
