import type { Context } from 'hono';
import type { Env } from '../index';

// Token management via Cloudflare KV namespace "TOKEN_META".
// To provision: `wrangler kv:namespace create "TOKEN_META"` then add
// the [[kv_namespaces]] binding to wrangler.toml.
//
// v0.3.5 design: We store a list of valid token fingerprints in KV,
// keyed by fp:<fingerprint>. Auth checks verify the presented token's
// fingerprint against this list. Revocation = delete the fingerprint
// entry. The active SCHOOL_API_TOKEN (env var) is the "bootstrap"
// secret; all *additional* tokens are managed via KV.
//
// Bootstrap flow:
//   1. Set SCHOOL_API_TOKEN in wrangler secret — this is the bootstrap
//      token. Its fingerprint is auto-registered as the first
//      fingerprint.
//   2. Call POST /api/admin/token/generate to mint additional tokens.
//   3. Revoke via DELETE /api/admin/token/<fingerprint>.
//
// Caveat: this does NOT rotate SCHOOL_API_TOKEN. To rotate the
// bootstrap token, redeploy with a new secret.

async function sha256Hex(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

function generateToken(bytes = 32): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  let bin = '';
  for (const b of arr) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function registerFingerprint(kv: KVNamespace, token: string): Promise<string> {
  const fp = await sha256Hex(token);
  const meta = {
    fingerprint: fp,
    created_at: Math.floor(Date.now() / 1000),
    length: token.length,
  };
  await kv.put(`fp:${fp}`, JSON.stringify(meta));
  return fp;
}

export async function generateApiToken(c: Context<{ Bindings: Env }>) {
  if (!c.env.TOKEN_META) {
    return c.json({
      detail: 'TOKEN_META KV namespace not bound — add [[kv_namespaces]] to wrangler.toml',
    }, 501);
  }
  const token = generateToken(32);
  const fingerprint = await registerFingerprint(c.env.TOKEN_META, token);
  return c.json({
    token,
    fingerprint,
    created_at: Math.floor(Date.now() / 1000),
    next_step:
      'Save this token — it will not be shown again. It works immediately ' +
      'without redeploying. To revoke, call DELETE /api/admin/token/' + fingerprint,
  });
}

export async function getTokenInfo(c: Context<{ Bindings: Env }>) {
  if (!c.env.TOKEN_META) {
    return c.json({
      detail: 'TOKEN_META KV namespace not bound',
    }, 501);
  }
  // List all fingerprints
  const list = await c.env.TOKEN_META.list({ prefix: 'fp:' });
  const tokens = await Promise.all((list.keys ?? []).map(async (k) => {
    const raw = await c.env.TOKEN_META!.get(k.name);
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  }));
  return c.json({
    bootstrap_token_active: !!c.env.SCHOOL_API_TOKEN,
    registered_fingerprints: tokens.filter((t) => t !== null),
  });
}

export async function revokeApiToken(c: Context<{ Bindings: Env }>) {
  if (!c.env.TOKEN_META) {
    return c.json({ detail: 'TOKEN_META KV namespace not bound' }, 501);
  }
  // Accept fingerprint via path param OR body OR query (?fp=)
  let fp = c.req.param('fingerprint');
  if (!fp) {
    try {
      const body = await c.req.json();
      if (body && typeof body.fingerprint === 'string') fp = body.fingerprint;
    } catch { /* no body */ }
  }
  if (!fp) fp = c.req.query('fp') ?? '';

  // Validate fingerprint shape (64 hex chars for full SHA-256)
  if (!/^[0-9a-f]{64}$/.test(fp)) {
    return c.json({ detail: 'fingerprint must be 64 hex chars (full SHA-256)' }, 400);
  }
  await c.env.TOKEN_META.delete(`fp:${fp}`);
  return c.json({ ok: true, revoked_fingerprint: fp });
}
