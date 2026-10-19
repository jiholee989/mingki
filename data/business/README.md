# 샘플 업무 데이터 (가상)

리플은행 개인신용대출의 상품 · 상품 규칙 · 계약 데이터입니다. Spring 앱이 PostgreSQL에 넣고, `business-mcp`가 `/internal/**`로 읽습니다(`get_product_rules`, `get_db_schema`).

데이터 기준 시점은 **2026-11-30**(v4 시행 전날)입니다. 상품 규칙은 전부 v3 기준이고, v4 반영은 Agent가 만들 변경입니다.

| 파일 | 테이블 | 건수 | 용도 |
|---|---|---|---|
| `products.json` | `products` | 3 | 상품 마스터 |
| `product_rules.json` | `product_rules` | 19 | 상품별 규칙값. `source`에 근거 조항 |
| `loan_contracts.json` | `loan_contracts` | 8 | 기존 계약 · 신청. 경과조치 확인용 |
| `applicants.json` | (테이블 아님) | 9 | 시행일 전후 신청자 fixture. `expected`는 v4 반영 후 정답 |

## 상품

| ID | 이름 | 특징 |
|---|---|---|
| P001 | 리플 직장인 신용대출 | 운영기준을 그대로 따르는 기본 상품 |
| P002 | 리플 시니어 든든대출 | 고령자 전용. `ELIGIBLE_MIN_AGE = 65`가 고령자 기준과 연결됨 |
| P003 | 리플 프리미엄 신용대출 | 상품 자체 DSR 0.35. 운영기준보다 엄격 |

## v4 반영 시 상품 규칙 영향 (사람 확인용)

| rule_id | 규칙 | 판단 | 이유 |
|---|---|---|---|
| R001, R011 | `DSR_LIMIT 0.40` | 변경 대상 | 제8조 40% → 35% |
| R010 | P002 `ELIGIBLE_MIN_AGE 65` | 변경 대상 | 제15조 고령자 기준. 키 이름에 SENIOR가 없어 찾기 어려움 |
| R015 | P003 `DSR_LIMIT 0.35` | 대상 아님 | 상품 기준이 이미 신 기준 이하 |
| R007, R018 | `MORTGAGE_LTV_LIMIT 0.40` | 대상 아님 (함정) | 같은 0.40이지만 LTV(제10조) |
| R008 | `INCOME_EST_RETIREMENT_AGE 65` | 대상 아님 (함정) | 같은 65지만 소득 추정용 정년(제7조) |
| R005, R013, R019 | `SENIOR_RATE_DISCOUNT 0.3` | 대상 아님 | 우대 폭은 그대로. 적용 대상만 넓어짐 |

변경은 기존 행을 고치지 않고 `effective_to = 2026-11-30`으로 닫은 뒤 `effective_from = 2026-12-01` 행을 추가합니다.

## 계약 · 신청자 시나리오

- **경과조치**: C0002(62세), C0007(DSR 0.39)은 v4 기준이면 달라지지만 기존 계약이라 그대로입니다. C0006은 2027년 기간 연장 때도 종전 DSR 한도를 씁니다(부칙 제2조 ②).
- **신청일 기준**: C0004는 시행일 전에 신청하고 시행일 뒤에 체결하므로 종전 기준입니다. C0008은 시행일 전에 신청한 64세라 시니어 상품에서 거절됐습니다.
- **경계값**: A01(59세) / A02(신청일에 60세) / A04(65세), A08(DSR 정확히 0.35는 허용).
- **시행일 전·후 쌍**: A03 ↔ A06(같은 62세), A07 ↔ A09(같은 DSR 0.37).

나이는 신청일 기준 만 나이, DSR은 `annual_debt_service / annual_income`입니다.

## 제안 스키마 (PostgreSQL)

C(Backend)와 확정 전 초안입니다. 컬럼명은 JSON 키와 같습니다.

```sql
CREATE TABLE products (
  product_id      VARCHAR(10) PRIMARY KEY,
  name            VARCHAR(100) NOT NULL,
  description     TEXT,
  repayment_types VARCHAR(20)[] NOT NULL,
  min_term_months INT NOT NULL,
  max_term_months INT NOT NULL,
  status          VARCHAR(20) NOT NULL
);

CREATE TABLE product_rules (
  rule_id        VARCHAR(10) PRIMARY KEY,
  product_id     VARCHAR(10) NOT NULL REFERENCES products(product_id),
  rule_key       VARCHAR(50) NOT NULL,
  value          VARCHAR(50) NOT NULL,
  unit           VARCHAR(20) NOT NULL,  -- ratio | percent_point | krw | age | score | bool
  effective_from DATE NOT NULL,
  effective_to   DATE,
  source         VARCHAR(100) NOT NULL  -- {regulation_id}/{version}/{article_id} 또는 product
);
CREATE INDEX ON product_rules (product_id, rule_key, effective_from);

CREATE TABLE loan_contracts (
  contract_id      VARCHAR(10) PRIMARY KEY,
  product_id       VARCHAR(10) NOT NULL REFERENCES products(product_id),
  customer_id      VARCHAR(10) NOT NULL,
  birth_date       DATE NOT NULL,
  applied_at       DATE NOT NULL,
  contracted_at    DATE,
  status           VARCHAR(20) NOT NULL,  -- APPLIED | ACTIVE | REJECTED
  amount           BIGINT NOT NULL,
  term_months      INT NOT NULL,
  repayment_type   VARCHAR(20) NOT NULL,
  maturity_date    DATE,
  extension_count  INT NOT NULL DEFAULT 0,
  annual_income    BIGINT NOT NULL,
  dsr_at_approval  NUMERIC(4, 3),
  senior_applied   BOOLEAN,
  rate_discount_pp NUMERIC(3, 2),
  reject_reason    VARCHAR(50),
  note             TEXT
);
```
