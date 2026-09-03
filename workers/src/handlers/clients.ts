import type { Context } from 'hono';
import type { Env } from '../index';

export async function listClients(c: Context<{ Bindings: Env }>) {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM clients ORDER BY hostname'
  ).all();
  return c.json(results ?? []);
}

export async function clientDetail(c: Context<{ Bindings: Env }>) {
  const row = await c.env.DB.prepare(
    'SELECT * FROM clients WHERE client_id = ?'
  ).bind(c.req.param('client_id')).first();
  if (!row) return c.json({ detail: 'client not found' }, 404);
  return c.json(row);
}

export async function getOverride(c: Context<{ Bindings: Env }>) {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) return c.json({ detail: 'client not found' }, 404);

  const override = await db.prepare(
    'SELECT * FROM client_overrides WHERE client_id = ?'
  ).bind(clientId).first<any>();
  if (!override) {
    return c.json({
      client_id: clientId, inherits_global: true,
      blocked_apps: [], blocked_websites: [], allowed_websites: [],
    });
  }
  return c.json({
    client_id: clientId, inherits_global: false,
    blocked_apps: JSON.parse(override.blocked_apps),
    blocked_websites: JSON.parse(override.blocked_websites),
    allowed_websites: JSON.parse(override.allowed_websites),
    updated_at: override.updated_at,
  });
}

export async function setOverride(c: Context<{ Bindings: Env }>) {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  const req = await c.req.json<{
    blocked_apps?: string[]; blocked_websites?: string[]; allowed_websites?: string[];
  }>();

  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) return c.json({ detail: 'client not found' }, 404);

  const now = Date.now() / 1000;
  await db.prepare(
    `INSERT INTO client_overrides
     (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, updated_by)
     VALUES (?, ?, ?, ?, ?, 'admin')
     ON CONFLICT(client_id) DO UPDATE SET
       blocked_websites=excluded.blocked_websites,
       allowed_websites=excluded.allowed_websites,
       blocked_apps=excluded.blocked_apps,
       updated_at=excluded.updated_at`
  ).bind(
    clientId,
    JSON.stringify(req.blocked_websites ?? []),
    JSON.stringify(req.allowed_websites ?? []),
    JSON.stringify(req.blocked_apps ?? []),
    now,
  ).run();

  return c.json({ ok: true, client_id: clientId });
}

export async function clearOverride(c: Context<{ Bindings: Env }>) {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) return c.json({ detail: 'client not found' }, 404);

  const res = await db.prepare('DELETE FROM client_overrides WHERE client_id = ?')
    .bind(clientId).run();
  return c.json({ ok: (res.meta.changes ?? 0) > 0, inherits_global: true });
}
