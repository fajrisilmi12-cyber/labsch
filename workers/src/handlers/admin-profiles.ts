import type { Context } from 'hono';
import type { Env } from '../index';
import {
  ValidationError, withErrorHandler, safeJsonParse, isValidProfileName,
} from './validation';

interface ProfileReq {
  name: string;
  blocked_apps?: string[];
  blocked_websites?: string[];
  allowed_websites?: string[];
  disable_camera?: boolean;
  disable_audio?: boolean;
}

function validateArrays(req: ProfileReq): void {
  const lists: Record<string, unknown> = {
    blocked_apps: req.blocked_apps,
    blocked_websites: req.blocked_websites,
    allowed_websites: req.allowed_websites,
  };
  const caps: Record<string, number> = {
    blocked_apps: 500, blocked_websites: 5000, allowed_websites: 5000,
  };
  for (const [k, v] of Object.entries(lists)) {
    if (v === undefined) continue;
    if (!Array.isArray(v)) {
      throw new ValidationError(`${k} must be an array, got ${typeof v}`);
    }
    if (v.length > caps[k]) {
      throw new ValidationError(`${k} exceeds ${caps[k]} items`);
    }
    v.forEach((item: unknown, i: number) => {
      if (typeof item !== 'string') {
        throw new ValidationError(`${k}[${i}] must be a string, got ${typeof item}`);
      }
      const t = item.trim();
      if (t.length === 0) throw new ValidationError(`${k}[${i}] must be non-empty`);
      if (t.length > 253) throw new ValidationError(`${k}[${i}] exceeds 253 chars`);
    });
  }
}

function profileRowToJson(row: any) {
  return {
    id: row.id,
    name: row.name,
    blocked_apps: safeJsonParse<string[]>(row.blocked_apps, []),
    blocked_websites: safeJsonParse<string[]>(row.blocked_websites, []),
    allowed_websites: safeJsonParse<string[]>(row.allowed_websites, []),
    disable_camera: !!row.disable_camera,
    disable_audio: !!row.disable_audio,
    created_at: row.created_at,
    activated_at: row.activated_at,
  };
}

export const createOrUpdateProfile = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  let req: ProfileReq;
  try {
    req = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }
  if (typeof req.name !== 'string' || !isValidProfileName(req.name)) {
    throw new ValidationError('name must match [A-Za-z0-9 _-]{1,64}');
  }
  validateArrays(req);

  const db = c.env.DB;
  const now = Date.now() / 1000;
  const cam = req.disable_camera === true ? 1 : 0;
  const aud = req.disable_audio === true ? 1 : 0;

  const existing = await db.prepare('SELECT id FROM profiles WHERE name = ?')
    .bind(req.name).first<any>();

  if (existing) {
    await db.prepare(
      `UPDATE profiles SET blocked_websites = ?, allowed_websites = ?, blocked_apps = ?,
       disable_camera = ?, disable_audio = ? WHERE name = ?`
    ).bind(
      JSON.stringify(req.blocked_websites ?? []),
      JSON.stringify(req.allowed_websites ?? []),
      JSON.stringify(req.blocked_apps ?? []),
      cam, aud, req.name,
    ).run();
  } else {
    await db.prepare(
      `INSERT INTO profiles (name, blocked_websites, allowed_websites, blocked_apps, created_at, disable_camera, disable_audio)
       VALUES (?, ?, ?, ?, ?, ?, ?)`
    ).bind(
      req.name,
      JSON.stringify(req.blocked_websites ?? []),
      JSON.stringify(req.allowed_websites ?? []),
      JSON.stringify(req.blocked_apps ?? []),
      now, cam, aud,
    ).run();
  }

  const row = await db.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(req.name).first<any>();
  if (!row) throw new ValidationError('profile write failed', 500);
  return c.json(profileRowToJson(row));
});

export const listProfiles = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM profiles ORDER BY name'
  ).all();
  return c.json((results ?? []).map(profileRowToJson));
});

export const getOneProfile = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const name = c.req.param('name') ?? '';
  if (!isValidProfileName(name)) {
    throw new ValidationError('profile name invalid');
  }
  const row = await c.env.DB.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(name).first<any>();
  if (!row) throw new ValidationError(`Profile '${name}' not found`, 404);
  return c.json(profileRowToJson(row));
});

export const deleteOneProfile = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const name = c.req.param('name') ?? '';
  if (!isValidProfileName(name)) {
    throw new ValidationError('profile name invalid');
  }
  const res = await c.env.DB.prepare('DELETE FROM profiles WHERE name = ?')
    .bind(name).run();
  if (!res.meta.changes) throw new ValidationError(`Profile '${name}' not found`, 404);
  return c.json({ ok: true, deleted: name });
});

export const activateProfile = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const db = c.env.DB;
  const name = c.req.param('name') ?? '';
  if (!isValidProfileName(name)) {
    throw new ValidationError('profile name invalid');
  }
  const row = await db.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(name).first<any>();
  if (!row) throw new ValidationError(`Profile '${name}' not found`, 404);

  // Re-validate profile JSON in case it was tampered with out-of-band.
  // (Mitigates audit finding #13.)
  const apps = safeJsonParse<string[]>(row.blocked_apps, []);
  const sites = safeJsonParse<string[]>(row.blocked_websites, []);
  const allowed = safeJsonParse<string[]>(row.allowed_websites, []);
  if (!Array.isArray(apps) || !Array.isArray(sites) || !Array.isArray(allowed)) {
    throw new ValidationError('profile contains malformed JSON; refusing to activate', 500);
  }

  // Optimistic concurrency: bump config_version atomically.
  // Retry on lost race.
  let attempts = 0;
  while (attempts < 3) {
    attempts++;
    const cfgRow = await db.prepare(
      'SELECT config_version FROM config WHERE id = 1'
    ).first<any>();
    const currentVersion = cfgRow?.config_version ?? 0;
    const newVersion = currentVersion + 1;

    const updateRes = await db.prepare(
      `UPDATE config
       SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
           disable_camera = ?, disable_audio = ?,
           config_version = ?, updated_at = ?, updated_by = ?
       WHERE id = 1 AND config_version = ?`
    ).bind(
      JSON.stringify(apps), JSON.stringify(sites), JSON.stringify(allowed),
      row.disable_camera ?? 0, row.disable_audio ?? 0,
      newVersion, Date.now() / 1000, `profile:${name}`,
      currentVersion,
    ).run();
    if (updateRes.meta.changes && updateRes.meta.changes > 0) {
      // Config updated successfully; only NOW record the activation.
      // (Mitigates audit finding #12: previously config was updated
      // before activated_at; if the activated_at write failed, the
      // audit trail would lie. Now if the activated_at write fails,
      // the next activation will correct it.)
      await db.prepare('UPDATE profiles SET activated_at = ? WHERE name = ?')
        .bind(Date.now() / 1000, name).run();
      return c.json({ ok: true, config_version: newVersion, profile: name });
    }
  }
  throw new ValidationError('config write contention; please retry', 503);
});
