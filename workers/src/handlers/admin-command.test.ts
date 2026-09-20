import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:test';
import worker from '../index';
import schema from '../../schema.sql?raw';

const db = (env as unknown as { DB: D1Database }).DB;
const bindings = { DB: db, SCHOOL_API_TOKEN: 'local-test-only', APP_VERSION: 'test' };
const headers = { 'Content-Type': 'application/json', 'X-Agent-Token': 'local-test-only' };
const client = 'command-client';

async function req(path: string, method='GET', body?: unknown) {
  return worker.fetch(new Request('http://local/api/'+path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }), bindings);
}

beforeEach(async () => {
  for (const sql of schema.replace(/--[^\n]*/g, '').split(';').filter((s: string) => s.trim())) await db.prepare(sql).run();
  await db.prepare('INSERT INTO clients (client_id, hostname) VALUES (?, ?)').bind(client, 'PC-CMD').run();
});

describe('remote command delivery confirmation', () => {
  it('heartbeat delivers command without deleting it', async () => {
    expect((await req(`admin/command/${client}`, 'POST', {command:'restart'})).status).toBe(200);
    const hb = await req('heartbeat', 'POST', {client_id:client, hostname:'PC-CMD'});
    expect((await hb.json() as any).pending_command).toBe('restart');
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBe('restart');
  });

  it('failed confirmation retains command and success clears matching command', async () => {
    await req(`admin/command/${client}`, 'POST', {command:'shutdown'});
    let res = await req(`command/${client}/confirm`, 'POST', {command:'shutdown', result:'failed', reason:'privilege denied'});
    expect(res.status).toBe(200);
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBe('shutdown');
    res = await req(`command/${client}/confirm`, 'POST', {command:'shutdown', result:'success'});
    expect(res.status).toBe(200);
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBeNull();
  });

  it('stale confirmation cannot clear a newer command', async () => {
    await req(`admin/command/${client}`, 'POST', {command:'restart'});
    const res = await req(`command/${client}/confirm`, 'POST', {command:'shutdown', result:'success'});
    expect(res.status).toBe(409);
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBe('restart');
  });

  it('launcher_start/launcher_stop accepted and confirmed like other commands', async () => {
    await req(`admin/command/${client}`, 'POST', {command:'launcher_start'});
    const hb = await req('heartbeat', 'POST', {client_id:client, hostname:'PC-CMD'});
    expect((await hb.json() as any).pending_command).toBe('launcher_start');
    let res = await req(`command/${client}/confirm`, 'POST', {command:'launcher_start', result:'success'});
    expect(res.status).toBe(200);
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBeNull();

    await req(`admin/command/${client}`, 'POST', {command:'launcher_stop'});
    const hb2 = await req('heartbeat', 'POST', {client_id:client, hostname:'PC-CMD'});
    expect((await hb2.json() as any).pending_command).toBe('launcher_stop');
    res = await req(`command/${client}/confirm`, 'POST', {command:'launcher_stop', result:'failed', reason:'kiosk flag already off'});
    expect(res.status).toBe(200);
    expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id=?').bind(client).first('pending_command')).toBe('launcher_stop');
  });
});
