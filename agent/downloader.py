"""LabSCH agent download worker — stdlib only.

Safe single-file download + optional autorun for the LabSCH download queue.
Design rules (from the download task requirements):

- Downloads stream to a same-volume .part file and are atomically renamed.
- The download and the execution are separate durable states; execution is
  claimed at most once per task even across process restarts.
- HTTPS only. Redirects are re-validated, including private-IP protection.
- The agent's X-Agent-Token is NEVER forwarded to download hosts.
- SHA256 verification is REQUIRED before any autorun launch.
- Execution modes that cannot be implemented safely (system context, script
  or installer extension types from the user-session agent) fail closed as
  'unsupported' rather than silently doing something unsafe.
- Report payloads never contain secrets.
"""
import base64
import hashlib
import http.client
import threading
import ipaddress
import json
import os
import re
import shutil
import socket
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "LabSCHDownloader/0.4.1"
MAX_REDIRECTS = 5
CHUNK = 64 * 1024
JITTER_MAX = 30
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 60
MAX_SIZE_MB = 2048
DISK_HEADROOM_MB = 64

FORBIDDEN_EXECUTABLE_EXTENSIONS = {
    ".msi", ".bat", ".cmd", ".ps1", ".scr", ".hta", ".msc", ".vbs", ".js", ".jse",
    ".wsf", ".wsh", ".pif", ".cpl", ".gadget", ".lnk", ".url", ".isp", ".apm",
    ".mst", ".msp", ".diagcab", ".appx", ".msix", ".reg",
}
DOCUMENT_MEDIA_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".mp3", ".mp4", ".zip", ".rar", ".7z",
}

PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
]

_DESTINATIONS = {"desktop": "Users/Public/Desktop", "documents": "Users/Public/Documents"}


class DownloadSizeExceeded(Exception):
    pass


class UnsafeUrlError(ValueError):
    pass


def _validate_resolved_host(hostname: str) -> bool:
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError):
        return False
    for info in addr_infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def validate_source_url(url: str):
    """Return the validated https URL or None when unsafe."""
    if not isinstance(url, str) or len(url) > 500 or any(ord(c) < 0x20 for c in url):
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if "\\" in url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or port not in (None, 443):
        return None
    if parsed.scheme != "https":
        return None
    if parsed.username or parsed.password:
        return None
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None
    if hostname in ("localhost",) or hostname.endswith(".localhost") or hostname.endswith(".local"):
        return None
    if not _validate_resolved_host(hostname):
        return None
    return url


def validate_redirect(url: str):
    """Same validation rules applied to a redirect target."""
    return validate_source_url(url)


def is_onedrive_share(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    return host in ("1drv.ms", "onedrive.live.com") or host.endswith(".sharepoint.com")


def onedrive_direct_url(url: str):
    if not is_onedrive_share(url):
        return None
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"https://api.onedrive.com/v1.0/shares/u!{encoded}/root/content"


def is_drive_share(url: str) -> bool:
    try:
        return urllib.parse.urlsplit(url).hostname.lower() in ("drive.google.com", "docs.google.com")
    except (ValueError, AttributeError):
        return False


def resolve_url(url: str):
    """Resolve Drive/OneDrive share links to a direct single-file URL.

    Direct https URLs pass through unchanged after validation. Unsupported
    sources (Drive folders, multi-file pages) return None.
    """
    validated = validate_source_url(url)
    if validated is None:
        return None
    if is_drive_share(url):
        parsed = urllib.parse.urlsplit(url)
        match = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            return None
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    if is_onedrive_share(url):
        return onedrive_direct_url(url)
    return validated


def sanitize_filename(name: str) -> str:
    base = str(name or "").split("/").pop().split("\\").pop()
    cleaned = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in base)
    cleaned = cleaned.replace("..", ".")
    if cleaned.startswith("."):
        cleaned = "_" + cleaned[1:]
    cleaned = cleaned[:120].rstrip(" .")
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", cleaned, re.I):
        cleaned = "_" + cleaned
    return cleaned


def validate_destination(dest: str) -> str:
    if dest not in _DESTINATIONS:
        raise ValueError(f"destination must be one of {sorted(_DESTINATIONS)}")
    return dest


def build_download_opener(agent_token=None):
    """Opener that follows redirects and never forwards the agent token.

    The token authenticates the LabSCH server; it must not leak to arbitrary
    download hosts via redirect or default headers.
    """

    class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if validate_redirect(newurl) is None:
                raise UnsafeUrlError(f"unsafe redirect target: {newurl}")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    class PublicHTTPSConnection(http.client.HTTPSConnection):
        def connect(self):
            # Resolve once, validate every address, then connect numerically.
            # TLS still authenticates the original hostname (SNI + cert).
            infos = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
            if not infos or any(not ipaddress.ip_address(i[4][0]).is_global for i in infos):
                raise UnsafeUrlError("connection address is not public")
            last = None
            for family, kind, proto, _, address in infos:
                sock = socket.socket(family, kind, proto)
                sock.settimeout(self.timeout)
                try:
                    sock.connect(address)
                    self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                    return
                except OSError as exc:
                    last = exc
                    sock.close()
            raise last or OSError("no usable address")

    class PublicHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(PublicHTTPSConnection, req)

    _SafeRedirectHandler.max_redirections = MAX_REDIRECTS
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicHTTPSHandler(), _SafeRedirectHandler)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def destination_dir(root: Path, destination: str) -> Path:
    if os.name == "nt":
        return Path(os.environ.get("PUBLIC", "C:/Users/Public")) / ("Desktop" if destination == "desktop" else "Documents")
    return root / _DESTINATIONS[destination]


def atomic_install(src: Path, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dest)


def _registry_path(root: Path) -> Path:
    return root / "downloads.json"


def _load_registry(root: Path) -> dict:
    path = _registry_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise ValueError("invalid download journal")
        return data
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("download registry unreadable; refusing possible duplicate execution") from exc


def _save_registry(root: Path, data: dict) -> None:
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def claim_task(root: Path, task_id: str, expected_sha256: str) -> bool:
    """Return True when this process may run the download for task_id."""
    data = _load_registry(root)
    entry = data.get(task_id)
    if entry and entry.get("download_state") == "done":
        return False
    if entry and entry.get("claimed"):
        return False
    data[task_id] = {
        "claimed": True,
        "download_state": "pending",
        "execution_state": "not_requested",
        "sha256": expected_sha256,
        "claimed_at": time.time(),
    }
    _save_registry(root, data)
    return True


def mark_download_done(root: Path, task_id: str, sha256: str, bytes_count: int) -> None:
    data = _load_registry(root)
    entry = data.get(task_id, {})
    entry.update({
        "download_state": "done",
        "sha256": sha256,
        "bytes": bytes_count,
        "downloaded_at": time.time(),
    })
    data[task_id] = entry
    _save_registry(root, data)


def mark_download_failed(root: Path, task_id: str, reason: str) -> None:
    data = _load_registry(root)
    entry = data.get(task_id, {})
    entry.update({
        "download_state": "failed",
        "failed_reason": str(reason)[:500],
        "downloaded_at": time.time(),
    })
    data[task_id] = entry
    _save_registry(root, data)


def execution_state(root: Path, task_id: str) -> str:
    entry = _load_registry(root).get(task_id, {})
    return entry.get("execution_state", "not_requested")


def claim_execution(root: Path, task_id: str) -> bool:
    """At-most-once execution claim; True only the first time per task."""
    data = _load_registry(root)
    entry = data.get(task_id)
    if not entry or entry.get("download_state") != "done":
        return False
    if entry.get("execution_state") not in (None, "not_requested"):
        return False
    entry["execution_state"] = "launching"
    entry["execution_claimed_at"] = time.time()
    _save_registry(root, data)
    return True


def mark_execution_state(root: Path, task_id: str, state: str) -> None:
    data = _load_registry(root)
    entry = data.get(task_id, {})
    entry["execution_state"] = state
    entry["execution_updated_at"] = time.time()
    data[task_id] = entry
    _save_registry(root, data)


def forget_task(root: Path, task_id: str) -> None:
    data = _load_registry(root)
    data.pop(task_id, None)
    _save_registry(root, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def disk_headroom_ok(dest_dir: Path, needed_bytes: int) -> bool:
    try:
        usage = shutil.disk_usage(str(dest_dir))
    except OSError:
        return False
    return usage.free >= needed_bytes + DISK_HEADROOM_MB * 1024 * 1024


def evaluate_launch(root: Path, task: dict, final_path: Path) -> dict:
    """Decide how (and whether) a downloaded file may be launched.

    The user-session agent may only launch plain document/media files and
    standalone executables from a protected destination directory. Installer,
    script, and MMC extensions fail closed as 'unsupported'. System context
    execution is not implemented and reports 'unsupported'. SHA256 must
    match the expected value before any launch is considered.
    """
    result = {"execution_state": "unsupported", "reason": None}
    if task.get("run_as") == "system":
        result["reason"] = "system execution is not supported by this agent build"
        return result
    expected_sha = task.get("sha256")
    if not expected_sha:
        result["execution_state"] = "failed_launch"
        result["reason"] = "sha256 required for autorun is missing"
        return result
    if not final_path or not final_path.is_file():
        result["execution_state"] = "failed_launch"
        result["reason"] = "downloaded file missing for launch"
        return result
    actual_sha = sha256_file(final_path)
    if actual_sha != expected_sha.lower():
        result["execution_state"] = "failed_launch"
        result["reason"] = f"sha256 mismatch: expected {expected_sha[:12]}... got {actual_sha[:12]}..."
        return result
    ext = final_path.suffix.lower()
    if ext in FORBIDDEN_EXECUTABLE_EXTENSIONS:
        result["reason"] = f"extension {ext} execution is unsupported from the user-session agent"
        return result
    if ext not in DOCUMENT_MEDIA_EXTENSIONS and ext != ".exe":
        result["reason"] = f"extension {ext} is not in the launch allowlist"
        return result
    try:
        resolved = final_path.resolve()
        if not any(resolved.is_relative_to(destination_dir(root, d).resolve()) for d in _DESTINATIONS):
            result["reason"] = "launch path is outside the public destination directory"
            return result
    except OSError:
        result["reason"] = "could not resolve launch path"
        return result
    result["execution_state"] = "launchable"
    return result


def stream_to_file(response, src_path: Path, max_bytes: int, report=None):
    """Stream an HTTP response body to src_path with a hard byte cap."""
    received = 0
    with open(src_path, "wb") as handle:
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            received += len(chunk)
            if received > max_bytes:
                raise DownloadSizeExceeded(f"download exceeded {max_bytes} bytes")
            if received == len(chunk) and chunk.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise UnsafeUrlError("HTML response is not a file; use a direct download link")
            handle.write(chunk)
            if report:
                report(received)
    return received


def download_task(root: Path, task: dict, opener, report=None):
    """Execute one download task: resolve, stream, verify, install, launch.

    Returns a report dict; never raises for expected failures — the caller
    reports the outcome to the server. The opener must be one built by
    build_download_opener (no token forwarding).
    """
    task_id = task.get("task_id", "")
    resolved = resolve_url(task.get("url", ""))
    if resolved is None:
        mark_download_failed(root, task_id, "unsafe or unsupported source URL")
        return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                "error": "unsafe or unsupported source URL"}
    try:
        destination = validate_destination(task.get("destination", "desktop"))
    except ValueError as exc:
        mark_download_failed(root, task_id, str(exc))
        return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                "error": str(exc)}
    filename = sanitize_filename(task.get("filename", "download.bin"))
    if not filename or filename in (".", ".."):
        mark_download_failed(root, task_id, "invalid filename")
        return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                "error": "invalid filename"}
    base = destination_dir(root, destination)
    base.mkdir(parents=True, exist_ok=True)
    dest_dir = base / ('LabSCH-' + hashlib.sha256(task_id.encode()).hexdigest())
    # Never reuse a pre-planted directory/junction, nor overwrite another task.
    dest_dir.mkdir(exist_ok=False)
    if os.name == 'nt':
        import subprocess
        subprocess.run(['icacls', str(dest_dir), '/inheritance:r', '/grant:r',
                        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F',
                        '*S-1-5-32-545:(OI)(CI)RX'], check=True, timeout=20,
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    max_bytes = min(int(task.get("max_size_mb", MAX_SIZE_MB)), MAX_SIZE_MB) * 1024 * 1024
    expected_sha = (task.get("sha256") or "").lower() or None
    if not disk_headroom_ok(dest_dir, max_bytes):
        mark_download_failed(root, task_id, "insufficient disk space")
        return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                "error": "insufficient disk space"}
    src_path = dest_dir / f".labsch-dl-{hashlib.sha256(task_id.encode()).hexdigest()}.part"
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with opener.open(resolved, timeout=60) as response:
                if response.status != 200:
                    raise OSError(f"HTTP status {response.status}")
                if "html" in response.headers.get("Content-Type", "").lower():
                    raise UnsafeUrlError("HTML/share interstitial is unsupported; use a direct file URL")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > max_bytes:
                            raise DownloadSizeExceeded(f"Content-Length {content_length} exceeds cap")
                    except ValueError:
                        pass
                received = stream_to_file(response, src_path, max_bytes, report=report)
                if content_length is not None and received != int(content_length):
                    raise OSError('truncated HTTP response')
            actual_sha = sha256_file(src_path)
            if expected_sha and actual_sha != expected_sha:
                src_path.unlink(missing_ok=True)
                mark_download_failed(root, task_id, "sha256 mismatch")
                return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                        "error": "sha256 mismatch", "sha256": actual_sha}
            final_path = dest_dir / filename
            atomic_install(src_path, final_path)
            mark_download_done(root, task_id, actual_sha, received)
            if not task.get("autorun", True):
                return {"task_id": task_id, "download_state": "done", "execution_state": "not_requested",
                        "bytes": received, "sha256": actual_sha}
            launch = evaluate_launch(root, task, final_path)
            if launch["execution_state"] != "launchable":
                mark_execution_state(root, task_id, launch["execution_state"])
                return {"task_id": task_id, "download_state": "done", "execution_state": launch["execution_state"],
                        "bytes": received, "sha256": actual_sha, "error": launch["reason"]}
            if not claim_execution(root, task_id):
                return {"task_id": task_id, "download_state": "done", "execution_state": execution_state(root, task_id),
                        "bytes": received, "sha256": actual_sha, "error": "execution already claimed; never retried"}
            try:
                from windows_launch import launch_user_file
                launch_user_file(final_path)
            except Exception as exc:
                mark_execution_state(root, task_id, "failed_launch")
                return {"task_id": task_id, "download_state": "done", "execution_state": "failed_launch",
                        "bytes": received, "sha256": actual_sha, "error": str(exc)[:500]}
            mark_execution_state(root, task_id, "launched")
            return {"task_id": task_id,  "download_state": "done",
                    "execution_state": "launched", "bytes": received, "sha256": actual_sha}
        except DownloadSizeExceeded as exc:
            src_path.unlink(missing_ok=True)
            mark_download_failed(root, task_id, str(exc))
            return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
                    "error": str(exc)}
        except (OSError, UnsafeUrlError) as exc:
            last_error = str(exc)
            src_path.unlink(missing_ok=True)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF)
    mark_download_failed(root, task_id, last_error or "download failed")
    return {"task_id": task_id, "download_state": "failed", "execution_state": "not_requested",
            "error": (last_error or "download failed")[:500]}


def jitter_seconds() -> int:
    import random
    return random.randint(0, JITTER_MAX)


class DownloadDispatcher:
    """One daemon worker, no backlog; server retains overflow for next poll.

    Must run under the agent's process singleton. Only this worker accesses
    the durable journal. Terminal reports replay even after cancellation.
    An interrupted launch is UNKNOWN, never retried or called successful.
    """
    def __init__(self, root, client, worker=download_task, jitter=jitter_seconds):
        self.root, self.client, self.worker, self.jitter = Path(root), client, worker, jitter
        self._guard = threading.Lock()
        self._thread = None
        self._stop = threading.Event()

    def submit(self, tasks):
        with self._guard:
            if self._thread and self._thread.is_alive():
                return 0
            self._thread = threading.Thread(target=self._run, args=(list(tasks)[:20],), daemon=True)
            self._thread.start()
            return min(1, len(tasks))

    def poll(self):
        """Network work is also off the heartbeat thread."""
        with self._guard:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()

    def _poll(self):
        try:
            tasks = self.client.get_pending_downloads(version="0.4.1")
            self._run(tasks or [])
        except Exception as exc:
            print("[downloads] poll failed:", type(exc).__name__)

    def _run(self, tasks):
        try:
            data = _load_registry(self.root)
            # Recover interrupted outcomes before accepting further work.
            for tid, entry in data.items():
                if not entry.get('result'):
                    state = entry.get('download_state', 'failed')
                    execution = entry.get('execution_state', 'not_requested')
                    if state == 'done':
                        execution = 'launched' if execution == 'launched' else 'failed_launch'
                    else:
                        state = 'failed'
                    entry['result'] = dict(task_id=tid, download_state=state, execution_state=execution,
                                           error='agent interrupted; launch outcome unknown, not retried')
                    entry['reported'] = False
            _save_registry(self.root, data)
            for tid, entry in data.items():
                if not entry.get('reported') and self.client.report_download_result(entry['result']):
                    entry['reported'] = True
                    _save_registry(self.root, data)
            for task in tasks:
                tid = task.get('task_id', '')
                if not re.fullmatch(r'[A-Za-z0-9-]{1,64}', tid) or tid in data:
                    continue
                if self._stop.wait(self.jitter()):
                    return
                # Revalidate cancellation after jitter, immediately before work.
                if hasattr(self.client, 'get_pending_downloads'):
                    current = self.client.get_pending_downloads(version="0.4.1")
                    if current is None or not any(t.get('task_id') == tid for t in current):
                        continue
                claim_task(self.root, tid, task.get('sha256'))
                try:
                    result = self.worker(self.root, task, build_download_opener())
                except Exception as exc:
                    result = dict(task_id=tid, download_state='failed', execution_state='not_requested',
                                  error='worker failure: ' + type(exc).__name__)
                data = _load_registry(self.root)
                data[tid]['result'] = result
                data[tid]['reported'] = False
                _save_registry(self.root, data)
                if self.client.report_download_result(result):
                    data[tid]['reported'] = True
                    _save_registry(self.root, data)
                break
        except Exception as exc:
            print('[downloads] stopped safely:', type(exc).__name__)

    def wait(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def close(self):
        self._stop.set()
        self.wait(1)
