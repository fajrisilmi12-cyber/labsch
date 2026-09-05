# Server lifecycle — systemd setup for LabSCH

The FastAPI server must run as a systemd unit or it dies on every reboot.
This reference covers the full lifecycle: install, verify, troubleshoot.

## TL;DR install one-liner

If the unit file doesn't exist yet:

```bash
sudo tee /etc/systemd/system/labsch-server.service >/dev/null <<'EOF'
[Unit]
Description=LabSCH Manager API (FastAPI)
Documentation=file:///opt/labsch/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/labsch/server
EnvironmentFile=/root/.hermes/.env
ExecStart=/opt/labsch/server/venv/bin/python -m uvicorn api:app --host 0.0.0.0 --port 8080 --log-level info
Restart=always
RestartSec=5
TimeoutStopSec=10
StandardOutput=append:/var/log/labsch-server.log
StandardError=append:/var/log/labsch-server.log
NoNewPrivileges=false
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=/opt/labsch/server /var/log

[Install]
WantedBy=multi-user.target
EOF
sudo touch /var/log/labsch-server.log && sudo chmod 644 /var/log/labsch-server.log
sudo systemctl daemon-reload
sudo systemctl enable --now labsch-server.service
```

After 2s, verify with `sudo systemctl is-active labsch-server.service` →
expect `active`.

## Verify state (quick health check)

```bash
sudo systemctl is-enabled labsch-server.service   # enabled
sudo systemctl is-active  labsch-server.service   # active
ss -tlnp | grep ':8080'                           # LISTEN python
curl -s http://127.0.0.1:8080/api/health          # {"status":"ok","version":"0.2.0"}
```

All four must succeed. If any fails, see "Failure modes" below.

## Install / update `labschctl` to PATH

The CLI lives at `/usr/local/bin/labschctl` for system-wide use; the
copy at `~/.hermes/skills/labsch/labschctl` is the development source.

```bash
# Copy from skill bundle to system PATH (one-time)
sudo install -m 0755 ~/.hermes/skills/labsch/labschctl /usr/local/bin/labschctl

# Update after editing the skill copy
sudo install -m 0755 ~/.hermes/skills/labsch/labschctl /usr/local/bin/labschctl
```

## Failure modes & recovery

| Symptom | Cause | Fix |
|---------|-------|-----|
| `systemctl status` says `inactive (dead)` | Service was stopped manually or failed | `sudo systemctl start labsch-server.service` |
| `Unit not found` | Unit file never installed | Re-run install one-liner above |
| `failed (exit code)` in logs | Bad venv path, missing deps | Check `/var/log/labsch-server.log`; ensure `/opt/labsch/server/venv/bin/python -c "import fastapi"` works |
| Port 8080 occupied by another process | Stale python or wrong app | `ss -tlnp \| grep :8080` → kill stray PID |
| Health 200 but `labschctl` says "Name or service not known" | CLI reading dead `SCHOOL_SERVER_URL` from `.env` | Run `LABSCH_URL=http://127.0.0.1:8080 labschctl health` |
| Token mismatch (HTTP 401) | New `.env` lost the token | `grep SCHOOL_API_TOKEN /root/.hermes/.env` — must match the one clients have |

## Log locations

- `journalctl -u labsch-server.service -n 100 --no-pager` — systemd journal
- `/var/log/labsch-server.log` — direct file (set via `StandardOutput=append:`)
- SQLite at `/opt/labsch/server/data/labsch.db`

## Restart policy

`Restart=always` + `RestartSec=5` means a crash is recovered automatically.
If you need to stop the service for maintenance:

```bash
sudo systemctl stop labsch-server.service
# do work
sudo systemctl start labsch-server.service
```

`kill <pid>` does NOT cleanly stop a systemd-managed process — always use
`systemctl stop` (then `disable` if you want it gone after reboot).

## Why not just `nohup python ... &`?

Because:

1. No auto-restart on crash.
2. Lost on every reboot (memory said "LabSCH server was running" but it
   wasn't — recurring confusion in past sessions).
3. No log rotation.
4. No clean shutdown signal on system halt.

systemd fixes all four for free.

## Original install (2026-09-01)

Installed by Mona in WA session with Fajri. Verified via:
- `systemctl is-enabled` → enabled
- `systemctl is-active` → active
- Port 8080 listen (python pid 653664)
- `curl /api/health` → 200 OK, version 0.2.0
- `labschctl health/clients/config` → all rc=0