# API Reference

All admin endpoints require `X-Agent-Token: <uuid>` header. Agent endpoints
(heartbeat, config) also require the token. `/api/health` is open.

Base URL: `https://<tunnel>.trycloudflare.com`

## Health

### `GET /api/health`

```json
{ "status": "ok", "ts": 1788095212.1, "version": "0.1.0" }
```

## Agent

### `POST /api/heartbeat`

Called by the agent every 30 seconds. Server de-duplicates by `device_id`.

Request:
```json
{
  "client_id": "desktop-3d1knvb-ec8871bc",
  "hostname": "DESKTOP-3D1KNVB",
  "ip": "192.168.1.11",
  "user": "MSI THIN 15",
  "version": "0.1.0",
  "status": "online",
  "device_id": "dev-78ff5203fbf2793b",
  "mac": "34:5A:60:8C:E1:E0",
  "display_name": "PC-LAB-01",
  "is_test": false
}
```

Response (200):
```json
{
  "config_version": 115,
  "blocked_apps": ["RobloxPlayerLauncher.exe"],
  "blocked_websites": ["tiktok.com"],
  "allowed_websites": ["google.com", ".google.com", ...],
  "canonical_client_id": "desktop-3d1knvb-ec8871bc"
}
```

### `GET /api/config`

Returns the current live config (same shape as the heartbeat response's
config block). Agents use this for the 60-second config pull.

### `POST /api/event`

Log an event from the agent. Best-effort, no FK constraint.

Request:
```json
{
  "client_id": "desktop-3d1knvb-ec8871bc",
  "event_type": "config_applied",
  "target": "v115_hosts:True_browsers:3",
  "details": null
}
```

## Clients

### `GET /api/clients`

Returns all clients (online + offline). Each:

```json
{
  "client_id": "...",
  "device_id": "...",
  "mac": "...",
  "display_name": "PC-LAB-01",
  "is_test": 0,
  "hostname": "DESKTOP-3D1KNVB",
  "ip": "192.168.1.11",
  "user": "MSI THIN 15",
  "version": "0.1.0",
  "last_seen": 1788095212.1,
  "first_seen": 1788095145.2,
  "status": "online"
}
```

### `GET /api/clients/{client_id}`

Returns a single client (404 if not found).

### `GET /api/clients/{client_id}/override`

Returns the override, or `{ "inherits_global": true, ... }` if none exists.

### `PUT /api/clients/{client_id}/override`

Replace the config for one client only:
```json
{
  "blocked_websites": ["youtube.com"],
  "allowed_websites": ["google.com"],
  "blocked_apps": ["RobloxPlayerBeta.exe"]
}
```

The global config is unchanged. The client receives this override on its next heartbeat.

### `DELETE /api/clients/{client_id}/override`

Remove the per-PC override. The client inherits the global config again.

## Events

### `GET /api/events?hours=1&client_id=...&event_type=...&limit=500`

Returns events from the last `hours` hours, newest first.

Query params:
- `hours` (int, default 24)
- `client_id` (optional, filter)
- `event_type` (optional, filter)
- `limit` (int, default 500)

## Admin — config

### `GET /api/admin/config`

Returns the live config:
```json
{
  "id": 1,
  "blocked_apps": ["RobloxPlayerLauncher.exe"],
  "blocked_websites": ["tiktok.com"],
  "allowed_websites": ["google.com"],
  "config_version": 115,
  "updated_at": 1788095093.1,
  "updated_by": "profile:Rules Lab"
}
```

### `POST /api/admin/config`

Replace the entire config (full update):
```json
{
  "blocked_apps": ["RobloxPlayerLauncher.exe"],
  "blocked_websites": ["tiktok.com", "instagram.com"],
  "allowed_websites": ["google.com", ".google.com"]
}
```

Returns `{ "config_version": <new> }`.

### `POST /api/admin/block-site`

```json
{ "name": "tiktok.com" }
```

Returns `{ "config_version": <new> }`. Idempotent (re-blocking is a no-op).

### `POST /api/admin/unblock-site`

```json
{ "name": "tiktok.com" }
```

Returns `{ "config_version": <new> }`.

### `POST /api/admin/allow-site`

Add to the allowlist (whitelist). Use the dot-prefix form for subdomains
(`.google.com` matches `google.com` and all subdomains).

```json
{ "name": "wikipedia.org" }
```

### `POST /api/admin/block-app`

```json
{ "name": "RobloxPlayerLauncher.exe" }
```

The `.exe` extension is optional.

### `POST /api/admin/unblock-app`

```json
{ "name": "RobloxPlayerLauncher.exe" }
```

### `POST /api/admin/clear-blocked-websites`

Empty the blocked-websites list. Returns `{ "ok": true, "config_version": <new> }`.

### `POST /api/admin/clear-blocked-apps`

Empty the blocked-apps list.

### `POST /api/admin/clear-allowed-websites`

Empty the allowlist.

## Admin — profiles

### `POST /api/admin/profiles`

Create or update a named profile (upsert by name).

```json
{
  "name": "Rules Lab",
  "blocked_apps": ["RobloxPlayerLauncher.exe"],
  "blocked_websites": ["tiktok.com", "instagram.com"],
  "allowed_websites": ["google.com", "wikipedia.org"]
}
```

Returns the saved profile with `id`, `created_at`, `activated_at`.

### `GET /api/admin/profiles`

List all profiles (id, name, blocked/allowed counts, created/activated timestamps).

### `GET /api/admin/profiles/{name}`

Get a single profile with full lists. 404 if not found.

### `DELETE /api/admin/profiles/{name}`

Delete a profile. 404 if not found.

### `POST /api/admin/profiles/{name}/activate`

Apply the profile to the live config. Returns:

```json
{ "ok": true, "config_version": 118, "profile": "Rules Lab" }
```

The agents will pick up the new config on their next 60-second cycle.
