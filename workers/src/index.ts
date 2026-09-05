import { Hono } from 'hono';
import { verifyToken } from './auth';
import { health } from './handlers/health';
import { heartbeat } from './handlers/heartbeat';
import { getAgentConfig } from './handlers/config';
import { postEvent, listEvents } from './handlers/events';
import { listClients, clientDetail, getOverride, setOverride, clearOverride } from './handlers/clients';
import {
  adminGetConfig, adminSetConfig, blockSite, unblockSite, blockApp, unblockApp,
  allowSite, clearBlockedWebsites, clearBlockedApps, clearAllowedWebsites,
} from './handlers/admin-config';
import {
  createOrUpdateProfile, listProfiles, getOneProfile, deleteOneProfile, activateProfile,
} from './handlers/admin-profiles';
import { setClientCommand, clearClientCommand } from './handlers/admin-command';
import { setDeviceFlags, getDeviceFlags } from './handlers/admin-device';
import { markStaleClients } from './handlers/health';
import { generateApiToken, getTokenInfo, revokeApiToken } from './handlers/admin-token';

export interface Env {
  DB: D1Database;
  SCHOOL_API_TOKEN: string;
  APP_VERSION: string;
  TOKEN_META?: KVNamespace;  // optional — add via `wrangler kv:namespace create "TOKEN_META"`
}

const app = new Hono<{ Bindings: Env }>();

// Health — open endpoint
app.get('/api/health', health);

// Auth middleware for everything else
app.use('/api/*', verifyToken);

// Agent endpoints
app.post('/api/heartbeat', heartbeat);
app.get('/api/config', getAgentConfig);
app.post('/api/event', postEvent);
app.get('/api/events', listEvents);

// Clients
app.get('/api/clients', listClients);
app.get('/api/clients/:client_id', clientDetail);
app.get('/api/clients/:client_id/override', getOverride);
app.put('/api/clients/:client_id/override', setOverride);
app.delete('/api/clients/:client_id/override', clearOverride);

// Admin — config
app.get('/api/admin/config', adminGetConfig);
app.post('/api/admin/config', adminSetConfig);
app.post('/api/admin/block-site', blockSite);
app.post('/api/admin/unblock-site', unblockSite);
app.post('/api/admin/block-app', blockApp);
app.post('/api/admin/unblock-app', unblockApp);
app.post('/api/admin/allow-site', allowSite);
app.post('/api/admin/clear-blocked-websites', clearBlockedWebsites);
app.post('/api/admin/clear-blocked-apps', clearBlockedApps);
app.post('/api/admin/clear-allowed-websites', clearAllowedWebsites);

// Admin — profiles
app.post('/api/admin/profiles', createOrUpdateProfile);
app.get('/api/admin/profiles', listProfiles);
app.get('/api/admin/profiles/:name', getOneProfile);
app.delete('/api/admin/profiles/:name', deleteOneProfile);
app.post('/api/admin/profiles/:name/activate', activateProfile);

// Admin — remote commands
app.post('/api/admin/command/:client_id', setClientCommand);
app.delete('/api/admin/command/:client_id', clearClientCommand);

// Admin — device control (camera/audio)
app.post('/api/admin/device', setDeviceFlags);            // global: {"disable_camera":true,"disable_audio":true}
app.get('/api/admin/device', getDeviceFlags);
app.post('/api/admin/device/:client_id', setDeviceFlags); // per-PC
app.delete('/api/admin/device/:client_id', setDeviceFlags); // per-PC: clear override

// Admin — token management (rotate / inspect / revoke metadata)
app.post('/api/admin/token/generate', generateApiToken);
app.get('/api/admin/token/info', getTokenInfo);
app.delete('/api/admin/token', revokeApiToken);

// Cron trigger — mark stale clients as offline
export default {
  fetch: app.fetch,
  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(markStaleClients(env.DB, 90));
  },
};
