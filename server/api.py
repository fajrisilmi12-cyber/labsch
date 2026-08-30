"""FastAPI server for labsch-manager.

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
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import db

# Init database on import
db.init_db()

app = FastAPI(title="labsch-manager", version="0.1.0")

# Auth: shared API token
API_TOKEN = os.environ.get("SCHOOL_API_TOKEN")
if not API_TOKEN:
    # generate random on first run, persist to .env
    API_TOKEN = secrets.token_urlsafe(32)
    env_file = Path.home() / ".hermes" / ".env"
    if env_file.exists():
        with open(env_file, "a") as f:
            f.write(f"\n# School Agent Manager\nSCHOOL_API_TOKEN={API_TOKEN}\n")


def verify_token(x_api_key: Optional[str] = Header(None, alias="X-Agent-Token")):
    if not API_TOKEN:
        raise HTTPException(status_code=500, detail="server: API_TOKEN not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, API_TOKEN):
        raise HTTPException(status_code=401, detail="invalid or missing X-Agent-Token")
    return x_api_key


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
async def health():
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
        canonical_client_id=req.client_id,
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
async def set_client_command(client_id: str, command: str, _: str = Depends(verify_token)):
    """Queue a remote command (shutdown/restart) for a specific client."""
    if not db.get_client(client_id):
        raise HTTPException(status_code=404, detail="client not found")
    if command not in db.VALID_COMMANDS:
        raise HTTPException(status_code=400, detail=f"invalid command: {command}. valid: {db.VALID_COMMANDS}")
    ok = db.set_client_command(client_id, command)
    return {"ok": ok, "client_id": client_id, "command": command}


@app.delete("/api/admin/command/{client_id}")
async def clear_client_command(client_id: str, _: str = Depends(verify_token)):
    ok = db.clear_client_command(client_id)
    return {"ok": ok, "client_id": client_id}


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


@app.put("/api/clients/{client_id}/override")
async def set_client_override(client_id: str, req: ClientOverrideRequest,
                              _: str = Depends(verify_token)):
    if not db.get_client(client_id):
        raise HTTPException(status_code=404, detail="client not found")
    return db.set_client_override(client_id, req.blocked_websites,
                                  req.allowed_websites, req.blocked_apps)


@app.delete("/api/clients/{client_id}/override")
async def clear_client_override(client_id: str, _: str = Depends(verify_token)):
    if not db.get_client(client_id):
        raise HTTPException(status_code=404, detail="client not found")
    return {"ok": db.clear_client_override(client_id), "inherits_global": True}


class FullConfigRequest(BaseModel):
    blocked_apps: list = Field(default_factory=list)
    blocked_websites: list = Field(default_factory=list)
    allowed_websites: list = Field(default_factory=list)


@app.post("/api/admin/config")
async def admin_set_config(req: FullConfigRequest, _: str = Depends(verify_token)):
    new_version = db.update_config(req.blocked_apps, req.blocked_websites, req.allowed_websites)
    return {"config_version": new_version}


class StringRequest(BaseModel):
    name: str


@app.post("/api/admin/block-app")
async def admin_block_app(req: StringRequest, _: str = Depends(verify_token)):
    v = db.add_blocked_app(req.name)
    return {"config_version": v}


@app.post("/api/admin/unblock-app")
async def admin_unblock_app(req: StringRequest, _: str = Depends(verify_token)):
    v = db.remove_blocked_app(req.name)
    return {"config_version": v}


@app.post("/api/admin/block-site")
async def admin_block_site(req: StringRequest, _: str = Depends(verify_token)):
    v = db.add_blocked_website(req.name)
    return {"config_version": v}


@app.post("/api/admin/unblock-site")
async def admin_unblock_site(req: StringRequest, _: str = Depends(verify_token)):
    v = db.remove_blocked_website(req.name)
    return {"config_version": v}


@app.post("/api/admin/clear-blocked-websites")
async def admin_clear_blocked_websites(_: str = Depends(verify_token)):
    """Empty blocked_websites (unblock ALL sites at once)."""
    cfg = db.get_config()
    new_version = db.update_config(cfg["blocked_apps"], [], cfg["allowed_websites"])
    return {"ok": True, "config_version": new_version}


@app.post("/api/admin/clear-blocked-apps")
async def admin_clear_blocked_apps(_: str = Depends(verify_token)):
    """Empty blocked_apps (unblock ALL apps at once)."""
    cfg = db.get_config()
    new_version = db.update_config([], cfg["blocked_websites"], cfg["allowed_websites"])
    return {"ok": True, "config_version": new_version}


@app.post("/api/admin/clear-allowed-websites")
async def admin_clear_allowed_websites(_: str = Depends(verify_token)):
    """Empty allowed_websites (clear whitelist)."""
    cfg = db.get_config()
    new_version = db.update_config(cfg["blocked_apps"], cfg["blocked_websites"], [])
    return {"ok": True, "config_version": new_version}


# Profile endpoints
class ProfileRequest(BaseModel):
    name: str
    blocked_apps: list = Field(default_factory=list)
    blocked_websites: list = Field(default_factory=list)
    allowed_websites: list = Field(default_factory=list)


@app.post("/api/admin/profiles")
async def create_or_update_profile(req: ProfileRequest, _: str = Depends(verify_token)):
    """Create or update a named profile."""
    profile = db.create_profile(
        req.name, req.blocked_websites, req.allowed_websites, req.blocked_apps
    )
    return profile


@app.get("/api/admin/profiles")
async def list_all_profiles(_: str = Depends(verify_token)):
    """List all named profiles."""
    return db.list_profiles()


@app.get("/api/admin/profiles/{name}")
async def get_one_profile(name: str, _: str = Depends(verify_token)):
    """Get a profile by name."""
    p = db.get_profile(name=name)
    if not p:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return p


@app.delete("/api/admin/profiles/{name}")
async def delete_one_profile(name: str, _: str = Depends(verify_token)):
    """Delete a profile by name."""
    ok = db.delete_profile(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return {"ok": True, "deleted": name}


@app.post("/api/admin/profiles/{name}/activate")
async def activate_one_profile(name: str, _: str = Depends(verify_token)):
    """Apply a profile's rules to the live config."""
    v = db.activate_profile(name)
    if v is None:
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")
    return {"ok": True, "config_version": v, "profile": name}


@app.post("/api/admin/allow-site")
async def admin_allow_site(req: StringRequest, _: str = Depends(verify_token)):
    v = db.add_allowed_website(req.name)
    return {"config_version": v}


if __name__ == "__main__":
    import uvicorn
    print(f"[labsch] API token: {API_TOKEN[:8]}...{API_TOKEN[-4:]}")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
