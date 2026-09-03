import type { Context } from 'hono';
import type { Env } from '../index';

// Admin device-control endpoints (camera / audio kill switches)
// POST /api/admin/device          → set GLOBAL flags
// POST /api/admin/device/:id      → set PER-PC override
// GET  /api/admin/device          → get global flags
// DELETE /api/admin/device/:id    → clear per-PC override (inherit global)

export async function setDeviceFlags(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const clientId = c.req.param('client_id'); // undefined for global route

  let body: { disable_camera?: boolean; disable_audio?: boolean } = {};
  try {
    body = await c.req.json();
  } catch {
    // DELETE route may have no body — treat as "clear override"
  }

  const cam = body.disable_camera === true ? 1 : 0;
  const aud = body.disable_audio === true ? 1 : 0;

  if (clientId === undefined) {
    // GLOBAL
    await db.prepare(
      'UPDATE config SET disable_camera = ?, disable_audio = ?, updated_at = ?, updated_by = ? WHERE id = 1'
    ).bind(cam, aud, Date.now() / 1000, 'admin:device').run();
    const row = await db.prepare(
      'SELECT disable_camera, disable_audio FROM config WHERE id = 1'
    ).first<any>();
    return c.json({
      scope: 'global',
      disable_camera: !!row.disable_camera,
      disable_audio: !!row.disable_audio,
    });
  }

  // Per-PC
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) return c.json({ detail: 'client not found' }, 404);

  if (c.req.method === 'DELETE') {
    // Reset override columns to 0 (inherit global)
    await db.prepare(
      'UPDATE client_overrides SET disable_camera = 0, disable_audio = 0 WHERE client_id = ?'
    ).bind(clientId).run();
    return c.json({ scope: 'per-pc', client_id: clientId, cleared: true });
  }

  // Upsert override row if missing, then set flags
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
}

export async function getDeviceFlags(c: Context<{ Bindings: Env }>) {
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
  const row = await c.env.DB.prepare(
    'SELECT disable_camera, disable_audio FROM client_overrides WHERE client_id = ?'
  ).bind(clientId).first<any>();
  return c.json({
    scope: 'per-pc', client_id: clientId,
    disable_camera: !!row?.disable_camera,
    disable_audio: !!row?.disable_audio,
    has_override: !!row,
  });
}
