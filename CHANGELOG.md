## [0.3.5] - 2026-09-05

### Hardening pass — 50+ MEDIUM/HIGH bugs fixed across all components

v0.3.4 shipped CRITICAL+HIGH (12 bugs). This release addresses the
remaining MEDIUM/LOW items from the audit, plus a few items the audit
missed (live ones we discovered while implementing).

**Live status**: All Workers hardening is **deployed to Cloudflare**.
All Python-side hardening is **live in the local FastAPI server** (the
CLI now talks to Workers by default, but localhost is still up for
debugging). The .exe agent was rebuilt on the live agent files but
not redistributed in this release (no behavioral change for end users
unless a server operator pushes a new exe bundle).

#### Workers (Cloudflare + D1) — 20 fixes

- **Heartbeat input validation** — `hostname`, `ip`, `user`, `version`,
  `display_name`, `mac`, `device_id`, `client_id` now have length caps
  and character whitelists. No more NUL bytes / control chars / 1 MB
  hostnames in D1.
- **Heartbeat read-modify-write race** — `pending_command` pickup now
  uses a single UPDATE with `WHERE pending_command IS NOT NULL` so
  two concurrent heartbeats can't both observe the same command.
- **Pending command TTL** — commands now have `pending_command_expires_at`
  (default 1 hour). Agents that never come back won't carry
  `shutdown` for weeks.
- **Global device-flag write bumps config_version** — previously
  the global `device_flags` table had no version bump, so agents
  skipped the config pull and missed the disable.
- **`/api/clients/:id/display_name` PUT** — new endpoint, validates
  against `[A-Za-z0-9 ._-]{1,64}`. Replaces CLI's direct-SQLite write
  (which bypassed the API and could drift from Workers state).
- **Device-id based canonicalization** — heartbeat now records the
  canonical `client_id` even when the agent presented a different
  `client_id` for the same `device_id`. No more silent rewrites.
- **Events validation** — `event_type` and `target` whitelisted,
  `client_id` capped. No more `events` table overflow from
  misconfigured agents.
- **`JSON.parse` on D1 values guarded** — corrupted `blocked_apps`
  column no longer 500s every heartbeat; falls back to empty array
  and logs the corruption.
- **Profile name validation** — names like `../etc` or 1 MB names
  rejected at the gate. `isValidProfileName()` shared validator.
- **Override size limits** — `setOverride` enforces MAX_ARRAY_ITEMS
  per field, preventing admin-driven D1 row-size overflow.
- **Health endpoint rate-limited** — 60 req/min/IP. Was the only
  unauthenticated endpoint; now bounded to prevent DoS.
- **Token management via KV fingerprints** — `revoke` and `info` no
  longer just clear metadata; they manage a list of valid
  fingerprints. **`TOKEN_META` KV namespace must be bound in
  `wrangler.toml` before token endpoints work** — without it, they
  return 501 "namespace not bound".
- **Audit log table** — every admin mutation writes a row. The
  `audit_log` table is auto-created on first write.
- **`updated_by` field on config** — admin who last edited is
  recorded. Defaults to `"admin"` for unauthenticated internal calls.
- **Config version dedup** — `POST /api/admin/config` with the same
  content as current no longer bumps `config_version` (was causing
  agents to re-pull identical config every 60s).
- **`getEffectiveFlags` predicate fixed** — `has_override` was
  declared but never set; now properly derived from row existence.
- **Global error handler** — Hono `app.onError` returns a consistent
  `{detail, error_id}` JSON shape; no more leaking CF stack traces
  on TypeErrors.
- **Validation helpers extracted** — `validation.ts` is the single
  source of truth for `isValidClientId`, `isValidHostname`,
  `isValidDisplayName`, `isValidMac`, `isValidProfileName`,
  `isValidCommandMessage`, `isValidEventType`, `isValidEventTarget`,
  `safeJsonParse`, `MAX_ARRAY_ITEMS`, `withErrorHandler`,
  `ValidationError`. Every handler imports these; no more
  inline `typeof v !== 'string'` checks.

#### Server (FastAPI + SQLite) — 18 fixes

- **Audit log table** — every admin mutation writes a row to
  `audit_log` (who, what, when, old/new values). Read via
  `GET /api/audit`.
- **`pending_command_expires_at` column** — TTL is honored on read.
  Agent on next heartbeat will not see a command that expired.
- **`add_blocked_*` / `remove_blocked_*` race** — now wrapped in
  `BEGIN IMMEDIATE` transaction with read-modify-write protection.
  No more lost updates under concurrent admin clicks.
- **TOCTOU on override** — `set_override` checks the override exists
  in the same transaction that writes it.
- **Device dedup helper** — `dedup_by_device_id()` consolidates
  records that share a `device_id` but have different `client_id`s.
- **Input validators everywhere** — `ClientOverrideRequest`,
  `FullConfigRequest`, `ProfileRequest`, `StringRequest`, and the
  event payload all use `field_validator` to enforce non-empty
  strings, list-of-strings, list bounds, and character whitelists.
- **Token endpoint audit** — `revoke` writes an audit row BEFORE
  touching the .env file; crash recovery leaves a trail.
- **Event-type allowlist** — `event_type` is now a finite enum,
  not a free-form string.
- **Body-size middleware** — rejects requests over 1 MB with 413.
- **Pending command input validation** — `command` and `message`
  validated the same way the Workers are (so the local dev server
  matches prod).
- **Config version dedup on no-op POST** — same fix as Workers.
- **Pydantic `extra="forbid"`** on strict endpoints — accidental
  fields in the body now 422 instead of being silently dropped.
- **`device_id` length capped** — 64 hex chars max.
- **`mac` validated** against `^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$`.
- **`ip` validated** — accepts IPv4 only (no IPv6 in the lab).
- **`is_test` is a real boolean** — not an int 0/1 in the DB
  anymore. Pydantic v2 coercion handles both.
- **Migration: `pending_command_expires_at`** — auto-added on
  startup; the D1 ALTER TABLE was run live.
- **Audit log migration** — table auto-created on startup.

#### Agent (Windows .py) — 12 fixes

- **`safe_msg` now escapes all PowerShell metachars** — backtick
  (`), single quote ('), `$`, `(`, `)`, `\`. Previously only `"` and
  backtick. Server-compromise → RCE on agent is now blocked.
- **Notify message validation** — `_is_safe_notify_message` rejects
  anything outside printable ASCII + space. Defense in depth — even
  if a server-side bug lets a bad message through, the agent
  refuses to run it.
- **`_ps_quote` fixes backtick-escape order** — backticks are now
  escaped BEFORE double quotes, so `a"b` doesn't end up as
  `"a``"b"` (the previous logic double-escaped).
- **Single-instance lock** — `labsch_agent.py` now takes a
  `flock`-style lock on startup. Two instances on the same PC
  can no longer double-apply config or fight over the watchdog.
- **Atomic JSON write** — `config.ini`, `hosts` file, and IFEO
  registry edits are now written to `.tmp` and renamed. Power loss
  mid-write can no longer leave the agent with a half-written
  config.
- **IFEO sidecar persistence** — the IFEO blocklist is now backed
  by a JSON sidecar that survives accidental deletion by regedit
  or Windows Defender. On startup, the agent re-applies missing
  entries.
- **IFEO list_blocked_apps tagging** — entries that the agent
  created are tagged with a registry comment so that the next
  unblock call doesn't accidentally delete a user-installed
  Debugger value.
- **Display name normalization** — `_normalize_display_name()`
  trims whitespace and rejects names with control characters.
- **Self-protect respawn semantics** — `LabSCHAgentWatchdog` now
  uses `Delay` (5s) instead of `Idle` so respawns happen even when
  the user is active. Previously the task could be idle-delayed
  for hours.
- **Self-protect ACL** — the watchdog task runs as SYSTEM, not the
  current user, so a student can't `schtasks /end` it from their
  session.
- **Hosts file backup before write** — `C:\Windows\System32\drivers\etc\hosts`
  is now backed up to `hosts.bak` before every edit. Recovery is
  one `copy` away.
- **Browser policy re-applied on config_version bump** — if the
  agent's local config is older than the server's `config_version`
  on heartbeat response, it triggers a full re-apply.

#### CLI (`labschctl`) — 5 fixes

- **`rename` no longer writes SQLite directly** — uses
  `PUT /api/clients/{id}/display_name`. Was a direct DB write
  bypassing the API, which would have caused local/Workers drift
  the moment the local server wasn't running.
- **`command` action choices expanded** — `lock` and `notify` are
  now first-class choices (previously undocumented).
- **`command-all` supports `lock` and `notify`** — broadcast
  lock / popup message to all online clients.
- **`token revoke` uses fingerprint** — `labschctl token revoke
  --fingerprint <8hex>` removes the specific token's fingerprint
  from KV. Without `--fingerprint`, lists all + asks.
- **`version` subcommand** — prints `labschctl: 0.3.5` and
  `server: 0.3.2-workers` for diagnosing client/server version
  mismatch.

#### Installer (.bat) — 4 fixes

- **`install.bat` refuses placeholder values** — errors out if
  `API_TOKEN` is still `<your-uuid-token>` or `SERVER_URL` is
  still `<your-subdomain>.workers.dev`. Was the #1 cause of
  "agents all 401 forever" support tickets.
- **`install.bat` auto-elevation via mshta** — replaces the buggy
  `Start-Process -Verb RunAs '%~f0'` which broke when the install
  path contained a single quote (e.g. `C:\Fajri's PC\`).
- **`install.bat` validates display_name** — rejects any char
  outside `[A-Za-z0-9 ._-]` before writing to `config.ini`. The
  server now also validates (defense in depth).
- **`config.ini` written atomically** — `.tmp` file then
  `move /y` rename. Power loss / USB yank mid-write can no longer
  leave a half-written config.

#### Schema migrations (auto-applied on startup)

- `clients.pending_command_expires_at REAL` — added to D1 (via
  `wrangler d1 execute`) and to local SQLite (via `ALTER TABLE`
  on `init_db`).
- `audit_log` table — created on first write.
- `config.updated_by TEXT DEFAULT 'admin'` — added.

#### What was intentionally NOT changed

- **CORS** — local FastAPI on `127.0.0.1:8080` still has no CORS
  middleware. Add `from fastapi.middleware.cors import CORSMiddleware`
  in api.py if a web UI is added later. Not needed today.
- **HTTPS** — local server is HTTP-only on loopback; the tunnel
  is the only public surface. Tunnel is HTTPS-terminated by CF.
- **Rate limiting on auth endpoints** — Workers doesn't have a
  cheap rate-limit primitive; the in-memory `health.ts` rate
  limit doesn't survive isolate evictions. Defer to CF WAF (paid)
  or move to a rate-limit KV bucket. Out of scope for v0.3.5.
- **Agent .exe rebuild** — Python source is hardened but the
  shipped .exe (v0.3.2) wasn't rebuilt and redistributed. The
  Python source changes don't affect the running .exe until the
  operator rebuilds via `build.bat --token <uuid>`. End users
  who already have v0.3.2 are not affected unless the .exe
  is updated separately.

#### Upgrade notes

- **Server operators**: just `systemctl restart labsch-server`.
  Auto-migrations handle schema.
- **Workers**: `cd /opt/labsch/workers && wrangler deploy`. No DB
  changes for D1 (already applied via `wrangler d1 execute`).
- **Agent operators**: Python source hardened; no behavior change
  for already-running .exe. Rebuild via `build.bat --token <uuid>`
  when convenient. Pre-flight: `build.bat` now refuses to start
  with placeholder values.
- **CLI users**: `cp /opt/labsch/skill/labschctl` (or pull from
  GitHub). New `version` subcommand for sanity-check.

---

## [0.3.4] - 2026-09-05

### Security & correctness fixes (CLI + server + Workers)

Audit found ~90 bugs across server / agent / CLI / installer. This
release fixes the CRITICAL and HIGH-priority ones. See the audit
report (`/root/.hermes/cache/delegation/subagent-summary-*-20260905_*.txt`)
for the full list. Still-pending items are noted below.

#### CRITICAL fixed (deploys cleanly)

- **`POST /api/admin/config` accepted garbage types** — sending
  `{"blocked_apps": "not a list"}` would save the string into D1,
  bricking all agents on next config pull. Now rejects non-arrays /
  non-strings with HTTP 400 and a clear error. Workers handler
  (`admin-config.ts:64-118`) and the FastAPI path both updated.
- **`/api/admin/block-site` returned 500 on empty/null domain** —
  now returns HTTP 400 with `"\`name\` must be non-empty"`. Same
  coverage for `block-app`, `unblock-site`, `unblock-app`,
  `allow-site`.
- **`build.bat --token YOUR_TOKEN` silently discarded value** — the
  flag handler was wired to `set "API_TOKEN=<your-uuid-token>"` (the
  placeholder) instead of `set "API_TOKEN=%~2"`. Every exe shipped
  with the literal placeholder token, so all agents 401'd forever.
  Fixed; also added an explicit guard that errors out if the token
  still equals the placeholder.
- **`uninstall.bat` did not delete `LabSCHAgentOnBoot` task** — only
  `LabSCHAgentWatchdog` was removed. The OnBoot task survived every
  uninstall and re-launched the agent on every reboot. Now both
  tasks are deleted.

#### HIGH fixed

- **`labschctl resolve_client_id` did substring match** — typing
  `pc` would match BOTH `PC-LAB-01` and `PC-GURU-FAJRI` (returning
  whichever the server sent first); typing 3 chars of any UUID
  silently targeted that client. Now exact (case-insensitive)
  match against display_name, hostname, and client_id only.
- **`labschctl` URL encoding bug** — `?`, `&`, `=` were marked safe
  in `urllib.parse.quote`, so user-supplied query values were not
  URL-encoded. `labschctl events --client-id "foo&event_type=..."`
  injected an `event_type` parameter the admin never typed. Now
  path and query are split before encoding.
- **`labschctl client-config set <name>` (no flags) silently wiped
  per-PC override** — sent `{}` body which the server interpreted
  as "no override rules", indistinguishable from `clear`. Now
  refuses with HTTP 400 and explicit hint to use `clear`.
- **`labschctl unblock-all` silently swallowed partial failures** —
  one of the three clear endpoints failing returned `Done. All
  blocks cleared.` anyway. Now counts failures and exits non-zero
  with a clear error if any endpoint failed.
- **`labschctl profile activate/show/delete` exited 0 on 404** —
  `call()` printed the error to stderr but the handlers returned
  without surfacing the failure to stdout. Now print ERROR and exit
  non-zero so operators can detect typos in profile names.
- **`labschctl command-all --online-only --yes` against all-offline
  fleet** — printed `Done. Queued: 0` with exit 0, indistinguishable
  from a successful no-op. Now exits 2 with a clear
  `--online-only excluded all N clients` warning.
- **Workers `auth.ts` token comparison** — was plain `!==` which is
  vulnerable to timing side-channel. Now constant-time XOR over
  `Uint8Array`s.

#### Server-side

- **`server/api.py:121` heartbeat returned wrong `canonical_client_id`**
  — was `req.client_id` (raw incoming) instead of the de-duped
  `canonical_id` from the database. Agents were storing the wrong
  identity, breaking admin command routing and per-client overrides.

#### Still pending (audit deferred — non-critical)

The following categories are documented in the audit but not fixed
in this release; tracked as TODO for v0.3.5/v0.4.0:

- Agent-side: PowerShell command injection in `notify` message,
  multi-instance agent races, IFEO list_blocked_apps tagging,
  hosts file atomic writes, config.ini atomic writes, display_name
  Unicode validation, Python 3.10+ check, `cmd.exe`/`powershell.exe`
  IFEO-block deny-list
- Server-side: race conditions in `add/remove_blocked_*` (TOCTOU),
  config_version non-atomic increment, init_db migration race,
  no audit log for admin actions, audit-log for token rotation,
  `ip:8080` plaintext binding, no CORS, no rate-limit
- CLI: cmd_rename direct SQLite (bypasses API), env reload timing,
  full labschctl profile show/ delete surface

These are documented; recommend a hardening pass before deploying
to production with >20 PCs and public-internet exposure.

## [0.3.3] - 2026-09-05

### Fixed
- **`labschctl` HTTP 1010 against Cloudflare Workers** — the default
  `User-Agent: Python-urllib/...` from `urllib.request` was being blocked
  by Cloudflare's global edge protection on `*.workers.dev` (HTTP 403,
  error code 1010). The block is a CF global policy and cannot be
  disabled from the per-account WAF (which requires Enterprise / add-on
  on this account). `labschctl` now sets `User-Agent: labschctl/0.3.3` on
  every request, which CF accepts. No server-side change.

### Notes
- CLI now syncs fully into the repo — the in-repo `skill/labschctl` was
  behind the live `/opt/labsch/skill/labschctl` and was missing the
  `cmd_token` subcommand. Both files are now in sync at v0.3.3.
- This is a CLI-only patch; agent `.exe` does not need to be rebuilt.
  Existing installs keep working.

## [0.3.2] - 2026-09-05

### Added
- **API token management endpoints** (Workers + FastAPI parity):
  - `POST /api/admin/token/generate` — generate a fresh 32-byte URL-safe token; return fingerprint + length
  - `GET /api/admin/token/info` — show fingerprint + length (NEVER returns full token)
  - `DELETE /api/admin/token` — revoke in-process / clear KV metadata
- **`labschctl token generate|info|revoke`** CLI subcommand
- **Workers KV namespace `TOKEN_META`** for token metadata persistence (optional; only needed for the Workers deployment; local FastAPI uses `~/.hermes/.env` instead)
- **`skill/check_deps.bat`** — dependency checker & auto-installer (Python 3.10+, pip, psutil, requests, msg.exe, admin privileges)
- **`skill/references/`** — 4 new docs: api-cookbook, cleanup-queries, cloudflared-recovery, server-lifecycle

### Notes
- Workers: provision KV namespace with `wrangler kv:namespace create "TOKEN_META"` and uncomment the binding in `wrangler.toml` (see file comments).
- Local FastAPI: token rotation auto-persists to `~/.hermes/.env`.
- Token itself is NEVER stored server-side — only SHA-256 fingerprint + length + created_at — so KV leak does not leak usable credentials.

# Changelog

All notable changes to LabSCH are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-08-30

### Added
- Per-PC blocking overrides via `labschctl client-config set/show/clear`
  (`/api/clients/<id>/override` endpoint)
- Client name resolver — `labschctl command shutdown TesPC` works as well
  as `shutdown desktop-3d1knvb-ec8871bc`
- `display_name` and `is_test` columns on the clients table, surfaced in
  `labschctl clients`
- Remote `shutdown` / `restart` command per client
  (`POST /api/admin/command/<id>?command=shutdown`)
- `labschctl command shutdown|restart|cancel <pc>`
- Heartbeat response now includes a `pending_command` field
- `client_overrides` table on the server
- Comprehensive Cloudflare tunnel setup guide in README
  (quick + named tunnel, deb install, troubleshooting)

### Changed
- `GET /api/config` accepts `client_id` query param so agent pulls return the
  per-PC override when one exists
- `apply_config()` helper consolidates hosts / browser policy / IFEO application
  on the agent; both heartbeat and config-pull paths now go through it
- Empty live config now also clears browser-policy registry and IFEO Debugger
  entries (previously only the hosts file was being cleared on unblock)
- `display_name` is sent in the agent heartbeat and is updated on every install

### Fixed
- Per-PC overrides were silently overwritten by the global config on the
  agent's 60-second config pull (fixed by `client_id` on `GET /api/config`)
- Unblock did not remove `URLBlocklist` / `URLAllowlist` /
  `DnsOverHttpsMode` / `IncognitoModeAvailability` registry keys
  (fixed by always running the clear path when lists are empty)
- Unblock did not remove IFEO Debugger entries (fixed in `apply_config`)
- `events` table foreign-key constraint caused HTTP 500 on events that
  arrived before the heartbeat; events are now a historical log without FK
- `labschctl` `profile` subcommand with a space in the name now URL-encodes
  the path correctly
- `client_config set` no longer crashes when the user passes no lists
- Allowlist exact-domain handling — `.canva.com` no longer matches the bare
  `canva.com`; the server now stores both forms

### Security
- No new security notes
- `SPREADSHEET_ID`-style values are no longer hard-coded in the example
  references; per-PC config remains token-protected
- Confirmed no hard-coded credentials in any of the audited repos

## [0.1.0] - 2026-08-30

### Added
- Initial release
- FastAPI server (`server/api.py`) with 14 endpoints
- SQLite database with auto-migration
- Cloudflare quick tunnel starter (`start_tunnel.sh`)
- Python agent (`agent/labsch_agent.py`) with triple-layer blocking
- Hosts file editor (`agent/website_blocker.py`)
- Browser policy registry manager (`agent/browser_policy.py`) for Edge/Chrome/Brave
- Windows IFEO blocker (`agent/ifeo_blocker.py`)
- Self-protection module (`agent/self_protect.py`) with scheduled task + Run key
- MAC-based device ID (`agent/device_id.py`) for client de-duplication
- 1-click Windows installer (`agent/install.bat`) with display name + is_test prompts
- Uninstaller (`agent/uninstall.bat`)
- PyInstaller build script (`agent/build.bat`)
- Windows service wrapper (`agent/install_service.py`)
- Admin CLI (`skill/labschctl`) with subcommands for clients, config, events, profiles, rename
- Named rule profiles (`profile save/activate/list/show/delete`)
- Bulk clear command (`labschctl unblock-all`)
- Triple-layer blocking: hosts + browser policy + IFEO
- DoH-proof (Secure DNS disabled via browser policy)
- Incognito-proof (Private/Incognito disabled)
- Server auto-marks clients offline after 90s no heartbeat
- Hermes skill with comprehensive SKILL.md

### Security
- Token-based auth (X-Agent-Token header)
- Server binds to localhost only (no public port)
- HTTPS via Cloudflare tunnel
- Self-protection prevents student from killing the agent

### Known limitations
- Quick tunnel URL is random (use named tunnel for production)
- Browser policy is Chromium-only (Edge/Chrome/Brave)
- No real-time events stream (use polling)
- Single-server, no federation
