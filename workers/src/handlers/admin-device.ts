import type { Context } from 'hono';
import type { Env } from '../index';
import { ValidationError, withErrorHandler } from './validation';

// Admin device-control endpoints (camera / audio kill switches)
// POST   /api/admin/device           → set GLOBAL flags
// POST   /api/admin/device/:id       → set PER-PC override
// GET    /api/admin/device           → get global flags
// GET    /api/admin/device/:id       → get per-PC override
// DELETE /api/admin/device/:id       → FULLY delete per-PC override (inherit global)

export const setDeviceFlags = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const db = c.env.DB;
  const clientId = c.req.param('client_id');

  if (clientId === undefined) {
    // GLOBAL — body required
    let body: any;
    try {
      body = await c.req.json();
    } catch {
      throw new ValidationError('invalid JSON body');
    }
    if (!body || typeof body !== 'object') {
      throw new ValidationError('body must be an object');
    }
    const cam = body.disable_camera === true ? 1 : 0;
    const aud = body.disable_audio === true ? 1 : 0;

    // v0.3.5: bump config_version so agents pick up the change.
    // (Mitigates audit finding #8 — agents were skipping the
    // heartbeat-returned config because version didn't change.)
    let attempts = 0;
    while (attempts < 3) {
      attempts++;
      const row = await db.prepare(
        'SELECT config_version FROM config WHERE id = 1'
      ).first<any>();
      const currentVersion = row?.config_version ?? 0;
      const newVersion = currentVersion + 1;
      const res = await db.prepare(
        `UPDATE config
         SET disable_camera = ?, disable_audio = ?, updated_at = ?, updated_by = ?,
             config_version = ?
         WHERE id = 1 AND config_version = ?`
      ).bind(cam, aud, Date.now() / 1000, 'admin:device', newVersion, currentVersion).run();
      if (res.meta.changes && res.meta.changes > 0) {
        return c.json({
          scope: 'global', config_version: newVersion,
          disable_camera: !!cam, disable_audio: !!aud,
        });
      }
    }
    throw new ValidationError('config write contention; please retry', 503);
  }

  // Per-PC
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

  if (c.req.method === 'DELETE') {
    // v0.3.5: DELETE fully removes the override row (was only zeroing
    // the columns, leaving the row present which confused
    // getEffectiveFlags). Mitigates audit findings #19, #20, #25.
    await db.prepare('DELETE FROM client_overrides WHERE client_id = ?')
      .bind(clientId).run();
    return c.json({ scope: 'per-pc', client_id: clientId, cleared: true });
  }

  // POST per-PC: parse body
  let body: any;
  try {
    body = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }
  if (!body || typeof body !== 'object') {
    throw new ValidationError('body must be an object');
  }
  const cam = body.disable_camera === true ? 1 : 0;
  const aud = body.disable_audio === true ? 1 : 0;

  await db.prepare(
    `INSERT INTO client_overrides
     (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, updated_by, disable_camera, disable_audio)
     VALUES (?, '[]', '[]', '[]', ?, 'admin:device', ?, ?)
     ON CONFLICT(client_id) DO UPDATE SET
       disable_camera = excluded.disable_camera,
       disable_audio = excluded.disable_audio,
       updated_at = excluded.updated_at`
  ).bind(clientId, Date.now() / 1000, cam, aud).run();

  return c.json({
    scope: 'per-pc', client_id: clientId,
    disable_camera: !!cam, disable_audio: !!aud,
  });
});

export const getDeviceFlags = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  if (!clientId) {
    const row = await c.env.DB.prepare(
      'SELECT disable_camera, disable_audio FROM config WHERE id = 1'
    ).first<any>();
    return c.json({
      scope: 'global',
      disable_camera: !!row?.disable_camera,
      disable_audio: !!row?.disable_audio,
    });
  }
  // v0.3.5: presence is determined by row existence, not by flag
  // values. Previously `has_override` was inferred from
  // `disable_camera=1 || disable_audio=1`, which meant an override row
  // with both flags at 0 was indistinguishable from "no override".
  // (Mitigates audit finding #20.)
  const row = await c.env.DB.prepare(
    'SELECT disable_camera, disable_audio FROM client_overrides WHERE client_id = ?'
  ).bind(clientId).first<any>();
  return c.json({
    scope: 'per-pc', client_id: clientId,
    disable_camera: !!row?.disable_camera,
    disable_audio: !!row?.disable_audio,
    has_override: !!row,
  });
});
