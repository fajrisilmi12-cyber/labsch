# LabSCH — Lab School Manager

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows%2010%2F11%20LTSC-blue.svg)]()
[![Status: v0.1.0](https://img.shields.io/badge/status-v0.1.0--beta-orange.svg)]()

Centralized Windows lab management for 20+ PCs. Push block/allow rules + app-block policies to lightweight Python agents on each client. The agent runs as a Windows service, can't be killed by students, and identifies each PC by its MAC address (so reinstalls never create duplicate records).

> **Live deployment**: Currently managing SMK + SMP lab PCs in Medan, Indonesia. Server runs on a Hermes homeserver (1.8 GB RAM, 6.9 GB swap) — see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the resource profile.

## Features

- 🛡️ **Triple-layer blocking** — hosts file, browser policy registry, Windows IFEO. DoH-proof (disables Secure DNS via policy). Incognito-proof (disables Private mode).
- 🆔 **MAC-based client ID** — one device = one record, even after agent reinstall or PC rename. No duplicates.
- 📦 **1-click installer** — `install.bat` asks for the PC's display name and `is_test` flag, then auto-elevates to Admin, registers the agent, and arms self-protection.
- 🔁 **Self-protection** — Scheduled task + Run key + (optional) Task Manager lockdown. The student cannot kill or uninstall the agent through normal means.
- 💾 **Named rule profiles** — Save the current config as "Rules Lab", "Ujian", "Bebas Akses", then activate with a single command.
- 🪟 **Windows 10/11 LTSC** — Tested on MSI Thin 15 (LTSC), should work on Pro/Home/Enterprise.
- 🌐 **Cloudflare tunnel ready** — Default install uses a quick tunnel URL; switch to a named tunnel for a stable production URL.
- 🛠️ **Hermes skill** — Bundled admin CLI integrates directly with the Hermes Agent skill system. Just `labschctl` from any terminal.

## Architecture

```
┌──────────────────────────────────┐
│  Hermes homeserver               │
│  (server/api.py + db.py)         │
│  FastAPI + SQLite                │
│  Exposed via Cloudflare tunnel   │
└──────────┬───────────────────────┘
           │ HTTPS polling
           │ 30s heartbeat + 60s config pull
           │ Auth: X-Agent-Token (UUID)
           ▼
┌──────────────────────────────────┐
│  Each Windows PC                 │
│  (agent/labsch_agent.py)         │
│  Python → PyInstaller .exe       │
│  Runs as Windows Service         │
│  Pulls config → applies policy   │
└──────────────────────────────────┘
```

The agent is **pull-based**: each client polls the server. No firewall ports to open on the school network, no NAT-traversal problems, no WebSocket. Just plain HTTP polling. This is intentionally simple — the alternative (MQTT, WebSocket, push) adds infra for no real benefit at 20-PC scale.

## Quick start (admin)

The server lives on a Hermes homeserver. To manage clients from anywhere with access to the tunnel URL:

```bash
# Set environment (or in ~/.hermes/.env):
export SCHOOL_SERVER_URL="https://<tunnel>.trycloudflare.com"
export SCHOOL_API_TOKEN="<uuid>"

# List all clients
labschctl clients

# Block / allow
labschctl config block-site tiktok.com
labschctl config block-app RobloxPlayerLauncher.exe
labschctl config allow-site wikipedia.org

# Bulk clear
labschctl unblock-all

# Named profiles
labschctl profile save "Rules Lab"
labschctl profile activate "Rules Lab"
labschctl profile list

# Rename a PC
labschctl rename <client_id> "PC-LAB-01"

# View events
labschctl events --hours 1
```

The CLI is at `skill/labschctl` after `pip install` or by symlinking into `~/.hermes/skills/labsch/`.

## Deploy to a new PC

1. **Download** `labsch-agent-v0.1.0.zip` from the [Releases](../../releases) page.
2. **Copy** to a USB drive or directly to the target PC.
3. **Extract** the zip.
4. **Right-click `install.bat` → "Run as administrator"**.
5. **Answer two prompts**:
   - Display name (e.g. `PC-LAB-01`)
   - Is this a test PC? (Y/N — test PCs are excluded from profile rules)
6. **Done.** The agent registers and starts applying the active config within 60 seconds.

Self-protection is enabled by default. Verify:

```powershell
schtasks /query /tn LabSCHAgentWatchdog
# Should show "Ready" status
```

## Per-PC overrides

The global config applies to every client by default. A per-PC override
replaces it for one client only — useful when one teacher PC or a test PC
needs different access.

```bash
# Find the client ID
labschctl clients

# Block YouTube + Roblox only on PC-LAB-01; allow Google there
labschctl client-config set desktop-abc123 \\
  --blocked-site youtube.com \\
  --allowed-site google.com \\
  --blocked-app RobloxPlayerBeta.exe

# Inspect the override
labschctl client-config show desktop-abc123

# Remove the override; it inherits global rules again
labschctl client-config clear desktop-abc123
```

Override behavior:

- **No override** → client receives the global config.
- **Override exists** → client receives only its per-PC lists.
- **Clear override** → client immediately returns to global config on its next heartbeat (within 30 seconds).
- The global config is never modified by per-PC commands.

## Uninstall (per PC)

```powershell
uninstall.bat   # Right-click → Run as administrator
```

Removes the scheduled task, Run key, re-enables Task Manager, and deletes the config file. The agent binary itself is not removed — delete the folder manually if desired.

## How blocking works (defense in depth)

The agent applies three layers on every config change:

### 1. Hosts file (legacy)
Appends `127.0.0.1 <domain>` lines with marker comments. Catches all DNS-aware software.

### 2. Browser policy (registry)
Sets `URLBlocklist` and `URLAllowlist` for Edge/Chrome/Brave under `HKLM\SOFTWARE\Policies\...`. Disables DoH (`DnsOverHttpsMode=off`) so the browser can't bypass by querying Cloudflare/Google DNS over HTTPS. Disables Incognito so students can't open a clean window.

### 3. IFEO (Image File Execution Options)
Sets `Debugger=cmd.exe /c exit` for each blocked `.exe`. The OS itself blocks execution *before* the process starts. The student cannot:
- Rename the binary to bypass (we match by full name)
- Run from a different path (IFEO matches name, not path)
- Kill the process (it never starts)

If config is cleared, the agent **deletes** the registry keys (not sets to empty) to avoid stale policy caching in Chromium browsers.

## Rule profiles

A profile is a named snapshot of `(blocked_apps, blocked_websites, allowed_websites)`. Workflow:

1. Set up the live config:
   ```bash
   labschctl config block-site tiktok.com
   labschctl config allow-site wikipedia.org
   labschctl config block-app RobloxPlayerLauncher.exe
   ```
2. Save it:
   ```bash
   labschctl profile save "Rules Lab"
   ```
3. Restore it later (one command):
   ```bash
   labschctl profile activate "Rules Lab"
   ```

Multiple profiles coexist (`Rules Lab`, `Ujian`, `Bebas Akses`, `Maintenance`). Activation bumps the `config_version`, which the agents pull on their next cycle.

## Self-protection

The `install.bat` enables three layers automatically:

| Layer | Mechanism | What it does |
|-------|-----------|--------------|
| Scheduled task | `schtasks /create` | Respawns the agent every 5 minutes |
| Run key | `HKLM\...\Run\LabSCHAgent` | Starts the agent on every boot |
| Task Manager | Registry `DisableTaskMgr=1` | Prevents the student from killing the process interactively |

To remove protection (e.g. for moving the PC):

```powershell
python labsch_agent.py --unprotect
```

## Requirements

### Server
- Python 3.10+
- 256 MB RAM (SQLite + FastAPI is light)
- `cloudflared` for tunnel (or any reverse proxy)
- Linux/macOS/Windows

### Agent (per PC)
- Windows 10 or 11 (LTSC, Pro, Home all tested)
- Python 3.10+ (or pre-built `.exe` via `build.bat`)
- Administrator privileges for install + first run
- Internet access to the tunnel URL

## Server setup (from scratch)

### 1. Install cloudflared

The agent reaches the server over HTTPS, so you need a tunnel. We use
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
(`cloudflared`) because it's free, no port-forwarding required, and works
behind any NAT. Install it once per server:

```bash
# Linux (Debian/Ubuntu) — official .deb from Cloudflare
curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version    # verify
```

Other platforms: see <https://pkg.cloudflare.com/> or the
[GitHub releases page](https://github.com/cloudflare/cloudflared/releases).

You can use **any** reverse proxy instead of cloudflared (nginx, caddy,
tailscale, ngrok, etc.) — the only requirement is that the server is
reachable over HTTPS at a stable URL the agent can poll. Cloudflare is
just the default because it's free and zero-config.

### 2. Get the server URL

#### Option A: Quick tunnel (development, random URL)

```bash
# One-time per server boot — gives you a random *.trycloudflare.com URL
cloudflared tunnel --url http://localhost:8080

# Output:
# https://random-words-1234.trycloudflare.com
```

The URL changes every restart. Set it as the `SCHOOL_SERVER_URL`
environment variable (or in `~/.hermes/.env` if using the Hermes skill).

#### Option B: Named tunnel (production, stable URL)

```bash
# 1. Login to Cloudflare (browser opens once)
cloudflared tunnel login

# 2. Create a named tunnel
cloudflared tunnel create labsch-server

# 3. Configure (~/.cloudflared/config.yml)
cat > ~/.cloudflared/config.yml <<'YAML'
tunnel: labsch-server
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: labsch.yourdomain.com
    service: http://localhost:8080
  - service: http_status:404
YAML

# 4. Add DNS record
cloudflared tunnel route dns labsch-server labsch.yourdomain.com

# 5. Run
cloudflared tunnel run labsch-server
```

The URL `https://labsch.yourdomain.com` is now stable. Use this as
`SCHOOL_SERVER_URL` in production.

### 3. Run the server

```bash
git clone https://github.com/fajrisilmi12-cyber/labsch
cd labsch/server
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn psutil pydantic
# Edit venv/bin/activate or use a wrapper: set SCHOOL_SERVER_URL
# and SCHOOL_API_TOKEN here.
python3 api.py
```

### 4. Set the API token

Generate a random token (UUID):

```bash
python3 -c "import uuid; print(uuid.uuid4())"
# e.g. 7f3a9b2e-4d1c-4a8b-9e2f-3b8c7d6e5f4a
```

Add to the agent's `install.bat` (line `set API_TOKEN=...`) and to the
server's environment. The agent sends this in the `X-Agent-Token` header
on every request. Without it, the server returns 401.

For a quick start, embed the token directly in `install.bat`. For
multi-tenant deployments, generate one token per school.

## Build (Windows .exe)

To distribute as a single `.exe` instead of Python scripts:

```cmd
cd agent
build.bat --server https://<tunnel>.trycloudflare.com --token <UUID>
```

Output: `dist\LabSCHAgent.exe` (~15 MB, self-contained, embeds the token).

For 1-click install across 20 PCs, use the Python version + `install.bat` — it's smaller (no .exe download) and updates the agent in one place.

## API

All admin endpoints require `X-Agent-Token: <token>` header. See [`docs/API.md`](docs/API.md) for the full list. Quick reference:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/heartbeat` | Agent heartbeat (returns latest config) |
| `GET` | `/api/clients` | List registered clients |
| `GET` | `/api/admin/config` | Live blocklist config |
| `POST` | `/api/admin/profiles` | Create or update named profile |
| `POST` | `/api/admin/profiles/{name}/activate` | Apply profile to all clients |

## File layout

```
labsch/
├── server/              FastAPI + SQLite
│   ├── api.py
│   ├── db.py
│   ├── start_tunnel.sh
│   └── venv/
├── agent/               Windows client
│   ├── labsch_agent.py
│   ├── config_sync.py
│   ├── browser_policy.py
│   ├── ifeo_blocker.py
│   ├── self_protect.py
│   ├── device_id.py
│   ├── website_blocker.py
│   ├── app_blocker.py
│   ├── install.bat
│   ├── uninstall.bat
│   ├── build.bat
│   └── install_service.py
├── skill/               Hermes skill
│   ├── SKILL.md
│   └── labschctl
└── docs/
    ├── ARCHITECTURE.md
    ├── API.md
    └── ALLOWLIST_BAT.md
```

## Roadmap

- [ ] Per-client config overrides (block site X only on PC-LAB-01)
- [ ] Group profiles (apply Rules Lab to group "lab", not test PCs)
- [ ] Web dashboard (replace CLI with browser UI)
- [ ] Real-time events stream (WebSocket for admin UI)
- [ ] Per-PC schedule (different rules for class time vs break time)
- [ ] Native Windows installer (MSI) for Group Policy deployment
- [ ] Multi-server federation (one tunnel per school)

## License

[MIT](LICENSE) — use freely for any school / lab / office environment.

## Credits

- Inspired by the [FULL ALLOWLIST WEB v4](docs/ALLOWLIST_BAT.md) BAT script (registry-based browser policy)
- Built for SMK/SMP schools in Medan, Indonesia
- Server architecture based on the [Hermes Agent](https://hermes-agent.nousresearch.com/) homeserver pattern
