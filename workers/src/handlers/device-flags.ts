// Device control helpers — camera/audio disable flags
// Stored as columns on config (global) and client_overrides (per-PC).

export interface DeviceFlags {
  disable_camera: number;
  disable_audio: number;
}

export const DEFAULT_FLAGS: DeviceFlags = { disable_camera: 0, disable_audio: 0 };

export async function getGlobalFlags(db: D1Database): Promise<DeviceFlags> {
  const row = await db.prepare(
    'SELECT disable_camera, disable_audio FROM config WHERE id = 1'
  ).first<any>();
  if (!row) return { ...DEFAULT_FLAGS };
  return {
    disable_camera: row.disable_camera ? 1 : 0,
    disable_audio: row.disable_audio ? 1 : 0,
  };
}

export async function getEffectiveFlags(
  db: D1Database, clientId: string
): Promise<DeviceFlags> {
  // Per-PC override wins; otherwise global
  const ov = await db.prepare(
    'SELECT disable_camera, disable_audio FROM client_overrides WHERE client_id = ?'
  ).bind(clientId).first<any>();
  if (ov && (ov.disable_camera === 1 || ov.disable_audio === 1 || ov.has_override)) {
    return {
      disable_camera: ov.disable_camera ? 1 : 0,
      disable_audio: ov.disable_audio ? 1 : 0,
    };
  }
  return getGlobalFlags(db);
}
