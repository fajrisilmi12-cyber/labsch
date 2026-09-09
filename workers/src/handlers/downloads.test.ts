import { beforeEach, expect, it } from 'vitest';
import { env } from 'cloudflare:test';
import worker from '../index';
import schema from '../../schema.sql?raw';

const db = (env as unknown as { DB: D1Database }).DB;
const bindings = { DB: db, SCHOOL_API_TOKEN: 'local-test-only', APP_VERSION: 'test' };
const task = { url: 'https://example.com/test.txt', filename: 'test.txt', autorun: false, clients: ['synthetic-download-a'] };
async function request(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST', token = 'local-test-only') {
  return worker.fetch(new Request(`https://local/api/${path}`, {
    method, headers: { 'Content-Type': 'application/json', 'X-Agent-Token': token },
    body: body === undefined ? undefined : JSON.stringify(body),
  }), bindings);
}
beforeEach(async () => {
  for (const sql of schema.replace(/--[^\n]*/g, '').split(';').filter(s => s.trim())) await db.prepare(sql).run();
  await db.prepare('INSERT INTO clients (client_id, hostname, version) VALUES (?, ?, ?)').bind('synthetic-download-a', 'SYNTHETIC-A', '0.4.0').run();
});
it('creates an explicitly targeted independent queue and delivers only to upgraded target', async () => {
  const response = await request('admin/downloads', task);
  expect(response.status).toBe(201);
  const created = await response.json() as any;
  expect(created.task_id).toMatch(/^[a-f0-9-]{36}$/);
  const pending = await request('downloads/pending?client_id=synthetic-download-a&protocol=1&version=0.4.0');
  expect((await pending.json() as any).pending_downloads[0].task_id).toBe(created.task_id);
  expect((await (await request('downloads/pending?client_id=synthetic-download-b&protocol=1&version=0.4.0')).json() as any).pending_downloads).toEqual([]);
  expect((await (await request('downloads/pending?client_id=synthetic-download-a')).json() as any).pending_downloads).toEqual([]);
  expect((await (await request('downloads/pending?client_id=synthetic-download-a&protocol=1')).json() as any).pending_downloads).toEqual([]);
  expect(await db.prepare('SELECT pending_command FROM clients WHERE client_id = ?').bind('synthetic-download-a').first('pending_command')).toBeNull();
});

it('accepts agent report idempotently with separate download and execution states', async () => {
  const created = await (await request('admin/downloads', task)).json() as any;
  const report = { task_id: created.task_id, client_id: 'synthetic-download-a', download_state: 'done', bytes: 12, sha256: 'a'.repeat(64), execution_state: 'launched', exit_code: 0 };
  const first = await request(`downloads/report`, report, 'POST');
  expect(first.status).toBe(200);
  const second = await request(`downloads/report`, report, 'POST');
  expect(second.status).toBe(200);
  const row = await db.prepare('SELECT download_state, execution_state, report FROM download_status WHERE task_id = ? AND client_id = ?')
    .bind(created.task_id, 'synthetic-download-a').first() as any;
  expect(row.download_state).toBe('done');
  expect(row.execution_state).toBe('launched');
  const count = await db.prepare('SELECT COUNT(*) AS c FROM download_status').first() as any;
  expect(count.c).toBe(1);
  const denied = await request(`downloads/report`, { ...report, client_id: 'synthetic-download-b' }, 'POST');
  expect(denied.status).toBe(403);
});

it('lists tasks with per-client rollup and cancels delivery', async () => {
  await db.prepare('INSERT INTO clients (client_id, hostname, version) VALUES (?, ?, ?)').bind('synthetic-download-b', 'SYNTHETIC-B', '0.4.0').run();
  const createdA = await (await request('admin/downloads', { ...task, clients: ['synthetic-download-a', 'synthetic-download-b'] })).json() as any;
  const report = (task_id: string, client_id: string, state: string) =>
    request('downloads/report', { task_id, client_id, download_state: state, execution_state: 'not_requested' }, 'POST');
  await report(createdA.task_id, 'synthetic-download-a', 'done');
  await report(createdA.task_id, 'synthetic-download-b', 'failed');
  const list = await (await request('admin/downloads')).json() as any;
  expect(list.tasks).toHaveLength(1);
  expect(list.tasks[0].task_id).toBe(createdA.task_id);
  expect(list.tasks[0].rollup).toEqual({ done: 1, failed: 1, pending: 0, downloading: 0, skipped: 0 });
  const cancel = await request(`admin/downloads/${createdA.task_id}/cancel`, undefined, 'POST');
  expect(cancel.status).toBe(200);
  const after = await (await request('downloads/pending?client_id=synthetic-download-a&protocol=1&version=0.4.0')).json() as any;
  expect(after.pending_downloads).toEqual([]);
  const second = await request(`admin/downloads/${createdA.task_id}/cancel`, undefined, 'POST');
  expect(second.status).toBe(200);
});

it('honors TTL and terminal reports stop delivery without regression', async () => {
  const created = await (await request('admin/downloads', { ...task, ttl_seconds: 60 })).json() as any;
  const row = await db.prepare('SELECT created_at, expires_at FROM download_tasks WHERE task_id = ?').bind(created.task_id).first() as any;
  expect(row.expires_at - row.created_at).toBe(60);
  const report = {task_id: created.task_id, client_id:'synthetic-download-a', download_state:'done', execution_state:'failed_launch', error:'no user'};
  await request('downloads/report', report);
  await request('downloads/report', {...report, download_state:'downloading', execution_state:'not_requested'});
  const pending = await (await request('downloads/pending?client_id=synthetic-download-a&protocol=1&version=0.4.0')).json() as any;
  expect(pending.pending_downloads).toEqual([]);
  const status = await db.prepare('SELECT download_state FROM download_status WHERE task_id=?').bind(created.task_id).first() as any;
  expect(status.download_state).toBe('done');
});
it('rejects unsupported groups and arguments rather than silently ignoring', async () => {
  expect((await request('admin/downloads', {...task, groups:['LabA']})).status).toBe(400);
  expect((await request('admin/downloads', {...task, run_args:'/quiet'})).status).toBe(400);
});

it('expired tasks are not delivered and are marked expired by listing', async () => {
  const created = await (await request('admin/downloads', task)).json() as any;
  await db.prepare('UPDATE download_tasks SET expires_at = ? WHERE task_id = ?').bind(1, created.task_id).run();
  const pending = await (await request('downloads/pending?client_id=synthetic-download-a&protocol=1&version=0.4.0')).json() as any;
  expect(pending.pending_downloads).toEqual([]);
  const list = await (await request('admin/downloads')).json() as any;
  expect(list.tasks[0].status).toBe('expired');
});

it('rejects private, non-https, and no-target (implicit broadcast) tasks', async () => {
  for (const url of ['http://example.com/a.pdf', 'https://192.168.1.20/a.pdf', 'https://10.0.0.5/a.pdf',
                     'https://172.16.0.1/a.pdf', 'file://host/share/a.pdf', 'https://127.0.0.1/a.pdf',
                     'https://user:pass@example.com/a.pdf', 'https://localhost/a.pdf']) {
    const res = await request('admin/downloads', { ...task, url, clients: ['synthetic-download-a'] });
    expect(res.status).toBe(400);
  }
  const noTargets = await request('admin/downloads', { url: task.url, filename: 'test.txt', sha256: 'a'.repeat(64) });
  expect(noTargets.status).toBe(400);
  const noSha = await request('admin/downloads', { ...task });
  expect(noSha.status).toBe(201);
  const autorunNoSha = await request('admin/downloads', { ...task, autorun: true });
  expect(autorunNoSha.status).toBe(400);
  const sysRun = await request('admin/downloads', { ...task, sha256: 'a'.repeat(64), run_as: 'system' });
  expect(sysRun.status).toBe(201);
  const autorunSys = await request('admin/downloads', { ...task, sha256: 'a'.repeat(64), run_as: 'system', autorun: true });
  expect(autorunSys.status).toBe(400);
});
