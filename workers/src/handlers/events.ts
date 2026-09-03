import type { Context } from 'hono';
import type { Env } from '../index';

export async function postEvent(c: Context<{ Bindings: Env }>) {
  const req = await c.req.json<{
    client_id: string; event_type: string; target: string; details?: string;
  }>();
  const res = await c.env.DB.prepare(
    'INSERT INTO events (client_id, event_type, target, timestamp, details) VALUES (?, ?, ?, ?, ?)'
  ).bind(req.client_id, req.event_type, req.target, Date.now() / 1000, req.details ?? null).run();
  return c.json({ ok: true, id: res.meta.last_row_id });
}

export async function listEvents(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const hours = Math.min(Math.max(parseInt(c.req.query('hours') ?? '24'), 1), 720);
  const clientId = c.req.query('client_id');
  const eventType = c.req.query('event_type');
  const limit = Math.min(Math.max(parseInt(c.req.query('limit') ?? '500'), 1), 5000);

  const cutoff = Date.now() / 1000 - hours * 3600;
  let sql = 'SELECT * FROM events WHERE timestamp > ?';
  const params: any[] = [cutoff];
  if (clientId) { sql += ' AND client_id = ?'; params.push(clientId); }
  if (eventType) { sql += ' AND event_type = ?'; params.push(eventType); }
  sql += ' ORDER BY timestamp DESC LIMIT ?';
  params.push(limit);

  const { results } = await db.prepare(sql).bind(...params).all();
  return c.json(results ?? []);
}
