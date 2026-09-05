import type { Context } from 'hono';
import type { Env } from '../index';

async function readConfig(db: D1Database) {
  const row = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  if (!row) return null;
  return {
    id: row.id,
    blocked_apps: JSON.parse(row.blocked_apps),
    blocked_websites: JSON.parse(row.blocked_websites),
    allowed_websites: JSON.parse(row.allowed_websites),
    config_version: row.config_version,
    updated_at: row.updated_at,
    updated_by: row.updated_by,
  };
}

async function writeConfig(
  db: D1Database,
  blockedApps: string[], blockedWebsites: string[], allowedWebsites: string[],
  updatedBy: string = 'admin'
): Promise<number> {
  const row = await db.prepare('SELECT config_version FROM config WHERE id = 1').first<any>();
  const newVersion = (row?.config_version ?? 0) + 1;
  await db.prepare(
    `UPDATE config SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
     config_version = ?, updated_at = ?, updated_by = ? WHERE id = 1`
  ).bind(
    JSON.stringify(blockedApps), JSON.stringify(blockedWebsites),
    JSON.stringify(allowedWebsites), newVersion,
    Date.now() / 1000, updatedBy,
  ).run();
  return newVersion;
}

// v0.3.4: Type-safe coercion. Refuses any non-array / non-string payload
// instead of silently JSON-stringifying it into a malformed config that
// bricks all agents on next config pull.
function ensureStringArray(v: unknown, fieldName: string): string[] {
  if (!Array.isArray(v)) {
    throw new Error(`${fieldName} must be an array, got ${typeof v}`);
  }
  return v.map((item, i) => {
    if (typeof item !== 'string') {
      throw new Error(`${fieldName}[${i}] must be a string, got ${typeof item}`);
    }
    const trimmed = item.trim();
    if (trimmed.length === 0) {
      throw new Error(`${fieldName}[${i}] must be a non-empty string`);
    }
    if (trimmed.length > 253) {
      throw new Error(`${fieldName}[${i}] exceeds 253 chars`);
    }
    return trimmed;
  });
}

export async function adminGetConfig(c: Context<{ Bindings: Env }>) {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({}, 404);
  return c.json(cfg);
}

export async function adminSetConfig(c: Context<{ Bindings: Env }>) {
  let req: {
    blocked_apps?: unknown; blocked_websites?: unknown; allowed_websites?: unknown;
  };
  try {
    req = await c.req.json<typeof(req)>();
  } catch {
    return c.json({ detail: 'invalid JSON body' }, 400);
  }
  try {
    const apps = ensureStringArray(req.blocked_apps ?? [], 'blocked_apps');
    const sites = ensureStringArray(req.blocked_websites ?? [], 'blocked_websites');
    const allowed = ensureStringArray(req.allowed_websites ?? [], 'allowed_websites');
    const v = await writeConfig(c.env.DB, apps, sites, allowed);
    return c.json({ config_version: v });
  } catch (e) {
    return c.json({ detail: (e as Error).message }, 400);
  }
}

async function mutateList(
  c: Context<{ Bindings: Env }>,
  listKey: 'blocked_apps' | 'blocked_websites' | 'allowed_websites',
  action: 'add' | 'remove',
) {
  const db = c.env.DB;
  let req: { name?: unknown };
  try {
    req = await c.req.json<typeof(req)>();
  } catch {
    return c.json({ detail: 'invalid JSON body' }, 400);
  }
  const name = req.name;
  if (typeof name !== 'string') {
    return c.json({ detail: '`name` must be a string' }, 400);
  }
  const trimmed = name.trim();
  if (trimmed.length === 0) {
    return c.json({ detail: '`name` must be non-empty' }, 400);
  }
  if (trimmed.length > 253) {
    return c.json({ detail: '`name` exceeds 253 chars' }, 400);
  }

  const cfg = await readConfig(db);
  if (!cfg) return c.json({ detail: 'config not initialized' }, 500);

  const list: string[] = [...cfg[listKey]];
  if (action === 'add' && !list.includes(trimmed)) list.push(trimmed);
  if (action === 'remove' && list.includes(trimmed)) {
    list.splice(list.indexOf(trimmed), 1);
  }

  const args: Record<string, [string[], string[], string[]]> = {
    blocked_apps: [list, cfg.blocked_websites, cfg.allowed_websites],
    blocked_websites: [cfg.blocked_apps, list, cfg.allowed_websites],
    allowed_websites: [cfg.blocked_apps, cfg.blocked_websites, list],
  };
  const [apps, sites, allowed] = args[listKey];
  const v = await writeConfig(db, apps, sites, allowed);
  return c.json({ config_version: v });
}

export const blockSite = (c: any) => mutateList(c, 'blocked_websites', 'add');
export const unblockSite = (c: any) => mutateList(c, 'blocked_websites', 'remove');
export const blockApp = (c: any) => mutateList(c, 'blocked_apps', 'add');
export const unblockApp = (c: any) => mutateList(c, 'blocked_apps', 'remove');
export const allowSite = (c: any) => mutateList(c, 'allowed_websites', 'add');

export async function clearBlockedWebsites(c: Context<{ Bindings: Env }>) {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({ detail: 'config not initialized' }, 500);
  const v = await writeConfig(c.env.DB, cfg.blocked_apps, [], cfg.allowed_websites);
  return c.json({ ok: true, config_version: v });
}

export async function clearBlockedApps(c: Context<{ Bindings: Env }>) {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({ detail: 'config not initialized' }, 500);
  const v = await writeConfig(c.env.DB, [], cfg.blocked_websites, cfg.allowed_websites);
  return c.json({ ok: true, config_version: v });
}

export async function clearAllowedWebsites(c: Context<{ Bindings: Env }>) {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({ detail: 'config not initialized' }, 500);
  const v = await writeConfig(c.env.DB, cfg.blocked_apps, cfg.blocked_websites, []);
  return c.json({ ok: true, config_version: v });
}