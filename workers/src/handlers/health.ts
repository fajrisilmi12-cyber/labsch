import type { Env } from '../index';

// v0.3.5: simple in-memory rate limit for /api/health (the only
// unauthenticated endpoint). Prevents DoS via hammering — each IP
// gets 60 requests per minute, then 429s.
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX = 60;
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();

// Garbage-collect stale entries periodically.
function gcRateLimit(now: number) {
  for (const [k, v] of rateLimitMap.entries()) {
    if (v.resetAt < now) rateLimitMap.delete(k);
  }
}

export async function health(c: any) {
  const ip = c.req.header('cf-connecting-ip') ?? 'unknown';
  const now = Date.now();
  if (rateLimitMap.size > 1000) gcRateLimit(now);  // bound memory
  const entry = rateLimitMap.get(ip);
  if (!entry || entry.resetAt < now) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
  } else {
    entry.count++;
    if (entry.count > RATE_LIMIT_MAX) {
      return c.json({ detail: 'rate limit exceeded' }, 429);
    }
  }
  return c.json({ status: 'ok', ts: Date.now() / 1000, version: c.env.APP_VERSION });
}

export async function markStaleClients(db: D1Database, thresholdSeconds: number) {
  const cutoff = Date.now() / 1000 - thresholdSeconds;
  const res = await db.prepare(
    "UPDATE clients SET status = 'offline' WHERE status = 'online' AND last_seen < ?"
  ).bind(cutoff).run();
  return res.meta.changes ?? 0;
}
