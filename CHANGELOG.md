# Changelog

All notable changes to LabSCH are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
