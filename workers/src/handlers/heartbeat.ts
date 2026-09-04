import type { Context } from 'hono';
import type { Env } from '../index';

interface HeartbeatReq {
  client_id: string;
  hostname: string;
  ip: string;
  user: string;
  version?: string;
  status?: string;
  device_id?: string;
  mac?: string;
  display_name?: string;
  is_test?: boolean;
}

export async function heartbeat(c: Context<{ Bindings: Env }>) {
  const req = await c.req.json<HeartbeatReq>();
  const db = c.env.DB;
  const now = Date.now() / 1000;

  if (!req.client_id || !req.hostname) {
    return c.json({ detail: 'client_id and hostname are required' }, 422);
  }

  // De-dup by device_id (MAC-stable ID)
  let existingClientId = req.client_id;
  if (req.device_id) {
    const row = await db.prepare(
      'SELECT client_id FROM clients WHERE device_id = ? AND client_id != ? LIMIT 1'
    ).bind(req.device_id, req.client_id).first<{ client_id: string }>();
    if (row) existingClientId = row.client_id;
  }

  // Upsert
  const existing = await db.prepare(
    'SELECT client_id FROM clients WHERE client_id = ?'
  ).bind(existingClientId).first();

  if (existing) {
    await db.prepare(
      `UPDATE clients SET hostname = ?, ip = ?, user = ?, version = ?,
       last_seen = ?, status = 'online',
       device_id = COALESCE(?, device_id),
       mac = COALESCE(?, mac),
       display_name = COALESCE(NULLIF(?, ''), display_name),
       is_test = COALESCE(?, is_test)
       WHERE client_id = ?`
    ).bind(
      req.hostname, req.ip, req.user, req.version ?? '0.1.0', now,
      req.device_id ?? null, req.mac ?? null,
      req.display_name ?? '', req.is_test === undefined ? null : (req.is_test ? 1 : 0),
      existingClientId,
    ).run();
  } else {
    await db.prepare(
      `INSERT INTO clients (client_id, device_id, mac, hostname, ip, user, version,
       first_seen, last_seen, status, display_name, is_test)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'online', ?, ?)`
    ).bind(
      existingClientId, req.device_id ?? null, req.mac ?? null,
      req.hostname, req.ip ?? null, req.user ?? null, req.version ?? '0.1.0',
      now, now, req.display_name ?? '', req.is_test ? 1 : 0,
    ).run();
  }

  // Get global config
  const cfgRow = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  let cfg = {
    config_version: cfgRow?.config_version ?? 0,
    blocked_apps: JSON.parse(cfgRow?.blocked_apps ?? '[]'),
    blocked_websites: JSON.parse(cfgRow?.blocked_websites ?? '[]'),
    allowed_websites: JSON.parse(cfgRow?.allowed_websites ?? '[]'),
  };

  // Per-client override takes precedence
  const override = await db.prepare(
    'SELECT * FROM client_overrides WHERE client_id = ?'
  ).bind(existingClientId).first<any>();
  if (override) {
    cfg.blocked_apps = JSON.parse(override.blocked_apps);
    cfg.blocked_websites = JSON.parse(override.blocked_websites);
    cfg.allowed_websites = JSON.parse(override.allowed_websites);
  }

  // Get + clear pending command (agent picks it up)
  let pendingCommand: string | null = null;
  let pendingMessage: string | null = null;
  const cmdRow = await db.prepare(
    'SELECT pending_command, pending_command_message FROM clients WHERE client_id = ?'
  ).bind(existingClientId).first<any>();
  if (cmdRow?.pending_command) {
    pendingCommand = cmdRow.pending_command;
    pendingMessage = cmdRow.pending_command_message ?? null;
    await db.prepare(
      'UPDATE clients SET pending_command = NULL, pending_command_message = NULL WHERE client_id = ?'
    ).bind(existingClientId).run();
  }

  // Device flags: per-PC override wins over global
  let disableCamera = 0, disableAudio = 0;
  const flagsRow = override
    ? await db.prepare(
        'SELECT disable_camera, disable_audio FROM client_overrides WHERE client_id = ?'
      ).bind(existingClientId).first<any>()
    : await db.prepare(
        'SELECT disable_camera, disable_audio FROM config WHERE id = 1'
      ).first<any>();
  if (flagsRow) {
    disableCamera = flagsRow.disable_camera ? 1 : 0;
    disableAudio = flagsRow.disable_audio ? 1 : 0;
  }

  return c.json({
    config_version: cfg.config_version,
    blocked_apps: cfg.blocked_apps,
    blocked_websites: cfg.blocked_websites,
    allowed_websites: cfg.allowed_websites,
    canonical_client_id: req.client_id,
    pending_command: pendingCommand,
    pending_command_message: pendingMessage,
    disable_camera: disableCamera === 1,
    disable_audio: disableAudio === 1,
  });
}
