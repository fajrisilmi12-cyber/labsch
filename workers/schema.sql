-- LabSCH D1 schema (migrated from server/db.py SQLite)
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip TEXT,
    user TEXT,
    version TEXT,
    last_seen REAL,
    first_seen REAL,
    status TEXT DEFAULT 'offline',
    device_id TEXT,
    mac TEXT,
    display_name TEXT DEFAULT '',
    is_test INTEGER DEFAULT 0,
    pending_command TEXT DEFAULT NULL,
    pending_command_message TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_clients_device ON clients(device_id);
CREATE INDEX IF NOT EXISTS idx_clients_mac ON clients(mac);
CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status, last_seen DESC);

CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    config_version INTEGER NOT NULL DEFAULT 0,
    updated_at REAL,
    updated_by TEXT
);

INSERT OR IGNORE INTO config (id, blocked_apps, blocked_websites, allowed_websites, config_version)
VALUES (1, '[]', '[]', '[]', 0);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT,
    event_type TEXT,
    target TEXT,
    timestamp REAL,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_client ON events(client_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    activated_at REAL
);

CREATE TABLE IF NOT EXISTS client_overrides (
    client_id TEXT PRIMARY KEY,
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    updated_by TEXT DEFAULT 'admin'
);
