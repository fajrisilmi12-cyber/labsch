# Architecture

## High-level flow

```
[Admin (CLI)]
    │  HTTPS REST
    ▼
[Server: FastAPI + SQLite]
    │  HTTPS polling
    ▼
[Agent: Python on each Windows PC]
    │
    ▼
[Windows: registry + hosts + services]
```

The system is **pull-based** by design. Each agent decides when to poll.
There is no persistent connection from server to client. This eliminates:

- **Firewall issues** — clients make outbound HTTPS only, no inbound ports
- **NAT traversal** — clients reach the server, not the other way around
- **DDNS / dynamic IP** — only the server needs a stable URL (via Cloudflare tunnel)
- **Disconnection resilience** — if a PC is offline for a day, no state is lost;
  it picks up the current config on reconnect

## Server

`server/api.py` exposes the REST API. All endpoints except `/api/health`
require `X-Agent-Token` header. Token is a UUID generated once and stored
in `~/.hermes/.env` (server side) + embedded in `install.bat` (client side).

### Tables

```sql
clients        -- one row per device, keyed by client_id, de-duped by device_id
config         -- single-row live blocklist
events         -- append-only log of agent activity
profiles       -- named saved configs
active_profile -- (reserved for future: which profile is currently active)
```

### Migrations

Schema changes use a 3-step process in `db.py`:

1. `CREATE TABLE IF NOT EXISTS` with the OLD schema (compatible)
2. `PRAGMA table_info(clients)` to inspect actual columns
3. `ALTER TABLE clients ADD COLUMN ...` for any missing columns

This means you can deploy a new server version over an old database without
data loss. No external migration tool needed.

### Background task

`asyncio.create_task(periodic_mark_stale())` runs every 30 seconds and
marks clients as `offline` if `last_seen > 90s`. The CLI's `pp_clients`
function uses this to display "1m ago" / "1h ago" / "offline" status.

## Agent

`agent/labsch_agent.py` is the entry point. The main loop:

```python
while True:
    now = time.time()

    # 1. Heartbeat (every 30s)
    if now - last_heartbeat >= 30:
        cfg_resp = client.heartbeat(...)
        last_heartbeat = now
        if client.has_config_changed(cfg_resp):
            apply_all_layers(...)

    # 2. App kill (every 5s)
    if now - last_app_kill >= 5:
        killed = app_blocker.kill_blocked_processes(...)
        last_app_kill = now

    time.sleep(1)
```

The three blocking layers are applied in this order, all inside
`apply_all_layers`:

1. **Hosts file** — `website_blocker.apply_blocklist()` writes/cleans
   `C:\Windows\System32\drivers\etc\hosts`.
2. **Browser policy** — `browser_policy.apply_browser_policy()` writes
   `HKLM\SOFTWARE\Policies\...` registry keys for Edge/Chrome/Brave.
3. **IFEO** — `ifeo_blocker.block_apps_ifeo()` writes registry Debugger
   values for each blocked `.exe`.

If config is empty, the **clear** path is used (deletes keys, not sets to
empty) to avoid stale Chromium policy caching.

## Tunnel

The server listens on `localhost:8080` only (no public binding). The
`cloudflared` daemon exposes it via a `trycloudflare.com` URL. The URL
is stored in `~/.hermes/.env` as `SCHOOL_SERVER_URL`.

For production:
- Quick tunnel (default): random URL, free, ephemeral
- Named tunnel: stable URL, free, requires `cloudflared tunnel login` once

## Resource profile

Server: 256 MB RAM, 1 vCPU, SQLite WAL mode. Comfortable for 100+ clients
heartbeating every 30 seconds (peak: ~3 req/sec, well under any limits).

Client: ~30 MB RAM (Python 3.14 + psutil), ~0% CPU idle, ~1% CPU during
the brief 1-2 second window when applying a config change.

## Security model

### What the agent blocks
- Direct process kill (if a blocked app sneaks past IFEO)
- Hosts file writes (bypass for software that respects hosts)
- Browser policy (registry-based, hard to override without admin)
- IFEO (OS-level, applies before process start)

### What the agent CANNOT block
- A student with physical access and a Linux live USB can boot into
  another OS and bypass everything. This is a general limitation of
  any software-based control; hardware-based (BIOS lock, drive encryption)
  is the only true defense. For school lab use, the threat model is
  the student during class time, which this handles well.

### Token security
- `X-Agent-Token` is a UUID, 128 bits of entropy
- Transmitted over HTTPS (Cloudflare tunnel)
- Stored in `config.ini` on the client (readable by user with admin
  rights, which is unavoidable)
- For multi-tenant deployments (multiple schools), each school gets a
  unique token

## File layout

```
labsch/
├── server/
│   ├── api.py            # FastAPI endpoints
│   ├── db.py             # SQLite + migrations
│   ├── start_tunnel.sh   # Cloudflare quick tunnel
│   └── venv/             # Python 3.14 venv
├── agent/
│   ├── labsch_agent.py   # Main loop
│   ├── config_sync.py    # HTTP client (urllib)
│   ├── website_blocker.py
│   ├── app_blocker.py
│   ├── browser_policy.py
│   ├── ifeo_blocker.py
│   ├── self_protect.py
│   ├── device_id.py
│   ├── install.bat       # 1-click installer
│   ├── uninstall.bat
│   ├── build.bat         # PyInstaller
│   └── install_service.py
├── skill/
│   ├── SKILL.md
│   └── labschctl         # Admin CLI
└── docs/
    ├── ARCHITECTURE.md   # This file
    ├── API.md
    └── ALLOWLIST_BAT.md
```

## Versioning

`version` is a single string (`0.1.0`). It is included in the agent
heartbeat and stored in the `clients.version` column for tracking
deployment progress.
