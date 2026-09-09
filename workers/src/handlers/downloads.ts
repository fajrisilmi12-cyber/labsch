import type { Context } from 'hono';
import type { Env } from '../index';
import { ValidationError, isValidClientId, withErrorHandler } from './validation';

const ALLOWED_DEST = new Set(['desktop', 'documents']);
const BLOCKED_EXTENSIONS = new Set(['.msc']);
const DOWNLOAD_PROTOCOL = 1;

function isPlainHttpsUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length === 0 || value.length > 500) return false;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'https:') return false;
  if (parsed.username || parsed.password) return false;
  const host = parsed.hostname.toLowerCase();
  if (/[\x00-\x20\x7f\\]/.test(value) || (parsed.port && parsed.port !== '443')) return false;
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) return false;
  if (host === '0.0.0.0' || host === '::' || host === '::1') return false;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) return false;
  if (host.includes(':')) return false;
  return true;
}

function sanitizeFilename(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? '';
  let cleaned = base.replace(/[\x00-\x1f\x7f]/g, '').replace(/[^A-Za-z0-9._ -]/g, '_');
  while (cleaned.includes('..')) cleaned = cleaned.replace(/\.\./g, '.');
  if (cleaned.startsWith('.')) cleaned = '_' + cleaned.slice(1);
  cleaned = cleaned.slice(0, 120).replace(/[ .]+$/, '');
  if (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(cleaned)) cleaned = '_' + cleaned;
  return cleaned;
}

interface DownloadTaskReq {
  url?: unknown;
  filename?: unknown;
  destination?: unknown;
  extensions?: unknown;
  autorun?: unknown;
  run_as?: unknown;
  clients?: unknown;
  groups?: unknown;
  sha256?: unknown;
  max_size_mb?: unknown;
  ttl_seconds?: unknown;
  run_args?: unknown;
}

interface TaskPayload {
  task_id: string;
  url: string;
  filename: string;
  destination: string;
  extensions: string[];
  autorun: boolean;
  run_as: 'user' | 'system';
  clients: string[];
  groups: string[];
  sha256: string | null;
  max_size_mb: number;
  protocol: number;
}

function validateCreate(req: DownloadTaskReq): TaskPayload {
  if (!req || typeof req !== 'object') throw new ValidationError('body must be a JSON object');
  if (req.run_args !== undefined) throw new ValidationError('run_args unsupported in this test release');
  if (!isPlainHttpsUrl(req.url)) throw new ValidationError('url must be an https URL on a public host');
  let filename = sanitizeFilename(typeof req.filename === 'string' && req.filename ? req.filename : new URL(req.url as string).pathname.split('/').pop() || '');
  if (!filename || filename === '.' || filename === '..') throw new ValidationError('filename required');
  const lower = filename.toLowerCase();
  for (const ext of BLOCKED_EXTENSIONS) {
    if (lower.endsWith(ext)) throw new ValidationError(`filename extension not allowed: ${ext}`);
  }
  const destination = req.destination === undefined ? 'desktop' : String(req.destination);
  if (!ALLOWED_DEST.has(destination)) throw new ValidationError('destination must be desktop|documents');
  if (req.extensions !== undefined) {
    if (!Array.isArray(req.extensions)) throw new ValidationError('extensions must be an array');
    for (const e of req.extensions) {
      if (typeof e !== 'string' || e.length === 0 || e.length > 16 || !/^[A-Za-z0-9]+$/.test(e)) {
        throw new ValidationError('each extension must be alphanumeric <=16 chars');
      }
    }
  }
  if (req.autorun !== undefined && typeof req.autorun !== 'boolean') throw new ValidationError('autorun must be boolean');
  const autorun = req.autorun === undefined ? true : req.autorun;
  if (req.run_as !== undefined && req.run_as !== 'user' && req.run_as !== 'system') throw new ValidationError('run_as must be user|system');
  const run_as = req.run_as === undefined ? 'user' : req.run_as;
  if (autorun && run_as === 'system') throw new ValidationError('system autorun is unsupported in this test release');
  const clientsRaw = req.clients === undefined ? [] : req.clients;
  if (!Array.isArray(clientsRaw)) throw new ValidationError('clients must be an array of client ids');
  for (const id of clientsRaw) {
    if (typeof id !== 'string' || !isValidClientId(id)) throw new ValidationError('clients entries must be valid client ids');
  }
  const groupsRaw = req.groups === undefined ? [] : req.groups;
  if (!Array.isArray(groupsRaw)) throw new ValidationError('groups must be an array of group names');
  for (const g of groupsRaw) {
    if (typeof g !== 'string' || g.length === 0 || g.length > 64) throw new ValidationError('groups entries must be names <=64 chars');
  }
  if (clientsRaw.length === 0 && groupsRaw.length === 0) {
    throw new ValidationError('targets required: at least one client or group');
  }
  if (groupsRaw.length) throw new ValidationError('groups unsupported; select explicit clients');
  if (clientsRaw.length > 100) throw new ValidationError('maximum 100 explicit clients');
  const sha256 = req.sha256 === undefined || req.sha256 === null || req.sha256 === '' ? null : String(req.sha256).toLowerCase();
  if (sha256 !== null && !/^[a-f0-9]{64}$/.test(sha256)) throw new ValidationError('sha256 must be 64 lowercase hex chars');
  if (autorun && sha256 === null) throw new ValidationError('sha256 is required when autorun is enabled');
  if (req.max_size_mb !== undefined && (typeof req.max_size_mb !== 'number' || !Number.isInteger(req.max_size_mb) || req.max_size_mb < 1 || req.max_size_mb > 2048)) {
    throw new ValidationError('max_size_mb must be an integer 1..2048');
  }
  if (req.ttl_seconds !== undefined && (typeof req.ttl_seconds !== 'number' || !Number.isInteger(req.ttl_seconds) || req.ttl_seconds < 60 || req.ttl_seconds > 604800)) {
    throw new ValidationError('ttl_seconds must be an integer 60..604800');
  }
  return {
    task_id: crypto.randomUUID(),
    url: req.url as string,
    filename,
    destination,
    extensions: (req.extensions as string[]) ?? [],
    autorun,
    run_as,
    clients: [...new Set(clientsRaw as string[])],
    groups: [...new Set(groupsRaw as string[])],
    sha256,
    max_size_mb: (req.max_size_mb as number) ?? 2048,
    protocol: DOWNLOAD_PROTOCOL,
  };
}

export const createDownloadTask = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const req = await c.req.json() as DownloadTaskReq;
  const payload = validateCreate(req);
  const db = c.env.DB;
  const known: string[] = [];
  const missing: string[] = [];
  for (const id of payload.clients) {
    const row = await db.prepare('SELECT client_id FROM clients WHERE client_id = ? OR display_name = ?').bind(id, id).first<{ client_id: string }>();
    if (row) known.push(row.client_id); else missing.push(id);
  }
  if (known.length === 0 && payload.groups.length === 0) {
    throw new ValidationError(`no known clients in targets (missing: ${missing.join(', ')})`);
  }
  payload.clients = known;
  const now = Date.now() / 1000;
  await db.prepare(
    'INSERT INTO download_tasks (task_id, payload, created_at, expires_at, status) VALUES (?, ?, ?, ?, ?)'
  ).bind(payload.task_id, JSON.stringify(payload), now, now + ((req.ttl_seconds as number) ?? 604800), 'active').run();
  return c.json({ task_id: payload.task_id, missing_clients: missing, protocol: DOWNLOAD_PROTOCOL }, 201);
});

export const pendingDownloads = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const client_id = c.req.query('client_id') ?? '';
  if (!isValidClientId(client_id)) throw new ValidationError('client_id query required');
  const protocol = Number(c.req.query('protocol') ?? '0');
  if (!Number.isInteger(protocol) || protocol < 0 || protocol > 99) throw new ValidationError('protocol must be an integer');
  const version = c.req.query('version') ?? '';
  if (protocol < DOWNLOAD_PROTOCOL || !version) {
    return c.json({ pending_downloads: [], upgrade_required: true, latest_protocol: DOWNLOAD_PROTOCOL });
  }
  const now = Date.now() / 1000;
  const rows = await c.env.DB.prepare(
    `SELECT payload FROM download_tasks t WHERE status = 'active' AND expires_at > ? AND EXISTS (SELECT 1 FROM json_each(t.payload, '$.clients') j WHERE j.value = ?) AND NOT EXISTS (SELECT 1 FROM download_status s WHERE s.task_id=t.task_id AND s.client_id=? AND s.download_state IN ('done','failed','skipped')) ORDER BY created_at LIMIT 20`
  ).bind(now, client_id, client_id).all<{ payload: string }>();
  const tasks = rows.results.map(r => JSON.parse(r.payload) as TaskPayload).filter(t => t.clients.includes(client_id));
  return c.json({ pending_downloads: tasks, upgrade_required: false, latest_protocol: DOWNLOAD_PROTOCOL });
});

const DOWNLOAD_STATES = new Set(['pending', 'downloading', 'done', 'failed', 'skipped']);
const EXECUTION_STATES = new Set(['not_requested', 'launching', 'launched', 'failed_launch', 'unsupported']);

function clampReportText(value: unknown): string {
  return String(value ?? '').slice(0, 500);
}

export const reportDownload = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const req = await c.req.json() as Record<string, unknown>;
  if (!req || typeof req !== 'object') throw new ValidationError('body must be a JSON object');
  const task_id = String(req.task_id ?? '');
  const client_id = String(req.client_id ?? '');
  if (!/^[a-f0-9-]{36}$/.test(task_id)) throw new ValidationError('task_id must be a UUID');
  if (!isValidClientId(client_id)) throw new ValidationError('client_id must match [A-Za-z0-9._-]{1,128}');
  const task = await c.env.DB.prepare('SELECT payload FROM download_tasks WHERE task_id = ?').bind(task_id).first<{ payload: string }>();
  if (!task) return c.json({ error: 'task not found' }, 404);
  const payload = JSON.parse(task.payload) as TaskPayload;
  if (!payload.clients.includes(client_id)) return c.json({ error: 'client not targeted by this task' }, 403);
  const download_state = req.download_state === undefined ? 'downloading' : String(req.download_state);
  if (!DOWNLOAD_STATES.has(download_state)) throw new ValidationError(`download_state must be one of: ${[...DOWNLOAD_STATES].join(', ')}`);
  const execution_state = req.execution_state === undefined ? 'not_requested' : String(req.execution_state);
  if (!EXECUTION_STATES.has(execution_state)) throw new ValidationError(`execution_state must be one of: ${[...EXECUTION_STATES].join(', ')}`);
  if (req.exit_code !== undefined && typeof req.exit_code !== 'number' && typeof req.exit_code !== 'string') throw new ValidationError('exit_code must be numeric');
  if (req.bytes !== undefined && (typeof req.bytes !== 'number' || !Number.isInteger(req.bytes) || req.bytes < 0 || req.bytes > 2 ** 48)) throw new ValidationError('bytes must be an integer >= 0');
  const reported_sha = req.sha256 === undefined || req.sha256 === null || req.sha256 === '' ? null : String(req.sha256).toLowerCase();
  if (reported_sha !== null && !/^[a-f0-9]{64}$/.test(reported_sha)) throw new ValidationError('sha256 must be 64 lowercase hex chars');
  const now = Date.now() / 1000;
  const report = {
    download_state, execution_state,
    bytes: req.bytes ?? null,
    sha256: reported_sha,
    exit_code: req.exit_code === undefined ? null : Number(req.exit_code),
    error: req.error === undefined ? null : clampReportText(req.error),
    updated_at: now,
  };
  await c.env.DB.prepare(
    `INSERT INTO download_status (task_id, client_id, download_state, execution_state, report, updated_at)
     VALUES (?, ?, ?, ?, ?, ?)
     ON CONFLICT(task_id, client_id) DO UPDATE SET
       download_state = excluded.download_state,
       execution_state = CASE
         WHEN excluded.execution_state = 'not_requested' AND download_status.execution_state != 'not_requested' THEN download_status.execution_state
         ELSE excluded.execution_state END,
       report = excluded.report,
       updated_at = excluded.updated_at
     WHERE download_status.download_state NOT IN ('done','failed','skipped')`
  ).bind(task_id, client_id, download_state, execution_state, JSON.stringify(report), now).run();
  return c.json({ ok: true });
});

export const listDownloadTasks = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const now = Date.now() / 1000;
  const tasks = await c.env.DB.prepare(
    'SELECT task_id, payload, created_at, expires_at, status FROM download_tasks ORDER BY created_at DESC LIMIT 100'
  ).all<{ task_id: string; payload: string; created_at: number; expires_at: number; status: string }>();
  const out = [];
  for (const row of tasks.results) {
    const payload = JSON.parse(row.payload) as TaskPayload;
    const statuses = await c.env.DB.prepare(
      'SELECT download_state, COUNT(*) AS n FROM download_status WHERE task_id = ? GROUP BY download_state'
    ).bind(row.task_id).all<{ download_state: string; n: number }>();
    const rollup: Record<string, number> = { pending: 0, downloading: 0, done: 0, failed: 0, skipped: 0 };
    for (const s of statuses.results) rollup[s.download_state] = s.n;
    rollup.pending = Math.max(0, payload.clients.length - statuses.results.reduce((n, s) => n + s.n, 0));
    const details = await c.env.DB.prepare('SELECT client_id, download_state, execution_state, report FROM download_status WHERE task_id=?').bind(row.task_id).all();
    let status = row.status;
    if (status === 'active' && row.expires_at <= now) status = 'expired';
    out.push({
      task_id: row.task_id, filename: payload.filename, url: payload.url, autorun: payload.autorun,
      run_as: payload.run_as, targets: { clients: payload.clients.length, groups: payload.groups.length },
      created_at: row.created_at, expires_at: row.expires_at, status, rollup, clients: details.results,
    });
  }
  return c.json({ tasks: out });
});

export const cancelDownloadTask = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const task_id = c.req.param('task_id') ?? '';
  if (!/^[a-f0-9-]{36}$/.test(task_id)) throw new ValidationError('task_id must be a UUID');
  const existing = await c.env.DB.prepare('SELECT status FROM download_tasks WHERE task_id = ?').bind(task_id).first<{ status: string }>();
  if (!existing) return c.json({ error: 'task not found' }, 404);
  await c.env.DB.prepare("UPDATE download_tasks SET status = 'cancelled' WHERE task_id = ?").bind(task_id).run();
  return c.json({ ok: true, status: 'cancelled' });
});
