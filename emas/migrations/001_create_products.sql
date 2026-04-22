-- ============================================================
-- Factory Operations Agent — MySQL Schema
-- Engine: InnoDB (required for foreign keys)
-- Charset: utf8mb4 (required for full Unicode / emoji in messages)
-- ============================================================

SET NAMES utf8mb4;
SET foreign_key_checks = 0;

-- Sessions (rate limit counters)
CREATE TABLE sessions (
    session_id          CHAR(36)        NOT NULL,
    user_id             VARCHAR(255)    NOT NULL,
    status              VARCHAR(50)     NOT NULL DEFAULT 'IDLE',
    -- valid: IDLE | PLANNING | WAITING_APPROVAL | EXECUTING | BLOCKED | FAILED | COMPLETED
    current_intent      TEXT,
    plan_id             CHAR(36),
    plan_version        INT             NOT NULL DEFAULT 0,
    plan_hash           VARCHAR(64),
    current_step_index  INT             NOT NULL DEFAULT 0,
    retry_count         INT             NOT NULL DEFAULT 0,
    step_count          INT             NOT NULL DEFAULT 0,
    replan_count        INT             NOT NULL DEFAULT 0,
    llm_call_count      INT             NOT NULL DEFAULT 0,
    session_started_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    error               TEXT,
    version             INT             NOT NULL DEFAULT 1,   -- optimistic lock
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    completed_at        DATETIME(3),
    PRIMARY KEY (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Messages
CREATE TABLE messages (
    message_id  CHAR(36)        NOT NULL,
    session_id  CHAR(36)        NOT NULL,
    role        VARCHAR(20)     NOT NULL,
    -- valid: user | assistant | system | tool_result
    content     MEDIUMTEXT      NOT NULL,
    step_id     CHAR(36),
    tool_name   VARCHAR(255),
    created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (message_id),
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Plans
CREATE TABLE plans (
    plan_id             CHAR(36)        NOT NULL,
    session_id          CHAR(36)        NOT NULL,
    version             INT             NOT NULL,
    dependency_graph    JSON,           -- {"0": [], "1": [0], "2": [1]}
    parallel_groups     JSON,           -- [[0,1], [2]]
    plan_hash           VARCHAR(64)     NOT NULL,
    plan_explanation    MEDIUMTEXT,     -- LLM-generated plain-English explanation
    risk_summary        MEDIUMTEXT,     -- LLM-generated risk description
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    created_by          VARCHAR(20)     NOT NULL DEFAULT 'llm',
    -- valid: llm | human_edit
    invalidated_at      DATETIME(3),
    invalidated_reason  TEXT,
    PRIMARY KEY (plan_id),
    CONSTRAINT fk_plans_session FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Plan Steps
CREATE TABLE plan_steps (
    step_id             CHAR(36)        NOT NULL,
    plan_id             CHAR(36)        NOT NULL,
    session_id          CHAR(36)        NOT NULL,
    step_index          INT             NOT NULL,
    tool_name           VARCHAR(255)    NOT NULL,
    args                JSON            NOT NULL,
    status              VARCHAR(20)     NOT NULL DEFAULT 'NOT_STARTED',
    -- valid: NOT_STARTED | IN_PROGRESS | DONE | FAILED | SKIPPED | AMBIGUOUS
    idempotency_key     VARCHAR(64)     NOT NULL,
    requires_approval   TINYINT(1)      NOT NULL DEFAULT 0,
    approval_id         CHAR(36),
    retry_count         INT             NOT NULL DEFAULT 0,
    max_retries         INT             NOT NULL DEFAULT 3,
    last_error          TEXT,
    result              JSON,
    result_summary      TEXT,
    started_at          DATETIME(3),
    completed_at        DATETIME(3),
    PRIMARY KEY (step_id),
    UNIQUE KEY uq_plan_steps_idempotency (idempotency_key),
    CONSTRAINT fk_plan_steps_plan    FOREIGN KEY (plan_id)    REFERENCES plans(plan_id),
    CONSTRAINT fk_plan_steps_session FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tools
-- Note: capability_tags stored as JSON array e.g. '["machine","status","maintenance"]'
-- Queried with: JSON_CONTAINS(capability_tags, '"machine"')
-- Generated column + index used for common single-tag lookups (see below)
CREATE TABLE tools (
    tool_id                 CHAR(36)        NOT NULL,
    name                    VARCHAR(255)    NOT NULL,
    description             TEXT            NOT NULL,
    endpoint                VARCHAR(500)    NOT NULL,
    method                  VARCHAR(10)     NOT NULL,
    -- valid: GET | POST | PATCH | DELETE
    version                 INT             NOT NULL DEFAULT 1,
    schema_version          INT             NOT NULL DEFAULT 1,
    input_schema            JSON            NOT NULL,
    output_schema           JSON,
    is_read_only            TINYINT(1)      NOT NULL DEFAULT 0,
    requires_approval       TINYINT(1)      NOT NULL DEFAULT 0,
    side_effect_level       VARCHAR(10)     NOT NULL DEFAULT 'NONE',
    -- valid: NONE | LOW | HIGH | CRITICAL
    is_concurrency_safe     TINYINT(1)      NOT NULL DEFAULT 1,
    is_idempotent           TINYINT(1)      NOT NULL DEFAULT 0,
    is_strongly_idempotent  TINYINT(1)      NOT NULL DEFAULT 0,
    capability_tags         JSON            NOT NULL DEFAULT (JSON_ARRAY()),
    deprecated_at           DATETIME(3),
    replacement_tool        VARCHAR(255),
    created_at              DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    updated_at              DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    PRIMARY KEY (tool_id),
    UNIQUE KEY uq_tools_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Approvals
CREATE TABLE approvals (
    approval_id         CHAR(36)        NOT NULL,
    session_id          CHAR(36)        NOT NULL,
    step_id             CHAR(36)        NOT NULL,
    tool_name           VARCHAR(255)    NOT NULL,
    args                JSON            NOT NULL,
    risk_summary        MEDIUMTEXT      NOT NULL,
    side_effect_level   VARCHAR(10)     NOT NULL,
    status              VARCHAR(10)     NOT NULL DEFAULT 'PENDING',
    -- valid: PENDING | APPROVED | REJECTED | EXPIRED
    expires_at          DATETIME(3)     NOT NULL,
    decided_by          VARCHAR(255),
    decided_at          DATETIME(3),
    rejection_reason    TEXT,
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (approval_id),
    CONSTRAINT fk_approvals_session FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    CONSTRAINT fk_approvals_step    FOREIGN KEY (step_id)    REFERENCES plan_steps(step_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Execution Snapshots
CREATE TABLE execution_snapshots (
    snapshot_id         CHAR(36)        NOT NULL,
    step_id             CHAR(36)        NOT NULL,
    session_id          CHAR(36)        NOT NULL,
    tool_name           VARCHAR(255)    NOT NULL,
    tool_version        INT             NOT NULL,
    schema_version      INT             NOT NULL,
    input_args          JSON            NOT NULL,
    plan_hash           VARCHAR(64)     NOT NULL,
    plan_version        INT             NOT NULL,
    idempotency_key     VARCHAR(64)     NOT NULL,
    http_status         INT,
    response_body       JSON,
    latency_ms          INT,
    executed_at         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (snapshot_id),
    CONSTRAINT fk_snapshots_step FOREIGN KEY (step_id) REFERENCES plan_steps(step_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Dead Letter Queue
CREATE TABLE dead_letters (
    dlq_id              CHAR(36)        NOT NULL,
    session_id          CHAR(36)        NOT NULL,
    step_id             CHAR(36),                   -- NULL for planning-level failures
    failure_type        VARCHAR(50)     NOT NULL,
    -- valid: max_retries_exceeded | replan_limit_reached | unrecoverable_error
    --        rate_limit_exceeded | session_timeout | validation_failure | ambiguous_execution
    reason              TEXT            NOT NULL,
    payload             JSON            NOT NULL,
    status              VARCHAR(20)     NOT NULL DEFAULT 'PENDING',
    -- valid: PENDING | REPLAYED | DISMISSED | ESCALATED
    replayed_at         DATETIME(3),
    replayed_by         VARCHAR(255),
    dismissed_at        DATETIME(3),
    dismissed_reason    TEXT,
    created_at          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (dlq_id),
    CONSTRAINT fk_dlq_session FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    CONSTRAINT fk_dlq_step    FOREIGN KEY (step_id)    REFERENCES plan_steps(step_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Idempotency Log (DB-level backup when Redis is unavailable)
-- key is the Idempotency-Key header value (max 255 chars)
CREATE TABLE idempotency_log (
    `key`           VARCHAR(255)    NOT NULL,
    request_hash    VARCHAR(64)     NOT NULL,
    response        MEDIUMBLOB      NOT NULL,   -- raw response bytes
    status_code     INT             NOT NULL,
    created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX idx_sessions_user_id           ON sessions(user_id);
CREATE INDEX idx_sessions_status            ON sessions(status);
CREATE INDEX idx_messages_session_id        ON messages(session_id);
CREATE INDEX idx_plan_steps_session_id      ON plan_steps(session_id);
CREATE INDEX idx_plan_steps_status          ON plan_steps(status);
-- idempotency_key already has UNIQUE KEY above (acts as index)
CREATE INDEX idx_approvals_session_id       ON approvals(session_id);
CREATE INDEX idx_approvals_status           ON approvals(status);
CREATE INDEX idx_snapshots_session_id       ON execution_snapshots(session_id);
CREATE INDEX idx_dlq_status                 ON dead_letters(status);
CREATE INDEX idx_dlq_session_id             ON dead_letters(session_id);

-- capability_tags: no GIN equivalent in MySQL.
-- Use JSON_CONTAINS for tag filtering:
--   SELECT * FROM tools WHERE JSON_CONTAINS(capability_tags, '"machine"');
-- For high-traffic tag lookups, add a generated column per common tag:
--   ALTER TABLE tools
--       ADD COLUMN tag_machine TINYINT(1) AS (JSON_CONTAINS(capability_tags, '"machine"')) VIRTUAL,
--       ADD INDEX idx_tools_tag_machine (tag_machine);

SET foreign_key_checks = 1;