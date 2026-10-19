-- Rule Ripple schema (docs/PROJECT.md 8절 기준)
-- 분석: analysis_tasks · regulation_documents · requirements · change_specs
-- 산출물: code_patches · test_cases · db_migrations(2단계)
-- 전달: approvals · deliveries · work_tickets · jobs
-- 운영: users · task_events  (LangGraph checkpointer 테이블은 Agent 가 직접 관리)
-- 샘플 업무: products · product_rules · loan_contracts

-- ===== 운영 =====
CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(64)  NOT NULL,
    -- OFFICER: 준법감시·상품기획 담당자 (규정 업로드, ① 요건 확정)
    -- DEVELOPER: 개발자 (② 검토·승인)
    role          VARCHAR(16)  NOT NULL CHECK (role IN ('OFFICER', 'DEVELOPER')),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ===== 분석 =====
CREATE TABLE analysis_tasks (
    id              UUID PRIMARY KEY,
    requester_id    BIGINT       NOT NULL REFERENCES users(id),
    title           VARCHAR(200) NOT NULL,
    status          VARCHAR(40)  NOT NULL,
        -- EXTRACTING | WAITING_REQUIREMENT_APPROVAL | LOCATING | DESIGNING | VERIFYING
        -- | WAITING_REVIEW | PUBLISHING | DONE | NO_CHANGE | HELD | REJECTED | FAILED
    current_node    VARCHAR(64),             -- Agent 가 마지막으로 알린 노드 (requirement_agent, verify ...)
    verify_round    INT          NOT NULL DEFAULT 0,
    thread_id       VARCHAR(128) NOT NULL,   -- LangGraph checkpointer thread id
    error_message   TEXT,
    report          JSONB,                   -- report 노드 결과 (명세서 markdown 등)
    evaluation      JSONB,                   -- 정답지 점수 · 키워드 검색 비교
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_analysis_tasks_requester ON analysis_tasks(requester_id, created_at DESC);

-- 업로드한 규정 v3(OLD) · v4(NEW) 원문. regulation-mcp 가 /internal 로 읽어간다.
CREATE TABLE regulation_documents (
    id            BIGSERIAL PRIMARY KEY,
    task_id       UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    side          VARCHAR(8)   NOT NULL CHECK (side IN ('OLD', 'NEW')),
    version_label VARCHAR(32)  NOT NULL,     -- v3, v4
    filename      VARCHAR(255) NOT NULL,
    content       TEXT         NOT NULL,
    sha256        VARCHAR(64)  NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, side)
);

-- requirement_agent 결과. 시행일 · 경과조치는 필수 필드.
CREATE TABLE requirements (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    req_key         VARCHAR(32)  NOT NULL,   -- Agent 가 붙인 키 (R1, R2 ...)
    summary         TEXT         NOT NULL,   -- 변경 내용
    target          TEXT,                    -- 대상 (상품, 고객군 ...)
    effective_date  DATE,                    -- 시행일
    transitional    TEXT,                    -- 경과조치
    article_ref     VARCHAR(64),             -- 근거 조항 (제15조)
    old_text        TEXT,                    -- 구 조항 원문
    new_text        TEXT,                    -- 신 조항 원문
    status          VARCHAR(16)  NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED', 'CONFIRMED', 'HELD')),
    detail          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, req_key)
);

-- locate_agent 결과. 대상이 아닌 위치도 이유와 함께 기록한다.
CREATE TABLE change_specs (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    spec_key        VARCHAR(32)  NOT NULL,   -- S1, S2 ...
    req_key         VARCHAR(32)  NOT NULL,
    location_kind   VARCHAR(16)  NOT NULL CHECK (location_kind IN ('CODE', 'CONFIG', 'DB', 'PRODUCT', 'DOC', 'UI')),
    file_path       VARCHAR(255),
    symbol          VARCHAR(255),            -- is_senior(), SENIOR_AGE_MONTHS ...
    line_no         INT,
    snippet         TEXT,                    -- 현재 코드 한 줄
    change_type     VARCHAR(16)  CHECK (change_type IN ('VALUE', 'LOGIC', 'DB', 'NEW')),  -- ① ② ③ ④, 대상 아님이면 NULL
    is_target       BOOLEAN      NOT NULL,
    reason          TEXT         NOT NULL,   -- 판단 이유 (대상 아님 이유 포함)
    bundle          VARCHAR(64),             -- design plan 의 파일 묶음
    detail          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, spec_key)
);

-- ===== 산출물 =====
-- design_agent 패치 + verify 결과. round 마다 새 행 (회차별 이력 유지)
CREATE TABLE code_patches (
    id              BIGSERIAL PRIMARY KEY,
    task_id         UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    bundle          VARCHAR(64)  NOT NULL,
    round           INT          NOT NULL,
    spec_keys       JSONB        NOT NULL DEFAULT '[]'::jsonb,  -- ["S1","S3"]
    file_path       VARCHAR(255) NOT NULL,
    diff            TEXT         NOT NULL,
    verify_status   VARCHAR(16)  NOT NULL DEFAULT 'PENDING' CHECK (verify_status IN ('PENDING', 'PASSED', 'FAILED')),
    verify_log      TEXT,
    failure_kind    VARCHAR(16)  CHECK (failure_kind IN ('PATCH', 'SYSTEM_TEST')),  -- PATCH → design, SYSTEM_TEST → locate
    detail          JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, bundle, round, file_path)
);

-- test_agent 결과. 한 번 저장되면 고정 (design 이 수정 불가)
CREATE TABLE test_cases (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    test_key    VARCHAR(32)  NOT NULL,
    req_key     VARCHAR(32)  NOT NULL,
    name        VARCHAR(255) NOT NULL,
    kind        VARCHAR(16)  NOT NULL CHECK (kind IN ('BOUNDARY', 'EFFECTIVE_DATE', 'SYSTEM', 'UNIT')),
    code        TEXT         NOT NULL,
    detail      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (task_id, test_key)
);

-- ③ DB 변경 (2단계). MVP 에서는 비어 있다.
CREATE TABLE db_migrations (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID         NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    round       INT          NOT NULL DEFAULT 1,
    up_sql      TEXT         NOT NULL,
    down_sql    TEXT         NOT NULL,
    detail      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ===== 진행 이벤트 (SSE · 폴링) =====
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
-- step: REQUIREMENTS (interrupt ① 요건 확정) | REVIEW (interrupt ② 검토·승인)
-- decision: REQUIREMENTS → CONFIRM (일부라도 확정) | HOLD (전부 보류)
--           REVIEW       → APPROVE | REJECT | REQUEST_CHANGES
CREATE TABLE approvals (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    step        VARCHAR(16) NOT NULL CHECK (step IN ('REQUIREMENTS', 'REVIEW')),
    decision    VARCHAR(20) NOT NULL CHECK (decision IN ('CONFIRM', 'HOLD', 'APPROVE', 'REJECT', 'REQUEST_CHANGES')),
    approver_id BIGINT      NOT NULL REFERENCES users(id),
    comment     TEXT,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,   -- 요건별 결정, 제외한 spec 등
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_approvals_task ON approvals(task_id);

-- Draft PR / 작업 티켓 (시연에서 PR 은 목 링크, 티켓은 work_tickets)
CREATE TABLE deliveries (
    id           BIGSERIAL PRIMARY KEY,
    task_id      UUID        NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    kind         VARCHAR(16) NOT NULL CHECK (kind IN ('PR', 'TICKET')),
    external_ref VARCHAR(128),
    url          VARCHAR(512),
    approval_id  BIGINT      REFERENCES approvals(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE work_tickets (
    id          BIGSERIAL PRIMARY KEY,
    task_id     UUID         REFERENCES analysis_tasks(id) ON DELETE SET NULL,
    title       VARCHAR(255) NOT NULL,
    description TEXT,
    type        VARCHAR(16)  NOT NULL CHECK (type IN ('CODE', 'CONFIG', 'DB', 'DOC', 'TEST')),
    target_ref  VARCHAR(255),
    assignee    VARCHAR(64),
    status      VARCHAR(16)  NOT NULL DEFAULT 'OPEN',
    approval_id BIGINT       REFERENCES approvals(id),
    created_by  VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- 대기열 작업 (가산점). 쓰기 작업은 approval_id + 멱등키 필수.
-- type: CHECK_PATCH | CREATE_DRAFT_PR | CREATE_TICKET
CREATE TABLE jobs (
    id              UUID PRIMARY KEY,
    task_id         UUID        REFERENCES analysis_tasks(id) ON DELETE SET NULL,
    type            VARCHAR(32) NOT NULL,
    payload         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    approval_id     BIGINT      REFERENCES approvals(id),
    idempotency_key VARCHAR(128) UNIQUE,
    status          VARCHAR(16) NOT NULL,   -- QUEUED | RUNNING | RETRYING | DONE | DEAD
    attempts        INT         NOT NULL DEFAULT 0,
    last_error      TEXT,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_task ON jobs(task_id);

-- ===== 샘플 업무 (개인신용대출, 가상 데이터) =====
CREATE TABLE products (
    id          VARCHAR(16) PRIMARY KEY,
    name        VARCHAR(64) NOT NULL,
    type        VARCHAR(16) NOT NULL,
    active      BOOLEAN     NOT NULL DEFAULT true
);

-- 규정 키별 상품 적용값. 시행일 버전(effective_from)으로 경과조치를 표현한다.
CREATE TABLE product_rules (
    id                 BIGSERIAL PRIMARY KEY,
    product_id         VARCHAR(16)  NOT NULL REFERENCES products(id),
    rule_key           VARCHAR(64)  NOT NULL,
    value              VARCHAR(64)  NOT NULL,
    description        VARCHAR(255),
    regulation_ref     VARCHAR(64),
    effective_from     DATE         NOT NULL,
    UNIQUE (product_id, rule_key, effective_from)
);

CREATE TABLE loan_contracts (
    id            BIGSERIAL PRIMARY KEY,
    product_id    VARCHAR(16)   NOT NULL REFERENCES products(id),
    customer_ref  VARCHAR(32)   NOT NULL,   -- 마스킹된 식별자만 (Guardrail)
    customer_age  INT           NOT NULL,
    principal     NUMERIC(14,0) NOT NULL,
    applied_at    DATE          NOT NULL,   -- 신청일 (경과조치 판단 기준)
    maturity_at   DATE          NOT NULL
);
