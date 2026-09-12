import { Context } from 'hono';
import { getEffectiveFlags } from './device-flags';
import { isValidMac } from './validation';

interface SessionEnv {
  DB: D1Database;
}

/**
 * POST /api/sessions/refresh
 * Body: { device_id, mac_address, student_name, request_id }
 *
 * 1. Validate all fields (device_id must be stable dev-<16hex>, not a hostname)
 * 2. Check client exists (device_id in clients table)
 * 3. Idempotency: if an active session for this (device_id, request_id) exists, return it
 * 4. Atomically soft-replace: one db.batch() = soft-delete old + insert new
 * 5. Return effective config for this client (overrides + device flags applied)
 */
export async function refreshSession(c: Context<{ Bindings: SessionEnv }>) {
  let body;
  try { body = await c.req.json<{ device_id?: string; mac_address?: string; student_name?: string; request_id?: string }>(); }
  catch { return c.json({ error: 'malformed JSON' }, 400); }

  const { device_id, mac_address, student_name, request_id } = body ?? {};

  // request_id required for retry safety
  if (typeof request_id !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(request_id)) {
    return c.json({ error: 'request_id must be 8-128 URL-safe characters' }, 400);
  }

  // --- validation ---
  // device_id must match the stable MAC-derived format, never a hostname
  if (!device_id || typeof device_id !== 'string' || !/^dev-[a-f0-9]{16}$/.test(device_id.trim())) {
    return c.json({ error: 'device_id must be stable dev-<16hex>, not a hostname' }, 400);
  }
  if (!mac_address || typeof mac_address !== 'string' || !mac_address.trim()) {
    return c.json({ error: 'mac_address is required' }, 400);
  }
  if (!isValidMac(mac_address.trim())) {
    return c.json({ error: 'mac_address format invalid' }, 400);
  }
  if (!student_name || typeof student_name !== 'string' || (student_name.match(/\p{L}/gu)?.length ?? 0) < 4 || student_name.length > 120) {
    return c.json({ error: 'student_name must be at least 4 letters (spaces/digits excluded from count)' }, 400);
  }

  const now = Date.now() / 1000;
  const db = c.env.DB;
  const devId = device_id.trim();

  // --- verify device is registered; resolve to canonical client_id ---
  const client = await db.prepare('SELECT client_id FROM clients WHERE device_id = ?').bind(devId).first<{ client_id: string }>();
  if (!client) return c.json({ error: 'registered device not found' }, 404);

  // --- idempotency: same request_id for same device is a no-op (retries safe) ---
  const existing = await db
    .prepare('SELECT device_id, student_name, created_at, request_id FROM sessions WHERE device_id = ? AND request_id = ? AND deleted_at IS NULL')
    .bind(devId, request_id)
    .first<{ device_id: string; student_name: string; created_at: number; request_id: string }>();
  if (existing) {
    return c.json({ already_active: true, session: { device_id: existing.device_id, student_name: existing.student_name, created_at: existing.created_at }, config: await getEffectiveConfig(db, client.client_id) });
  }

  // --- atomic soft-replace: single batch so a retry/crash can't leave 0 or 2 active ---
  await db.batch([
    db.prepare('UPDATE sessions SET deleted_at = ? WHERE device_id = ? AND deleted_at IS NULL').bind(now, devId),
    db.prepare('INSERT INTO sessions (device_id, mac_address, student_name, request_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)')
      .bind(devId, mac_address.trim(), student_name.trim(), request_id, now, now),
  ]);

  // --- return effective config (per-client overrides + device flags applied) ---
  return c.json({ session: { device_id: devId, student_name: student_name.trim(), created_at: now }, config: await getEffectiveConfig(db, client.client_id) });
}

/**
 * Effective config for a client: global config overlaid with the per-PC
 * override (if present) and the per-PC device flags (override > global).
 * Mirrors what the agent would pull from GET /api/config + heartbeat.
 */
async function getEffectiveConfig(db: D1Database, clientId: string) {
  const cfgRow = await db.prepare(
    'SELECT blocked_apps, blocked_websites, allowed_websites, config_version FROM config WHERE id = 1'
  ).first<any>();
  if (!cfgRow) return null;

  const flags = await getEffectiveFlags(db, clientId);

  let cfg: any = {
    blocked_apps: JSON.parse(cfgRow.blocked_apps),
    blocked_websites: JSON.parse(cfgRow.blocked_websites),
    allowed_websites: JSON.parse(cfgRow.allowed_websites),
    config_version: cfgRow.config_version,
    disable_camera: !!flags.disable_camera,
    disable_audio: !!flags.disable_audio,
  };

  const override = await db.prepare(
    'SELECT blocked_websites, allowed_websites, blocked_apps, has_list_override FROM client_overrides WHERE client_id = ?'
  ).bind(clientId).first<any>();
  if (override && override.has_list_override) {
    cfg.blocked_apps = JSON.parse(override.blocked_apps);
    cfg.blocked_websites = JSON.parse(override.blocked_websites);
    cfg.allowed_websites = JSON.parse(override.allowed_websites);
  }
  return cfg;
}

/**
 * Daily purge — runs at 00:00 WIB (17:00 UTC) via its own cron trigger.
 * Deletes ALL sessions older than 30 days INCLUDING still-active ones:
 * any device that hasn't refreshed for 30 days is gone from the lab,
 * so its session is stale by definition. Active devices re-establish
 * on next boot/login, which is the designed flow.
 *
 * (Distinct from the every-5-minute stale-client cron, which does NOT
 * touch sessions.)
 */
export async function purgeOldSessions(db: D1Database): Promise<void> {
  const THIRTY_DAYS_S = 30 * 24 * 60 * 60;
  const cutoff = Date.now() / 1000 - THIRTY_DAYS_S;
  await db
    .prepare('DELETE FROM sessions WHERE (deleted_at IS NOT NULL AND deleted_at < ?) OR (deleted_at IS NULL AND updated_at < ?)')
    .bind(cutoff, cutoff)
    .run();
}
