import type { Context } from 'hono';
import type { Env } from '../index';

const VALID_COMMANDS = new Set(['shutdown', 'restart', 'lock', 'notify']);

export async function setClientCommand(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const clientId = c.req.param('client_id');
  const command = c.req.query('command') ?? '';

  const client = await db.prepare('SELECT client_id FROM clients WHERE client_id = ?')
    .bind(clientId).first();
  if (!client) return c.json({ detail: 'client not found' }, 404);

  if (!VALID_COMMANDS.has(command)) {
    return c.json({ detail: `invalid command: ${command}. valid: ${[...VALID_COMMANDS]}` }, 400);
  }

  // notify requires a message
  let message: string | null = null;
  if (command === 'notify') {
    message = c.req.query('message') ?? null;
    if (!message) {
      return c.json({ detail: 'notify requires a message query param' }, 400);
    }
  }

  await db.prepare(
    'UPDATE clients SET pending_command = ?, pending_command_message = ? WHERE client_id = ?'
  ).bind(command, message, clientId).run();

  return c.json({ ok: true, client_id: clientId, command });
}

export async function clearClientCommand(c: Context<{ Bindings: Env }>) {
  const clientId = c.req.param('client_id');
  const res = await c.env.DB.prepare(
    'UPDATE clients SET pending_command = NULL, pending_command_message = NULL WHERE client_id = ?'
  ).bind(clientId).run();
  return c.json({ ok: (res.meta.changes ?? 0) > 0, client_id: clientId });
}
