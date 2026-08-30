"""HTTP polling client. Talks to labsch-manager server.

Handles heartbeat, config pull, event send.
"""
import json
import time
import urllib.request
import urllib.error
from typing import Optional


class AgentClient:
    """Polling client for the labsch-manager server."""

    def __init__(self, server_url: str, api_token: str, client_id: str):
        self.server_url = server_url.rstrip("/")
        self.api_token = api_token
        self.client_id = client_id
        self.last_config_version = -1

    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 timeout: int = 15) -> Optional[dict]:
        url = f"{self.server_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Agent-Token", self.api_token)
        req.add_header("User-Agent", "LabSCHAgent/0.1.0")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            print(f"[client] HTTP {e.code} on {method} {path}: {body}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"[client] connection error on {method} {path}: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"[client] bad JSON from {method} {path}: {e}")
            return None

    def heartbeat(self, hostname: str, ip: str, user: str, version: str,
                  device_id: str = None, mac: str = None,
                  display_name: str = None, is_test: bool = None) -> Optional[dict]:
        """POST /api/heartbeat. Returns latest config (or None on error).

        device_id and mac are optional but recommended for stable client_id.
        display_name and is_test for human-readable identification.
        """
        body = {
            "client_id": self.client_id,
            "hostname": hostname,
            "ip": ip,
            "user": user,
            "version": version,
            "status": "online",
        }
        if device_id:
            body["device_id"] = device_id
        if mac:
            body["mac"] = mac
        if display_name:
            body["display_name"] = display_name
        if is_test is not None:
            body["is_test"] = is_test
        return self._request("POST", "/api/heartbeat", body)

    def get_config(self) -> Optional[dict]:
        """GET /api/config for this client, including any per-PC override."""
        from urllib.parse import quote
        return self._request("GET", f"/api/config?client_id={quote(self.client_id)}")

    def log_event(self, event_type: str, target: str, details: str = None) -> bool:
        """POST /api/event. Best-effort, never raises."""
        body = {
            "client_id": self.client_id,
            "event_type": event_type,
            "target": target,
            "details": details,
        }
        result = self._request("POST", "/api/event", body)
        return result is not None and result.get("ok", False)

    def has_config_changed(self, new_config: dict) -> bool:
        """Check if config_version increased."""
        v = new_config.get("config_version", -1)
        if v > self.last_config_version:
            self.last_config_version = v
            return True
        return False


# Demo / CLI test
if __name__ == "__main__":
    import argparse
    import socket
    import getpass
    import device_id

    parser = argparse.ArgumentParser(description="MadaniAgent — client")
    parser.add_argument("--server", required=True, help="Server URL (e.g. https://abc.trycloudflare.com)")
    parser.add_argument("--token", required=True, help="API token")
    parser.add_argument("--client-id", required=True, help="Unique client ID")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()

    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)
    user = getpass.getuser()
    dev_id = device_id.get_device_id()
    mac = device_id.get_primary_mac() or "unknown"

    client = AgentClient(args.server, args.token, args.client_id)
    print(f"=== Heartbeat from {hostname} ({ip}) as {user} (device {dev_id}, mac {mac}) ===")
    cfg = client.heartbeat(hostname, ip, user, args.version, dev_id, mac)
    if cfg:
        print(json.dumps(cfg, indent=2))
    else:
        print("FAILED")
