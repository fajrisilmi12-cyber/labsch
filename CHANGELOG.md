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
