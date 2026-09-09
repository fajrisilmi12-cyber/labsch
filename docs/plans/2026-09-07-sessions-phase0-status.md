# Phase 0 Status: Sessions Backend (2026-09-07)

## Scope (accomplished)

| Requirement | Status | Detail |
|---|---|---|
| `POST /api/sessions/refresh` | ✅ Done | `src/handlers/sessions.ts` |
| `student_name` ≥ 4 **letters** (not spaces/digits) | ✅ | `\p{L}` regex, 4–120 chars |
| `device_id` uses stable MAC-derived format | ✅ | Regex `^dev-[a-f0-9]{16}$`, 400 if hostname; 404 if not in `clients` |
| Atomic soft-replace | ✅ | Single `db.batch()` — no window for 0 or 2 active sessions |
| Config respects per-client overrides | ✅ | `getEffectiveConfig()` merges override + device flags |
| `client_overrides` schema corrected | ✅ | Added `disable_camera`/`disable_audio` columns (was missing in schema.sql for fresh DBs) |
| `request_id` required | ✅ | 8–128 `[A-Za-z0-9_-]` chars |
| Idempotent retries | ✅ | Same `(device_id, request_id)` returns `already_active: true` |
| Malformed JSON → 400 | ✅ | `try/catch` around `c.req.json()` |
| Daily 00:00 WIB (17:00 UTC) purge | ✅ | `purgeOldSessions()` runs only on `cron === '0 17 * * *'`; includes active rows stale >30 days |
| Cron config updated | ✅ | `wrangler.toml`: `crons = ["*/5 * * * *", "0 17 * * *"]` |
| Auth required | ✅ | `/api/sessions/refresh` under `/api/*` catch-all `verifyToken` middleware |

**Test command**: `cd /root/labsch/workers && npm test`
**Result (2026-09-07 13:25 UTC)**: 18 passed, 0 failed, 10.7s
**TSC**: clean (`tsc --noEmit`)

### Test coverage (18 tests)

1. Malformed JSON → 400
2. Missing `request_id` → 400
3. Short `request_id` → 400
4. Non-URL-safe `request_id` → 400
5. Hostname device_id (`LAB-01`) → 400
6. Unregistered device_id (`dev-ffffffffffffffff`) → 404
7. Names < 4 letters (3 cases: digits-only, mixed, short) → 400
8. Name with spaces ok (≥4 letters) → 200
9. Happy path: creates session + returns config
10. Atomic replace: new request_id soft-deletes old, one active remains
11. Idempotency: duplicate request_id → `already_active: true`
12. Purge: old soft-deleted rows removed, fresh kept
13. Purge: stale ACTIVE rows (>30 days) also removed (daily cron)
14. Purge: fresh active sessions preserved
15. Config: per-client override applied over global
16. Config: global + device flags returned when no override
17. Per-PC device flag beats global flag
18. Wrong token → 401

---

## Migration required before production deploy

**Production D1** does not auto-migrate. Run:

```bash
cd /root/labsch/workers
wrangler d1 execute labsch-db --remote --file=migrations/003-sessions.sql
```

Verify:
```bash
wrangler d1 execute labsch-db --remote --command "PRAGMA table_info(sessions)"
# expect: id, device_id, mac_address, student_name, request_id, created_at, updated_at, deleted_at
```

`client_overrides` columns (`disable_camera`, `disable_audio`) already exist
in production D1 (added via manual ALTER on 2026-09-04/05) — no extra
migration needed for those.

---

## Scope discrepancy: config/profiles/overrides/clients

The `refreshSession` response includes the effective config row (global +
per-client override + device flags). This is a subset of the admin-only
config/profiles/overrides surface that was part of the original request.

**What's preserved for now:**
- `GET /api/admin/config` — global config (admin only)
- `POST /api/admin/config` — set global config (admin only)
- `GET /api/admin/profiles`, `POST`, `DELETE`, `POST /activate` — all unchanged
- `GET/PUT/DELETE /api/clients/:id/override` — per-PC override endpoints unchanged

**Production discrepancy to resolve before full rollout:**
The original request referenced "registered computer data" for the
sessions endpoint. The current implementation returns the effective
*config* for the client (blocked lists + device flags) — the same
payload the agent already pulls from `GET /api/config`. The profiles
and overrides management surfaces remain admin-only and unchanged.

**Decision needed:** should `POST /api/sessions/refresh` also return
the active profile name, or just the flat effective config? The current
behavior (flat config only) matches what the agent already works with.

---

## Outstanding gaps (NOT done in this phase)

### 1. Windows ONSTART SYSTEM gate — not implemented

The Windows agent's ONSTART modal (session 0 / desktop gate) is not
part of phase 0. In phase 0, the sessions endpoint is called by the
agent after Windows login, but there is **no enforcement on the Windows
side** that blocks the desktop until the session is established.

A future phase needs:
- Per-user shell gate (HKCU registry) that runs
  `sessions/refresh` before the user's desktop loads
- Windows UI to prompt for `student_name`
- Integration test on real Windows (or Wine + PowerShell)

### 2. Per-user shell gate (Windows)

Requires:
- `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders`
  or a custom Shell replacement that blocks `explorer.exe` until
  the session is confirmed
- Agent hook: run `POST /api/sessions/refresh` early in startup
  before user desktop appears

This is genuinely complex on Windows and needs real hardware testing.
Do not pretend this is done.

### 3. No live fleet changes in this phase

No git push, no `wrangler deploy`, no `wrangler d1 execute --remote`.
Schema migration is provided but must be executed manually by admin
after review.

### 4. No real Windows integration test

All tests are local D1 + Workers runtime (miniflare). No actual
Windows client test. This phase is the backend API + schema only.

### 5. Cron drift note

The daily purge uses `0 17 * * *` (17:00 UTC = 00:00 WIB).
Cloudflare cron triggers are not exact — they may fire up to 1 minute
late. The 30-day threshold has ample margin.
