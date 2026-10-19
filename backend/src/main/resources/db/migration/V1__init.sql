-- Rule Ripple schema
-- 영역: 운영(users, task_events) / 분석(analysis_tasks, task_artifacts) / 전달(approvals, deliveries, work_tickets, jobs)
--       샘플 업무(products, product_rules, loan_contracts)

-- ===== 운영 =====
CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(64)  NOT NULL,
    role          VARCHAR(16)  NOT NULL CHECK (role IN ('DEVELOPER', 'LEAD')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ===== 분석 =====
CREATE TABLE analysis_tasks (
    id              UUID PRIMARY KEY,
    requester_id    BIGINT       NOT NULL REFERENCES users(id),
    regulation_id   VARCHAR(64)  NOT NULL,
    old_version     VARCHAR(32)  NOT NULL,
    new_version     VARCHAR(32)  NOT NULL,
    question        TEXT,
    status          VARCHAR(32)  NOT NULL,
        -- QUEUED | RUNNING | WAITING_REVIEW | WAITING_PUBLISH | PUBLISHING | DONE | FAILED | REJECTED
    thread_id       VARCHAR(128),            -- LangGraph checkpointer thread id (= id 문자열)
    current_step    VARCHAR(64),
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_analysis_tasks_requester ON analysis_tasks(requester_id, created_at DESC);

-- Agent 가 /internal/tasks/{id}/artifacts 로 저장하는 산출물
-- kind: REQUIREMENTS | CHANGE_SPEC | CODE_PATCH | DB_MIGRATION | TEST_CASE | VERIFY_RESULT | REPORT
CREATE TABLE task_artifacts (
    id         BIGSERIAL PRIMARY KEY,
    task_id    UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    kind       VARCHAR(32) NOT NULL,
    round      INT         NOT NULL DEFAULT 0,
    payload    JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_task_artifacts_task ON task_artifacts(task_id, kind);

-- SSE 로 흘려보내는 진행 이벤트. 재접속 시 seq 기준으로 재생.
-- type: TOKEN | TOOL_START | TOOL_END | STEP | APPROVAL_REQUIRED | RESUMED | DONE | FAILED
CREATE TABLE task_events (
    id         BIGSERIAL PRIMARY KEY,
    task_id    UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    seq        INT         NOT NULL,
    type       VARCHAR(32) NOT NULL,
    payload    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (task_id, seq)
);

-- ===== 전달 =====
-- step: REVIEW(명세서 확정, interrupt ①) | PUBLISH(PR·티켓 생성, interrupt ②)
CREATE TABLE approvals (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    step        VARCHAR(16) NOT NULL CHECK (step IN ('REVIEW', 'PUBLISH')),
    decision    VARCHAR(16) NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
    approver_id BIGINT      NOT NULL REFERENCES users(id),
    comment     TEXT,
    payload     JSONB,                    -- 개발자가 수정한 명세서 등
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Draft PR / Jira 티켓 등 외부로 나간 산출물 (시연에서는 목 링크)
CREATE TABLE deliveries (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    kind        VARCHAR(16) NOT NULL CHECK (kind IN ('PR', 'TICKET')),
    external_ref VARCHAR(128),
    url         VARCHAR(512),
    status      VARCHAR(16) NOT NULL DEFAULT 'CREATED',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- business-mcp 의 create_work_ticket 결과 (사내 작업 티켓, Jira 대체)
CREATE TABLE work_tickets (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID        REFERENCES analysis_tasks(id) ON DELETE SET NULL,
    title       VARCHAR(255) NOT NULL,
    description TEXT,
    type        VARCHAR(16) NOT NULL CHECK (type IN ('CODE', 'DB', 'DOC', 'TEST')),
    target_ref  VARCHAR(255),           -- 파일 경로, 테이블명 등
    assignee    VARCHAR(64),
    status      VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    created_by  VARCHAR(64) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 대기열 작업 이력 (가산점: 큐 처리 + 실패 재시도)
-- type: CHECK_PATCH | CREATE_DRAFT_PR | CREATE_TICKET
-- status: QUEUED | RUNNING | RETRYING | DONE | DEAD
CREATE TABLE jobs (
    id            UUID PRIMARY KEY,
    task_id       UUID        REFERENCES analysis_tasks(id) ON DELETE SET NULL,
    type          VARCHAR(32) NOT NULL,
    payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    status        VARCHAR(16) NOT NULL,
    attempts      INT         NOT NULL DEFAULT 0,
    last_error    TEXT,
    result        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_task ON jobs(task_id);

-- ===== 샘플 업무 (개인신용대출 도메인) =====
CREATE TABLE products (
    id          VARCHAR(16) PRIMARY KEY,   -- L001 ...
    name        VARCHAR(64) NOT NULL,
    type        VARCHAR(16) NOT NULL,      -- credit | mortgage | jeonse
    active      BOOLEAN     NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 규정 키 → 상품별 적용값. 경과조치용 effective_from 포함
-- rule_key 예: SENIOR_AGE, DSR_LIMIT, PREPAY_FEE_RATE_MAX, OVERDUE_SPREAD_MAX
CREATE TABLE product_rules (
    id             BIGSERIAL PRIMARY KEY,
    product_id     VARCHAR(16)  NOT NULL REFERENCES products(id),
    rule_key       VARCHAR(64)  NOT NULL,
    value          VARCHAR(64)  NOT NULL,
    value_type     VARCHAR(16)  NOT NULL DEFAULT 'number',   -- number | string | bool
    regulation_id  VARCHAR(64),                              -- 근거 규정 (rag-mcp Resource 와 연결)
    regulation_article VARCHAR(32),
    effective_from DATE         NOT NULL,
    effective_to   DATE,
    UNIQUE (product_id, rule_key, effective_from)
);

CREATE TABLE loan_contracts (
    id            BIGSERIAL PRIMARY KEY,
    product_id    VARCHAR(16) NOT NULL REFERENCES products(id),
    customer_ref  VARCHAR(32) NOT NULL,     -- 마스킹된 고객 식별자 (Guardrail: 실명·주민번호 없음)
    customer_age  INT         NOT NULL,
    principal     NUMERIC(14,0) NOT NULL,
    rate_pct      NUMERIC(5,2) NOT NULL,
    contracted_at DATE        NOT NULL,
    maturity_at   DATE        NOT NULL
);
CREATE INDEX idx_loan_contracts_product ON loan_contracts(product_id);
