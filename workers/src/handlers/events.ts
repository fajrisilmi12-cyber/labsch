import type { Context } from 'hono';
import type { Env } from '../index';
import {
  ValidationError, withErrorHandler, isValidClientId, isValidEventType,
  isValidEventTarget,
} from './validation';

// Whitelist of valid event types. Anything else is rejected to prevent
// arbitrary event_type values from filling up the events table.
// v0.3.6: expanded whitelist to include v0.2.x agent event types
// for backward compat. Old agents send: command_received, notify_rejected,
// ifeo_applied, ifeo_cleared, config_apply_failed
const VALID_EVENT_TYPES = new Set([
  'config_applied', 'blocked_app', 'blocked_website', 'allowed_website',
  'command_executed', 'command_failed', 'command_received',
  'agent_started', 'agent_stopped',
  'self_protect_breach', 'device_id_rewrite', 'auth_failed',
  'override_set', 'override_cleared',
  'notify_rejected', 'ifeo_applied', 'ifeo_cleared', 'config_apply_failed',
]);

function safeParseInt(s: string | null | undefined, defaultVal: number, min: number, max: number): number {
  if (!s) return defaultVal;
  const n = parseInt(s, 10);
  if (!Number.isFinite(n)) return defaultVal;
  return Math.min(Math.max(n, min), max);
}

export const postEvent = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  let req: any;
  try {
    req = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }
  if (!req || typeof req !== 'object') {
    throw new ValidationError('body must be a JSON object');
  }
  if (typeof req.client_id !== 'string' || !isValidClientId(req.client_id)) {
    throw new ValidationError('client_id must match [A-Za-z0-9._-]{1,128}');
  }
  if (typeof req.event_type !== 'string' || !isValidEventType(req.event_type)) {
    throw new ValidationError('event_type must match [a-z_]{1,32}');
  }
  if (!VALID_EVENT_TYPES.has(req.event_type)) {
    throw new ValidationError(`event_type not in whitelist: ${[...VALID_EVENT_TYPES].join(', ')}`);
  }
  if (typeof req.target !== 'string' || !isValidEventTarget(req.target)) {
    // v0.3.6: coerce non-string target for backward compat with old agents
    if (typeof req.target !== 'string') {
      try {
        req.target = JSON.stringify(req.target);
      } catch {
        req.target = String(req.target);
      }
    }
    if (!isValidEventTarget(req.target)) {
      throw new ValidationError('target must be printable ASCII <=512 chars');
    }
  }
  if (req.details !== undefined) {
    // v0.3.6: coerce non-string details for backward compat with old agents
    if (typeof req.details !== 'string') {
      try {
        req.details = JSON.stringify(req.details);
      } catch {
        req.details = String(req.details);
      }
    }
    if (req.details.length > 4096) {
      req.details = req.details.slice(0, 4096);
    }
  }
  const res = await c.env.DB.prepare(
    'INSERT INTO events (client_id, event_type, target, timestamp, details) VALUES (?, ?, ?, ?, ?)'
  ).bind(req.client_id, req.event_type, req.target, Date.now() / 1000, req.details ?? null).run();
  return c.json({ ok: true, id: res.meta.last_row_id });
});

export const listEvents = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const db = c.env.DB;
  const hours = safeParseInt(c.req.query('hours'), 24, 1, 720);
  const clientId = c.req.query('client_id');
  const eventType = c.req.query('event_type');
  const limit = safeParseInt(c.req.query('limit'), 500, 1, 5000);

  const cutoff = Date.now() / 1000 - hours * 3600;
  let sql = 'SELECT * FROM events WHERE timestamp > ?';
  const params: any[] = [cutoff];
  if (clientId) {
    if (!isValidClientId(clientId)) {
      throw new ValidationError('client_id filter invalid');
    }
    sql += ' AND client_id = ?';
    params.push(clientId);
  }
  if (eventType) {
    if (!isValidEventType(eventType)) {
      throw new ValidationError('event_type filter invalid');
    }
    sql += ' AND event_type = ?';
    params.push(eventType);
  }
  sql += ' ORDER BY timestamp DESC LIMIT ?';
  params.push(limit);

  const { results } = await db.prepare(sql).bind(...params).all();
  return c.json(results ?? []);
});
