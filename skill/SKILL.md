---
name: labsch
description: Lab School Manager — manage 20+ Windows lab PCs from a single Hermes homeserver. Use when user asks to install/uninstall LabSCH agent on lab PCs, block websites or apps centrally, push rule profiles, view client status, or troubleshoot agent connectivity.
version: 0.1.0
author: Fajri (Muhammad Al-Fajri Silmi)
license: MIT
---

# LabSCH — Lab School Manager

Centralized Windows lab management for 20+ PCs. Server lives on a Hermes
homeserver and pushes block/allow rules + app-block policies to lightweight
Python agents on each client. The agent runs as a Windows service, can't be
killed by students, and identifies each PC by its MAC address (so reinstalls
don't create duplicate records).

## When to load this skill

Load whenever the user mentions any of:

- "LabSCH" or "lab school manager" or "Madani Agent" (legacy name)
- "install agent ke PC" / "deploy ke 20 lab" / "blocking di lab"
- "block youtube" / "block roblox" / "block tiktok"
- "profile Rules Lab" / "aktifkan profile"
- "client offline" / "agent tidak connect"
- "labschctl" / "labsch-agent-v0.1.0.zip"

## Architecture (pull-based)

```
┌──────────────────────────────────┐
│  Hermes homeserver               │
│  (server/api.py + db.py)         │
│  FastAPI + SQLite                │
│  Exposed via Cloudflare tunnel   │
└──────────┬───────────────────────┘
           │ HTTPS polling (30s heartbeat, 60s config)
           │ Auth: X-Agent-Token (UUID)
           ▼
┌──────────────────────────────────┐
│  Each Windows PC                 │
│  (agent/labsch_agent.py)         │
│  Python → PyInstaller .exe       │
│  Runs as Windows Service         │
│  Pulls config → applies policy   │
│  Sends events back to server     │
└──────────────────────────────────┘
```

**Key files**:

- `server/api.py` — FastAPI 14 endpoints (heartbeat, config, admin, profiles)
- `server/db.py` — SQLite layer (clients, config, events, profiles)
- `agent/labsch_agent.py` — main loop
- `agent/browser_policy.py` — Edge/Chrome/Brave registry policy (DoH-proof)
- `agent/ifeo_blocker.py` — Windows IFEO Debugger (un-killable app block)
- `agent/self_protect.py` — scheduled task + Run key (auto-respawn)
- `agent/device_id.py` — MAC-based stable client ID
- `skill/labschctl` — admin CLI

## Quick start (admin)

The server is already running on the Hermes homeserver. To manage clients:

```bash
# Make sure these are set in ~/.hermes/.env:
#   SCHOOL_SERVER_URL=https://<tunnel>.trycloudflare.com
#   SCHOOL_API_TOKEN=<uuid>

# List all clients
labschctl clients

# Show / edit live blocklist
labschctl config show
labschctl config block-site tiktok.com
labschctl config block-app RobloxPlayerLauncher.exe
labschctl config allow-site wikipedia.org

# Bulk clear
labschctl unblock-all

# Saved rule profiles (e.g. "Rules Lab", "Ujian", "Bebas Akses")
labschctl profile save "Rules Lab"          # snapshot current config
labschctl profile activate "Rules Lab"      # apply to all clients
labschctl profile list
labschctl profile show "Rules Lab"

# Rename a client (sets display_name)
labschctl rename <client_id> "PC-LAB-01"

# View events
labschctl events --hours 1
```

## Deploy to a new PC

1. **Download the zip** from the Discord `#general-chat` channel
   (latest: `labsch-agent-v0.1.0.zip`).
2. **Copy to USB** or directly to the target Windows PC.
3. **Extract** the zip.
4. **Run `install.bat` as Administrator** (right-click → Run as administrator).
5. **Answer the prompts**:
   - Display name (e.g. `PC-LAB-01`)
   - Is this a test PC? (Y/N) — test PCs are excluded from profile rules
6. **Done.** The agent registers itself and starts applying the active config
   within 60 seconds.

Self-protection is enabled automatically:
- Scheduled task `LabSCHAgentWatchdog` restarts the agent every 5 minutes.
- `HKLM\...\Run\LabSCHAgent` starts the agent on boot.
- Task Manager is disabled.

## Uninstall (per PC)

```powershell
# Run uninstall.bat as Administrator
uninstall.bat
```

This removes the scheduled task, Run key, re-enables Task Manager, and deletes
the config file. The agent binary itself is not removed — delete the folder
manually if desired.

## Blocking layers (defense in depth)

The agent applies three layers in this order on every config change:

1. **Hosts file** (legacy) — appends/removes `127.0.0.1 <domain>` lines.
2. **Browser policy** (registry) — sets `URLBlocklist` + `URLAllowlist` for
   Edge/Chrome/Brave under `HKLM\SOFTWARE\Policies\...`. Disables DoH
   (`DnsOverHttpsMode=off`) and Incognito mode so students can't bypass.
3. **IFEO** (registry) — sets `Debugger=cmd.exe /c exit` for each blocked
   `.exe`. The OS itself blocks execution before the process starts; the
   student cannot rename, kill, or run a different binary of the same name.

If config is empty (all cleared), the agent **deletes** the registry keys
rather than setting them to empty — this avoids stale policy issues with
Chromium browsers.

## Profile (named ruleset) workflow

1. Set up the live config exactly how you want it:
   ```bash
   labschctl config block-site tiktok.com
   labschctl config allow-site wikipedia.org
   labschctl config block-app RobloxPlayerLauncher.exe
   ```
2. Save it as a named profile:
   ```bash
   labschctl profile save "Rules Lab"
   ```
3. Later, restore it with one command:
   ```bash
   labschctl profile activate "Rules Lab"
   ```

Multiple profiles can coexist (e.g. `Rules Lab`, `Ujian`, `Bebas Akses`,
`Maintenance`). Switching is a single command and bumps the config version,
which the agents pull on their next 60-second cycle.

## Client identification (no duplicates)

Each agent reads its primary MAC address on startup, hashes it to a
`dev-<16hex>` device ID, and sends it with every heartbeat. The server
de-duplicates by device ID, so reinstalling the agent or restarting the PC
never creates a new client record. The `client_id` stays stable.

Hostname + IP are stored but not used as the primary key — they can change
(DHCP lease, PC rename) without causing issues.

## Self-protection

The `--protect` mode (installed by `install.bat` automatically) adds:

| Layer | What it does |
|-------|--------------|
| Scheduled task | `LabSCHAgentWatchdog` respawns the agent every 5 minutes |
| Run key | `HKLM\...\Run\LabSCHAgent` starts the agent on every boot |
| Task Manager | Disabled (configurable) |
| Process kill | Agent itself has no `taskkill` exit on stop attempts |

To remove protection (e.g. for moving the PC or maintenance):

```powershell
python labsch_agent.py --unprotect
```

## Database

SQLite at `data/labsch.db`. Tables:

- `clients` — registered PCs (`client_id`, `device_id`, `mac`, `display_name`,
  `is_test`, `hostname`, `ip`, `status`, `last_seen`, `first_seen`)
- `config` — single-row live config (`blocked_apps`, `blocked_websites`,
  `allowed_websites`, `config_version`)
- `profiles` — named saved configs (same columns as `config` + `created_at`,
  `activated_at`)
- `events` — log of agent events (`config_applied`, `blocked_app`, etc.)

Migrations are automatic: missing columns are added with `ALTER TABLE` on
server startup.

## Environment variables

The agent reads from `C:\ProgramData\LabSCHAgent\config.ini`:

```ini
{
  "server_url": "https://<tunnel>.trycloudflare.com",
  "api_token": "<uuid>",
  "client_id": "",
  "display_name": "PC-LAB-01",
  "is_test": false,
  "version": "0.1.0"
}
```

The server's URL and token are embedded in `install.bat` defaults, so most
installs just need to answer the two prompts.

## Troubleshooting

**Agent stuck on "starting", no heartbeat**
- Run PowerShell as Administrator (right-click → "Run as administrator")
- Check `python labsch_agent.py --once` — should print JSON config
- If it says "Permission denied" for `C:\Windows\System32\drivers\etc\hosts`,
  the PowerShell was not elevated

**Browser still blocks after config cleared**
- Restart Chrome fully: `taskkill /f /im chrome.exe` then reopen
- Check `chrome://policy` → "URLBlocklist" should be empty
- The agent deletes keys on clear (not sets to empty) so this should not
  happen unless Chrome cached the old policy

**Agent keeps getting killed by student**
- Run `python labsch_agent.py --protect --lockdown` to re-install protection
- Verify with: `schtasks /query /tn LabSCHAgentWatchdog`

**Multiple client records for same PC**
- This is normal during the first few agent restarts; the server de-dups by
  `device_id` within a few heartbeats. Old duplicates can be cleaned up:
  `python3 /tmp/cleanup_clients.py` (only on the server)

**Tunnel URL changed after restart**
- Cloudflare quick tunnel uses a random subdomain. To get a stable URL, switch to a named tunnel (one-time setup):
  ```bash
  # Install cloudflared (one-time, Debian/Ubuntu)
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
  sudo dpkg -i /tmp/cloudflared.deb

  # Login + create + route + run
  cloudflared tunnel login
  cloudflared tunnel create labsch-server
  cloudflared tunnel route dns labsch-server labsch.yourdomain.com
  cloudflared tunnel run labsch-server
  ```
  After that, `https://labsch.yourdomain.com` is permanent. See
  `README.md` "Server setup" section for the full guide.

## File map

```
labsch/
├── server/
│   ├── api.py              # FastAPI endpoints
│   ├── db.py               # SQLite + migrations
│   ├── start_tunnel.sh     # Cloudflare quick tunnel starter
│   └── venv/               # Python 3.14 + fastapi + uvicorn + psutil
├── agent/
│   ├── labsch_agent.py     # Main loop
│   ├── config_sync.py      # HTTP client
│   ├── website_blocker.py  # Hosts file editor
│   ├── browser_policy.py   # Edge/Chrome/Brave registry policy
│   ├── ifeo_blocker.py     # Windows IFEO Debugger
│   ├── app_blocker.py      # psutil fallback
│   ├── self_protect.py     # --protect / --unprotect
│   ├── device_id.py        # MAC-based stable ID
│   ├── install.bat         # 1-click installer (asks name + is_test)
│   ├── uninstall.bat       # Clean uninstall
│   ├── build.bat           # PyInstaller .exe builder
│   └── install_service.py  # Windows service wrapper
├── skill/
│   ├── SKILL.md            # This file
│   └── labschctl           # Admin CLI
└── docs/
    ├── ARCHITECTURE.md
    └── ALLOWLIST_BAT.md    # Reference: FULL ALLOWLIST WEB v4 BAT scripts
```

## API quick reference

All admin endpoints require `X-Agent-Token: <token>` header.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check |
| POST | `/api/heartbeat` | Agent heartbeat (returns config) |
| GET | `/api/config` | Agent config pull |
| GET | `/api/clients` | List all clients |
| GET | `/api/clients/{id}` | Client detail |
| GET | `/api/events` | Recent events |
| GET | `/api/admin/config` | Live config |
| POST | `/api/admin/config` | Replace config (full update) |
| POST | `/api/admin/block-site` | Add site to blocklist |
| POST | `/api/admin/unblock-site` | Remove site from blocklist |
| POST | `/api/admin/block-app` | Add app to blocklist |
| POST | `/api/admin/unblock-app` | Remove app from blocklist |
| POST | `/api/admin/allow-site` | Add site to allowlist |
| POST | `/api/admin/clear-blocked-websites` | Clear all blocked sites |
| POST | `/api/admin/clear-blocked-apps` | Clear all blocked apps |
| POST | `/api/admin/clear-allowed-websites` | Clear allowlist |
| POST | `/api/admin/profiles` | Create or update profile |
| GET | `/api/admin/profiles` | List profiles |
| GET | `/api/admin/profiles/{name}` | Get one profile |
| DELETE | `/api/admin/profiles/{name}` | Delete profile |
| POST | `/api/admin/profiles/{name}/activate` | Apply profile to live config |

## Security notes

- All admin endpoints require the `X-Agent-Token` header. Keep the token
  out of Discord / WhatsApp / public chats.
- `install.bat` embeds the token by default. For multi-tenant deployments
  (e.g. 2 schools), generate a unique token per school and rebuild the
  zip without embedding.
- The agent config file at `C:\ProgramData\LabSCHAgent\config.ini` is
  readable by the user. If a student reads it, they get the tunnel URL
  and token — but without admin rights they can't open the tunnel since
  the homeserver validates the token. Still, rotate the token if a
  school laptop is compromised.

## Skill commands (when used via Hermes)

The admin CLI is available at `~/.hermes/skills/labsch/labschctl`. Hermes
calls it directly. If the user asks for something this skill can't do,
just say so — the CLI itself has `--help` for all subcommands.
