import type { Context } from 'hono';
import type { Env } from '../index';
import {
  ValidationError, withErrorHandler, safeJsonParse,
} from './validation';

const CLIENT_COLUMNS = [
  'client_id', 'hostname', 'ip', 'user', 'version', 'status',
  'device_id', 'mac', 'display_name', 'is_test',
  'last_seen', 'first_seen',
  'pending_command', 'pending_command_message',
].join(', ');

function validateOverrideArrays(req: any): void {
  const caps: Record<string, number> = {
    blocked_apps: 500, blocked_websites: 5000, allowed_websites: 5000,
  };
  for (const [k, max] of Object.entries(caps)) {
    const v = req[k];
    if (v === undefined) continue;
    if (!Array.isArray(v)) {
      throw new ValidationError(`${k} must be an array, got ${typeof v}`);
    }
    if (v.length > max) {
      throw new ValidationError(`${k} exceeds ${max} items`);
    }
    v.forEach((item: unknown, i: number) => {
      if (typeof item !== 'string') {
        throw new ValidationError(`${k}[${i}] must be a string, got ${typeof item}`);
      }
      const t = item.trim();
      if (t.length === 0) throw new ValidationError(`${k}[${i}] must be non-empty`);
      if (t.length > 253) throw new ValidationError(`${k}[${i}] exceeds 253 chars`);
    });
  }
}

export const listClients = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  // Project columns explicitly. Don't leak password hashes, internal
  // notes, or future PII columns. (Mitigates audit finding #7.)
  const { results } = await c.env.DB.prepare(
    `SELECT ${CLIENT_COLUMNS} FROM clients ORDER BY hostname`
  ).all();
  return c.json(results ?? []);
});

export const clientDetail = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const row = await c.env.DB.prepare(
    `SELECT ${CLIENT_COLUMNS} FROM clients WHERE client_id = ?`
  ).bind(c.req.param('client_id')).first();
  if (!row) throw new ValidationError('client not found', 404);
  return c.json(row);
});

export const getOverride = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

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
    blocked_apps: safeJsonParse<string[]>(override.blocked_apps, []),
    blocked_websites: safeJsonParse<string[]>(override.blocked_websites, []),
    allowed_websites: safeJsonParse<string[]>(override.allowed_websites, []),
    updated_at: override.updated_at,
    updated_by: override.updated_by,
  });
});

export const setOverride = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  let req: any;
  try {
    req = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }

  validateOverrideArrays(req);

  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

  const now = Date.now() / 1000;
  // v0.3.5: read admin identity from header (X-Admin-User) with
  // fallback to 'admin'. Audit trail now records who made the change.
  const updatedBy = (c.req.header('X-Admin-User') ?? 'admin').slice(0, 64);

  await db.prepare(
    `INSERT INTO client_overrides
     (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, updated_by)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT(client_id) DO UPDATE SET
       blocked_websites=excluded.blocked_websites,
       allowed_websites=excluded.allowed_websites,
       blocked_apps=excluded.blocked_apps,
       updated_at=excluded.updated_at,
       updated_by=excluded.updated_by`
  ).bind(
    clientId,
    JSON.stringify(req.blocked_websites ?? []),
    JSON.stringify(req.allowed_websites ?? []),
    JSON.stringify(req.blocked_apps ?? []),
    now, updatedBy,
  ).run();

  return c.json({ ok: true, client_id: clientId, updated_by: updatedBy });
});

export const clearOverride = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

  const res = await db.prepare('DELETE FROM client_overrides WHERE client_id = ?')
    .bind(clientId).run();
  return c.json({ ok: (res.meta.changes ?? 0) > 0, inherits_global: true });
});

// v0.3.5: rename endpoint (PUT /api/clients/:id/display_name).
// Replaces the CLI's direct-SQLite write path (which bypassed the API
// and could drift from the canonical name on the agent side).
export const renameClient = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  const db = c.env.DB;
  let req: any;
  try { req = await c.req.json(); } catch { throw new ValidationError('invalid JSON body'); }
  if (!req || typeof req !== 'object') {
    throw new ValidationError('body must be an object');
  }
  if (typeof req.display_name !== 'string' || !isValidDisplayName(req.display_name)) {
    throw new ValidationError('display_name must match [A-Za-z0-9 ._-]{1,64}');
  }
  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

  const res = await db.prepare(
    'UPDATE clients SET display_name = ? WHERE client_id = ?'
  ).bind(req.display_name, clientId).run();
  if (!res.meta.changes) {
    throw new ValidationError('rename failed (no row updated)', 500);
  }
  return c.json({ ok: true, client_id: clientId, display_name: req.display_name });
});
