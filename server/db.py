"""SQLite database layer for labsch-manager."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "labsch.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_db():
    """Context manager for SQLite connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist. Idempotent. Migrates old schema."""
    with get_db() as conn:
        # 1. Create table WITHOUT device_id/mac first (compatible with old schema)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            client_id TEXT PRIMARY KEY,
            hostname TEXT,
            ip TEXT,
            user TEXT,
            version TEXT,
            last_seen REAL,
            first_seen REAL,
            status TEXT DEFAULT 'offline'
        );

        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            blocked_apps TEXT NOT NULL DEFAULT '[]',
            blocked_websites TEXT NOT NULL DEFAULT '[]',
            allowed_websites TEXT NOT NULL DEFAULT '[]',
            config_version INTEGER NOT NULL DEFAULT 0,
            updated_at REAL,
            updated_by TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id TEXT,
            event_type TEXT,
            target TEXT,
            timestamp REAL,
            details TEXT
        );

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

        CREATE TABLE IF NOT EXISTS active_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_id INTEGER,
            FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE SET NULL
        );
        """)

        # 2. Migration: add device_id, mac, display_name, is_test columns if missing
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(clients)").fetchall()]
        if "device_id" not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN device_id TEXT")
            print("[db] migration: added device_id column")
        if "mac" not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN mac TEXT")
            print("[db] migration: added mac column")
        if "display_name" not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN display_name TEXT DEFAULT ''")
            print("[db] migration: added display_name column")
        if "is_test" not in cols:
            conn.execute("ALTER TABLE clients ADD COLUMN is_test INTEGER DEFAULT 0")
            print("[db] migration: added is_test column")

        # 3. Indexes
        conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_clients_device ON clients(device_id);
        CREATE INDEX IF NOT EXISTS idx_clients_mac ON clients(mac);
        CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_events_client ON events(client_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status, last_seen DESC);

        INSERT OR IGNORE INTO config (id, blocked_apps, blocked_websites, allowed_websites, config_version)
        VALUES (1, '[]', '[]', '[]', 0);
        """)


# Client operations
def get_canonical_client_id(client_id: str, device_id: str = None) -> str:
    """Resolve the stored client ID after device-based de-duplication."""
    with get_db() as conn:
        if device_id:
            row = conn.execute("SELECT client_id FROM clients WHERE device_id = ? ORDER BY last_seen DESC LIMIT 1", (device_id,)).fetchone()
            if row:
                return row["client_id"]
        return client_id


def upsert_heartbeat(client_id: str, hostname: str, ip: str, user: str, version: str,
                     device_id: str = None, mac: str = None,
                     display_name: str = None, is_test: bool = None) -> dict:
    """Update or insert client heartbeat. De-dup by device_id if provided.

    Returns current config.
    """
    now = time.time()
    with get_db() as conn:
        existing_client_id = client_id

        # De-dup: if device_id given, prefer existing client by device_id
        if device_id:
            row = conn.execute(
                "SELECT client_id FROM clients WHERE device_id = ? AND client_id != ?",
                (device_id, client_id)
            ).fetchone()
            if row:
                existing_client_id = row["client_id"]
                print(f"[db] de-dup: device {device_id[:16]}... -> {existing_client_id}")

        # Build update query
        if display_name is not None and is_test is not None:
            sql = """UPDATE clients SET hostname = ?, ip = ?, user = ?, version = ?,
                     last_seen = ?, status = 'online',
                     device_id = COALESCE(?, device_id),
                     mac = COALESCE(?, mac),
                     display_name = COALESCE(NULLIF(?, ''), display_name),
                     is_test = COALESCE(?, is_test)
                     WHERE client_id = ?"""
            params = (hostname, ip, user, version, now, device_id, mac,
                      display_name, int(bool(is_test)), existing_client_id)
        else:
            sql = """UPDATE clients SET hostname = ?, ip = ?, user = ?, version = ?,
                     last_seen = ?, status = 'online',
                     device_id = COALESCE(?, device_id),
                     mac = COALESCE(?, mac)
                     WHERE client_id = ?"""
            params = (hostname, ip, user, version, now, device_id, mac, existing_client_id)

        existing = conn.execute("SELECT * FROM clients WHERE client_id = ?", (existing_client_id,)).fetchone()
        if existing:
            conn.execute(sql, params)
        else:
            if display_name is not None and is_test is not None:
                conn.execute("""
                    INSERT INTO clients (client_id, device_id, mac, hostname, ip, user, version,
                                         first_seen, last_seen, status, display_name, is_test)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)
                """, (existing_client_id, device_id, mac, hostname, ip, user, version,
                      now, now, display_name or "", int(bool(is_test))))
            else:
                conn.execute("""
                    INSERT INTO clients (client_id, device_id, mac, hostname, ip, user, version,
                                         first_seen, last_seen, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online')
                """, (existing_client_id, device_id, mac, hostname, ip, user, version, now, now))

        cfg = conn.execute("SELECT * FROM config WHERE id = 1").fetchone()
        d = dict(cfg)
        d["blocked_apps"] = json.loads(d["blocked_apps"])
        d["blocked_websites"] = json.loads(d["blocked_websites"])
        d["allowed_websites"] = json.loads(d["allowed_websites"])
        return d


def get_clients() -> list:
    """List all clients."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM clients ORDER BY hostname").fetchall()
        return [dict(r) for r in rows]


def get_client(client_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE client_id = ?", (client_id,)).fetchone()
        return dict(row) if row else None


def mark_stale_clients(threshold_seconds: int = 90) -> int:
    """Mark clients as offline if last_seen > threshold."""
    now = time.time()
    cutoff = now - threshold_seconds
    with get_db() as conn:
        cur = conn.execute("""
            UPDATE clients SET status = 'offline'
            WHERE status = 'online' AND last_seen < ?
        """, (cutoff,))
        return cur.rowcount


# Config operations
def get_config() -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM config WHERE id = 1").fetchone()
        if not row:
            return {}
        d = dict(row)
        d["blocked_apps"] = json.loads(d["blocked_apps"])
        d["blocked_websites"] = json.loads(d["blocked_websites"])
        d["allowed_websites"] = json.loads(d["allowed_websites"])
        return d


def update_config(blocked_apps: list, blocked_websites: list,
                  allowed_websites: list, updated_by: str = "admin") -> int:
    """Replace all config lists. Returns new config_version."""
    with get_db() as conn:
        new_version = (conn.execute("SELECT config_version FROM config WHERE id = 1").fetchone()[0]) + 1
        conn.execute("""
            UPDATE config SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
                              config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1
        """, (
            json.dumps(blocked_apps),
            json.dumps(blocked_websites),
            json.dumps(allowed_websites),
            new_version,
            time.time(),
            updated_by,
        ))
        return new_version


def add_blocked_app(name: str, updated_by: str = "admin") -> int:
    cfg = get_config()
    if name in cfg["blocked_apps"]:
        return cfg["config_version"]
    cfg["blocked_apps"].append(name)
    return update_config(cfg["blocked_apps"], cfg["blocked_websites"],
                         cfg["allowed_websites"], updated_by)


def remove_blocked_app(name: str, updated_by: str = "admin") -> int:
    cfg = get_config()
    if name not in cfg["blocked_apps"]:
        return cfg["config_version"]
    cfg["blocked_apps"].remove(name)
    return update_config(cfg["blocked_apps"], cfg["blocked_websites"],
                         cfg["allowed_websites"], updated_by)


def add_blocked_website(domain: str, updated_by: str = "admin") -> int:
    cfg = get_config()
    if domain in cfg["blocked_websites"]:
        return cfg["config_version"]
    cfg["blocked_websites"].append(domain)
    return update_config(cfg["blocked_apps"], cfg["blocked_websites"],
                         cfg["allowed_websites"], updated_by)


def remove_blocked_website(domain: str, updated_by: str = "admin") -> int:
    cfg = get_config()
    if domain not in cfg["blocked_websites"]:
        return cfg["config_version"]
    cfg["blocked_websites"].remove(domain)
    return update_config(cfg["blocked_apps"], cfg["blocked_websites"],
                         cfg["allowed_websites"], updated_by)


def add_allowed_website(domain: str, updated_by: str = "admin") -> int:
    cfg = get_config()
    if domain in cfg["allowed_websites"]:
        return cfg["config_version"]
    cfg["allowed_websites"].append(domain)
    return update_config(cfg["blocked_apps"], cfg["blocked_websites"],
                         cfg["allowed_websites"], updated_by)


# Event operations
def log_event(client_id: str, event_type: str, target: str, details: str = None) -> int:
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO events (client_id, event_type, target, timestamp, details)
            VALUES (?, ?, ?, ?, ?)
        """, (client_id, event_type, target, time.time(), details))
        return cur.lastrowid


def get_events(hours: int = 24, client_id: str = None,
               event_type: str = None, limit: int = 500) -> list:
    cutoff = time.time() - (hours * 3600)
    sql = "SELECT * FROM events WHERE timestamp > ?"
    params = [cutoff]
    if client_id:
        sql += " AND client_id = ?"
        params.append(client_id)
    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


# Profile operations
def create_profile(name: str, blocked_websites: list, allowed_websites: list,
                   blocked_apps: list) -> dict:
    """Create or replace a named profile. Returns the profile dict."""
    now = time.time()
    with get_db() as conn:
        # Upsert by name
        existing = conn.execute("SELECT id FROM profiles WHERE name = ?", (name,)).fetchone()
        if existing:
            conn.execute("""
                UPDATE profiles
                SET blocked_websites = ?, allowed_websites = ?, blocked_apps = ?
                WHERE name = ?
            """, (json.dumps(blocked_websites), json.dumps(allowed_websites),
                  json.dumps(blocked_apps), name))
            pid = existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO profiles (name, blocked_websites, allowed_websites, blocked_apps, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (name, json.dumps(blocked_websites), json.dumps(allowed_websites),
                  json.dumps(blocked_apps), now))
            pid = cur.lastrowid
        return get_profile(pid)


def get_profile(profile_id: int = None, name: str = None) -> dict:
    """Get a profile by ID or name. Returns dict with parsed JSON lists."""
    with get_db() as conn:
        if profile_id is not None:
            row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        elif name:
            row = conn.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
        else:
            return None
        if not row:
            return None
        d = dict(row)
        d["blocked_websites"] = json.loads(d["blocked_websites"])
        d["allowed_websites"] = json.loads(d["allowed_websites"])
        d["blocked_apps"] = json.loads(d["blocked_apps"])
        return d


# Per-client override operations
def get_client_override(client_id: str) -> dict | None:
    """Return override with parsed lists, or None when inheriting global."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM client_overrides WHERE client_id = ?", (client_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    for key in ("blocked_websites", "allowed_websites", "blocked_apps"):
        result[key] = json.loads(result[key])
    return result


def set_client_override(client_id: str, blocked_websites: list,
                        allowed_websites: list, blocked_apps: list,
                        updated_by: str = "admin") -> dict:
    """Replace one client's complete override configuration."""
    now = time.time()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO client_overrides
                (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                blocked_websites=excluded.blocked_websites,
                allowed_websites=excluded.allowed_websites,
                blocked_apps=excluded.blocked_apps,
                updated_at=excluded.updated_at,
                updated_by=excluded.updated_by
        """, (client_id, json.dumps(blocked_websites), json.dumps(allowed_websites),
              json.dumps(blocked_apps), now, updated_by))
    return get_client_override(client_id)


def clear_client_override(client_id: str) -> bool:
    """Remove override; client inherits global config."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM client_overrides WHERE client_id = ?", (client_id,))
    return cur.rowcount > 0



def list_profiles() -> list:
    """List all profiles."""
    with get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM profiles ORDER BY name").fetchall()]


def delete_profile(name: str) -> bool:
    """Delete a profile by name. Returns True if existed."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM profiles WHERE name = ?", (name,))
        return cur.rowcount > 0


def activate_profile(name: str) -> int:
    """Apply profile rules to live config. Returns new config_version."""
    profile = get_profile(name=name)
    if not profile:
        return None
    new_version = update_config(
        profile["blocked_apps"],
        profile["blocked_websites"],
        profile["allowed_websites"],
        updated_by=f"profile:{name}",
    )
    with get_db() as conn:
        conn.execute("UPDATE profiles SET activated_at = ? WHERE name = ?",
                     (time.time(), name))
    return new_version


def cleanup_events(older_than_days: int = 30) -> int:
    cutoff = time.time() - (older_than_days * 86400)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        return cur.rowcount
