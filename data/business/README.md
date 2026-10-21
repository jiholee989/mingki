# 샘플 업무 데이터 (가상)

리플은행 개인신용대출의 상품 · 상품 규칙 · 계약 데이터입니다. Spring 앱이 PostgreSQL에 넣고, `business-mcp`가 `/internal/**`로 읽습니다(`get_product_rules`, `get_db_schema`).

데이터 기준 시점은 **2026-11-30**입니다.

| 파일 | 테이블 | 건수 | 용도 |
|---|---|---|---|
| `products.json` | `products` | 12 | 상품 마스터 (판매 중단 1개 포함) |
| `product_rules.json` | `product_rules` | 82 | 상품별 규칙값 (종료된 옛 버전 행 포함) |
| `loan_contracts.json` | `loan_contracts` | 120 | 기존 계약 · 신청 · 거절 (만기 지난 계약 포함) |

이 폴더는 Agent가 MCP로 보는 입력입니다. 판단 근거나 정답은 넣지 않고 `eval/`에 둡니다.
`product_rules.basis_articles`는 정답이 아니라 규칙의 사실 정보입니다. "이 규칙이 어느 규정 조항을 따르는가"(규정 ↔ 규칙 연결)이고, "이번 개정으로 바뀌어야 하는가"는 담지 않습니다. 상품 자체 기준(최대 금액 등)이거나 확인되지 않은 규칙은 비워 둡니다. 숫자로 표현되지 않는 상품 정보(심사 절차, 설명 항목, 화면 문구)는 `data/product-docs/`에 있습니다.

## 상품

| ID | 이름 |
|---|---|
| P001 | 리플 직장인 신용대출 |
| P002 | 리플 시니어 든든대출 |
| P003 | 리플 프리미엄 신용대출 |
| P004 | 리플 전문직 신용대출 |
| P005 | 리플 청년 희망대출 |
| P006 | 리플 비상금 소액대출 |
| P007 | 리플 직장인 마이너스통장 |
| P008 | 리플 갈아타기 대환대출 |
| P009 | 리플 사장님 신용대출 |
| P010 | 리플 중금리 신용대출 |
| P011 | 리플 외국인 신용대출 |
| P012 | 리플 직장인 신용대출(구) — 판매 중단 |

실제 운영 데이터처럼 정리되지 않은 부분이 있습니다. 같은 개념이라도 상품마다 규칙 키 이름이나 단위가 다를 수 있고, `effective_to`가 있는 행은 지금은 적용되지 않는 옛 버전입니다. 기존 ID(P001~P003, R001~R019, C0001~C0008)는 바꾸지 않고 뒤에 추가했습니다.

## 규칙값 변경 방식

기존 행을 고치지 않고 `effective_to`로 닫은 뒤 새 `effective_from` 행을 추가합니다.

나이는 신청일 기준 만 나이, DSR은 연간 원리금 상환액 / 연간 소득입니다. `status`: 상품은 `ON_SALE` · `SALE_ENDED`, 계약은 `APPLIED` · `ACTIVE` · `REJECTED`. 상환 방식에 한도대출 `REVOLVING`이 있습니다.

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
  unit           VARCHAR(20) NOT NULL,  -- ratio | percent | percent_point | krw | months | years | days | count | age | score | bool
  effective_from DATE NOT NULL,
  effective_to   DATE,
  basis_articles VARCHAR(50)[] NOT NULL DEFAULT '{}'  -- 이 규칙이 따르는 규정 조항 {regulation_id}/{article_id}
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
