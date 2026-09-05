---
name: labsch
description: Lab School Manager — manage 20+ Windows lab PCs from a single Hermes homeserver. Use when user asks to install/uninstall LabSCH agent on lab PCs, block websites or apps centrally, push rule profiles, view client status, remote shutdown/restart a PC, or troubleshoot agent/server connectivity. Also load when the server itself isn't running, when systemd needs to be set up, or when the Cloudflare tunnel URL changes.
version: 0.3.2
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

- "LabSCH" / "lab school manager" / "Madani Agent" (legacy name)
- "install agent ke PC" / "deploy ke 20 lab" / "blocking di lab"
- "block youtube" / "block roblox" / "block tiktok"
- "profile Rules Lab" / "aktifkan profile"
- "client offline" / "agent tidak connect"
- "labschctl" / "labsch-agent-v*.zip"
- "server mati" / "hidupkan server" / "systemd labsch"
- "shutdown TesPC" / "restart PC-LAB-01" (remote command)
- "tunnel trycloudflare" / "tunnel mati"

## Architecture (pull-based)

```
┌──────────────────────────────────┐
│  Hermes homeserver               │
│  (server/api.py + db.py)         │
│  FastAPI + SQLite                │
│  systemd-managed on port 8080    │
│  Cloudflare tunnel (optional)    │
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

- `server/api.py` — FastAPI endpoints (heartbeat, config, admin, profiles, override, command)
- `server/db.py` — SQLite layer (clients, config, events, profiles, overrides)
- `agent/labsch_agent.py` — main loop
- `agent/browser_policy.py` — Edge/Chrome/Brave registry policy (DoH-proof)
- `agent/ifeo_blocker.py` — Windows IFEO Debugger (un-killable app block)
- `agent/self_protect.py` — scheduled task + Run key (auto-respawn)
- `agent/device_id.py` — MAC-based stable client ID

## Server lifecycle (READ FIRST)

The FastAPI server runs at `/opt/labsch/server/` (venv at `server/venv/`).
**It must be systemd-managed or it dies on reboot.** Verify state before
doing anything else:

```bash
systemctl is-enabled labsch-server.service   # expected: enabled
systemctl is-active  labsch-server.service   # expected: active
ss -tlnp | grep ':8080'                      # expected: LISTEN python
curl -s http://127.0.0.1:8080/api/health     # expected: {"status":"ok"...}
```

If any check fails, see `references/server-lifecycle.md` for the full
setup recipe (unit file, logs, restart-on-failure, install one-liner).

### Token & URL

Server reads auth + URL from `/root/.hermes/.env`:

```
SCHOOL_API_TOKEN=<uuid>          # auto-generated on first run
SCHOOL_SERVER_URL=https://...    # used by AGENTS, baked into install.bat
```

**Pitfall**: `SCHOOL_SERVER_URL` points to the Cloudflare quick-tunnel
URL, which rotates every tunnel restart. Agents re-read this from their
own config; the admin CLI on the homeserver should talk to localhost.

**`labschctl` URL resolution**: the CLI reads `SCHOOL_SERVER_URL` from
`~/.hermes/.env` and uses it verbatim — there is no `LABSCH_URL`
override and no localhost default. If that URL points at a dead tunnel,
`labschctl` fails with `Name or service not known`. Fix by pointing
`.env` at the local systemd-managed server:

```bash
sed -i 's|SCHOOL_SERVER_URL=.*|SCHOOL_SERVER_URL=http://127.0.0.1:8080|' /root/.hermes/.env
```

(The agent `install.bat` reads the same `.env` — if you flip this
variable for the CLI, re-bake the agent zip or PCs will point to
localhost too.)

## Quick start (admin)

Source for the CLI lives at `/opt/labsch/skill/labschctl` (also
`/opt/github-repos/labsch/skill/labschctl`). There is **no** system-wide
install at `/usr/local/bin/labschctl` — call the source file directly or
`ln -s` it. Subcommand layout is `config <action>`, not flat top-level
verbs (the older `block-site` / `clear-blocked-sites` layout is gone).

```bash
# List all clients
labschctl clients
labschctl client <id>             # detail

# Show / edit live blocklist
labschctl config show
labschctl config block-site tiktok.com
labschctl config unblock-site tiktok.com
labschctl config block-app RobloxPlayerLauncher.exe
labschctl config unblock-app RobloxPlayerLauncher.exe
labschctl config allow-site wikipedia.org

# Bulk clear (three sub-actions)
labschctl config clear-websites
labschctl config clear-apps
labschctl config clear-allowed

# One-shot: nuke everything (sites + allowed + apps in one call)
labschctl unblock-all

# Saved rule profiles (e.g. "Rules Lab", "Ujian", "Bebas Akses")
labschctl profile list
labschctl profile show "Rules Lab"
labschctl profile save "Rules Lab"   # snapshot current live config
labschctl profile activate "Rules Lab"
labschctl profile delete "Rules Lab"

# Per-PC blocking override
labschctl client-config show <client-or-name>
labschctl client-config set <client-or-name> \
  --blocked-site youtube.com \
  --allowed-site google.com \
  --blocked-app  RobloxPlayerBeta.exe
labschctl client-config clear <client-or-name>

# Remote command (shutdown / restart / lock / notify) — accepts display_name
labschctl command shutdown TesPC
labschctl command restart "PC-LAB-01"
labschctl command lock TesPC                   # Windows+L (lock the workstation)
labschctl command notify TesPC -m "Jangan buka aneh2"   # popup message
labschctl command cancel TesPC

# Bulk remote command (v0.2.1+)
labschctl command-all shutdown --online-only --yes
labschctl command-all restart  --online-only --yes
labschctl command-all lock     --online-only --yes
labschctl command-all notify   --online-only --yes -m "Hei semua, waktunya pulang"
labschctl command-all cancel

# Audit / rename / health
labschctl events --hours 1
labschctl rename <client_id> "PC-LAB-01"
labschctl health
```

Note: client IDs look like `desktop-3d1knvb-ec8871bc` (long). The `command`
and `client-config` subcommands resolve display names (`TesPC`,
`PC-LAB-01`) automatically by looking up `/api/clients` first.

## Deploy to a new PC

1. **Download the zip** from the Discord `#general-chat` channel
   (latest: `labsch-agent-v0.2.0.zip`).
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

## Per-PC override

To prevent a PC from inheriting global rules, save an explicit empty override:

```bash
labschctl client-config set <client_id>
```

This is different from `client-config clear`: `clear` removes the override
and returns the PC to global inheritance. An empty `set` keeps that PC free
while the rest of the lab follows global rules.

## Profile (named ruleset) workflow

1. Set up the live config exactly how you want it:
   ```bash
   labschctl block-site tiktok.com
   labschctl allow-site wikipedia.org
   labschctl block-app RobloxPlayerLauncher.exe
   ```
2. Save it as a named profile:
   ```bash
   labschctl profile create "Rules Lab" \
     --block-site tiktok.com \
     --allow-site wikipedia.org \
     --block-app  RobloxPlayerLauncher.exe
   ```
3. Later, restore it with one command:
   ```bash
   labschctl profile activate "Rules Lab"
   ```

Multiple profiles can coexist (e.g. `Rules Lab`, `Ujian`, `Bebas Akses`,
`Maintenance`). Switching is a single command and bumps the config version,
which the agents pull on their next 60-second cycle.

## Remote command (shutdown / restart / lock / notify)

For v0.2.0+, the heartbeat response includes a `pending_command` field. The
agent checks for a queued command on every heartbeat and acts on it.

```bash
labschctl command shutdown TesPC            # queue shutdown (shutdown /s /t 5)
labschctl command restart  TesPC            # queue restart  (shutdown /r /t 5)
labschctl command lock     TesPC            # lock workstation (Windows+L via rundll32)
labschctl command notify   TesPC -m "..."   # popup MessageBox on the PC
labschctl command cancel   TesPC            # undo before agent picks it up
```

The command is delivered on the next 30s heartbeat, so worst-case latency
is 30s + OS shutdown time. The agent runs the command locally and clears
the queue. There is no built-in confirmation ping back.

### `lock` — Windows+L

Runs `rundll32.exe user32.dll,LockWorkStation` on the target. The user
sees the lock screen immediately. Nothing else changes — they can
log back in with their existing password. Useful for "berhenti dulu"
without losing their work, or for quickly securing a PC that's been
left unattended. There is no remote unlock — the user has to type
their password at the workstation.

### `notify` — popup message

Pops up a Windows `MessageBox` (Info icon, OK button) with the text
you provide. The `--message` / `-m` flag is **required** for `notify`:

```bash
labschctl command notify TesPC -m "Jangan buka situs aneh-aneh"
labschctl command-all notify --online-only --yes -m "Waktu istirahat 15 menit"
```

The server stores `pending_command_message` alongside `pending_command`
in the `clients` table. The agent runs a PowerShell
`System.Windows.Forms.MessageBox::Show` subprocess to render the popup.
Quirks worth knowing:

- The popup is **modal** — it blocks input on the focused session
  until the user clicks OK. Don't use it for non-urgent messages.
- The message is **URL-decoded** by the server (the CLI calls `quote()`
  for transport). The agent sees a decoded string. Pass plain text;
  don't pre-encode.
- There's no rate limit, but if you fire 50 `notify` commands to 50
  PCs in a row, you get 50 MessageBox popups — use `command-all` with
  a single message, not 50 individual `notify` calls.
- The MessageBox runs as the user, so it appears on the **active
  session** of the logged-in user. Locked or RDP-only PCs may not
  show it visibly.

### Bulk remote command (v0.2.1+, `command-all`)

For "matikan semua PC sekaligus" / "kelas bubar" scenarios:

```bash
labschctl command-all shutdown                       # all registered clients
labschctl command-all shutdown --online-only         # only status=online
labschctl command-all restart  --online-only --yes   # skip confirmation
labschctl command-all lock     --online-only --yes
labschctl command-all notify   --online-only --yes -m "Hei, ini pesan broadcast"
labschctl command-all cancel                         # clear all pending commands
```

- Without `--yes`, prints the target list (with `is_test` markers) + a
  `Proceed? [y/N]` prompt. Default to `--online-only --yes` for
  school-day scenarios.
- `cancel` only touches clients that already have `pending_command` set;
  silent no-op for the rest.
- Same queue + heartbeat pickup as per-PC `command`. Each client gets its
  own `pending_command` row, processed independently on its next 30s tick.

### Offline clients still get the command

The `pending_command` is stored on the server side, so a command queued
against an **offline** client will execute the next time that PC boots
and its agent sends a heartbeat (≤30s after boot). This is useful for
"shutdown Lab8 tonight" workflows even when the student left the PC on
standby, but be aware: if you queue `shutdown` against a PC the student
turns on tomorrow morning, **it will shut down within 30 seconds of
boot**. Use `command cancel <name>` to clear queued commands before
letting a PC come back online.

### What the remote-command path does NOT do

The agent only sets `pending_command` and runs `shutdown /s /t 5` or
`shutdown /r /t 5`. It cannot:
- **Kill a specific process** (e.g. `taskkill chrome.exe`). To stop an
  already-running app, `block-app` (IFEO) only blocks *future* launches
  of that exe; running processes are not terminated. For "kill chrome
  on Lab3", the admin has to RDP/AnyDesk in and run `taskkill` manually.
- Show a "are you sure?" dialog on the target PC.
- Cancel a `shutdown /t 5` already in flight, except by the user pressing
  `shutdown /a` within the 5-second window.

**Safety note**: there is no auth check on this endpoint beyond the shared
API token. If the token leaks, anyone with it can shut down the entire
school. Treat the token like a root password. The `command-all` form
amplifies the blast radius — rotate the token if any PC leaks it.

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

SQLite at `/opt/labsch/server/data/labsch.db`. Tables:

- `clients` — registered PCs (`client_id`, `device_id`, `mac`, `display_name`,
  `is_test`, `hostname`, `ip`, `status`, `last_seen`, `first_seen`)
- `config` — single-row live config (`blocked_apps`, `blocked_websites`,
  `allowed_websites`, `config_version`)
- `profiles` — named saved configs (same columns as `config` + `created_at`,
  `activated_at`)
- `client_overrides` — per-PC overrides (same 3 lists + `updated_at`)
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
  "version": "0.2.0"
}
```

The server's URL and token are embedded in `install.bat` defaults, so most
installs just need to answer the two prompts.

## Troubleshooting

**Server is down (port 8080 not listening)**
```bash
sudo systemctl status labsch-server.service
sudo journalctl -u labsch-server.service -n 50 --no-pager
tail -50 /var/log/labsch-server.log
```
If the unit doesn't exist, run the install one-liner in
`references/server-lifecycle.md`.

**`labschctl` fails with "Name or service not known"**
The CLI uses `SCHOOL_SERVER_URL` from `~/.hermes/.env` verbatim, and that
variable still points to a dead Cloudflare quick-tunnel. The CLI does
NOT fall back to localhost. Fix:
```bash
sed -i 's|SCHOOL_SERVER_URL=.*|SCHOOL_SERVER_URL=http://127.0.0.1:8080|' /root/.hermes/.env
```
Then re-run. (If you need the tunnel up for the agents, restart
`cloudflared` and update the variable back to the new URL — but make
sure to re-bake the agent zip first.)

**`labschctl: error: argument cmd: invalid choice`**
The subcommand layout was rewritten. Top-level verbs like `block-site`,
`unblock-site`, `clear-blocked-sites`, `clear-blocked-apps` no longer
exist. New layout:
- `labschctl config block-site <domain>` (not `labschctl block-site ...`)
- `labschctl config clear-websites` (not `clear-blocked-sites`)
- `labschctl config clear-apps` (not `clear-blocked-apps`)
- `labschctl config clear-allowed` (not `clear-allowed-sites`)
- `labschctl unblock-all` — one-shot to nuke all three lists
- `labschctl profile save <name>` (not `profile create`)
- `labschctl rename <client_id> <display_name>` — new
- `labschctl client <id>` — new
Run `labschctl --help` to see the full current list.

**`AttributeError: 'Namespace' object has no attribute 'name'`**
You ran an old subcommand name against the new CLI. Same fix as above
— use the `config <action>` form. This used to silently no-op via the
old bug; now it crashes loudly.

**Tunnel URL changed after restart**
Cloudflare quick tunnel uses a random subdomain. Two options:
1. Just restart the tunnel — agents re-resolve via `SCHOOL_SERVER_URL` on
   next config pull, but the URL they have stored is stale. Plan a
   re-deploy (rebuild zip with new URL, push to all PCs).
2. Switch to a named tunnel (stable subdomain). See `README.md` "Server
   setup" section for the full guide. The cloudflare-tunnel skill has the
   command sequence.

**`start_tunnel.sh` says "cloudflared not found"**
The script has a fallback chain: `command -v cloudflared` → `/usr/local/bin` →
`/usr/bin` → `/root/.9router/bin/cloudflared`. The 9Router path was a common
case when 9Router was installed as a packaged app, but if 9Router was
uninstalled (`rm -rf /root/.9router`) the binary dies with it. Reinstall
cloudflared from the official `.deb` (works on Arch via `ar` + `tar` — no
`dpkg` needed; see `references/cloudflared-recovery.md` for the recipe).

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
This is normal during the first few agent restarts; the server de-dups by
`device_id` within a few heartbeats. Old duplicates can be cleaned up with
the SQL in `references/cleanup-queries.md`.

**`labschctl client-config set TesPC` says "client not found"**
The display_name didn't match. List clients first (`labschctl clients`)
and use either the `display_name` or the full `client_id`. **Match is
case-sensitive AND whitespace-sensitive** — `Laptop ASUS` (with space)
and `LaptopAsus` (no space) are different clients to the resolver. The
resolver matches `name.lower() in (display.lower(), hostname.lower(),
client_id.lower())` against what the agent sent during install. If a
PC was installed as "LaptopAsus" (no space, as typed in `install.bat`),
calling `labschctl command restart "Laptop ASUS"` returns
`HTTP 404: client not found`. Fix: use the exact string the install
prompt captured, or `labschctl clients` to copy-paste the canonical
form. To normalize, `labschctl rename <client_id> "Laptop ASUS"`
renames the record so future lookups work with the new spelling — but
the rename only updates the server-side record, the agent's local
display_name in `config.ini` stays as it was at install time.

**`command shutdown` becomes a loop — the PC keeps coming back**
This is the most operationally surprising issue, and it is **not a
LabSCH bug**: Windows machines whose BIOS has "Restore on AC Power
Loss" set to **Power On** will boot themselves as soon as electricity
returns. Combined with the `LabSCHAgentWatchdog` scheduled task and
the `HKLM\...\Run\LabSCHAgent` entry, the PC:
1. Boots from BIOS power-on
2. Agent starts automatically (Run key)
3. Sends heartbeat → server still has `pending_command=shutdown` queued
4. Agent runs `shutdown /s /t 5`
5. PC powers off → mains still has power → BIOS powers it back on
6. Goto 1

This is observed regularly on LabSCH-managed school PCs. Two
mitigations, in order of how much admin trust you want to keep:

- **Per-PC fix (best)**: shut down the PC, enter BIOS, find
  "Restore on AC Power Loss" (under Power Management / ACPI
  Configuration depending on vendor), set it to **Power Off** (or
  "Last State" on some boards). Save and exit. The PC will then stay
  off when AC is interrupted.
- **Server-side workaround**: after queueing `command shutdown`,
  also use `command cancel` after a few minutes. The `pending_command`
  is cleared by the agent on pickup, but if the PC keeps coming back
  before the agent re-queues, this won't help. The real fix is BIOS.
- **Group shutdown sanity check**: if `labschctl clients` shows a
  bunch of PCs going `online → shutdown pending → online` in a tight
  loop in `/api/events`, it's BIOS power-on, not a network storm.

**`notify` shows up as URL-encoded gibberish in the DB**
Symptom: `sqlite3 ... "SELECT pending_command_message FROM clients"`
returns `jangan%20buka%20aneh2` instead of `jangan buka aneh2`. The
CLI correctly calls `urllib.parse.quote()` to encode the message for
the URL transport, but the server endpoint must call
`urllib.parse.unquote()` before storing. If the server's `unquote()`
call is missing or skipped, the agent will pop up a MessageBox with
`jangan%20buka%20aneh2` literally. Check `server/api.py`
`set_client_command` — it should look like:
```python
if message:
    from urllib.parse import unquote
    message = unquote(message)
ok = db.set_client_command(client_id, command, message)
```
If you see encoded text in the DB, run `labschctl command cancel
<name>` to clear the bad row and re-issue the command — the fix
takes effect immediately on the next `notify` queue.

**`labschctl command notify` says "notify requires --message"**
The CLI refuses to queue `notify` without a `-m` / `--message` text.
This is intentional: a blank MessageBox on a user-facing PC is
worse than no notification. If you genuinely want to test the path
without a real message, pass `-m "test"` or any non-empty string.

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
│   ├── labschctl           # Admin CLI (source — also at /usr/local/bin)
│   └── references/         # Server lifecycle, SQL cleanup
└── docs/
    ├── ARCHITECTURE.md
    └── ALLOWLIST_BAT.md    # Reference: FULL ALLOWLIST WEB v4 BAT scripts
```

## API quick reference

All admin endpoints require `X-Agent-Token: <token>` header.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Health check |
| POST | `/api/heartbeat` | Agent heartbeat (returns config + pending_command) |
| GET | `/api/config` | Agent config pull |
| GET | `/api/clients` | List all clients — **requires** `X-Agent-Token` (401 without) |
| GET | `/api/clients/{id}` | Client detail |
| POST | `/api/event` | Agent event log |
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
| GET | `/api/clients/{id}/override` | Get per-PC override |
| PUT | `/api/clients/{id}/override` | Set per-PC override |
| DELETE | `/api/clients/{id}/override` | Clear per-PC override |
| POST | `/api/admin/command/{id}` | Queue remote shutdown/restart — `?command=shutdown` as **query param**, NOT body (422 if body) |
| DELETE | `/api/admin/command/{id}` | Cancel queued command |
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
- The remote-shutdown endpoint has no per-PC allowlist. Anyone with the
  API token can shut down any registered PC. Treat the token like a root
  password.

## Skill commands (when used via Hermes)

The admin CLI source is at `/opt/labsch/skill/labschctl` (also reachable
via `/root/.hermes/skills/labsch/labschctl` — same file, the skill
directory is a symlink). There is no `/usr/local/bin/labschctl`
install — call the source file directly, or symlink it. Run
`labschctl --help` first; the layout has changed at least once
already and the help text is the source of truth.

## Reference files

- `references/server-lifecycle.md` — systemd unit template, install
  one-liner, log locations, restart-on-failure recipe
- `references/cleanup-queries.md` — SQL for removing duplicate client
  records, resetting config version, archiving old events
- `references/cloudflared-recovery.md` — what to do when
  `start_tunnel.sh` says "cloudflared not found" (Arch `.deb` extract,
  why the 9Router-bundled binary disappears when 9Router is removed)
- `references/api-cookbook.md` — copy-paste curl recipes for the direct API path
  (resolve display_name → client_id, queue shutdown/restart/cancel, verify
  pending, bulk operations, OpenAPI as ground truth for parameter shapes)
- `references/override-semantics.md` — `client-config set` vs
  `clear` vs `unblock-all` vs per-PC override, with the matrix
  of "what does this PC actually see after each command"
