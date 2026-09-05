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
