import { beforeEach, describe, expect, it } from 'vitest';
import { env } from 'cloudflare:test';
import worker from '../index';
import schema from '../../schema.sql?raw';

const db = (env as unknown as { DB: D1Database }).DB;
const bindings = { DB: db, SCHOOL_API_TOKEN: 'local-test-only', APP_VERSION: 'test' };
const headers = { 'Content-Type': 'application/json', 'X-Agent-Token': 'local-test-only' };

async function heartbeat(body: unknown) {
  return worker.fetch(new Request('http://local/api/heartbeat', {
    method: 'POST', headers, body: JSON.stringify(body),
  }), bindings);
}

beforeEach(async () => {
  for (const sql of schema.replace(/--[^\n]*/g, '').split(';').filter((s: string) => s.trim())) await db.prepare(sql).run();
});

describe('placeholder client_id collision repair', () => {
  it('maps two devices using literal client_id to separate stable records', async () => {
    const lab3 = { client_id:'client_id', hostname:'DESKTOP-LAB3', display_name:'Lab3', device_id:'dev-1111111111111111', mac:'00:11:22:33:44:55', version:'0.4.0-test9' };
    const lab8 = { client_id:'client_id', hostname:'DESKTOP-LAB8', display_name:'Lab8', device_id:'dev-8888888888888888', mac:'00:11:22:33:44:88', version:'0.4.0-test9' };
    const a = await (await heartbeat(lab3)).json() as any;
    const b = await (await heartbeat(lab8)).json() as any;
    expect(a.canonical_client_id).not.toBe('client_id');
    expect(b.canonical_client_id).not.toBe('client_id');
    expect(a.canonical_client_id).not.toBe(b.canonical_client_id);
    const rows = await db.prepare("SELECT client_id, display_name, device_id FROM clients WHERE display_name IN ('Lab3','Lab8') ORDER BY display_name").all<any>();
    expect(rows.results).toHaveLength(2);
    expect(rows.results.map(r => r.display_name)).toEqual(['Lab3','Lab8']);
    const again = await (await heartbeat(lab3)).json() as any;
    expect(again.canonical_client_id).toBe(a.canonical_client_id);
  });
});
