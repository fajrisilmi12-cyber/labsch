import type { Env } from '../index';

export async function health(c: any) {
  return c.json({ status: 'ok', ts: Date.now() / 1000, version: c.env.APP_VERSION });
}

export async function markStaleClients(db: D1Database, thresholdSeconds: number) {
  const cutoff = Date.now() / 1000 - thresholdSeconds;
  const res = await db.prepare(
    "UPDATE clients SET status = 'offline' WHERE status = 'online' AND last_seen < ?"
  ).bind(cutoff).run();
  return res.meta.changes ?? 0;
}
