import type { Context } from 'hono';
import type { Env } from '../index';

export async function createOrUpdateProfile(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const req = await c.req.json<{
    name: string; blocked_apps?: string[]; blocked_websites?: string[]; allowed_websites?: string[];
    disable_camera?: boolean; disable_audio?: boolean;
  }>();
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
      cam, aud,
      req.name,
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

  // Return the just-saved profile directly (no route param available here)
  const row = await db.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(req.name).first<any>();
  return c.json({
    id: row.id,
    name: row.name,
    blocked_apps: JSON.parse(row.blocked_apps),
    blocked_websites: JSON.parse(row.blocked_websites),
    allowed_websites: JSON.parse(row.allowed_websites),
    disable_camera: !!row.disable_camera,
    disable_audio: !!row.disable_audio,
    created_at: row.created_at,
    activated_at: row.activated_at,
  });
}

export async function listProfiles(c: Context<{ Bindings: Env }>) {
  const { results } = await c.env.DB.prepare(
    'SELECT * FROM profiles ORDER BY name'
  ).all();
  return c.json((results ?? []).map((r: any) => ({
    ...r,
    blocked_apps: JSON.parse(r.blocked_apps),
    blocked_websites: JSON.parse(r.blocked_websites),
    allowed_websites: JSON.parse(r.allowed_websites),
    disable_camera: !!r.disable_camera,
    disable_audio: !!r.disable_audio,
  })));
}

export async function getOneProfile(c: Context<{ Bindings: Env }>) {
  const name = c.req.param('name');
  const row = await c.env.DB.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(name).first<any>();
  if (!row) return c.json({ detail: `Profile '${name}' not found` }, 404);
  return c.json({
    id: row.id,
    name: row.name,
    blocked_apps: JSON.parse(row.blocked_apps),
    blocked_websites: JSON.parse(row.blocked_websites),
    allowed_websites: JSON.parse(row.allowed_websites),
    disable_camera: !!row.disable_camera,
    disable_audio: !!row.disable_audio,
    created_at: row.created_at,
    activated_at: row.activated_at,
  });
}

export async function deleteOneProfile(c: Context<{ Bindings: Env }>) {
  const name = c.req.param('name');
  const res = await c.env.DB.prepare('DELETE FROM profiles WHERE name = ?')
    .bind(name).run();
  if (!res.meta.changes) return c.json({ detail: `Profile '${name}' not found` }, 404);
  return c.json({ ok: true, deleted: name });
}

export async function activateProfile(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const name = c.req.param('name');
  const row = await db.prepare('SELECT * FROM profiles WHERE name = ?')
    .bind(name).first<any>();
  if (!row) return c.json({ detail: `Profile '${name}' not found` }, 404);

  const cfgRow = await db.prepare('SELECT config_version FROM config WHERE id = 1').first<any>();
  const newVersion = (cfgRow?.config_version ?? 0) + 1;

  await db.batch([
    db.prepare(
      `UPDATE config SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
       disable_camera = ?, disable_audio = ?,
       config_version = ?, updated_at = ?, updated_by = ? WHERE id = 1`
    ).bind(
      row.blocked_apps, row.blocked_websites, row.allowed_websites,
      row.disable_camera ?? 0, row.disable_audio ?? 0,
      newVersion, Date.now() / 1000, `profile:${name}`,
    ),
    db.prepare('UPDATE profiles SET activated_at = ? WHERE name = ?')
      .bind(Date.now() / 1000, name),
  ]);

  return c.json({ ok: true, config_version: newVersion, profile: name });
}
