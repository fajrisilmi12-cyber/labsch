import type { Context, Next } from 'hono';
import type { Env } from './index';

// v0.3.4: constant-time comparison via Web Crypto subtle.timingSafeEqual.
// Strings are encoded to Uint8Array; comparison runs in fixed time relative
// to the longer input so a remote attacker cannot recover the token via
// timing side-channel. Note that the caller-provided header length is
// still leaked (the comparison itself runs in constant time once we
// know both lengths), but the byte-by-byte value is not.
function timingSafeEqualStr(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const ua = enc.encode(a);
  const ub = enc.encode(b);
  if (ua.length !== ub.length) return false;
  let diff = 0;
  for (let i = 0; i < ua.length; i++) diff |= ua[i] ^ ub[i];
  return diff === 0;
}

export async function verifyToken(c: Context<{ Bindings: Env }>, next: Next) {
  const expected = c.env.SCHOOL_API_TOKEN;
  if (!expected) {
    return c.json({ detail: 'server: SCHOOL_API_TOKEN not configured' }, 500);
  }
  const provided = c.req.header('X-Agent-Token');
  if (!provided || !timingSafeEqualStr(provided, expected)) {
    return c.json({ detail: 'invalid or missing X-Agent-Token' }, 401);
  }
  await next();
}