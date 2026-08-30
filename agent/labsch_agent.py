"""Main LabSCHAgent — runs as scheduled loop, can also be installed as Windows service.

Usage:
  # Run as foreground process (testing)
  python3 labsch_agent.py

  # Run as Windows service (after install)
  python3 labsch_agent.py --service
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Make sibling modules importable when run as script
sys.path.insert(0, str(Path(__file__).parent))

import config_sync
import app_blocker
import website_blocker
import ifeo_blocker
import browser_policy
import self_protect
import device_id

# Config
DEFAULT_HEARTBEAT_INTERVAL = 30  # seconds
DEFAULT_CONFIG_PULL_INTERVAL = 60
DEFAULT_APP_KILL_INTERVAL = 5

CONFIG_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHAgent"
CONFIG_FILE = CONFIG_DIR / "config.ini"


def load_agent_config() -> dict:
    """Load agent config from disk. Creates default if missing."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        default = {
            "server_url": os.environ.get("SCHOOL_SERVER_URL", "http://localhost:8080"),
            "api_token": os.environ.get("SCHOOL_API_TOKEN", ""),
            "client_id": os.environ.get("SCHOOL_CLIENT_ID", ""),
            "display_name": os.environ.get("SCHOOL_DISPLAY_NAME", ""),
            "is_test": False,
            "version": "0.1.0",
        }
        CONFIG_FILE.write_text(json.dumps(default, indent=2))
        return default
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    # Backfill new fields for old configs
    if "display_name" not in cfg:
        cfg["display_name"] = ""
    if "is_test" not in cfg:
        cfg["is_test"] = False
    return cfg


def save_agent_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_identity() -> tuple:
    """Return (hostname, ip, user)."""
    import socket
    import getpass
    hostname = socket.gethostname()
    try:
        ip = socket.gethostbyname(hostname)
    except (socket.gaierror, OSError):
        ip = "127.0.0.1"
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "unknown"
    return hostname, ip, user


def ensure_client_id(cfg: dict) -> str:
    """Generate client_id if missing."""
    cid = cfg.get("client_id", "").strip()
    if not cid:
        import uuid
        import platform
        # Use hostname + uuid suffix for human-readable id
        hostname = get_identity()[0]
        short = uuid.uuid4().hex[:8]
        cid = f"{hostname.lower()}-{short}"
        cfg["client_id"] = cid
        save_agent_config(cfg)
    return cid


def apply_config(cfg_resp, client, previous_blocked_apps):
    """Apply config to hosts, browser policy, and IFEO consistently."""
    blocked_apps = cfg_resp.get("blocked_apps", [])
    blocked_websites = cfg_resp.get("blocked_websites", [])
    allowed_websites = cfg_resp.get("allowed_websites", [])

    ok, msg = website_blocker.apply_blocklist(
        blocked_websites, allowed_websites, log_fn=print
    )

    if not blocked_websites and not allowed_websites:
        browser_count = browser_policy.clear_browser_policy(log_fn=print)
    else:
        browser_count = browser_policy.apply_browser_policy(
            blocked_websites, allowed_websites, log_fn=print
        )

    if blocked_apps:
        ifeo_count = ifeo_blocker.block_apps_ifeo(blocked_apps, log_fn=print)
        if ifeo_count:
            client.log_event("ifeo_applied", f"{ifeo_count} apps")
    else:
        blocked_now = ifeo_blocker.list_blocked_apps()
        for app in blocked_now:
            ifeo_blocker.unblock_app_via_ifeo(app, log_fn=print)
        if blocked_now:
            client.log_event("ifeo_cleared", f"{len(blocked_now)} apps")

    if ok or browser_count > 0 or blocked_apps != previous_blocked_apps:
        client.log_event(
            "config_applied",
            f"v{cfg_resp.get('config_version')}_hosts:{ok}_browsers:{browser_count}"
        )
    elif msg:
        client.log_event("config_apply_failed", msg)
    return blocked_apps, blocked_websites, allowed_websites


def run_loop(cfg: dict) -> None:
    """Main agent loop."""
    client_id = ensure_client_id(cfg)
    server_url = cfg["server_url"]
    api_token = cfg["api_token"]
    version = cfg.get("version", "0.1.0")

    if not api_token:
        print("FATAL: api_token not set. Run with --setup first.", file=sys.stderr)
        sys.exit(1)

    client = config_sync.AgentClient(server_url, api_token, client_id)
    hostname, ip, user = get_identity()
    dev_id = device_id.get_device_id()
    mac = device_id.get_primary_mac() or "unknown"
    display_name = cfg.get("display_name", "") or f"PC-{hostname}"
    is_test = bool(cfg.get("is_test", False))

    print(f"[labsch_agent] starting", flush=True)
    print(f"  client_id    = {client_id}", flush=True)
    print(f"  display_name = {display_name}", flush=True)
    print(f"  is_test      = {is_test}", flush=True)
    print(f"  device_id    = {dev_id}", flush=True)
    print(f"  mac          = {mac}", flush=True)
    print(f"  hostname     = {hostname}", flush=True)
    print(f"  ip           = {ip}", flush=True)
    print(f"  user         = {user}", flush=True)
    print(f"  server       = {server_url}", flush=True)
    print(f"  version      = {version}", flush=True)

    last_heartbeat = 0
    last_config_pull = 0
    last_app_kill = 0
    current_blocked_apps: list = []
    current_blocked_websites: list = []
    current_allowed_websites: list = []

    while True:
        now = time.time()
        try:
            # Heartbeat
            if now - last_heartbeat >= DEFAULT_HEARTBEAT_INTERVAL:
                cfg_resp = client.heartbeat(hostname, ip, user, version, dev_id, mac,
                                            display_name=display_name, is_test=is_test)
                if cfg_resp is not None:
                    last_heartbeat = now
                    # Heartbeat response includes config — use it
                    if client.has_config_changed(cfg_resp):
                        current_blocked_apps, current_blocked_websites, current_allowed_websites = apply_config(
                            cfg_resp, client, current_blocked_apps
                        )
                # else: server unreachable, will retry next cycle

            # Pull config (in case heartbeat didn't return config)
            if now - last_config_pull >= DEFAULT_CONFIG_PULL_INTERVAL:
                cfg_resp = client.get_config()
                if cfg_resp and client.has_config_changed(cfg_resp):
                    current_blocked_apps, current_blocked_websites, current_allowed_websites = apply_config(
                        cfg_resp, client, current_blocked_apps
                    )
                if cfg_resp is not None:
                    last_config_pull = now

            # Kill blocked apps
            if now - last_app_kill >= DEFAULT_APP_KILL_INTERVAL and current_blocked_apps:
                killed = app_blocker.block_apps(current_blocked_apps, log_fn=print)
                if killed:
                    for n in current_blocked_apps:
                        client.log_event("blocked_app", n)
                last_app_kill = now

        except Exception as e:
            print(f"[labsch_agent] loop error: {e}", file=sys.stderr)

        time.sleep(1)


def setup() -> None:
    """Interactive or CLI-driven setup: ask for server URL, token, write config."""
    import argparse
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--server", help="Server URL (skip prompt)")
    p.add_argument("--token", help="API token (skip prompt)")
    p.add_argument("--client-id", help="Client ID (blank=auto)")
    setup_args, _ = p.parse_known_args()

    print("=== LabSCHAgent Setup ===", flush=True)
    cfg = load_agent_config()

    # Server URL: CLI > input > existing
    if setup_args.server:
        cfg["server_url"] = setup_args.server
    else:
        try:
            val = input(f"Server URL [{cfg.get('server_url')}]: ").strip()
            cfg["server_url"] = val or cfg.get("server_url", "http://localhost:8080")
        except (EOFError, OSError):
            print("\n[!] No stdin available. Use --server and --token flags.")
            print(f"    Example: MadaniAgent.exe --setup --server https://abc.trycloudflare.com --token YOUR_TOKEN")
            return

    # API token: CLI > input > existing
    if setup_args.token:
        cfg["api_token"] = setup_args.token
    else:
        try:
            existing = cfg.get("api_token", "")[:8]
            val = input(f"API token [{existing}...]: ").strip()
            cfg["api_token"] = val or cfg.get("api_token", "")
        except (EOFError, OSError):
            print("[!] api_token not set. Use --token YOUR_TOKEN flag.")
            return

    # Client ID: optional
    if not cfg.get("client_id") and not setup_args.client_id:
        try:
            val = input("Client ID (blank=auto): ").strip()
            cfg["client_id"] = val or ""
        except (EOFError, OSError):
            pass
    elif setup_args.client_id:
        cfg["client_id"] = setup_args.client_id

    save_agent_config(cfg)
    print(f"Config saved to: {CONFIG_FILE}", flush=True)
    print(f"  server_url: {cfg['server_url']}", flush=True)
    print(f"  api_token:  {cfg['api_token'][:8]}...", flush=True)
    print(f"  client_id:  {cfg.get('client_id', '(auto)')}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="LabSCHAgent — labsch client")
    parser.add_argument("--setup", action="store_true", help="Interactive setup")
    parser.add_argument("--server", help="Server URL (for --setup)")
    parser.add_argument("--token", help="API token (for --setup)")
    parser.add_argument("--client-id", help="Client ID (for --setup)")
    parser.add_argument("--once", action="store_true", help="Run heartbeat once and exit")
    parser.add_argument("--protect", action="store_true", help="Install self-protection (run as Admin)")
    parser.add_argument("--unprotect", action="store_true", help="Remove self-protection")
    parser.add_argument("--lockdown", action="store_true", help="Disable Task Manager (with --protect)")
    args = parser.parse_args()

    if args.setup:
        # Pass flags to setup
        sys.argv = ["labsch_agent.py", "--setup"]
        if args.server:
            sys.argv += ["--server", args.server]
        if args.token:
            sys.argv += ["--token", args.token]
        if args.client_id:
            sys.argv += ["--client-id", args.client_id]
        setup()
        return

    cfg = load_agent_config()
    if args.protect:
        # Install self-protection layers
        agent_path = sys.executable  # python.exe or LabSCHAgent.exe
        if getattr(sys, 'frozen', False):
            agent_path = sys.executable
        else:
            # Running as script, use python.exe + script path
            agent_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        self_protect.install_self_protection(agent_path)
        if args.lockdown:
            self_protect.disable_task_manager()
        return
    if args.unprotect:
        self_protect.uninstall_self_protection()
        if args.lockdown:
            self_protect.enable_task_manager()
        return
    if args.once:
        client_id = ensure_client_id(cfg)
        client = config_sync.AgentClient(cfg["server_url"], cfg["api_token"], client_id)
        hostname, ip, user = get_identity()
        dev_id = device_id.get_device_id()
        mac = device_id.get_primary_mac() or "unknown"
        result = client.heartbeat(hostname, ip, user, cfg.get("version", "0.1.0"), dev_id, mac)
        print(json.dumps(result, indent=2) if result else "FAILED")
        return

    run_loop(cfg)


if __name__ == "__main__":
    main()
