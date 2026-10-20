-- 단순화 흐름(v2): 상품별 변경 제안과 기존 계약 영향. 계약은 docs/BACKEND_API.md 10.2 · 10.6.
-- 제안 1건 = 상품 1개 × 규칙 1개. (proposal_key, round)마다 행을 남겨 근거 검사 회차 이력이 보인다.
CREATE TABLE rule_proposals (
    id              BIGSERIAL    PRIMARY KEY,
    task_id         UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    proposal_key    VARCHAR(100) NOT NULL,          -- Agent 가 정한다 (권장 {productId}:{ruleKey})
    round           INT          NOT NULL CHECK (round >= 1),
    req_key         VARCHAR(64),
    product_id      VARCHAR(10)  NOT NULL,
    rule_id         VARCHAR(10),                    -- 새 규칙이면 null
    rule_key        VARCHAR(50),
    impact          VARCHAR(20)  NOT NULL CHECK (impact IN ('change_required', 'keep', 'needs_check')),
    current_text    TEXT,
    proposed_text   TEXT,
    unit            VARCHAR(20),
    current_value   VARCHAR(50),
    proposed_value  VARCHAR(50),
    effective_date  DATE,
    basis           VARCHAR(200),
    reason          TEXT         NOT NULL,
    transition      TEXT,
    follow_up       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    verify_status   VARCHAR(16)  NOT NULL DEFAULT 'PENDING' CHECK (verify_status IN ('PENDING', 'PASSED', 'FAILED')),
    verify_log      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, proposal_key, round)
);
CREATE INDEX idx_rule_proposals_task ON rule_proposals(task_id);

-- 경과조치로 종전 기준이 유지되는 계약. Agent 가 통째로 바꾼다.
ALTER TABLE analysis_tasks ADD COLUMN contract_impacts JSONB;
