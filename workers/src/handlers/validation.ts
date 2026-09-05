// v0.3.5: shared input validation helpers.
// One regex / one length / one trim, used everywhere. No more ad-hoc
// per-handler checks. If you need a new constraint, add it here.

import type { Context } from 'hono';
import type { Env } from '../index';

// Conservative character whitelist. Allows what Windows / domains / UUIDs
// actually use; rejects control chars, NUL, RTL, emoji, etc. Update if
// a new field legitimately needs a different charset.
const SAFE_NAME = /^[A-Za-z0-9 ._:\-/()&@#]{1,253}$/;
const SAFE_PROFILE_NAME = /^[A-Za-z0-9 _\-]{1,64}$/;
const SAFE_CLIENT_ID = /^[A-Za-z0-9._\-]{1,128}$/;
const SAFE_HOSTNAME = /^[A-Za-z0-9._\-]{1,253}$/;
const SAFE_MAC = /^[A-Fa-f0-9:.\-]{1,32}$/;
const SAFE_EVENT_TYPE = /^[a-z_]{1,32}$/;
const SAFE_DISPLAY_NAME = /^[A-Za-z0-9 ._\-]{1,64}$/;
// Pending command message validation is in isValidCommandMessage() below
// (excludes " ' ` $ \ in addition to the printable-ASCII range).
// Allowed event target: printable, no newlines, no control chars.
const SAFE_EVENT_TARGET = /^[\x20-\x7E]{1,512}$/;

export class ValidationError extends Error {
  status: number;
  constructor(msg: string, status = 400) {
    super(msg);
    this.status = status;
  }
}

export function isValidName(s: string): boolean {
  return SAFE_NAME.test(s);
}
export function isValidProfileName(s: string): boolean {
  return SAFE_PROFILE_NAME.test(s);
}
export function isValidClientId(s: string): boolean {
  return SAFE_CLIENT_ID.test(s);
}
export function isValidHostname(s: string): boolean {
  return SAFE_HOSTNAME.test(s);
}
export function isValidMac(s: string): boolean {
  return SAFE_MAC.test(s);
}
export function isValidDisplayName(s: string): boolean {
  return SAFE_DISPLAY_NAME.test(s);
}
export function isValidEventType(s: string): boolean {
  return SAFE_EVENT_TYPE.test(s);
}
export function isValidCommandMessage(s: string): boolean {
  if (typeof s !== 'string') return false;
  if (s.length === 0 || s.length > 200) return false;
  for (const ch of s) {
    const code = ch.charCodeAt(0);
    if (code < 0x20 || code > 0x7E) return false;
    if (ch === '"' || ch === "'" || ch === '`' || ch === '$' || ch === '\\') return false;
  }
  return true;
}
export function isValidEventTarget(s: string): boolean {
  return SAFE_EVENT_TARGET.test(s);
}

// Cap on number of items in a config-array field. Prevents
// admin-induced D1 row-size exhaustion.
export const MAX_ARRAY_ITEMS = 5000;

// Wrap an async handler with a global error net. Without this, an
// unhandled exception (e.g. JSON.parse of a corrupted config row)
// returns a generic 500 with no body and no trace ID. With this, the
// caller sees a structured error and the operator gets a console log
// with the trace ID.
export function withErrorHandler<T extends (c: Context<{ Bindings: Env }>) => Promise<Response>>(fn: T) {
  return async (c: Context<{ Bindings: Env }>): Promise<Response> => {
    try {
      return await fn(c);
    } catch (e) {
      if (e instanceof ValidationError) {
        return c.json({ detail: e.message }, e.status as 400 | 404 | 422);
      }
      const traceId = crypto.randomUUID();
      console.error(`[${traceId}] ${c.req.method} ${c.req.path}: ${(e as Error).message}`);
      return c.json({ detail: 'internal error', trace_id: traceId }, 500);
    }
  };
}

// Safe JSON parse with default fallback. Prevents a single corrupted
// row from bricking every heartbeat.
export function safeJsonParse<T = any>(s: string | null | undefined, fallback: T): T {
  if (!s) return fallback;
  try {
    return JSON.parse(s) as T;
  } catch {
    console.warn(`safeJsonParse: corrupted value, using fallback. value head: ${s.slice(0, 64)}`);
    return fallback;
  }
}
