-- Migration 003 — sessions table for login-gate phase 0 (2026-09-07)
--
-- Run against PRODUCTION D1 with:
--   wrangler d1 execute labsch-db --remote --file=migrations/003-sessions.sql
--
-- NOTE: schema.sql already contains this table for FRESH deployments.
--       This file is for the EXISTING production database, which does not
--       auto-migrate (D1 has no runtime migration support).

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    student_name TEXT NOT NULL,
    request_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    deleted_at REAL
);

CREATE INDEX IF NOT EXISTS idx_sessions_device ON sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted ON sessions(deleted_at);

-- client_overrides already has disable_camera/disable_audio in production
-- (added via manual ALTER on 2026-09-04/05). Only schema.sql for fresh DBs
-- needed the correction. Verify before deploying:
--   wrangler d1 execute labsch-db --remote --command "PRAGMA table_info(client_overrides)"
