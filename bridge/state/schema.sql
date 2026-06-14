-- bridge/state/schema.sql
-- v2.0 persistence — SIRO 對話歷史 + task queue + audit log
-- 用 sqlite3 直接執行：sqlite3 siro-data.db < schema.sql

-- ==================== Sessions ====================
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    persona    TEXT NOT NULL DEFAULT 'siro-default',
    created_at INTEGER NOT NULL,  -- unix ms
    updated_at INTEGER NOT NULL,
    metadata   TEXT               -- JSON blob
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

-- ==================== Messages ====================
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content     TEXT NOT NULL,
    emotion     TEXT,             -- happy / sad / ...
    expression  TEXT,             -- Live2D exp_01 等
    tool_name   TEXT,             -- v1.5+ tool_use
    tool_args   TEXT,             -- JSON
    tool_result TEXT,             -- JSON
    created_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(session_id, role, id DESC);
CREATE INDEX IF NOT EXISTS idx_messages_content ON messages(content);

-- ==================== Tasks ====================
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,           -- UUID
    name         TEXT NOT NULL,              -- 'llm.reply' / 'unity.sendtask' / ...
    payload      TEXT NOT NULL,              -- JSON
    status       TEXT NOT NULL CHECK(status IN ('pending', 'running', 'done', 'failed', 'cancelled')),
    result       TEXT,                       -- JSON
    error        TEXT,
    worker_id    TEXT,
    enqueued_at  INTEGER NOT NULL,
    started_at   INTEGER,
    finished_at  INTEGER,
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3
);

CREATE INDEX IF NOT EXISTS idx_tasks_pending ON tasks(status, enqueued_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(json_extract(payload, '$.session_id'));
CREATE INDEX IF NOT EXISTS idx_tasks_status_enqueued ON tasks(status, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(name, enqueued_at DESC);

-- ==================== Audit log ====================
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id    TEXT,
    action     TEXT NOT NULL,    -- 'tool.execute' / 'memory.save' / ...
    target     TEXT,             -- sandbox path / shell cmd / ...
    result     TEXT NOT NULL DEFAULT 'ok',  -- 'ok' / 'denied' / 'error'
    detail     TEXT,             -- JSON
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ==================== v2.0 KV table (給 v1.5+ memory / config) ====================
-- v1.5+ 已經用 bridge/data/siro-memory.db；v2.0 整進來同個 DB
-- 為了不破壞既有 v1.5+ tools/memory.py、加一張 v2_kv 但 v1.5+ 暫不動
CREATE TABLE IF NOT EXISTS v2_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,             -- JSON
    updated_at INTEGER NOT NULL
);
