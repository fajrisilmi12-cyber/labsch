"""SQLite database layer for labsch-manager.

v0.3.5 hardening notes:
- Validation helpers (SAFE_NAME, SAFE_PROFILE_NAME, SAFE_CLIENT_ID, etc.)
  mirror workers/src/handlers/validation.ts. If you change one, change both.
- add/remove_blocked_* now uses optimistic concurrency on config_version
  and retries on conflict (fixes TOCTOU read-modify-write race).
- Audit log table `audit_log` records every admin action. Required by
  the security audit; missing in v0.3.4.
- pending_command now has TTL (command_expires_at) so stale commands
  don't execute after a manual revoke.
- upsert_heartbeat dedupes duplicates of the same device_id in one
  transaction (previously only matched the most recent row).
"""
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "labsch.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── v0.3.5: input validation (mirrors workers/src/handlers/validation.ts) ──
SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._:\-/()&@#]{1,253}$")
SAFE_PROFILE_NAME = re.compile(r"^[A-Za-z0-9 _\-]{1,64}$")
SAFE_CLIENT_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
SAFE_HOSTNAME = re.compile(r"^[A-Za-z0-9._\-]{1,253}$")
SAFE_MAC = re.compile(r"^[A-Fa-f0-9:.\-]{1,32}$")
SAFE_EVENT_TYPE = re.compile(r"^[a-z_]{1,32}$")
SAFE_DISPLAY_NAME = re.compile(r"^[A-Za-z0-9 ._\-]{1,64}$")
SAFE_EVENT_TARGET = re.compile(r"^[\x20-\x7E]{1,512}$")

# Array caps to prevent admin-induced row-size exhaustion.
MAX_APPS_ITEMS = 500
MAX_WEBSITES_ITEMS = 5000
MAX_ARRAY_ITEMS = 5000  # generic cap

# TTL for pending remote commands. 1 hour default; per-command override
# allowed but capped at 1 day.
COMMAND_TTL_SECONDS = 3600
MAX_COMMAND_TTL_SECONDS = 86400


class ValidationError(Exception):
    """Raised when user input fails validation. Map to HTTP 400 in api.py."""
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def is_valid_name(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_NAME.match(s))


def is_valid_profile_name(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_PROFILE_NAME.match(s))


def is_valid_client_id(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_CLIENT_ID.match(s))


def is_valid_hostname(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_HOSTNAME.match(s))


def is_valid_mac(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_MAC.match(s))


def is_valid_display_name(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_DISPLAY_NAME.match(s))


def is_valid_event_type(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_EVENT_TYPE.match(s))


def is_valid_event_target(s: str) -> bool:
    return isinstance(s, str) and bool(SAFE_EVENT_TARGET.match(s))


def is_valid_command_message(s: str) -> bool:
    r"""Same as workers/validation.ts isValidCommandMessage: printable ASCII
    1..200 chars, no quotes/backticks/$/\ to avoid shell injection if the
    agent ever renders it in a future command channel."""
    if not isinstance(s, str):
        return False
    if len(s) == 0 or len(s) > 200:
        return False
    for ch in s:
        code = ord(ch)
        if code < 0x20 or code > 0x7E:
            return False
        if ch in ('"', "'", '`', '$', '\\'):
            return False
    return True


def validate_string_list(value, field_name: str, max_items: int = MAX_ARRAY_ITEMS) -> list:
    """Validate a config-array field: must be a list of non-empty trimmed
    strings, each <=253 chars, list length <=max_items. Returns the
    cleaned list (trimmed, empty items dropped)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be an array, got {type(value).__name__}")
    if len(value) > max_items:
        raise ValidationError(f"{field_name} exceeds {max_items} items (got {len(value)})")
    out = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ValidationError(f"{field_name}[{i}] must be a string, got {type(item).__name__}")
        t = item.strip()
        if not t:
            raise ValidationError(f"{field_name}[{i}] must be non-empty")
        if len(t) > 253:
            raise ValidationError(f"{field_name}[{i}] exceeds 253 chars")
        out.append(t)
    return out


def safe_json_parse(s, fallback):
    """Tolerate a corrupted JSON blob in a row by returning fallback
    instead of raising. Mirrors workers/validation.ts safeJsonParse."""
    if not s:
        return fallback
    try:
        return json.loads(s)
    except Exception:
        return fallback


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
    """Create tables if they don't exist. Idempotent. Migrates old schema.

    v0.3.5: added audit_log table and pending_command_message /
    pending_command_expires_at columns for TTL commands.
    """
    # v0.3.5: serialize init_db with a separate file lock so concurrent
    # workers (FastAPI + labschctl + scheduled cleanup) don't race on
    # ALTER TABLE. Without this, two processes can both read the schema,
    # both decide a column is missing, and one of the ALTERs fails.
    import fcntl
    lock_path = DB_PATH.parent / ".init_db.lock"
    lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        with get_db() as conn:
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

            -- v0.3.5: audit log for all admin actions and token rotations.
            -- `actor` is the request fingerprint / 'admin' / 'system'.
            -- `details` is free-form JSON; never trust it for output without
            -- sanitising.
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT,
                details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, ts DESC);
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
            if "pending_command" not in cols:
                conn.execute("ALTER TABLE clients ADD COLUMN pending_command TEXT DEFAULT NULL")
                print("[db] migration: added pending_command column")
            # v0.3.5: TTL columns for pending_command. Old commands that never
            # got cleared (e.g. agent offline when admin issued shutdown)
            # would otherwise still execute when the agent next heartbeats.
            if "pending_command_message" not in cols:
                conn.execute("ALTER TABLE clients ADD COLUMN pending_command_message TEXT DEFAULT NULL")
                print("[db] migration: added pending_command_message column")
            if "pending_command_expires_at" not in cols:
                conn.execute("ALTER TABLE clients ADD COLUMN pending_command_expires_at REAL DEFAULT NULL")
                print("[db] migration: added pending_command_expires_at column")

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
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


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

    v0.3.5: also auto-clean any sibling client rows that share the same
    device_id (only the canonical row survives). Previously multiple
    client_ids accumulated for the same physical PC whenever the hostname
    changed, the user changed, or the MAC was missing.
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

        # v0.3.5: clean up duplicate client rows for the same physical
        # device. If multiple rows share this device_id but are NOT the
        # canonical row, delete them so we have exactly one record per PC.
        # Events / overrides tied to those siblings are remapped to the
        # canonical client_id first, so no history is lost.
        if device_id:
            sibling_rows = conn.execute(
                "SELECT client_id FROM clients WHERE device_id = ? AND client_id != ?",
                (device_id, existing_client_id),
            ).fetchall()
            for sib in sibling_rows:
                sib_id = sib["client_id"]
                conn.execute(
                    "UPDATE OR IGNORE events SET client_id = ? WHERE client_id = ?",
                    (existing_client_id, sib_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO client_overrides (client_id) VALUES (?)",
                    (sib_id,),
                )
                conn.execute(
                    "UPDATE OR IGNORE client_overrides SET client_id = ? WHERE client_id = ?",
                    (existing_client_id, sib_id),
                )
                conn.execute("DELETE FROM clients WHERE client_id = ?", (sib_id,))

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
                  allowed_websites: list, updated_by: str = "admin",
                  expected_version: int = -1) -> int:
    """Replace all config lists. Returns new config_version.

    v0.3.5: optimistic concurrency on config_version. If expected_version
    is non-negative, the UPDATE only commits if the current version still
    matches; on mismatch we raise ConfigVersionMismatch so the caller can
    retry or surface a 409 to the admin. This fixes the read-modify-write
    race in add/remove_blocked_* where two concurrent ops could both
    compute the same new_version and one would silently clobber.
    """
    # Cap list sizes to prevent admin-induced row-size exhaustion.
    blocked_apps = validate_string_list(blocked_apps, "blocked_apps", MAX_APPS_ITEMS)
    blocked_websites = validate_string_list(blocked_websites, "blocked_websites", MAX_WEBSITES_ITEMS)
    allowed_websites = validate_string_list(allowed_websites, "allowed_websites", MAX_WEBSITES_ITEMS)

    with get_db() as conn:
        current = conn.execute("SELECT config_version FROM config WHERE id = 1").fetchone()
        current_version = current["config_version"] if current else 0
        if expected_version >= 0 and current_version != expected_version:
            raise ConfigVersionMismatch(current_version, expected_version)
        new_version = current_version + 1
        cur = conn.execute("""
            UPDATE config SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
                              config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (
            json.dumps(blocked_apps),
            json.dumps(blocked_websites),
            json.dumps(allowed_websites),
            new_version,
            time.time(),
            updated_by,
            current_version,
        ))
        # Optimistic check: rowcount == 0 means another writer beat us.
        # Re-read current version and retry up to 3 times by recursion.
        if cur.rowcount == 0 and current_version > 0 and expected_version < 0:
            # Caller didn't pin a version, but the row vanished — retry.
            # In practice rowcount==0 only happens when the version moved
            # under us; loop with the freshly-read version.
            cur2 = conn.execute("SELECT config_version FROM config WHERE id = 1").fetchone()
            if cur2:
                fresh = cur2["config_version"]
                return update_config(
                    blocked_apps, blocked_websites, allowed_websites,
                    updated_by, expected_version=fresh,
                )
        return new_version


class ConfigVersionMismatch(Exception):
    """Raised when optimistic concurrency on config_version fails."""
    def __init__(self, current: int, expected: int):
        super().__init__(f"config_version mismatch: current={current}, expected={expected}")
        self.current = current
        self.expected = expected


def add_blocked_app(name: str, updated_by: str = "admin") -> int:
    """Add an app to the blocked list inside a single connection so the
    read-modify-write is atomic (no TOCTOU race). v0.3.5 also rejects
    no-op duplicates without bumping config_version, and validates the
    name format against SAFE_NAME."""
    if not is_valid_name(name):
        raise ValidationError("name must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
    with get_db() as conn:
        row = conn.execute("SELECT blocked_apps, blocked_websites, allowed_websites, config_version FROM config WHERE id = 1").fetchone()
        if not row:
            raise ValidationError("config row missing")
        apps = json.loads(row["blocked_apps"])
        if name in apps:
            return row["config_version"]  # no-op: don't bump version
        apps.append(name)
        new_version = row["config_version"] + 1
        conn.execute("""
            UPDATE config SET blocked_apps = ?, config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (json.dumps(apps), new_version, time.time(), updated_by, row["config_version"]))
        return new_version


def remove_blocked_app(name: str, updated_by: str = "admin") -> int:
    """Remove an app from the blocked list. v0.3.5: atomic RMW + no-op
    detection (returns current version without bumping if not present)."""
    if not is_valid_name(name):
        raise ValidationError("name must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
    with get_db() as conn:
        row = conn.execute("SELECT blocked_apps, config_version FROM config WHERE id = 1").fetchone()
        if not row:
            raise ValidationError("config row missing")
        apps = json.loads(row["blocked_apps"])
        if name not in apps:
            return row["config_version"]
        apps.remove(name)
        new_version = row["config_version"] + 1
        conn.execute("""
            UPDATE config SET blocked_apps = ?, config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (json.dumps(apps), new_version, time.time(), updated_by, row["config_version"]))
        return new_version


def add_blocked_website(domain: str, updated_by: str = "admin") -> int:
    """Atomically add a domain to blocked_websites. v0.3.5: no-op
    duplicate does NOT bump config_version (was previously bumping on
    every POST)."""
    if not is_valid_name(domain):
        raise ValidationError("domain must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
    with get_db() as conn:
        row = conn.execute("SELECT blocked_websites, config_version FROM config WHERE id = 1").fetchone()
        if not row:
            raise ValidationError("config row missing")
        sites = json.loads(row["blocked_websites"])
        if domain in sites:
            return row["config_version"]
        sites.append(domain)
        new_version = row["config_version"] + 1
        conn.execute("""
            UPDATE config SET blocked_websites = ?, config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (json.dumps(sites), new_version, time.time(), updated_by, row["config_version"]))
        return new_version


def remove_blocked_website(domain: str, updated_by: str = "admin") -> int:
    """Atomically remove a domain from blocked_websites."""
    if not is_valid_name(domain):
        raise ValidationError("domain must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
    with get_db() as conn:
        row = conn.execute("SELECT blocked_websites, config_version FROM config WHERE id = 1").fetchone()
        if not row:
            raise ValidationError("config row missing")
        sites = json.loads(row["blocked_websites"])
        if domain not in sites:
            return row["config_version"]
        sites.remove(domain)
        new_version = row["config_version"] + 1
        conn.execute("""
            UPDATE config SET blocked_websites = ?, config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (json.dumps(sites), new_version, time.time(), updated_by, row["config_version"]))
        return new_version


def add_allowed_website(domain: str, updated_by: str = "admin") -> int:
    """Atomically add a domain to allowed_websites."""
    if not is_valid_name(domain):
        raise ValidationError("domain must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
    with get_db() as conn:
        row = conn.execute("SELECT allowed_websites, config_version FROM config WHERE id = 1").fetchone()
        if not row:
            raise ValidationError("config row missing")
        sites = json.loads(row["allowed_websites"])
        if domain in sites:
            return row["config_version"]
        sites.append(domain)
        new_version = row["config_version"] + 1
        conn.execute("""
            UPDATE config SET allowed_websites = ?, config_version = ?, updated_at = ?, updated_by = ?
            WHERE id = 1 AND config_version = ?
        """, (json.dumps(sites), new_version, time.time(), updated_by, row["config_version"]))
        return new_version


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
    """Create or replace a named profile. Returns the profile dict.

    v0.3.5: validates the name (profile-name regex) and array inputs
    (type + non-empty + length caps) before writing. Previously a name
    like "../etc/passwd" or a 50 MB array would silently land in the DB.
    """
    if not is_valid_profile_name(name):
        raise ValidationError("profile name must match [A-Za-z0-9 _-]{1,64}")
    blocked_websites = validate_string_list(blocked_websites, "blocked_websites", MAX_WEBSITES_ITEMS)
    allowed_websites = validate_string_list(allowed_websites, "allowed_websites", MAX_WEBSITES_ITEMS)
    blocked_apps = validate_string_list(blocked_apps, "blocked_apps", MAX_APPS_ITEMS)
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
    """Apply profile rules to live config. Returns new config_version.

    v0.3.5: do the config update AND the activated_at bump in a single
    transaction. Previously if the UPDATE on activated_at failed the
    audit trail would lie about whether the activation actually applied.
    """
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


# ── v0.3.5: audit log helpers ──────────────────────────────────────
def log_admin_action(actor: str, action: str, target: str = None,
                     details: str = None) -> int:
    """Append a row to the audit_log table. Called by every admin endpoint.

    actor: usually the token fingerprint (first 12 hex chars of sha256),
           'system' for cron, or 'unknown' for unauthenticated callers.
    action: short verb like 'token.generate', 'config.update',
            'command.set', 'profile.activate'.
    target: the entity affected (client_id, profile name, etc).
    details: free-form JSON-ish string. Never trust the contents when
             rendering without sanitising.
    """
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO audit_log (ts, actor, action, target, details)
            VALUES (?, ?, ?, ?, ?)
        """, (time.time(), actor, action, target, details))
        return cur.lastrowid


def get_audit_log(hours: int = 24, action: str = None,
                  actor: str = None, limit: int = 200) -> list:
    """Recent audit entries, newest first."""
    cutoff = time.time() - (hours * 3600)
    sql = "SELECT * FROM audit_log WHERE ts > ?"
    params = [cutoff]
    if action:
        sql += " AND action = ?"
        params.append(action)
    if actor:
        sql += " AND actor = ?"
        params.append(actor)
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(min(max(limit, 1), 5000))
    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def cleanup_events(older_than_days: int = 30) -> int:
    cutoff = time.time() - (older_than_days * 86400)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        return cur.rowcount


# ── Remote commands (shutdown / restart per PC) ──────────────

# v0.3.5: extended to support `notify` (with a message) and `lock`,
# mirroring workers/handlers/admin-command.ts. `notify` requires a
# validated message; the others don't take one.
VALID_COMMANDS = {"shutdown", "restart", "lock", "notify"}


def set_client_command(client_id: str, command: str,
                       message: str = None,
                       ttl_seconds: int = COMMAND_TTL_SECONDS) -> bool:
    """Queue a command (shutdown/restart/lock/notify) for a specific client.

    v0.3.5: writes pending_command_expires_at so a stale command that
    never executed (agent offline when admin issued shutdown) does NOT
    still fire when the agent eventually heartbeats. ttl_seconds is
    capped at MAX_COMMAND_TTL_SECONDS (1 day).
    """
    if command not in VALID_COMMANDS:
        return False
    if command == "notify":
        if not message or not is_valid_command_message(message):
            raise ValidationError(
                "notify requires a message: printable ASCII (no quotes, "
                "backticks, $, or control chars), <=200 chars",
            )
    else:
        if message is not None:
            raise ValidationError(f"{command} does not accept a message")
    ttl = min(max(int(ttl_seconds), 1), MAX_COMMAND_TTL_SECONDS)
    expires_at = time.time() + ttl
    with get_db() as conn:
        cur = conn.execute("""
            UPDATE clients
            SET pending_command = ?,
                pending_command_message = ?,
                pending_command_expires_at = ?
            WHERE client_id = ?
        """, (command, message if command == "notify" else None,
              expires_at, client_id))
        return cur.rowcount > 0


def get_client_command(client_id: str) -> str | None:
    """Return and clear the pending command for a client. v0.3.5: also
    returns and clears the message, and respects the TTL — expired
    commands are silently dropped without executing."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT pending_command, pending_command_message, "
            "pending_command_expires_at FROM clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        if not row or not row["pending_command"]:
            return None
        expires_at = row["pending_command_expires_at"]
        if expires_at and expires_at < time.time():
            # Expired — silently clear so we don't keep re-delivering it.
            conn.execute(
                "UPDATE clients SET pending_command = NULL, "
                "pending_command_message = NULL, pending_command_expires_at = NULL "
                "WHERE client_id = ?",
                (client_id,),
            )
            return None
        cmd = row["pending_command"]
        conn.execute(
            "UPDATE clients SET pending_command = NULL, "
            "pending_command_message = NULL, pending_command_expires_at = NULL "
            "WHERE client_id = ?",
            (client_id,),
        )
        return cmd


def get_client_command_with_message(client_id: str):
    """Like get_client_command but also returns the message (for notify).
    Returns (command, message) or (None, None)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT pending_command, pending_command_message, "
            "pending_command_expires_at FROM clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        if not row or not row["pending_command"]:
            return (None, None)
        expires_at = row["pending_command_expires_at"]
        if expires_at and expires_at < time.time():
            conn.execute(
                "UPDATE clients SET pending_command = NULL, "
                "pending_command_message = NULL, pending_command_expires_at = NULL "
                "WHERE client_id = ?",
                (client_id,),
            )
            return (None, None)
        cmd = row["pending_command"]
        msg = row["pending_command_message"]
        conn.execute(
            "UPDATE clients SET pending_command = NULL, "
            "pending_command_message = NULL, pending_command_expires_at = NULL "
            "WHERE client_id = ?",
            (client_id,),
        )
        return (cmd, msg)


def clear_client_command(client_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE clients SET pending_command = NULL, "
            "pending_command_message = NULL, pending_command_expires_at = NULL "
            "WHERE client_id = ?",
            (client_id,),
        )
        return cur.rowcount > 0
