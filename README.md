# LabSCH — Lab School Manager

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Cloudflare Workers](https://img.shields.io/badge/server-Cloudflare%20Workers%20%2B%20D1-orange.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%2F11%20LTSC-blue.svg)]()
[![Status: v0.3.1](https://img.shields.io/badge/status-v0.3.1--workers-green.svg)]()

Centralized Windows lab management for 20+ PCs — **100% serverless**. Push block/allow rules, app-block policies, and camera/audio controls to lightweight Python agents on each client. The agent runs as a Windows service, can't be killed by students, and identifies each PC by its MAC address (so reinstalls never create duplicate records).

> **Live deployment**: Managing SMK + SMP lab PCs in Medan, Indonesia. Server runs on **Cloudflare Workers + D1** (free tier, $0/month) — no homeserver required, no tunnel to maintain, no VM to babysit.

## Features

- 🛡️ **Triple-layer blocking** — hosts file, browser policy registry, Windows IFEO. DoH-proof (disables Secure DNS via policy). Incognito-proof (disables Private mode).
- 📷🔊 **Camera & audio control** — kill switches per-PC or globally, reversible, delivered via heartbeat.
- 🆔 **MAC-based client ID** — one device = one record, even after agent reinstall or PC rename. No duplicates.
- 📦 **1-click installers** — `install.bat` (agent) + `labsch_startup.bat` (4-layer auto-start that survives reboots) + `labsch_full_uninstall.bat` (clean removal of everything).
- 🔁 **Self-protection** — Scheduled tasks + Run key + (optional) Task Manager lockdown. The student cannot kill or uninstall the agent through normal means.
- 💾 **Named rule profiles** — Save config as "Rules Lab", "Ujian", "Bebas Akses", activate with one command.
- 🪟 **Windows 10/11 LTSC** — Tested on MSI Thin 15 (LTSC), should work on Pro/Home/Enterprise.
- ⚡ **Serverless edge** — Cloudflare Workers global anycast, <50ms latency from Indonesia, 100k requests/day free.
- 🛠️ **Hermes skill** — Bundled admin CLI integrates with the Hermes Agent skill system. Just `labschctl` from any terminal.

## Architecture

```
┌──────────────────────────────────────────┐
│  Cloudflare Edge (serverless)            │
│                                          │
│  Workers: labsch-api (Hono, TS)          │
│  ├─ 29 REST endpoints                    │
│  ├─ X-Agent-Token auth middleware        │
│  └─ Cron: mark-stale (every 5 min)       │
│                                          │
│  D1 Database: labsch-db (SQLite)         │
│  ├─ clients / config / events            │
│  └─ profiles / client_overrides          │
└────────────┬─────────────────────────────┘
             │ HTTPS polling
             │ 30s heartbeat (configurable)
             │ Auth: X-Agent-Token (UUID)
             ▼
┌──────────────────────────────────────────┐
│  Each Windows PC                         │
│  (agent/labsch_agent.py)                 │
│  Python → PyInstaller .exe               │
│  4-layer auto-start, self-protect        │
│  Pulls config → applies policy           │
│  Hosts + browser policy + IFEO + devices │
└──────────────────────────────────────────┘
             ▲
             │ HTTPS (X-Agent-Token)
             │
┌────────────┴─────────────────────────────┐
│  Admin (anywhere)                        │
│  labschctl CLI or Hermes Agent           │
└──────────────────────────────────────────┘
```

The agent is **pull-based**: each client polls the server. No firewall ports to open on the school network, no NAT-traversal, no WebSocket. Plain HTTPS polling — simple and reliable at 20-PC scale.

**Why serverless?** The old design (FastAPI on a homeserver + Cloudflare Tunnel) worked, but meant babysitting a VM: systemd restarts, tunnel URL rotations, disk space. Workers + D1 removes all of that — $0/month, scales automatically, and the deployment URL never changes.

## Quick start (admin)

The server is already deployed at `https://labsch-api.fajrisilmi6.workers.dev` (or your own Workers URL — see [Server setup](#server-setup-cloudflare-workers) below).

```bash
# Set environment (or in ~/.hermes/.env):
export SCHOOL_SERVER_URL="https://labsch-api.fajrisilmi6.workers.dev"
export SCHOOL_API_TOKEN="<uuid>"

# List all clients
labschctl clients

# Block / allow
labschctl config block-site tiktok.com
labschctl config block-app RobloxPlayerLauncher.exe
labschctl config allow-site wikipedia.org

# Camera / audio control (v0.3.1+)
# (via API: POST /api/admin/device {"disable_camera": true})

# Bulk clear
labschctl unblock-all

# Named profiles
labschctl profile save "Rules Lab"
labschctl profile activate "Rules Lab"

# Rename a PC, view events
labschctl rename <client_id> "PC-LAB-01"
labschctl events --hours 1
```

## Deploy to a new PC

1. **Download** `labsch-agent-v0.3.1.zip` from the [Releases](../../releases) page.
2. **Copy** to a USB drive or directly to the target PC.
3. **Extract** the zip.
4. **Right-click `install.bat` → "Run as administrator"**.
5. **Answer two prompts**:
   - Display name (e.g. `PC-LAB-01`)
   - Is this a test PC? (Y/N — test PCs are excluded from profile rules)
6. **Run `labsch_startup.bat`** (also as admin) — installs 4-layer auto-start so the agent survives reboots reliably.
7. **Done.** The agent registers and starts applying the active config within 60 seconds.

### Auto-start layers (v0.3.1+)

`labsch_startup.bat` installs all of these:

| Layer | Trigger | Purpose |
|---|---|---|
| Startup folder (user) | User login | First chance |
| Startup folder (all users) | Any user login | Coverage for shared PCs |
| Run key HKLM | Boot | Classic auto-start |
| Scheduled task ONSTART (SYSTEM) | **Before login** | Runs even at the login screen |

Plus a **starter script with retry**: waits until Python is available on PATH (up to 5 min), then launches the agent, then respawns it every 10 seconds if it dies. This fixes the "sometimes doesn't load after reboot" issue where Windows fires the Run key before Python/PATH is ready.

## Per-PC overrides

The global config applies to every client by default. A per-PC override replaces it for one client only.

```bash
# Block YouTube + Roblox only on PC-LAB-01; allow Google there
labschctl client-config set desktop-abc123 \
  --blocked-site youtube.com \
  --allowed-site google.com \
  --blocked-app RobloxPlayerBeta.exe

# Inspect the override
labschctl client-config show desktop-abc123

# Remove the override; it inherits global rules again
labschctl client-config clear desktop-abc123
```

To keep one PC completely free while the global profile remains active, save an explicit empty override:

```bash
labschctl client-config set desktop-abc123
```

`set` with no lists means "free access for this PC". `clear` means "inherit global rules".

## Camera & audio control (v0.3.1+)

Two new kill switches, set globally or per-PC, delivered through the same heartbeat as blocking rules:

| Flag | Effect | Mechanism |
|---|---|---|
| `disable_camera` | No app can access the webcam | Registry policy `AllowCamera=0` + device-install restriction on the camera class GUID |
| `disable_audio` | System-wide silence | Stop + disable `audiosrv` and `AudioEndpointBuilder` services |

Both are **reversible** — flipping the flag off immediately restores the device. Set via the admin API:

```bash
# Global: kill both
curl -X POST -H "X-Agent-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"disable_camera": true, "disable_audio": true}' \
  $SCHOOL_SERVER_URL/api/admin/device

# Per-PC only
curl -X POST ... $SCHOOL_SERVER_URL/api/admin/device/<client_id>

# Clear per-PC override (inherit global)
curl -X DELETE ... $SCHOOL_SERVER_URL/api/admin/device/<client_id>
```

## Uninstall (per PC)

```powershell
labsch_full_uninstall.bat   # Right-click → Run as administrator
```

Removes **everything**: agent processes, all 4 auto-start layers, hosts-file entries, browser policies, IFEO keys, re-enables Task Manager, and deletes `C:\ProgramData\LabSCHAgent`. The PC returns to a clean state.

For the agent files only (keep auto-start), use `uninstall.bat` instead.

## How blocking works (defense in depth)

The agent applies three layers on every config change:

### 1. Hosts file
Appends `127.0.0.1 <domain>` lines with marker comments. Catches all DNS-aware software.

### 2. Browser policy (registry)
Sets `URLBlocklist` and `URLAllowlist` for Edge/Chrome/Brave. Disables DoH and Incognito so the browser can't bypass.

### 3. IFEO (Image File Execution Options)
Sets `Debugger=cmd.exe /c exit` for each blocked `.exe`. The OS itself blocks execution *before* the process starts — renaming or moving the binary doesn't help.

If config is cleared, the agent **deletes** the registry keys (not sets to empty) to avoid stale policy caching in Chromium browsers.

## Rule profiles

A profile is a named snapshot of `(blocked_apps, blocked_websites, allowed_websites)`. Workflow:

1. Set up the live config:
   ```bash
   labschctl config block-site tiktok.com
   labschctl config allow-site wikipedia.org
   labschctl config block-app RobloxPlayerLauncher.exe
   ```
2. Save it: `labschctl profile save "Rules Lab"`
3. Restore it later: `labschctl profile activate "Rules Lab"`

Multiple profiles coexist. Activation bumps `config_version`, which agents pull on their next cycle.

## Requirements

### Server (Cloudflare)
- Cloudflare free account
- Node.js 18+ with `wrangler` (deploy-time only, not runtime)
- D1 database (free tier: 5 GB storage, 5M reads/day)

### Agent (per PC)
- Windows 10 or 11 (LTSC, Pro, Home all tested)
- Python 3.10+ (or pre-built `.exe` via `build.bat`)
- Administrator privileges for install + first run
- Internet access to `*.workers.dev` (or your custom domain)

### Quota math (free tier)

| Item | Usage at 20 PCs | Free limit |
|---|---|---|
| Workers requests | ~86,500/day | 100,000/day ✅ |
| D1 reads | ~50,000/day | 5M/day ✅ |
| D1 writes | ~5,000/day | 100k/day ✅ |

Heartbeat interval is configurable (`heartbeat_interval` in config.ini, default 30s) if you need to trade latency for quota headroom.

## Server setup (Cloudflare Workers)

From scratch (replacing the old homeserver + tunnel setup):

```bash
# 1. Install wrangler + login
npm install -g wrangler
wrangler login          # browser OAuth (or --device flow on headless)

# 2. Create the D1 database
wrangler d1 create labsch-db
# Note the database_id → put in workers/wrangler.toml

# 3. Apply schema
cd workers
wrangler d1 execute labsch-db --remote --file=schema.sql -y

# 4. Set the auth token secret
wrangler secret put SCHOOL_API_TOKEN   # paste a UUID

# 5. Deploy
wrangler deploy
# → https://labsch-api.<your-subdomain>.workers.dev
```

Set the URL as `SCHOOL_SERVER_URL` for `labschctl`, and bake it into the agent's `install.bat` before distribution. Cron trigger (mark-stale every 5 min) is already in `wrangler.toml`.

## Build (Windows .exe)

To distribute as a single `.exe` instead of Python scripts:

```cmd
cd agent
build.bat --server https://labsch-api.fajrisilmi6.workers.dev --token <UUID>
```

Output: `dist\LabSCHAgent.exe` (~15 MB, self-contained).

For 1-click install across 20 PCs, use the Python version + `install.bat` — it's smaller and updates the agent in one place.

## API

All admin endpoints require `X-Agent-Token: <token>` header. See [`docs/API.md`](docs/API.md) for the full list. Quick reference:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (open) |
| `POST` | `/api/heartbeat` | Agent heartbeat — returns config + device flags + pending command |
| `GET` | `/api/clients` | List registered clients |
| `GET` | `/api/admin/config` | Live blocklist config |
| `POST` | `/api/admin/profiles` | Create or update named profile |
| `POST` | `/api/admin/profiles/{name}/activate` | Apply profile to all clients |
| `POST` | `/api/admin/device` | Set camera/audio flags (global) |
| `POST` | `/api/admin/device/{client_id}` | Set camera/audio flags (per-PC) |
| `POST` | `/api/admin/command/{client_id}` | Queue shutdown/restart/lock/notify |

## File layout

```
labsch/
├── workers/             Cloudflare Workers server (TypeScript, Hono)
│   ├── src/index.ts         Entry + routing
│   ├── src/auth.ts          Token middleware
│   ├── src/handlers/        Endpoint handlers (9 modules)
│   ├── schema.sql           D1 schema
│   ├── wrangler.toml        Deploy config (D1 binding, cron)
│   └── package.json
├── server/              LEGACY: FastAPI + SQLite homeserver version
├── agent/               Windows client
│   ├── labsch_agent.py          Main loop
│   ├── config_sync.py           HTTP client (custom UA, CF bot-fight safe)
│   ├── device_blocker.py        Camera/audio kill switches (v0.3.1)
│   ├── browser_policy.py        Edge/Chrome/Brave registry policy
│   ├── ifeo_blocker.py          App execution block
│   ├── website_blocker.py       Hosts file editor
│   ├── self_protect.py          Scheduled task + Run key
│   ├── device_id.py             MAC-based stable ID
│   ├── install.bat              1-click agent installer
│   ├── labsch_startup.bat       4-layer auto-start installer
│   ├── labsch_full_uninstall.bat Full clean uninstall
│   ├── uninstall.bat            Minimal uninstall
│   └── build.bat                PyInstaller .exe builder
├── skill/               Hermes skill
│   ├── SKILL.md
│   └── labschctl        Admin CLI
└── docs/
    ├── ARCHITECTURE.md
    ├── API.md
    ├── ALLOWLIST_BAT.md
    └── plans/           Migration plans
```

## Roadmap

- [x] Per-client config overrides (block site X only on PC-LAB-01)
- [x] Serverless migration (Cloudflare Workers + D1)
- [x] Camera & audio control
- [x] Reliable auto-start across reboots (4-layer)
- [ ] Group profiles (apply Rules Lab to group "lab", not test PCs)
- [ ] Web dashboard (replace CLI with browser UI)
- [ ] Real-time events stream (WebSocket/SSE for admin UI)
- [ ] Per-PC schedule (different rules for class time vs break time)
- [ ] Native Windows installer (MSI) for Group Policy deployment

## License

[MIT](LICENSE) — use freely for any school / lab / office environment.

## Credits

- Inspired by the [FULL ALLOWLIST WEB v4](docs/ALLOWLIST_BAT.md) BAT script (registry-based browser policy)
- Built for SMK/SMP schools in Medan, Indonesia
- Runs on [Cloudflare Workers](https://workers.cloudflare.com/) + D1 (free tier)
