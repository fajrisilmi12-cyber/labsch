import type { Context, Next } from 'hono';
import type { Env } from './index';

export async function verifyToken(c: Context<{ Bindings: Env }>, next: Next) {
  const expected = c.env.SCHOOL_API_TOKEN;
  if (!expected) {
    return c.json({ detail: 'server: SCHOOL_API_TOKEN not configured' }, 500);
  }
  const provided = c.req.header('X-Agent-Token');
  if (!provided || provided !== expected) {
    return c.json({ detail: 'invalid or missing X-Agent-Token' }, 401);
  }
  await next();
}
