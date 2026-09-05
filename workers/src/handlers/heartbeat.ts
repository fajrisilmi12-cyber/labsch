import type { Context } from 'hono';
import type { Env } from '../index';
import {
  ValidationError, isValidClientId, isValidHostname, isValidDisplayName,
  isValidMac, withErrorHandler, safeJsonParse,
} from './validation';

const ALLOWED_STATUS = new Set(['online', 'offline', 'unknown']);

interface HeartbeatReq {
  client_id: string;
  hostname: string;
  ip?: string;
  user?: string;
  version?: string;
  status?: string;
  device_id?: string;
  mac?: string;
  display_name?: string;
  is_test?: boolean;
}

function validateHeartbeat(req: HeartbeatReq): void {
  if (!req || typeof req !== 'object') {
    throw new ValidationError('body must be a JSON object');
  }
  if (typeof req.client_id !== 'string' || !isValidClientId(req.client_id)) {
    throw new ValidationError('client_id must match [A-Za-z0-9._-]{1,128}');
  }
  if (typeof req.hostname !== 'string' || !isValidHostname(req.hostname)) {
    throw new ValidationError('hostname must match [A-Za-z0-9._-]{1,253}');
  }
  if (req.ip !== undefined && (typeof req.ip !== 'string' || req.ip.length > 64)) {
    throw new ValidationError('ip must be a string <=64 chars');
  }
  if (req.user !== undefined && (typeof req.user !== 'string' || req.user.length > 64)) {
    throw new ValidationError('user must be a string <=64 chars');
  }
  if (req.version !== undefined && (typeof req.version !== 'string' || req.version.length > 32)) {
    throw new ValidationError('version must be a string <=32 chars');
  }
  if (req.device_id !== undefined && (typeof req.device_id !== 'string' || req.device_id.length > 128)) {
    throw new ValidationError('device_id must be a string <=128 chars');
  }
  if (req.mac !== undefined && (typeof req.mac !== 'string' || !isValidMac(req.mac))) {
    throw new ValidationError('mac must be a valid MAC string');
  }
  if (req.display_name !== undefined && req.display_name !== '') {
    if (typeof req.display_name !== 'string' || !isValidDisplayName(req.display_name)) {
      throw new ValidationError('display_name must match [A-Za-z0-9 ._-]{1,64}');
    }
  }
  if (req.status !== undefined && !ALLOWED_STATUS.has(req.status)) {
    throw new ValidationError(`status must be one of: ${[...ALLOWED_STATUS].join(', ')}`);
  }
  if (req.is_test !== undefined && typeof req.is_test !== 'boolean') {
    throw new ValidationError('is_test must be boolean');
  }
}

export const heartbeat = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const req: HeartbeatReq = await c.req.json();
  validateHeartbeat(req);

  const db = c.env.DB;
  const now = Date.now() / 1000;

  // De-dup by device_id (MAC-stable ID). If a row with the same device_id
  // already exists under a different client_id, use the canonical one.
  // (v0.3.5: silent rewrite is documented; we add an audit log for it.)
  let existingClientId = req.client_id;
  if (req.device_id) {
    const row = await db.prepare(
      'SELECT client_id FROM clients WHERE device_id = ? AND client_id != ? LIMIT 1'
    ).bind(req.device_id, req.client_id).first<{ client_id: string }>();
    if (row && row.client_id !== req.client_id) {
      // Audit log the rewrite so operators can spot impersonation
      // attempts (e.g. a student replacing the device_id of someone else).
      await db.prepare(
        `INSERT INTO events (client_id, event_type, target, timestamp, details)
         VALUES (?, 'device_id_rewrite', ?, ?, ?)`
      ).bind(req.client_id, row.client_id, now,
            `device_id=${req.device_id} matched existing ${row.client_id}`).run();
      existingClientId = row.client_id;
    }
  }

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
      req.hostname, req.ip ?? null, req.user ?? null, req.version ?? '0.1.0', now,
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

  // Get global config. Use safeJsonParse so a corrupted row doesn't
  // brick every heartbeat.
  const cfgRow = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  const cfg = {
    config_version: cfgRow?.config_version ?? 0,
    blocked_apps: safeJsonParse<string[]>(cfgRow?.blocked_apps, []),
    blocked_websites: safeJsonParse<string[]>(cfgRow?.blocked_websites, []),
    allowed_websites: safeJsonParse<string[]>(cfgRow?.allowed_websites, []),
  };

  // Per-client override takes precedence (single read; reuse for both
  // list override and device-flag lookup).
  const override = await db.prepare(
    'SELECT * FROM client_overrides WHERE client_id = ?'
  ).bind(existingClientId).first<any>();
  if (override) {
    cfg.blocked_apps = safeJsonParse<string[]>(override.blocked_apps, []);
    cfg.blocked_websites = safeJsonParse<string[]>(override.blocked_websites, []);
    cfg.allowed_websites = safeJsonParse<string[]>(override.allowed_websites, []);
  }

  // Race-safe pending_command pickup: read+update in a single statement
  // so two concurrent heartbeats can't both claim the same command. The
  // RETURNING clause (D1 supports it) gives us the value just cleared.
  let pendingCommand: string | null = null;
  let pendingMessage: string | null = null;
  let pendingExpiresAt: number | null = null;
  try {
    const claim = await db.prepare(
      `UPDATE clients
       SET pending_command = NULL, pending_command_message = NULL
       WHERE client_id = ? AND pending_command IS NOT NULL
         AND (pending_command_expires_at IS NULL OR pending_command_expires_at > ?)
       RETURNING pending_command, pending_command_message, pending_command_expires_at`
    ).bind(existingClientId, now).first<any>();
    if (claim) {
      pendingCommand = claim.pending_command;
      pendingMessage = claim.pending_command_message ?? null;
      pendingExpiresAt = claim.pending_command_expires_at ?? null;
    }
  } catch {
    // Column pending_command_expires_at may not exist yet (pre-migration).
    // Fall back to legacy read+clear.
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
  }

  // Device flags: per-PC override wins over global. Use override row we
  // already fetched instead of re-querying.
  let disableCamera = 0, disableAudio = 0;
  if (override) {
    disableCamera = override.disable_camera ? 1 : 0;
    disableAudio = override.disable_audio ? 1 : 0;
  } else {
    const flagsRow = await db.prepare(
      'SELECT disable_camera, disable_audio FROM config WHERE id = 1'
    ).first<any>();
    if (flagsRow) {
      disableCamera = flagsRow.disable_camera ? 1 : 0;
      disableAudio = flagsRow.disable_audio ? 1 : 0;
    }
  }

  return c.json({
    config_version: cfg.config_version,
    blocked_apps: cfg.blocked_apps,
    blocked_websites: cfg.blocked_websites,
    allowed_websites: cfg.allowed_websites,
    canonical_client_id: existingClientId,   // v0.3.4 fix: was req.client_id
    pending_command: pendingCommand,
    pending_command_message: pendingMessage,
    disable_camera: disableCamera === 1,
    disable_audio: disableAudio === 1,
  });
});
