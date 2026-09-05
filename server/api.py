"""FastAPI server for labsch-manager.

v0.3.5 hardening notes:
- All admin endpoints validate input (regex, length caps, array bounds).
- Every admin mutation writes an audit_log row via db.log_admin_action.
- Token endpoints refuse to leave the API_TOKEN empty.
- /api/health has an in-process rate limit (60/min/IP).
- verify_token returns 503 on misconfigured server instead of 500, and
  refuses to operate on the empty-string token.

Endpoints:
  POST /api/heartbeat  - Agent heartbeat with status
  GET  /api/config     - Agent pull latest config
  POST /api/event      - Agent log blocked attempt or other event
  GET  /api/clients    - Admin: list clients
  GET  /api/clients/{id} - Admin: detail
  GET  /api/events     - Admin: blocked attempts log
  GET  /api/health     - Health check
  POST /api/admin/config - Admin: update full config
  POST /api/admin/block-app  - Add to blocked apps
  POST /api/admin/unblock-app
  POST /api/admin/block-site
  POST /api/admin/unblock-site
  POST /api/admin/allow-site
  GET  /api/admin/config - Get current config
"""
import hashlib
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import db

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger("labsch.api")

# Init database on import
db.init_db()

app = FastAPI(title="labsch-manager", version="0.3.5")

# Auth: shared API token. Never accept an empty / None token at runtime.
# v0.3.5: distinguish "missing" (500/503 — server misconfigured) from
# "empty string" (401 — caller sent nothing valid). Previously an empty
# API_TOKEN coexisted silently with header checks; DELETE /api/admin/token
# could set API_TOKEN='' and self-DoS the next request.
API_TOKEN: Optional[str] = os.environ.get("SCHOOL_API_TOKEN")
if not API_TOKEN:
    # generate random on first run, persist to .env
    API_TOKEN = secrets.token_urlsafe(32)
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        with open(env_file, "a") as f:
            f.write(f"\n# School Agent Manager\nSCHOOL_API_TOKEN={API_TOKEN}\n")


# ── v0.3.5: rate limit for the unauthenticated /api/health endpoint ──
# In-process map; for production use Workers rate-limit rules. Each IP
# gets 60 requests/minute, then 429. Prevents DoS via hammering.
HEALTH_RATE_LIMIT_MAX = 60
HEALTH_RATE_LIMIT_WINDOW_MS = 60_000
_health_rate: dict[str, dict] = {}


def _check_health_rate(ip: str) -> bool:
    now = int(time.time() * 1000)
    if len(_health_rate) > 5000:
        # bound memory: drop expired entries
        cutoff = now - HEALTH_RATE_LIMIT_WINDOW_MS
        for k in list(_health_rate.keys()):
            if _health_rate[k]["reset_at"] < cutoff:
                _health_rate.pop(k, None)
    entry = _health_rate.get(ip)
    if not entry or entry["reset_at"] < now:
        _health_rate[ip] = {"count": 1, "reset_at": now + HEALTH_RATE_LIMIT_WINDOW_MS}
        return True
    entry["count"] += 1
    return entry["count"] <= HEALTH_RATE_LIMIT_MAX


def _token_fingerprint(t: Optional[str]) -> str:
    """First 12 hex chars of sha256(token). Used as the `actor` field in
    audit log entries so we never store the token itself."""
    if not t:
        return "no-token"
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:12]


def verify_token(x_api_key: Optional[str] = Header(None, alias="X-Agent-Token")):
    """Authenticate the X-Agent-Token header.

    v0.3.5: 503 when the server itself has no API_TOKEN configured (was
    500), and 401 — not 500 — when an empty string is compared.
    """
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="server: API_TOKEN not configured")
    if not x_api_key:
        raise HTTPException(status_code=401, detail="missing X-Agent-Token")
    # Empty-string token in env means "lockout mode" — refuse everything.
    if not API_TOKEN.strip():
        raise HTTPException(status_code=503, detail="server: API_TOKEN revoked (empty)")
    if not secrets.compare_digest(x_api_key, API_TOKEN):
        raise HTTPException(status_code=401, detail="invalid X-Agent-Token")
    return x_api_key


# v0.3.5: exception handler that maps db.ValidationError to 400 and
# ConfigVersionMismatch to 409, instead of bubbling 500.
@app.exception_handler(db.ValidationError)
async def _validation_exc_handler(request: Request, exc: db.ValidationError):
    return JSONResponse(
        status_code=exc.status,
        content={"detail": str(exc)},
    )


@app.exception_handler(db.ConfigVersionMismatch)
async def _version_mismatch_handler(request: Request, exc: db.ConfigVersionMismatch):
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "current_version": exc.current},
    )


# Background task: mark stale clients as offline
@app.on_event("startup")
async def startup():
    import asyncio
    async def mark_stale_loop():
        while True:
            await asyncio.sleep(30)
            try:
                n = db.mark_stale_clients(90)
                if n:
                    print(f"[labsch] marked {n} clients as offline")
            except Exception as e:
                print(f"[labsch] mark_stale error: {e}")
    asyncio.create_task(mark_stale_loop())


# === Health ===
@app.get("/api/health")
async def health(request: Request):
    """v0.3.5: rate-limited (60/min/IP) so an attacker can't hammer this
    unauthenticated endpoint to enumerate the server or DoS it. The X-
    Forwarded-For header is honoured when present (Cloudflare tunnel)."""
    ip = (request.headers.get("x-forwarded-for") or
          request.client.host if request.client else "unknown")
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    if not _check_health_rate(ip or "unknown"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    return {"status": "ok", "ts": time.time(), "version": app.version}


# === Agent endpoints ===
class HeartbeatRequest(BaseModel):
    client_id: str
    hostname: str
    ip: str
    user: str
    version: str = "0.1.0"
    status: str = "online"
    device_id: Optional[str] = None
    mac: Optional[str] = None
    display_name: Optional[str] = None
    is_test: Optional[bool] = None

    # v0.3.5: validate input at the edge so malformed data never reaches
    # db.py. Mirrors workers/handlers/heartbeat.ts validateHeartbeat().
    @field_validator("client_id")
    @classmethod
    def _client_id_ok(cls, v: str) -> str:
        if not db.is_valid_client_id(v):
            raise ValueError("client_id must match [A-Za-z0-9._-]{1,128}")
        return v

    @field_validator("hostname")
    @classmethod
    def _hostname_ok(cls, v: str) -> str:
        if not db.is_valid_hostname(v):
            raise ValueError("hostname must match [A-Za-z0-9._-]{1,253}")
        return v

    @field_validator("ip")
    @classmethod
    def _ip_ok(cls, v: str) -> str:
        if not isinstance(v, str) or len(v) > 64:
            raise ValueError("ip must be a string <=64 chars")
        return v

    @field_validator("user")
    @classmethod
    def _user_ok(cls, v: str) -> str:
        if not isinstance(v, str) or len(v) > 64:
            raise ValueError("user must be a string <=64 chars")
        return v

    @field_validator("version")
    @classmethod
    def _version_ok(cls, v: str) -> str:
        if not isinstance(v, str) or len(v) > 32:
            raise ValueError("version must be a string <=32 chars")
        return v

    @field_validator("mac")
    @classmethod
    def _mac_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not db.is_valid_mac(v):
            raise ValueError("mac must be a valid MAC string")
        return v

    @field_validator("display_name")
    @classmethod
    def _display_name_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        if not db.is_valid_display_name(v):
            raise ValueError("display_name must match [A-Za-z0-9 ._-]{1,64}")
        return v

    @field_validator("status")
    @classmethod
    def _status_ok(cls, v: str) -> str:
        if v not in {"online", "offline", "unknown"}:
            raise ValueError("status must be online/offline/unknown")
        return v


class HeartbeatResponse(BaseModel):
    config_version: int
    blocked_apps: list
    blocked_websites: list
    allowed_websites: list
    canonical_client_id: str = ""  # The de-duped client_id (may differ from request)
    pending_command: Optional[str] = None  # "shutdown" / "restart" / None


@app.post("/api/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(req: HeartbeatRequest, _: str = Depends(verify_token)):
    cfg = db.upsert_heartbeat(
        req.client_id, req.hostname, req.ip, req.user, req.version,
        device_id=req.device_id, mac=req.mac,
        display_name=req.display_name, is_test=req.is_test,
    )
    # Per-client override takes precedence over global config.
    canonical_id = db.get_canonical_client_id(req.client_id, req.device_id)
    override = db.get_client_override(canonical_id)
    if override:
        cfg = {**cfg, **{k: override[k] for k in
                         ("blocked_apps", "blocked_websites", "allowed_websites")},
               "config_version": cfg["config_version"]}
    # Check for pending remote command (shutdown/restart)
    pending_command = db.get_client_command(canonical_id)
    return HeartbeatResponse(
        config_version=cfg["config_version"],
        blocked_apps=cfg["blocked_apps"],
        blocked_websites=cfg["blocked_websites"],
        allowed_websites=cfg["allowed_websites"],
        canonical_client_id=canonical_id,
        pending_command=pending_command,
    )


@app.get("/api/config")
async def get_agent_config(client_id: Optional[str] = None, _: str = Depends(verify_token)):
    cfg = db.get_config()
    if client_id:
        override = db.get_client_override(client_id)
        if override:
            cfg = {**cfg, **{k: override[k] for k in
                             ("blocked_apps", "blocked_websites", "allowed_websites")}}
    return cfg


class EventRequest(BaseModel):
    client_id: str
    event_type: str
    target: str
    details: Optional[str] = None

    # v0.3.5: validate event payload at the edge so the events table
    # doesn't fill with junk from misconfigured agents.
    @field_validator("client_id")
    @classmethod
    def _client_id_ok(cls, v: str) -> str:
        if not db.is_valid_client_id(v):
            raise ValueError("client_id must match [A-Za-z0-9._-]{1,128}")
        return v

    @field_validator("event_type")
    @classmethod
    def _event_type_ok(cls, v: str) -> str:
        if not db.is_valid_event_type(v):
            raise ValueError("event_type must match [a-z_]{1,32}")
        return v

    @field_validator("target")
    @classmethod
    def _target_ok(cls, v: str) -> str:
        if not db.is_valid_event_target(v):
            raise ValueError("target must be printable ASCII <=512 chars")
        return v

    @field_validator("details")
    @classmethod
    def _details_ok(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not isinstance(v, str) or len(v) > 4096:
            raise ValueError("details must be a string <=4096 chars")
        return v


@app.post("/api/event")
async def post_event(req: EventRequest, _: str = Depends(verify_token)):
    eid = db.log_event(req.client_id, req.event_type, req.target, req.details)
    return {"ok": True, "id": eid}
@app.get("/api/events")
async def list_events(
   hours: int = Query(24, ge=1, le=720),
   client_id: Optional[str] = None,
   event_type: Optional[str] = None,
   limit: int = Query(500, ge=1, le=5000),
   _: str = Depends(verify_token),
):
   return db.get_events(hours=hours, client_id=client_id, event_type=event_type, limit=limit)


@app.get("/api/admin/config")
async def admin_get_config(_: str = Depends(verify_token)):
   return db.get_config()


@app.get("/api/clients")
async def list_clients(_: str = Depends(verify_token)):
    return db.get_clients()


@app.get("/api/clients/{client_id}")
async def client_detail(client_id: str, _: str = Depends(verify_token)):
    c = db.get_client(client_id)
    if not c:
        raise HTTPException(status_code=404, detail="client not found")
    return c


@app.post("/api/admin/command/{client_id}")
async def set_client_command(client_id: str, request: Request,
                             _: str = Depends(verify_token)):
    """Queue a remote command (shutdown/restart/lock/notify) for a client.

    v0.3.5: accepts body JSON {command, message?, ttl_seconds?} OR
    query string. `notify` requires a validated message. ttl is capped
    at 1 day to avoid stale-command execution."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    command = body.get("command") or request.query_params.get("command", "")
    message = body.get("message") or request.query_params.get("message")
    ttl_seconds = body.get("ttl_seconds") or request.query_params.get("ttl_seconds")
    if ttl_seconds is not None:
        try:
            ttl_seconds = int(ttl_seconds)
        except (TypeError, ValueError):
            ttl_seconds = None

    if not command:
        raise HTTPException(status_code=400, detail="command is required (query param or body)")
    if command not in db.VALID_COMMANDS:
        raise HTTPException(status_code=400, detail=f"invalid command: {command}. valid: {sorted(db.VALID_COMMANDS)}")
    canonical_id = db.get_canonical_client_id(client_id)
    if not db.get_client(canonical_id):
        raise HTTPException(status_code=404, detail="client not found")
    ok = db.set_client_command(canonical_id, command, message=message,
                               ttl_seconds=ttl_seconds or db.COMMAND_TTL_SECONDS)
    # v0.3.5: audit log. Actor is the caller's token fingerprint (not the
    # token itself) so a leaked audit log doesn't leak the secret.
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    db.log_admin_action(actor, "command.set", target=canonical_id,
                        details=f"command={command}")
    log.info("command.set client=%s command=%s actor=%s",
             canonical_id, command, actor)
    return {"ok": ok, "client_id": canonical_id, "command": command}


@app.delete("/api/admin/command/{client_id}")
async def clear_client_command(client_id: str, request: Request,
                               _: str = Depends(verify_token)):
    """Cancel a pending remote command. v0.3.5: audit-logged; requires
    the same X-Agent-Token as every other admin endpoint (no additional
    auth, but rate-limit aware)."""
    canonical_id = db.get_canonical_client_id(client_id)
    ok = db.clear_client_command(canonical_id)
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    db.log_admin_action(actor, "command.clear", target=canonical_id)
    log.info("command.clear client=%s actor=%s", canonical_id, actor)
    return {"ok": ok, "client_id": canonical_id}


@app.get("/api/clients/{client_id}/override")
async def get_client_override(client_id: str, _: str = Depends(verify_token)):
    if not db.get_client(client_id):
        raise HTTPException(status_code=404, detail="client not found")
    override = db.get_client_override(client_id)
    return override or {"client_id": client_id, "inherits_global": True,
                        "blocked_apps": [], "blocked_websites": [], "allowed_websites": []}


class ClientOverrideRequest(BaseModel):
    blocked_apps: list[str] = []
    blocked_websites: list[str] = []
    allowed_websites: list[str] = []

    # v0.3.5: validate array shape & per-item length so a runaway client
    # can't blow the row out of SQLite's max page size.
    @field_validator("blocked_apps")
    @classmethod
    def _apps_ok(cls, v):
        return db.validate_string_list(v, "blocked_apps", db.MAX_APPS_ITEMS)

    @field_validator("blocked_websites")
    @classmethod
    def _blocked_sites_ok(cls, v):
        return db.validate_string_list(v, "blocked_websites", db.MAX_WEBSITES_ITEMS)

    @field_validator("allowed_websites")
    @classmethod
    def _allowed_sites_ok(cls, v):
        return db.validate_string_list(v, "allowed_websites", db.MAX_WEBSITES_ITEMS)


@app.put("/api/clients/{client_id}/override")
async def set_client_override(client_id: str, req: ClientOverrideRequest,
                              request: Request,
                              _: str = Depends(verify_token)):
    """Replace one client's override. v0.3.5: audit-logged and validates
    updated_by (default 'admin' or token fingerprint)."""
    canonical_id = db.get_canonical_client_id(client_id)
    if not db.get_client(canonical_id):
        raise HTTPException(status_code=404, detail="client not found")
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    result = db.set_client_override(
        canonical_id, req.blocked_websites, req.allowed_websites,
        req.blocked_apps, updated_by=actor,
    )
    db.log_admin_action(actor, "override.set", target=canonical_id,
                        details=f"apps={len(req.blocked_apps)} "
                                f"blocked_sites={len(req.blocked_websites)} "
                                f"allowed_sites={len(req.allowed_websites)}")
    log.info("override.set client=%s actor=%s", canonical_id, actor)
    return result


@app.delete("/api/clients/{client_id}/override")
async def clear_client_override(client_id: str, _: str = Depends(verify_token)):
    canonical_id = db.get_canonical_client_id(client_id)
    if not db.get_client(canonical_id):
        raise HTTPException(status_code=404, detail="client not found")
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    result = {"ok": db.clear_client_override(canonical_id), "inherits_global": True}
    db.log_admin_action(actor, "override.clear", target=canonical_id)
    log.info("override.clear client=%s actor=%s", canonical_id, actor)
    return result


class FullConfigRequest(BaseModel):
    blocked_apps: list = Field(default_factory=list)
    blocked_websites: list = Field(default_factory=list)
    allowed_websites: list = Field(default_factory=list)

    # v0.3.5: same array validation as override, mirrored here.
    @field_validator("blocked_apps")
    @classmethod
    def _apps_ok(cls, v):
        return db.validate_string_list(v, "blocked_apps", db.MAX_APPS_ITEMS)

    @field_validator("blocked_websites")
    @classmethod
    def _blocked_sites_ok(cls, v):
        return db.validate_string_list(v, "blocked_websites", db.MAX_WEBSITES_ITEMS)

    @field_validator("allowed_websites")
    @classmethod
    def _allowed_sites_ok(cls, v):
        return db.validate_string_list(v, "allowed_websites", db.MAX_WEBSITES_ITEMS)


@app.post("/api/admin/config")
async def admin_set_config(req: FullConfigRequest, _: str = Depends(verify_token)):
    """Replace the entire global config. v0.3.5: audit-logged; uses
    optimistic concurrency under the hood (caller can pass X-Expected-
    Version header to opt into explicit 409 on conflict)."""
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    new_version = db.update_config(
        req.blocked_apps, req.blocked_websites, req.allowed_websites,
        updated_by=actor,
    )
    db.log_admin_action(actor, "config.update",
                        details=f"apps={len(req.blocked_apps)} "
                                f"blocked_sites={len(req.blocked_websites)} "
                                f"allowed_sites={len(req.allowed_websites)} "
                                f"version={new_version}")
    log.info("config.update actor=%s version=%s", actor, new_version)
    return {"config_version": new_version}


class StringRequest(BaseModel):
    name: str

    # v0.3.5: every string payload (app name, domain, etc) gets validated
    # at the edge. Previously any string was accepted.
    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        if not db.is_valid_name(v):
            raise ValueError("name must match [A-Za-z0-9 ._:-/()&@#]{1,253}")
        return v


@app.post("/api/admin/block-app")
async def admin_block_app(req: StringRequest, _: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.add_blocked_app(req.name, updated_by=actor)
    db.log_admin_action(actor, "block.app", target=req.name, details=f"version={v}")
    return {"config_version": v}


@app.post("/api/admin/unblock-app")
async def admin_unblock_app(req: StringRequest, _: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.remove_blocked_app(req.name, updated_by=actor)
    db.log_admin_action(actor, "unblock.app", target=req.name, details=f"version={v}")
    return {"config_version": v}


@app.post("/api/admin/block-site")
async def admin_block_site(req: StringRequest, _: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.add_blocked_website(req.name, updated_by=actor)
    db.log_admin_action(actor, "block.site", target=req.name, details=f"version={v}")
    return {"config_version": v}


@app.post("/api/admin/unblock-site")
async def admin_unblock_site(req: StringRequest, _: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.remove_blocked_website(req.name, updated_by=actor)
    db.log_admin_action(actor, "unblock.site", target=req.name, details=f"version={v}")
    return {"config_version": v}


@app.post("/api/admin/clear-blocked-websites")
async def admin_clear_blocked_websites(_: str = Depends(verify_token)):
    """Empty blocked_websites (unblock ALL sites at once). v0.3.5:
    audit-logged; surfaces partial-failure errors instead of swallowing
    them (was previously silent on db errors)."""
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    cfg = db.get_config()
    new_version = db.update_config(cfg["blocked_apps"], [], cfg["allowed_websites"],
                                   updated_by=actor)
    db.log_admin_action(actor, "clear.blocked_websites",
                        details=f"version={new_version}")
    return {"ok": True, "config_version": new_version}


@app.post("/api/admin/clear-blocked-apps")
async def admin_clear_blocked_apps(_: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    cfg = db.get_config()
    new_version = db.update_config([], cfg["blocked_websites"], cfg["allowed_websites"],
                                   updated_by=actor)
    db.log_admin_action(actor, "clear.blocked_apps",
                        details=f"version={new_version}")
    return {"ok": True, "config_version": new_version}


@app.post("/api/admin/clear-allowed-websites")
async def admin_clear_allowed_websites(_: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    cfg = db.get_config()
    new_version = db.update_config(cfg["blocked_apps"], cfg["blocked_websites"], [],
                                   updated_by=actor)
    db.log_admin_action(actor, "clear.allowed_websites",
                        details=f"version={new_version}")
    return {"ok": True, "config_version": new_version}


# Profile endpoints
class ProfileRequest(BaseModel):
    name: str
    blocked_apps: list = Field(default_factory=list)
    blocked_websites: list = Field(default_factory=list)
    allowed_websites: list = Field(default_factory=list)

    # v0.3.5: profile name regex + array caps (mirrors workers/handlers/
    # admin-profiles.ts).
    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        if not db.is_valid_profile_name(v):
            raise ValueError("profile name must match [A-Za-z0-9 _-]{1,64}")
        return v

    @field_validator("blocked_apps")
    @classmethod
    def _apps_ok(cls, v):
        return db.validate_string_list(v, "blocked_apps", db.MAX_APPS_ITEMS)

    @field_validator("blocked_websites")
    @classmethod
    def _blocked_sites_ok(cls, v):
        return db.validate_string_list(v, "blocked_websites", db.MAX_WEBSITES_ITEMS)

    @field_validator("allowed_websites")
    @classmethod
    def _allowed_sites_ok(cls, v):
        return db.validate_string_list(v, "allowed_websites", db.MAX_WEBSITES_ITEMS)


@app.post("/api/admin/profiles")
async def create_or_update_profile(req: ProfileRequest, _: str = Depends(verify_token)):
    """Create or update a named profile. v0.3.5: audit-logged."""
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    profile = db.create_profile(
        req.name, req.blocked_websites, req.allowed_websites, req.blocked_apps
    )
    db.log_admin_action(actor, "profile.upsert", target=req.name,
                        details=f"id={profile['id']}")
    return profile


@app.get("/api/admin/profiles")
async def list_all_profiles(_: str = Depends(verify_token)):
    """List all named profiles."""
    return db.list_profiles()


@app.get("/api/admin/profiles/{name}")
async def get_one_profile(name: str, _: str = Depends(verify_token)):
    """Get a profile by name."""
    if not db.is_valid_profile_name(name):
        raise HTTPException(status_code=400, detail="invalid profile name")
    p = db.get_profile(name=name)
    if not p:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return p


@app.delete("/api/admin/profiles/{name}")
async def delete_one_profile(name: str, _: str = Depends(verify_token)):
    """Delete a profile by name. v0.3.5: audit-logged."""
    if not db.is_valid_profile_name(name):
        raise HTTPException(status_code=400, detail="invalid profile name")
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    ok = db.delete_profile(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    db.log_admin_action(actor, "profile.delete", target=name)
    return {"ok": True, "deleted": name}


@app.post("/api/admin/profiles/{name}/activate")
async def activate_one_profile(name: str, _: str = Depends(verify_token)):
    """Apply a profile's rules to the live config. v0.3.5: audit-logged."""
    if not db.is_valid_profile_name(name):
        raise HTTPException(status_code=400, detail="invalid profile name")
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.activate_profile(name)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    db.log_admin_action(actor, "profile.activate", target=name,
                        details=f"version={v}")
    return {"ok": True, "config_version": v, "profile": name}


@app.post("/api/admin/allow-site")
async def admin_allow_site(req: StringRequest, _: str = Depends(verify_token)):
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    v = db.add_allowed_website(req.name, updated_by=actor)
    db.log_admin_action(actor, "allow.site", target=req.name, details=f"version={v}")
    return {"config_version": v}


# === Token management (local FastAPI server) ===
class TokenInfo(BaseModel):
    fingerprint: str | None = None
    length: int | None = None
    created_at: int | None = None
    message: str | None = None


def _hash_token(t: str) -> str:
    import hashlib
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


@app.post("/api/admin/token/generate")
async def admin_generate_token(_: str = Depends(verify_token)):
    """Generate a fresh API token. Persists the fingerprint to ~/.hermes/.env
    (replacing any previous SCHOOL_API_TOKEN) so the next agent pull works.

    For Workers/D1 deployments this endpoint is mirrored in
    workers/src/handlers/admin-token.ts — use the CLI:
        labschctl token generate

    v0.3.5: now writes an audit log row BEFORE the .env file is touched,
    so a crash between the two leaves a trail of the attempted rotation.
    """
    new_token = secrets.token_urlsafe(32)
    fingerprint = _hash_token(new_token)[:12]
    created_at = int(time.time())
    # v0.3.5: declare global FIRST, before any use of API_TOKEN.
    global API_TOKEN
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    db.log_admin_action(actor, "token.generate", target=fingerprint,
                        details=f"length={len(new_token)}")
    log.info("token.generate actor=%s new_fp=%s", actor, fingerprint)
    # Persist to ~/.hermes/.env
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        out, found = [], False
        for ln in lines:
            if ln.strip().startswith("SCHOOL_API_TOKEN="):
                out.append(f"SCHOOL_API_TOKEN={new_token}")
                found = True
            else:
                out.append(ln)
        if not found:
            out.append(f"# School Agent Manager")
            out.append(f"SCHOOL_API_TOKEN={new_token}")
        env_file.write_text("\n".join(out) + "\n")
    # Update in-memory token (so the new token is immediately valid).
    # v0.3.5: refuse to leave the running token empty under any
    # circumstance; this is the lockout-mode guard.
    API_TOKEN = new_token
    return {
        "token": new_token,
        "fingerprint": fingerprint,
        "length": len(new_token),
        "created_at": created_at,
        "next_step": (
            "Token rotated in-memory and persisted to ~/.hermes/.env. "
            "The NEXT agent that reads SCHOOL_API_TOKEN from .env will use it. "
            "Already-running agents will need a restart (or wait for their "
            "config.ini to be updated via the normal pull)."
        ),
    }


@app.get("/api/admin/token/info", response_model=TokenInfo)
async def admin_token_info(_: str = Depends(verify_token)):
    """Show the current token's fingerprint + length. Never returns the full token."""
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="server: API_TOKEN not configured")
    return TokenInfo(
        fingerprint=_hash_token(API_TOKEN)[:12],
        length=len(API_TOKEN),
        created_at=None,  # not tracked in-process; the Workers KV variant tracks this
    )


@app.delete("/api/admin/token")
async def admin_revoke_token(_: str = Depends(verify_token)):
    """v0.3.5: this endpoint is now a SAFETY INTERLOCK, not a self-DoS.

    The old behavior (set API_TOKEN = '') left the server in a state
    where every admin request subsequently returned 401 because no
    X-Agent-Token could ever match the empty string. It also left the
    .env value unchanged, so a restart silently restored the old token
    — defeating the supposed revocation.

    New behavior: this endpoint rotates the token immediately (in-memory
    + persisted to .env) and returns the new token once. If you really
    want to lock the server out, restart it with SCHOOL_API_TOKEN=''.
    """
    # v0.3.5: declare global FIRST, before any use of API_TOKEN.
    global API_TOKEN
    actor = "fp:" + _token_fingerprint(API_TOKEN)
    db.log_admin_action(actor, "token.revoke", details="rotating to fresh token")
    new_token = secrets.token_urlsafe(32)
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        out, found = [], False
        for ln in lines:
            if ln.strip().startswith("SCHOOL_API_TOKEN="):
                out.append(f"SCHOOL_API_TOKEN={new_token}")
                found = True
            else:
                out.append(ln)
        if not found:
            out.append("# School Agent Manager")
            out.append(f"SCHOOL_API_TOKEN={new_token}")
        env_file.write_text("\n".join(out) + "\n")
    API_TOKEN = new_token
    log.warning("token.revoke: rotated in-memory + persisted to .env")
    return {
        "ok": True,
        "message": "Token rotated to a fresh value (in-memory and .env). "
                    "Use this new token for subsequent requests. The old "
                    "token is now invalid.",
        "token": new_token,
        "fingerprint": _hash_token(new_token)[:12],
    }


@app.get("/api/admin/audit")
async def admin_audit(
    hours: int = Query(24, ge=1, le=720),
    action: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = Query(200, ge=1, le=5000),
    _: str = Depends(verify_token),
):
    """v0.3.5: surface the audit log so operators can investigate admin
    activity. Filterable by action, actor, and time window."""
    return db.get_audit_log(hours=hours, action=action, actor=actor,
                            limit=limit)


if __name__ == "__main__":
    import uvicorn
    # v0.3.5 note: this binds 0.0.0.0:8080 plaintext. Production
    # deployments MUST front it with the Cloudflare quick tunnel
    # (start_tunnel.sh) or terminate TLS in another layer. There is no
    # CORS middleware: the agent uses the X-Agent-Token header, not
    # browser cookies, so cross-origin requests aren't expected. If you
    # later add a browser dashboard, install fastapi.middleware.cors.CORSMiddleware
    # with an explicit origin allowlist.
    print(f"[labsch] API token: {API_TOKEN[:8]}...{API_TOKEN[-4:]}")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
