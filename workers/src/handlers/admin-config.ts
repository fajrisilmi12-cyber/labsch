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
  blockedApps: string[], blockedWebsites: string[],
  allowedWebsites: string[], updatedBy: string = 'admin'
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

export async function adminGetConfig(c: Context<{ Bindings: Env }>) {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({}, 404);
  return c.json(cfg);
}

export async function adminSetConfig(c: Context<{ Bindings: Env }>) {
  const req = await c.req.json<{
    blocked_apps?: string[]; blocked_websites?: string[]; allowed_websites?: string[];
  }>();
  const v = await writeConfig(
    c.env.DB,
    req.blocked_apps ?? [], req.blocked_websites ?? [], req.allowed_websites ?? [],
  );
  return c.json({ config_version: v });
}

async function mutateList(
  c: Context<{ Bindings: Env }>,
  listKey: 'blocked_apps' | 'blocked_websites' | 'allowed_websites',
  action: 'add' | 'remove',
) {
  const db = c.env.DB;
  const req = await c.req.json<{ name: string }>();
  const cfg = await readConfig(db);
  if (!cfg) return c.json({ detail: 'config not initialized' }, 500);

  const list: string[] = [...cfg[listKey]];
  const name = req.name;
  if (action === 'add' && !list.includes(name)) list.push(name);
  if (action === 'remove' && list.includes(name)) {
    list.splice(list.indexOf(name), 1);
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
