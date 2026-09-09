import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:test';
import worker from '../index';
import schema from '../../schema.sql?raw';

const db = (env as unknown as { DB: D1Database }).DB;
const bindings = { DB: db, SCHOOL_API_TOKEN: 'local-test-only', APP_VERSION: 'test' };
const device = 'dev-0123456789abcdef';
const payload = { device_id: device, mac_address: '00:11:22:33:44:55', student_name: 'Alice', request_id: 'request-0001' };

async function post(body: unknown = payload, token = 'local-test-only') {
  return worker.fetch(new Request('http://local/api/sessions/refresh', {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Agent-Token': token },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  }), bindings);
}

beforeEach(async () => {
  // Reset database by running schema fresh (D1 isolate-per-test)
  for (const sql of schema.replace(/--[^\n]*/g, '').split(';').filter((s: string) => s.trim())) {
    await db.prepare(sql).run();
  }
  // Seed a registered client matching the device
  await db.prepare('INSERT INTO clients (client_id, device_id, hostname) VALUES (?, ?, ?)')
    .bind('canonical-client', device, 'LAB-01').run();
});

describe('real local D1 sessions API', () => {
  // --- Malformed JSON ---
  it('returns 400 for malformed JSON rather than 500', async () => {
    const res = await post('{');
    expect(res.status).toBe(400);
    const body = await res.json() as any;
    expect(body.error).toContain('malformed JSON');
  });

  // --- request_id validation ---
  it('requires a valid request_id', async () => {
    const { request_id, ...noId } = payload;
    expect((await post(noId)).status).toBe(400);
  });
  it('rejects short request_id', async () => {
    expect((await post({ ...payload, request_id: 'abc' })).status).toBe(400);
  });
  it('rejects non-URL-safe request_id', async () => {
    expect((await post({ ...payload, request_id: 'abc def!gh' })).status).toBe(400);
  });

  // --- device_id validation ---
  it('rejects hostname-style device_id', async () => {
    expect((await post({ ...payload, device_id: 'LAB-01' })).status).toBe(400);
  });
  it('rejects unregistered device_id', async () => {
    expect((await post({ ...payload, device_id: 'dev-ffffffffffffffff' })).status).toBe(404);
  });

  // --- student_name validation ---
  it('rejects names with fewer than 4 letters', async () => {
    // "1234" has 0 letters, "Ab12" has 2 letters, "Hi" has 2 letters
    expect((await post({ ...payload, student_name: '1234' })).status).toBe(400);
    expect((await post({ ...payload, student_name: 'Ab12' })).status).toBe(400);
    expect((await post({ ...payload, student_name: 'Hi' })).status).toBe(400);
  });
  it('accepts names with 4+ letters even with spaces', async () => {
    expect((await post({ ...payload, student_name: 'A B C D' })).status).toBe(200);
  });

  // --- happy path ---
  it('creates session and returns config row', async () => {
    const res = await post();
    expect(res.status).toBe(200);
    const body = await res.json() as any;
    expect(body.session.device_id).toBe(device);
    expect(body.session.student_name).toBe('Alice');
    expect(body.config).toBeDefined();
    expect(body.config.config_version).toBe(0);
  });

  // --- atomic replace ---
  it('replaces existing session on new request_id', async () => {
    await post({ ...payload, request_id: 'request-aaa1' });
    await post({ ...payload, student_name: 'Bobby', request_id: 'request-aaa2' });
    // Only Bob's session should be active
    const active = await db.prepare('SELECT student_name FROM sessions WHERE device_id = ? AND deleted_at IS NULL')
      .bind(device).all();
    expect(active.results).toHaveLength(1);
    expect((active.results[0] as any).student_name).toBe('Bobby');
  });

  // --- idempotency ---
  it('deduplicates fast reconnects with the same request_id', async () => {
    const first = await post();
    expect(first.status).toBe(200);
    const second = await post();
    expect(second.status).toBe(200);
    const body = await second.json() as any;
    expect(body.already_active).toBe(true);
    // Only one active session
    const active = await db.prepare('SELECT COUNT(*) as cnt FROM sessions WHERE device_id = ? AND deleted_at IS NULL')
      .bind(device).first() as any;
    expect(active.cnt).toBe(1);
  });

  // --- purge ---
  it('purgeOldSessions deletes only old soft-deleted rows', async () => {
    const res = await post();
    expect(res.status).toBe(200);
    // Soft-delete with a fake old timestamp
    const thirtyOneDaysAgo = Date.now() / 1000 - 31 * 24 * 60 * 60;
    await db.prepare('UPDATE sessions SET deleted_at = ? WHERE device_id = ?').bind(thirtyOneDaysAgo, device).run();
    // Insert a fresh active session
    await post({ ...payload, request_id: 'request-purge-test' });
    // Purge: only the old deleted one should go
    const { purgeOldSessions } = await import('./sessions');
    await purgeOldSessions(db);
    const remaining = await db.prepare('SELECT COUNT(*) as cnt FROM sessions WHERE device_id = ?').bind(device).first() as any;
    expect(remaining.cnt).toBe(1);
  });

  it('daily purge also deletes stale ACTIVE sessions after 30 days', async () => {
    const res = await post();
    expect(res.status).toBe(200);
    const thirtyOneDaysAgo = Date.now() / 1000 - 31 * 24 * 60 * 60;
    await db.prepare('UPDATE sessions SET updated_at = ? WHERE device_id = ?').bind(thirtyOneDaysAgo, device).run();
    const { purgeOldSessions } = await import('./sessions');
    await purgeOldSessions(db);
    const remaining = await db.prepare('SELECT COUNT(*) as cnt FROM sessions WHERE device_id = ?').bind(device).first() as any;
    expect(remaining.cnt).toBe(0);
  });

  it('purge keeps fresh ACTIVE sessions (30-day device re-establishes)', async () => {
    const res = await post();
    expect(res.status).toBe(200);
    const { purgeOldSessions } = await import('./sessions');
    await purgeOldSessions(db);
    const remaining = await db.prepare('SELECT COUNT(*) as cnt FROM sessions WHERE device_id = ?').bind(device).first() as any;
    expect(remaining.cnt).toBe(1);
  });

  // --- config: per-client overrides and device flags ---
  it('returns effective config respecting per-client overrides', async () => {
    // Global config has one blocked app; set an override with different lists for this client
    await db.prepare('UPDATE config SET blocked_apps = ?, blocked_websites = ?, config_version = 5 WHERE id = 1')
      .bind(JSON.stringify(['game.exe']), JSON.stringify(['blocked.example'])).run();
    // config_version = 5 is a literal (2 placeholders)
    await db.prepare(
      'INSERT INTO client_overrides (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, has_list_override) VALUES (?, ?, ?, ?, ?, 1)'
    ).bind('canonical-client', JSON.stringify(['override.example']), JSON.stringify(['allow.example']), JSON.stringify(['ov-app.exe']), Date.now() / 1000).run();

    const res = await post();
    expect(res.status).toBe(200);
    const body = await res.json() as any;
    expect(body.config.blocked_apps).toEqual(['ov-app.exe']);
    expect(body.config.blocked_websites).toEqual(['override.example']);
    expect(body.config.allowed_websites).toEqual(['allow.example']);
    expect(body.config.config_version).toBe(5);
  });

  it('device-only override does not erase inherited website and app rules', async () => {
    await db.prepare('UPDATE config SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?, config_version = 6 WHERE id = 1')
      .bind(JSON.stringify(['game.exe']), JSON.stringify(['blocked.example']), JSON.stringify(['allow.example'])).run();
    await db.prepare(
      `INSERT INTO client_overrides
       (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at, updated_by, disable_camera, disable_audio, has_list_override)
       VALUES (?, '[]', '[]', '[]', ?, 'admin:device', 1, 1, 0)`
    ).bind('canonical-client', Date.now() / 1000).run();

    const res = await post();
    expect(res.status).toBe(200);
    const body = await res.json() as any;
    expect(body.config.blocked_apps).toEqual(['game.exe']);
    expect(body.config.blocked_websites).toEqual(['blocked.example']);
    expect(body.config.allowed_websites).toEqual(['allow.example']);
    expect(body.config.disable_camera).toBe(true);
    expect(body.config.disable_audio).toBe(true);
  });

  it('returns global config (with device flags) when no override exists', async () => {
    await db.prepare('UPDATE config SET blocked_apps = ?, disable_camera = 1, disable_audio = 0, config_version = 7 WHERE id = 1')
      .bind(JSON.stringify(['game.exe'])).run();
    const res = await post();
    expect(res.status).toBe(200);
    const body = await res.json() as any;
    expect(body.config.blocked_apps).toEqual(['game.exe']);
    expect(body.config.disable_camera).toBe(true);
    expect(body.config.disable_audio).toBe(false);
    expect(body.config.config_version).toBe(7);
  });

  it('per-PC device flag override beats global flag', async () => {
    // Global: camera disabled; per-PC override: camera enabled
    await db.prepare('UPDATE config SET disable_camera = 1, disable_audio = 0 WHERE id = 1').run();
    await db.prepare('INSERT INTO client_overrides (client_id, blocked_websites, allowed_websites, blocked_apps, updated_at) VALUES (?, ?, ?, ?, ?)')
      .bind('canonical-client', '[]', '[]', '[]', Date.now() / 1000).run();
    // add flag columns via UPDATE on the override row
    await db.prepare('UPDATE client_overrides SET disable_camera = 0 WHERE client_id = ?').bind('canonical-client').run();
    const res = await post();
    expect(res.status).toBe(200);
    const body = await res.json() as any;
    expect(body.config.disable_camera).toBe(false); // per-PC wins
    expect(body.config.disable_audio).toBe(false);
  });

  it('rejects unauthenticated requests', async () => {
    const res = await post(payload, 'wrong-token');
    expect(res.status).toBe(401);
  });
});
