import type { Context } from 'hono';
import type { Env } from '../index';
import { withErrorHandler, safeJsonParse } from './validation';

export const getAgentConfig = withErrorHandler(async (c: Context<{ Bindings: Env }>) => {
  const db = c.env.DB;
  const clientId = c.req.query('client_id');

  const cfgRow = await db.prepare('SELECT * FROM config WHERE id = 1').first<any>();
  if (!cfgRow) return c.json({});

  const cfg: any = {
    id: cfgRow.id,
    blocked_apps: safeJsonParse<string[]>(cfgRow.blocked_apps, []),
    blocked_websites: safeJsonParse<string[]>(cfgRow.blocked_websites, []),
    allowed_websites: safeJsonParse<string[]>(cfgRow.allowed_websites, []),
    config_version: cfgRow.config_version,
    updated_at: cfgRow.updated_at,
    updated_by: cfgRow.updated_by,
  };

  // Device flags: global defaults from config row
  let disableCamera = cfgRow.disable_camera ? 1 : 0;
  let disableAudio = cfgRow.disable_audio ? 1 : 0;

  if (clientId) {
    const override = await db.prepare(
      'SELECT * FROM client_overrides WHERE client_id = ?'
    ).bind(clientId).first<any>();
    if (override && override.has_list_override) {
      cfg.blocked_apps = safeJsonParse<string[]>(override.blocked_apps, []);
      cfg.blocked_websites = safeJsonParse<string[]>(override.blocked_websites, []);
      cfg.allowed_websites = safeJsonParse<string[]>(override.allowed_websites, []);
    }
    // Per-client device-flag override wins over global (mirror heartbeat.ts)
    if (override) {
      disableCamera = override.disable_camera ? 1 : 0;
      disableAudio = override.disable_audio ? 1 : 0;
    }
  }

  cfg.disable_camera = disableCamera === 1;
  cfg.disable_audio = disableAudio === 1;

  return c.json(cfg);
});
