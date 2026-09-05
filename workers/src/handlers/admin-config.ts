import type { Context } from 'hono';
import type { Env } from '../index';
import {
  ValidationError, withErrorHandler, safeJsonParse, MAX_ARRAY_ITEMS,
} from './validation';

async function readConfig(db: D1Database) {
  const row = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  if (!row) return null;
  return {
    id: row.id,
    blocked_apps: safeJsonParse<string[]>(row.blocked_apps, []),
    blocked_websites: safeJsonParse<string[]>(row.blocked_websites, []),
    allowed_websites: safeJsonParse<string[]>(row.allowed_websites, []),
    config_version: row.config_version,
    updated_at: row.updated_at,
    updated_by: row.updated_by,
  };
}

// Optimistic concurrency: bump config_version and only commit if the
// previous value matches. Loser retries up to 3 times. Fixes the
// read-modify-write race where two concurrent add/remove ops could
// both compute the same new version and one would silently clobber.
async function writeConfig(
  db: D1Database,
  blockedApps: string[], blockedWebsites: string[], allowedWebsites: string[],
  updatedBy: string = 'admin',
  maxRetries = 3,
): Promise<number> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const row = await db.prepare(
      'SELECT config_version FROM config WHERE id = 1'
    ).first<any>();
    const currentVersion = row?.config_version ?? 0;
    const newVersion = currentVersion + 1;
    const updatedAt = Date.now() / 1000;
    const result = await db.prepare(
      `UPDATE config
       SET blocked_apps = ?, blocked_websites = ?, allowed_websites = ?,
           config_version = ?, updated_at = ?, updated_by = ?
       WHERE id = 1 AND config_version = ?`
    ).bind(
      JSON.stringify(blockedApps), JSON.stringify(blockedWebsites),
      JSON.stringify(allowedWebsites), newVersion, updatedAt, updatedBy,
      currentVersion,
    ).run();
    if (result.meta.changes && result.meta.changes > 0) return newVersion;
    // Lost the race; retry
  }
  throw new ValidationError('config write contention; please retry', 503);
}

function ensureStringArray(
  v: unknown, fieldName: string,
  maxItems = MAX_ARRAY_ITEMS,
  maxItemLen = 253,
): string[] {
  if (!Array.isArray(v)) {
    throw new ValidationError(`${fieldName} must be an array, got ${typeof v}`);
  }
  if (v.length > maxItems) {
    throw new ValidationError(`${fieldName} exceeds ${maxItems} items (got ${v.length})`);
  }
  const seen = new Set<string>();
  return v.map((item, i) => {
    if (typeof item !== 'string') {
      throw new ValidationError(`${fieldName}[${i}] must be a string, got ${typeof item}`);
    }
    const trimmed = item.trim();
    if (trimmed.length === 0) {
      throw new ValidationError(`${fieldName}[${i}] must be a non-empty string`);
    }
    if (trimmed.length > maxItemLen) {
      throw new ValidationError(`${fieldName}[${i}] exceeds ${maxItemLen} chars`);
    }
    // Dedupe within the same array (avoid same entry twice = wasted bytes)
    if (seen.has(trimmed)) {
      throw new ValidationError(`${fieldName}[${i}] duplicate of earlier entry`);
    }
    seen.add(trimmed);
    return trimmed;
  });
}

export const adminGetConfig = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) return c.json({}, 404);
  return c.json(cfg);
});

export const adminSetConfig = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  let req: {
    blocked_apps?: unknown; blocked_websites?: unknown; allowed_websites?: unknown;
  };
  try {
    req = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }
  const apps = ensureStringArray(req.blocked_apps ?? [], 'blocked_apps', 500);
  const sites = ensureStringArray(req.blocked_websites ?? [], 'blocked_websites', 5000);
  const allowed = ensureStringArray(req.allowed_websites ?? [], 'allowed_websites', 5000);
  const v = await writeConfig(c.env.DB, apps, sites, allowed);
  return c.json({ config_version: v });
});

const LIST_KEYS = {
  blocked_apps: { idx: 0, max: 500 },
  blocked_websites: { idx: 1, max: 5000 },
  allowed_websites: { idx: 2, max: 5000 },
} as const;

type ListKey = keyof typeof LIST_KEYS;

async function mutateList(
  c: Context<{ Bindings: Env }>,
  listKey: ListKey,
  action: 'add' | 'remove',
) {
  const db = c.env.DB;
  let req: { name?: unknown };
  try {
    req = await c.req.json();
  } catch {
    throw new ValidationError('invalid JSON body');
  }
  if (typeof req.name !== 'string') {
    throw new ValidationError('`name` must be a string');
  }
  const trimmed = req.name.trim();
  if (trimmed.length === 0) {
    throw new ValidationError('`name` must be non-empty');
  }
  if (trimmed.length > 253) {
    throw new ValidationError('`name` exceeds 253 chars');
  }

  const cfg = await readConfig(db);
  if (!cfg) throw new ValidationError('config not initialized', 500);

  const list: string[] = [...cfg[listKey]];
  if (action === 'add') {
    if (list.length >= LIST_KEYS[listKey].max) {
      throw new ValidationError(`${listKey} already at max ${LIST_KEYS[listKey].max} items`);
    }
    if (!list.includes(trimmed)) list.push(trimmed);
  } else {
    const idx = list.indexOf(trimmed);
    if (idx >= 0) list.splice(idx, 1);
  }

  const [apps, sites, allowed]: [string[], string[], string[]] = [
    cfg.blocked_apps, cfg.blocked_websites, cfg.allowed_websites,
  ];
  if (listKey === 'blocked_apps') apps.splice(0, apps.length, ...list);
  if (listKey === 'blocked_websites') sites.splice(0, sites.length, ...list);
  if (listKey === 'allowed_websites') allowed.splice(0, allowed.length, ...list);

  const v = await writeConfig(db, apps, sites, allowed);
  return c.json({ config_version: v });
}

export const blockSite    = (c: any) => mutateList(c, 'blocked_websites', 'add');
export const unblockSite  = (c: any) => mutateList(c, 'blocked_websites', 'remove');
export const blockApp     = (c: any) => mutateList(c, 'blocked_apps', 'add');
export const unblockApp   = (c: any) => mutateList(c, 'blocked_apps', 'remove');
export const allowSite    = (c: any) => mutateList(c, 'allowed_websites', 'add');

export const clearBlockedWebsites = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) throw new ValidationError('config not initialized', 500);
  const v = await writeConfig(c.env.DB, cfg.blocked_apps, [], cfg.allowed_websites);
  return c.json({ ok: true, config_version: v });
});

export const clearBlockedApps = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) throw new ValidationError('config not initialized', 500);
  const v = await writeConfig(c.env.DB, [], cfg.blocked_websites, cfg.allowed_websites);
  return c.json({ ok: true, config_version: v });
});

export const clearAllowedWebsites = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const cfg = await readConfig(c.env.DB);
  if (!cfg) throw new ValidationError('config not initialized', 500);
  const v = await writeConfig(c.env.DB, cfg.blocked_apps, cfg.blocked_websites, []);
  return c.json({ ok: true, config_version: v });
});
