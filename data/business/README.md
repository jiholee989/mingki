# 샘플 업무 데이터 (가상)

리플은행 개인신용대출의 상품 · 상품 규칙 · 계약 데이터입니다. Spring 앱이 PostgreSQL에 넣고, `business-mcp`가 `/internal/**`로 읽습니다(`get_product_rules`, `get_db_schema`).

데이터 기준 시점은 **2026-11-30**입니다.

| 파일 | 테이블 | 건수 | 용도 |
|---|---|---|---|
| `products.json` | `products` | 3 | 상품 마스터 |
| `product_rules.json` | `product_rules` | 19 | 상품별 규칙값 |
| `loan_contracts.json` | `loan_contracts` | 8 | 기존 계약 · 신청 |

이 폴더는 Agent가 MCP로 보는 입력입니다. 판단 근거나 정답은 넣지 않고 `eval/`에 둡니다.

## 상품

| ID | 이름 |
|---|---|
| P001 | 리플 직장인 신용대출 |
| P002 | 리플 시니어 든든대출 |
| P003 | 리플 프리미엄 신용대출 |

## 규칙값 변경 방식

기존 행을 고치지 않고 `effective_to`로 닫은 뒤 새 `effective_from` 행을 추가합니다.

나이는 신청일 기준 만 나이, DSR은 연간 원리금 상환액 / 연간 소득입니다.

## 스키마 (PostgreSQL)

C(Backend)와 확정한 스키마입니다. 컬럼명은 JSON 키와 같습니다.

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
  effective_to   DATE
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
  reject_reason    VARCHAR(50)
);
```
