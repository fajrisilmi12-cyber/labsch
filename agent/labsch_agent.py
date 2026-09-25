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
import re
import sys
import time
if os.name != "nt":
    import fcntl
import subprocess
from pathlib import Path

# v0.3.5 — enforce Python 3.10+ (Windows 10 LTSC 2021 baseline; walrus/pattern
# matching in helper code paths). Fail loudly instead of silently misbehaving.
if sys.version_info < (3, 10):
    print(
        f"FATAL: LabSCHAgent v0.3.5 requires Python 3.10 or newer (you have "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}).",
        file=sys.stderr,
    )
    sys.exit(2)

# Make sibling modules importable when run as script
sys.path.insert(0, str(Path(__file__).parent))

import config_sync
import app_blocker
import website_blocker
import ifeo_blocker
import browser_policy
import self_protect
import device_id
import device_blocker
import command_executor
from downloader import DownloadDispatcher
from version import AGENT_VERSION
from datetime import datetime, timezone

# v0.3.5 — subprocess.CREATE_NO_WINDOW so spawned reg.exe/schtasks.exe/etc.
# never flash a console window at the student. Constant is Windows-only;
# fall back to 0 on other platforms so dev on Linux still works.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0

# v0.3.5 — display_name rules mirror server regex
# (server-side: /^[A-Za-z0-9 ._-]{1,64}$/). Used for early validation so the
# user gets a clear local error instead of a server-side rejection.
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")

# v0.3.5 — single-instance file lock. Prevents two agent processes from
# simultaneously writing registry/hosts (last-writer-wins, inconsistent state).
LOCK_FILE = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHAgent" / "agent.lock"


def _acquire_single_instance_lock() -> int:
    """Acquire an exclusive cross-platform file lock for the agent singleton.

    Returns the fd on success. Raises OSError if another instance already
    holds the lock — caller should exit cleanly with a non-zero status.
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if os.name == "nt":
            import msvcrt
            os.write(fd, b" ")
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        os.close(fd)
        raise
    # Stash PID so the user / log can identify the holder if needed.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
        os.fsync(fd)
    except OSError:
        pass
    return fd


# v0.3.5 — chars that must NEVER appear in a 'notify' message: a single quote
# breaks the PowerShell single-quoted string, `$` enables sub-expression
# injection, parens enable call grouping, semicolons chain statements,
# backtick enables escape tricks, `\\` enables escape-sequence injection,
# and any non-printable / non-ASCII byte could break terminal output. The
# server already enforces this; this is defense-in-depth.
_NOTIFY_FORBIDDEN = set("'" + '"' + "$" + "`" + "()" + ";" + "\\" + "\n" + "\r" + "\0")


def _is_safe_notify_message(msg: str) -> bool:
    """Return True iff `msg` is safe to splice into a PowerShell single-quoted
    string. Length cap matches the server-side cap (200 chars).
    """
    if not isinstance(msg, str):
        return False
    if len(msg) == 0 or len(msg) > 200:
        return False
    if any(ord(c) < 0x20 or ord(c) > 0x7E for c in msg):
        return False
    if any(c in _NOTIFY_FORBIDDEN for c in msg):
        return False
    return True


def _ps_quote(s: str) -> str:
    """Quote a string for use as a single PowerShell command-line argument.

    PowerShell strips the outermost pair of double quotes from the
    -Command argument and concatenates the rest verbatim, so we wrap the
    payload in double quotes and escape embedded `"` and backticks. The
    order matters: we MUST double-escape backticks first (otherwise our
    own backtick-escaped `"` would itself get doubled).
    """
    return '"' + s.replace("`", "``").replace('"', '`"') + '"'


# Config
DEFAULT_HEARTBEAT_INTERVAL = 30  # seconds (overridable via config.ini: heartbeat_interval)
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
        _atomic_write_json(CONFIG_FILE, default)
        return default
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # Corrupt config: back it up, write a fresh default, don't crash.
        try:
            import time as _time
            stamp = _time.strftime("%Y%m%d-%H%M%S")
            backup = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.corrupt-{stamp}")
            try:
                import shutil as _shutil
                _shutil.copyfile(CONFIG_FILE, backup)
            except OSError:
                pass
        except Exception:
            pass
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        default = {
            "server_url": os.environ.get("SCHOOL_SERVER_URL", "http://localhost:8080"),
            "api_token": os.environ.get("SCHOOL_API_TOKEN", ""),
            "client_id": os.environ.get("SCHOOL_CLIENT_ID", ""),
            "display_name": os.environ.get("SCHOOL_DISPLAY_NAME", ""),
            "is_test": False,
            "version": "0.1.0",
        }
        try:
            _atomic_write_json(CONFIG_FILE, default)
        except OSError:
            pass
        return default
    # Backfill new fields for old configs
    if "display_name" not in cfg:
        cfg["display_name"] = ""
    if "is_test" not in cfg:
        cfg["is_test"] = False
    return cfg


def save_agent_config(cfg: dict) -> None:
    """v0.3.5 — atomic write so a crash mid-write never leaves a half-written
    config.json (which would brick the agent on next boot)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(CONFIG_FILE, cfg)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: temp file in same dir, then os.replace.

    Same-directory temp + os.replace is atomic on NTFS and POSIX, so the
    reader either sees the old file or the new one — never a torn write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        # Don't leave stale .tmp behind if replace failed.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


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
        import platform
        # Prefer a stable ID derived from device_id before random fallback.
        try:
            import device_id as _device_id
            dev = _device_id.get_device_id()
            # get_device_id returns e.g. 'dev-<16hex>' or 'host-<16hex>'
            hexpart = ""
            if isinstance(dev, str) and "-" in dev:
                hexpart = dev.split("-", 1)[1]
            hexpart = "".join(c for c in hexpart if c in "0123456789abcdefABCDEF")[:12].lower()
            if len(hexpart) == 12:
                hostname = get_identity()[0]
                cid = f"{hostname.lower()}-{hexpart}"
                cfg["client_id"] = cid
                save_agent_config(cfg)
                return cid
        except Exception:
            pass
        import uuid
        # Use hostname + uuid suffix for human-readable id
        hostname = get_identity()[0]
        short = uuid.uuid4().hex[:8]
        cid = f"{hostname.lower()}-{short}"
        cfg["client_id"] = cid
        save_agent_config(cfg)
    return cid


# ---------------------------------------------------------------------------
# LabSCH Launcher (kiosk) control — v0.4.1
# ---------------------------------------------------------------------------

LAUNCHER_STATE_FILE = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHLauncher" / "launcher.json"
_LAUNCHER_ADMIN_EXIT_GRACE = 90  # seconds; don't re-spawn right after an admin exit


def _launcher_state() -> dict:
    try:
        return json.loads(LAUNCHER_STATE_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _launcher_write_state(patch: dict) -> None:
    LAUNCHER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = _launcher_state()
    state.update(patch)
    tmp = LAUNCHER_STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, LAUNCHER_STATE_FILE)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass


def _launcher_running() -> bool:
    """True iff a labsch_launcher.py process is alive (check command line)."""
    try:
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -match 'labsch_launcher' } | "
              "Select-Object -First 1 -ExpandProperty ProcessId")
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        blob = out.stdout.decode("utf-8", errors="replace").strip() if isinstance(out.stdout, bytes) else str(out.stdout or "").strip()
        return bool(blob)
    except Exception:
        return False


def _launch_in_user_session(script: str) -> tuple[bool, str]:
    """Start launcher via windows_launch (console session, non-elevated)."""
    try:
        import windows_launch
        windows_launch.launch_user_file(script)
        return True, "dispatched to user session"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _launcher_start() -> tuple[bool, str]:
    """Enable kiosk mode + start launcher in the logged-in user's session."""
    _launcher_write_state({"kiosk_enabled": True})
    script = str(Path(__file__).resolve().parent / "labsch_launcher.py")
    if not Path(script).is_file():
        return False, f"launcher script missing: {script}"
    # Marker so the launcher window is identifiable in tasklist output.
    ok, reason = _launch_in_user_session(script)
    if ok:
        _launcher_write_state({"started_at": int(time.time())})
        _launcher_write_state({"spawn_pending": True})
    return ok, reason


def _launcher_stop() -> tuple[bool, str]:
    """Disable kiosk mode (agent stops re-spawning). Launcher itself stays
    password-protected — this flips the flag; process exit still needs admin
    password unless admin also confirms on the PC."""
    _launcher_write_state({"kiosk_enabled": False, "stopped_at": int(time.time())})
    return True, "kiosk mode disabled"


def _launcher_maybe_respawn() -> None:
    """Re-spawn launcher if kiosk mode is on and no launcher is running.
    Skipped briefly after a password-authenticated admin exit."""
    try:
        state = _launcher_state()
    except Exception:
        return
    if not state.get("kiosk_enabled"):
        return
    admin_exit_at = state.get("admin_exit_at")
    if admin_exit_at and time.time() - admin_exit_at < _LAUNCHER_ADMIN_EXIT_GRACE:
        return
    if _launcher_running():
        return
    script = Path(__file__).resolve().parent / "labsch_launcher.py"
    if script.is_file():
        _launch_in_user_session(str(script))


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


LAST_FAILURE = ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_health_report(last_heartbeat_iso, policy_status, launcher_status):
    """PC health report for heartbeat (v0.4.0 unified)."""
    return {
        "agent_version": AGENT_VERSION,
        "last_heartbeat": last_heartbeat_iso or "",
        "policy_status": policy_status or {},
        "launcher_status": launcher_status or "unknown",
        "last_failure": LAST_FAILURE,
    }


def save_health_report(report) -> None:
    try:
        base = os.environ.get("PROGRAMDATA") or ("C:/ProgramData" if os.name == "nt" else "/tmp/LabSCHAgent-state")
        path = Path(base) / "LabSCHAgent" / "health.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        pass


def run_loop(cfg: dict, stop_check=None) -> None:
    """Main agent loop.

    stop_check: optional callable returning True when the loop should exit
    (used by the Windows service wrapper for cooperative shutdown).
    """
    client_id = ensure_client_id(cfg)
    server_url = cfg["server_url"]
    api_token = cfg["api_token"]
    global LAST_FAILURE
    version = AGENT_VERSION  # single source of truth: agent/VERSION
    if cfg.get("version") != version:
        cfg["version"] = version
        try:
            save_agent_config(cfg)
        except Exception:
            pass

    if not api_token:
        print("FATAL: api_token not set. Run with --setup first.", file=sys.stderr)
        sys.exit(1)

    client = config_sync.AgentClient(server_url, api_token, client_id)
    downloads = DownloadDispatcher(CONFIG_DIR, client)
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

    last_download_poll = 0
    last_heartbeat = 0
    last_heartbeat_iso = ""
    last_failure = ""
    last_config_pull = 0
    last_app_kill = 0
    current_blocked_apps: list = []
    current_blocked_websites: list = []
    current_allowed_websites: list = []
    current_device_flags: dict = {}  # {"disable_camera": bool, "disable_audio": bool}
    consecutive_failures = 0

    while True:
        if stop_check is not None:
            try:
                if stop_check():
                    print("[labsch_agent] stop requested, exiting loop", flush=True)
                    break
            except Exception:
                pass
        now = time.time()
        try:
            if now - last_download_poll >= DEFAULT_HEARTBEAT_INTERVAL:
                downloads.poll()
                last_download_poll = now
            # Heartbeat
            if now - last_heartbeat >= int(cfg.get("heartbeat_interval", DEFAULT_HEARTBEAT_INTERVAL)):
                try:
                    launcher_ok = _launcher_running()
                    launcher_status = "running" if launcher_ok else "stopped"
                except Exception:
                    launcher_status = "unknown"
                policy_status = {
                    "apps_blocked": len(current_blocked_apps),
                    "websites_blocked": len(current_blocked_websites),
                    "websites_allowed": len(current_allowed_websites),
                    "camera_disabled": bool(current_device_flags.get("disable_camera", False)),
                    "audio_disabled": bool(current_device_flags.get("disable_audio", False)),
                }
                LAST_FAILURE = last_failure
                health = build_health_report(last_heartbeat_iso, policy_status, launcher_status)
                save_health_report(health)
                cfg_resp = client.heartbeat(hostname, ip, user, version, dev_id, mac,
                                            display_name=display_name, is_test=is_test,
                                            health=health)
                if cfg_resp is not None:
                    last_heartbeat = now
                    last_heartbeat_iso = _utcnow_iso()
                    consecutive_failures = 0
                    last_failure = ""
                    LAST_FAILURE = ""
                    # Heartbeat response includes config — use it
                    if client.has_config_changed(cfg_resp):
                        current_blocked_apps, current_blocked_websites, current_allowed_websites = apply_config(
                            cfg_resp, client, current_blocked_apps
                        )
                    # Device flags (camera/audio) — apply on change
                    def report_device_result(message):
                        print(message, flush=True)
                        failed = "failed" in message.lower()
                        client.log_event(
                            "device_flags_failed" if failed else "device_flags_applied",
                            "camera" if "camera" in message.lower() else "audio",
                            message[:2000],
                        )
                    current_device_flags = device_blocker.apply_device_flags(
                        bool(cfg_resp.get("disable_camera", False)),
                        bool(cfg_resp.get("disable_audio", False)),
                        current_device_flags,
                        log_fn=report_device_result,
                    )
                    # LabSCH Launcher kiosk guard — re-spawn if killed
                    try:
                        _launcher_maybe_respawn()
                    except Exception as exc:
                        print(f"[labsch_agent] launcher respawn check failed: {exc}", flush=True)
                    # v0.4.0-test2 — accept canonical_client_id from server.
                    # If the server resolved our unstable client_id to a
                    # canonical one (via device_id), update our local
                    # client_id + config.ini so future heartbeats use the
                    # canonical ID directly. This stops the
                    # device_id_rewrite event storm.
                    canonical = cfg_resp.get("canonical_client_id")
                    if canonical and canonical != client.client_id:
                        print(f"[labsch_agent] updating client_id to canonical: {canonical}", flush=True)
                        client.client_id = canonical
                        client_id = canonical
                        cfg["client_id"] = canonical
                        save_agent_config(cfg)

                    # Check for pending remote command
                    pending = cfg_resp.get("pending_command")
                    if pending:
                        print(f"[labsch_agent] received remote command: {pending}", flush=True)
                        client.log_event("command_received", pending)
                        # v0.3.7+ — execute with return code check + confirm flow.
                        # Server keeps pending_command on failure for retry.
                        cmd_ok = False
                        command_reason = "command was not executed"
                        try:
                            if pending in ("shutdown", "restart", "lock"):
                                outcome = command_executor.execute(pending)
                                cmd_ok = outcome.ok
                                command_reason = outcome.reason
                            elif pending == "launcher_start":
                                cmd_ok, command_reason = _launcher_start()
                            elif pending == "launcher_stop":
                                cmd_ok, command_reason = _launcher_stop()
                            elif pending == "notify":
                                message = cfg_resp.get("pending_command_message") or "Message from admin"
                                if not _is_safe_notify_message(message):
                                    client.log_event("notify_rejected", "unsafe message payload")
                                    message = "Message from admin"
                                safe_msg = message
                                msg_ok = False
                                sched_ok = False
                                msg_reason = ""
                                sched_reason = ""
                                try:
                                    r = subprocess.run(
                                        ["msg.exe", "console", safe_msg],
                                        capture_output=True, timeout=10,
                                        creationflags=_NO_WINDOW,
                                    )
                                    msg_ok = (r.returncode == 0)
                                    if not msg_ok:
                                        err = (r.stderr.decode(errors="replace") if isinstance(r.stderr, bytes) else str(r.stderr or "")).strip()
                                        msg_reason = f"msg.exe returncode={r.returncode}" + (f": {err[:200]}" if err else "")
                                except Exception as e:
                                    msg_reason = f"{type(e).__name__}: {e}"
                                if not msg_ok:
                                    try:
                                        ps_cmd = (
                                            "Add-Type -AssemblyName System.Windows.Forms; "
                                            "[System.Windows.Forms.MessageBox]::Show('"
                                            + safe_msg.replace("'", "''")
                                            + "', 'LabSCH Notify')"
                                        )
                                        r1 = subprocess.run(
                                            ["schtasks", "/Create", "/F", "/SC", "ONCE",
                                             "/ST", "23:59", "/TN", "LabSCHNotify",
                                             "/TR",
                                             "powershell -NoProfile -WindowStyle Hidden -Command "
                                             + _ps_quote(ps_cmd)],
                                            capture_output=True, timeout=10,
                                            creationflags=_NO_WINDOW,
                                        )
                                        r2 = subprocess.run(
                                            ["schtasks", "/Run", "/TN", "LabSCHNotify"],
                                            capture_output=True, timeout=10,
                                            creationflags=_NO_WINDOW,
                                        )
                                        sched_ok = (r1.returncode == 0 and r2.returncode == 0)
                                        if not sched_ok:
                                            sched_reason = f"schtasks create rc={r1.returncode}, run rc={r2.returncode}"
                                    except Exception as e:
                                        sched_reason = f"{type(e).__name__}: {e}"
                                if msg_ok:
                                    cmd_ok = True
                                    command_reason = "notify via msg.exe"
                                elif sched_ok:
                                    cmd_ok = True
                                    command_reason = "notify via schtasks fallback (msg.exe failed: %s)" % (msg_reason or "non-zero exit")
                                else:
                                    cmd_ok = False
                                    command_reason = "notify failed: %s; %s" % (
                                        msg_reason or "msg.exe failed",
                                        sched_reason or "schtasks fallback failed",
                                    )
                            else:
                                print(f"[labsch_agent] unknown command: {pending}", flush=True)
                        except Exception as e:
                            command_reason = f"{type(e).__name__}: {e}"
                            print(f"[labsch_agent] command {pending} failed: {command_reason}", flush=True)

                        # Confirm includes the command identity so an old/stale agent
                        # cannot clear a newer command queued by the administrator.
                        if cmd_ok:
                            if client.confirm_command(pending, "success"):
                                client.log_event("command_executed", pending, command_reason)
                        else:
                            client.confirm_command(pending, "failed", reason=command_reason)
                            client.log_event("command_failed", pending, command_reason)
                            print(
                                f"[labsch_agent] command {pending} failed: {command_reason}; will retry",
                                flush=True,
                            )
                # else: server unreachable — back off so we don't hammer it every second
                else:
                    consecutive_failures += 1
                    last_failure = "heartbeat failed %sx (server unreachable)" % consecutive_failures
                    LAST_FAILURE = last_failure
                    backoff = min(1 * (2 ** consecutive_failures), 60)
                    last_heartbeat = now + backoff - int(cfg.get("heartbeat_interval", DEFAULT_HEARTBEAT_INTERVAL))
                    print(f"[labsch_agent] heartbeat failed ({consecutive_failures}x), backing off {backoff}s", flush=True)

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
            last_failure = "loop error: %s" % str(e)[:300]
            LAST_FAILURE = last_failure
            print(f"[labsch_agent] loop error: {e}", file=sys.stderr)

        time.sleep(1)


def setup() -> None:
    """Interactive or CLI-driven setup: ask for server URL, token, write config."""
    import argparse
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--server", help="Server URL (skip prompt)")
    p.add_argument("--token", help="API token (skip prompt)")
    p.add_argument("--client-id", help="Client ID (blank=auto)")
    p.add_argument("--display-name", help="Display name (skip prompt)")
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

    # v0.3.5 — display_name: validate + normalize BEFORE save. Server-side
    # regex is /^[A-Za-z0-9 ._-]{1,64}$/; we mirror it locally so the user
    # sees a clear error at install time instead of a server rejection. We
    # also strip whitespace and title-case the result, because the server
    # lookup is case-sensitive and the install prompt accepts any casing.
    while True:
        if setup_args.display_name:
            raw = setup_args.display_name
        else:
            existing = cfg.get("display_name", "")
            try:
                raw = input(f"Display name (e.g. PC-12-Lab-A) [{existing}]: ").strip()
            except (EOFError, OSError):
                raw = existing
        if not raw:
            cfg["display_name"] = ""
            break
        normalized = _normalize_display_name(raw)
        if not _DISPLAY_NAME_RE.match(normalized):
            print(
                f"[!] Invalid display name. Allowed: letters, digits, space, "
                f"underscore, hyphen, period. 1–64 chars. Got: {raw!r}",
                file=sys.stderr,
            )
            if setup_args.display_name:
                # Non-interactive: bail out rather than loop forever.
                sys.exit(2)
            continue
        cfg["display_name"] = normalized
        break

    save_agent_config(cfg)
    print(f"Config saved to: {CONFIG_FILE}", flush=True)
    print(f"  server_url:    {cfg['server_url']}", flush=True)
    print(f"  api_token:     {cfg['api_token'][:8]}...", flush=True)
    print(f"  client_id:     {cfg.get('client_id', '(auto)')}", flush=True)
    print(f"  display_name:  {cfg.get('display_name', '')}", flush=True)


def _normalize_display_name(raw: str) -> str:
    """v0.3.5 — strip whitespace and title-case before saving.

    Server-side lookup is case-sensitive, so a user typing "lab-a-3"
    must match "Lab-A-3" stored by another install path. Title-case via
    str.title() is good enough for ASCII display names (the only chars
    the regex allows); we also collapse runs of whitespace.
    """
    s = " ".join(raw.split())
    return s.title()


def main():
    parser = argparse.ArgumentParser(description="LabSCHAgent — labsch client")
    parser.add_argument("--setup", action="store_true", help="Interactive setup")
    parser.add_argument("--server", help="Server URL (for --setup)")
    parser.add_argument("--token", help="API token (for --setup)")
    parser.add_argument("--client-id", help="Client ID (for --setup)")
    parser.add_argument("--display-name", help="Display name (for --setup)")
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
        if args.display_name:
            sys.argv += ["--display-name", args.display_name]
        setup()
        return

    cfg = load_agent_config()

    # v0.3.5 — acquire single-instance lock. A second agent process would
    # otherwise race the first on registry/hosts writes (last-writer-wins
    # leaves the PC in an inconsistent state). If we lose the race we exit
    # cleanly so the existing agent keeps running.
    try:
        _lock_fd = _acquire_single_instance_lock()
    except (OSError, BlockingIOError):
        print("[labsch_agent] another instance is already running, exiting",
              file=sys.stderr, flush=True)
        sys.exit(0)

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
        once_health = build_health_report("", {"mode": "once"}, "unknown")
        result = client.heartbeat(hostname, ip, user, AGENT_VERSION, dev_id, mac, health=once_health)
        print(json.dumps(result, indent=2) if result else "FAILED")
        return

    run_loop(cfg)


if __name__ == "__main__":
    main()
