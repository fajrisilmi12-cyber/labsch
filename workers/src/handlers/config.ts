import type { Context } from 'hono';
import type { Env } from '../index';

export async function getAgentConfig(c: Context<{ Bindings: Env }>) {
  const db = c.env.DB;
  const clientId = c.req.query('client_id');

  const cfgRow = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  if (!cfgRow) return c.json({});

  const cfg: any = {
    id: cfgRow.id,
    blocked_apps: JSON.parse(cfgRow.blocked_apps),
    blocked_websites: JSON.parse(cfgRow.blocked_websites),
    allowed_websites: JSON.parse(cfgRow.allowed_websites),
    config_version: cfgRow.config_version,
    updated_at: cfgRow.updated_at,
    updated_by: cfgRow.updated_by,
  };

  if (clientId) {
    const override = await db.prepare(
      'SELECT * FROM client_overrides WHERE client_id = ?'
    ).bind(clientId).first<any>();
    if (override) {
      cfg.blocked_apps = JSON.parse(override.blocked_apps);
      cfg.blocked_websites = JSON.parse(override.blocked_websites);
      cfg.allowed_websites = JSON.parse(override.allowed_websites);
    }
  }

  return c.json(cfg);
}
