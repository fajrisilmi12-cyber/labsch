import type { Context, Next } from 'hono';
import type { Env } from './index';

// v0.3.4: constant-time comparison via Web Crypto subtle.timingSafeEqual.
// v0.3.5: verify against KV-stored fingerprints as well as the
// bootstrap SCHOOL_API_TOKEN env var. KV-registered tokens can be
// revoked without redeploy.

async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  const ab = new TextEncoder().encode(a);
  const bb = new TextEncoder().encode(b);
  let result = 0;
  for (let i = 0; i < ab.length; i++) {
    result |= ab[i] ^ bb[i];
  }
  return result === 0;
}

export async function verifyToken(c: Context<{ Bindings: Env }>, next: Next) {
  const presented = c.req.header('X-Agent-Token') ?? '';
  if (!presented) {
    return c.json({ detail: 'X-Agent-Token header required' }, 401);
  }
  const bootstrap = c.env.SCHOOL_API_TOKEN ?? '';
  if (!bootstrap) {
    return c.json({ detail: 'server misconfigured: no bootstrap token' }, 500);
  }
  // 1) Compare against bootstrap token (constant-time)
  let valid = false;
  if (presented.length === bootstrap.length && timingSafeEqual(presented, bootstrap)) {
    valid = true;
  }
  // 2) Compare against KV-registered fingerprints (if KV bound)
  if (!valid && c.env.TOKEN_META) {
    const fp = await sha256Hex(presented);
    const stored = await c.env.TOKEN_META.get(`fp:${fp}`);
    if (stored) {
      // We don't need the metadata; just the existence proves validity
      valid = true;
    }
  }
  if (!valid) {
    return c.json({ detail: 'invalid token' }, 401);
  }
  await next();
}
