import type { Context } from 'hono';
import type { Env } from '../index';

// Token store lives in Cloudflare KV namespace binding "TOKEN_META".
// To provision: `wrangler kv:namespace create "TOKEN_META"` then add the
// [[kv_namespaces]] binding to wrangler.toml.
//
// We never store the full token — only its SHA-256 fingerprint and creation
// metadata — so a leak of the KV namespace does not leak usable credentials.

async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function generateToken(bytes = 32): string {
  // 32 bytes -> 43-char URL-safe base64
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  let bin = '';
  for (const b of arr) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function generateApiToken(c: Context<{ Bindings: Env }>) {
  // 1) Build candidate token + fingerprint
  const token = generateToken(32);
  const fingerprint = (await sha256Hex(token)).slice(0, 12);
  const now = Math.floor(Date.now() / 1000);

  // 2) Persist metadata in KV (if bound).  Token itself is NOT stored.
  const meta = { fingerprint, created_at: now, length: token.length };
  if (c.env.TOKEN_META) {
    await c.env.TOKEN_META.put('current', JSON.stringify(meta));
  }

  // 3) Return the token ONCE — caller must save it.  We also tell the
  //    admin how to set it as a Workers secret:
  //      wrangler secret put SCHOOL_API_TOKEN
  return c.json({
    token,
    fingerprint,
    created_at: now,
    next_step:
      'Save this token — it will not be shown again. ' +
      'Set it as a Workers secret with:  wrangler secret put SCHOOL_API_TOKEN ' +
      '(paste when prompted). The current SCHOOL_API_TOKEN continues to work ' +
      'until you redeploy with the new secret.',
  });
}

export async function getTokenInfo(c: Context<{ Bindings: Env }>) {
  if (!c.env.TOKEN_META) {
    return c.json({
      detail:
        'TOKEN_META KV namespace not bound — add [[kv_namespaces]] to wrangler.toml ' +
        'and `wrangler kv:namespace create "TOKEN_META"`.',
    }, 501);
  }
  const raw = await c.env.TOKEN_META.get('current');
  if (!raw) {
    return c.json({ fingerprint: null, created_at: null, message: 'no token generated yet' });
  }
  return c.json(JSON.parse(raw));
}

export async function revokeApiToken(c: Context<{ Bindings: Env }>) {
  if (!c.env.TOKEN_META) {
    return c.json({ detail: 'TOKEN_META KV namespace not bound' }, 501);
  }
  await c.env.TOKEN_META.delete('current');
  return c.json({ ok: true, message: 'token metadata cleared — rotate SCHOOL_API_TOKEN in secrets to fully revoke' });
}
