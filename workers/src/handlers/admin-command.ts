import type { Context } from 'hono';
import type { Env } from '../index';
import { ValidationError, withErrorHandler, isValidCommandMessage } from './validation';

const VALID_COMMANDS = new Set(['shutdown', 'restart', 'lock', 'notify']);
const COMMAND_TTL_SECONDS = 3600;  // 1 hour

export const setClientCommand = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const db = c.env.DB;
  const clientId = c.req.param('client_id');

  // Accept command from query (CLI convention) OR body. Prefer body
  // for messages since query-string URL caps are tighter.
  let command = c.req.query('command');
  let message: string | null = c.req.query('message') ?? null;
  let ttlOverride: number | null = null;

  // v0.3.5: also accept body JSON. If body is provided, prefer it.
  try {
    const body = await c.req.json();
    if (body && typeof body === 'object') {
      if (typeof body.command === 'string') command = body.command;
      if (typeof body.message === 'string') message = body.message;
      if (typeof body.ttl_seconds === 'number' && body.ttl_seconds > 0) {
        ttlOverride = Math.min(body.ttl_seconds, 86400);  // cap at 1 day
      }
    }
  } catch {
    // No body is fine for query-string callers
  }

  if (!command) throw new ValidationError('command is required (query param or body)');
  if (!VALID_COMMANDS.has(command)) {
    throw new ValidationError(
      `invalid command: ${command}. valid: ${[...VALID_COMMANDS].join(', ')}`,
    );
  }

  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) throw new ValidationError('client not found', 404);

  if (command === 'notify') {
    if (!message) throw new ValidationError('notify requires a message');
    if (!isValidCommandMessage(message)) {
      throw new ValidationError(
        'message must be printable ASCII (no quotes, backticks, $, or control chars) and <=200 chars',
      );
    }
  }

  const ttl = ttlOverride ?? COMMAND_TTL_SECONDS;
  const expiresAt = Date.now() / 1000 + ttl;

  await db.prepare(
    `UPDATE clients
     SET pending_command = ?, pending_command_message = ?, pending_command_expires_at = ?
     WHERE client_id = ?`
  ).bind(command, message, expiresAt, clientId).run();

  return c.json({ ok: true, client_id: clientId, command, expires_in_seconds: ttl });
});

export const clearClientCommand = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const clientId = c.req.param('client_id');
  const res = await c.env.DB.prepare(
    `UPDATE clients
     SET pending_command = NULL, pending_command_message = NULL, pending_command_expires_at = NULL
     WHERE client_id = ?`
  ).bind(clientId).run();
  return c.json({ ok: (res.meta.changes ?? 0) > 0, client_id: clientId });
});
