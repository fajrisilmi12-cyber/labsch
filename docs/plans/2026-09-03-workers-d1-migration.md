# Plan: Migrasi LabSCH Server ke Cloudflare Workers + D1

**Tanggal**: 2026-09-03
**Author**: Mona (untuk Fajri / Muhammad Al-Fajri Silmi)
**Status**: APPROVED — siap eksekusi
**Target**: Lepas dari homeserver Linux, serverless 100% di edge Cloudflare

---

## TL;DR

Server LabSCH (FastAPI + SQLite) yang sekarang jalan di homeserver bakal
dipindah ke **Cloudflare Workers + D1**. Agent Windows **tidak berubah
sedikit pun** — API contract tetap 1:1. `labschctl` admin CLI di homeserver
tetap jalan, cuma diarahkan ke URL Workers (`https://labsch.<account>.workers.dev`).

**Estimasi effort**: 2-3 hari.
**Biaya**: $0 (free tier cukup untuk 20+ client).

---

## Mengapa Cloudflare Workers + D1

| Aspek | Cloudflare Workers + D1 |
|---|---|
| **Free quota** | 100.000 request/hari (cukup untuk 20 PC × 30 detik = 57.600/hari) |
| **Database** | D1 = SQLite-compatible, native Workers integration |
| **Latency** | Edge runtime, <50ms ping dari Indonesia |
| **Persistent connection** | HTTP request/response standard — cukup untuk model pull-based |
| **Quota heartbeat polling** | 57.600/hari << 100.000 — aman |
| **CLI integration** | `labschctl` tinggal swap `SCHOOL_SERVER_URL` env var |
| **Agent compatibility** | **Zero change** — endpoint contract sama persis |
| **Cost** | $0 (free tier). $5/bulan kalau exceed |

D1 pakai dialect SQLite penuh, jadi migrasi SQL schema dari `server/db.py`
itu **copy-paste + minor tweaks**.

---

## Arsitektur Target

```
┌──────────────────────────────────────────────┐
│  Cloudflare Edge                             │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Workers (labsch-api)                  │  │
│  │  Hono router, ~30 endpoints            │  │
│  │  X-Agent-Token middleware              │  │
│  │  Stale-client cron trigger (5 min)     │  │
│  └────────────┬───────────────────────────┘  │
│               │                              │
│  ┌────────────▼───────────────────────────┐  │
│  │  D1 Database (labsch-db)               │  │
│  │  5 tables: clients, config, events,    │  │
│  │  profiles, client_overrides            │  │
│  └────────────────────────────────────────┘  │
│                                              │
└──────────────────────────────────────────────┘
           ▲
           │ HTTPS polling (30s heartbeat, 60s config pull)
           │ Auth: X-Agent-Token (UUID)
           │
┌──────────┴───────────────────────────────────┐
│  Each Windows PC (TIDAK BERUBAH)             │
│  agent/labsch_agent.py — Python → .exe       │
│  Windows Service, self-protection, MAC ID    │
└──────────────────────────────────────────────┘
           ▲
           │ HTTPS (X-Agent-Token)
           │
┌──────────┴───────────────────────────────────┐
│  Homeserver (opsional, untuk admin CLI)      │
│  labschctl → SCHOOL_SERVER_URL=workers.dev   │
└──────────────────────────────────────────────┘
```

---

## Mapping API Endpoint (FastAPI → Workers)

Semua endpoint di `server/api.py` dipindah 1:1:

| Method | Path | Workers handler | Perubahan |
|--------|------|-----------------|-----------|
| GET | `/api/health` | ✅ | None |
| POST | `/api/heartbeat` | ✅ | None — agent contract sama |
| GET | `/api/config` | ✅ | None |
| POST | `/api/event` | ✅ | None |
| GET | `/api/clients` | ✅ | None |
| GET | `/api/clients/{id}` | ✅ | None |
| GET | `/api/clients/{id}/override` | ✅ | None |
| PUT | `/api/clients/{id}/override` | ✅ | None |
| DELETE | `/api/clients/{id}/override` | ✅ | None |
| POST | `/api/admin/command/{id}` | ✅ | None |
| DELETE | `/api/admin/command/{id}` | ✅ | None |
| POST | `/api/admin/config` | ✅ | None |
| GET | `/api/admin/config` | ✅ | None |
| POST | `/api/admin/block-site` | ✅ | None |
| POST | `/api/admin/unblock-site` | ✅ | None |
| POST | `/api/admin/block-app` | ✅ | None |
| POST | `/api/admin/unblock-app` | ✅ | None |
| POST | `/api/admin/allow-site` | ✅ | None |
| POST | `/api/admin/clear-blocked-websites` | ✅ | None |
| POST | `/api/admin/clear-blocked-apps` | ✅ | None |
| POST | `/api/admin/clear-allowed-websites` | ✅ | None |
| POST | `/api/admin/profiles` | ✅ | None |
| GET | `/api/admin/profiles` | ✅ | None |
| GET | `/api/admin/profiles/{name}` | ✅ | None |
| DELETE | `/api/admin/profiles/{name}` | ✅ | None |
| POST | `/api/admin/profiles/{name}/activate` | ✅ | None |

**Total**: 25 endpoint, 1:1 mapping. Zero agent-side changes.

---

## Database Schema (D1 SQL)

```sql
CREATE TABLE IF NOT EXISTS clients (
    client_id TEXT PRIMARY KEY,
    hostname TEXT,
    ip TEXT,
    user TEXT,
    version TEXT,
    last_seen REAL,
    first_seen REAL,
    status TEXT DEFAULT 'offline',
    device_id TEXT,
    mac TEXT,
    display_name TEXT DEFAULT '',
    is_test INTEGER DEFAULT 0,
    pending_command TEXT DEFAULT NULL,
    pending_command_message TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_clients_device ON clients(device_id);
CREATE INDEX IF NOT EXISTS idx_clients_mac ON clients(mac);
CREATE INDEX IF NOT EXISTS idx_clients_status ON clients(status, last_seen DESC);

CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    config_version INTEGER NOT NULL DEFAULT 0,
    updated_at REAL,
    updated_by TEXT
);

INSERT OR IGNORE INTO config (id, blocked_apps, blocked_websites, allowed_websites, config_version)
VALUES (1, '[]', '[]', '[]', 0);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT,
    event_type TEXT,
    target TEXT,
    timestamp REAL,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_client ON events(client_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    activated_at REAL
);

CREATE TABLE IF NOT EXISTS client_overrides (
    client_id TEXT PRIMARY KEY,
    blocked_websites TEXT NOT NULL DEFAULT '[]',
    allowed_websites TEXT NOT NULL DEFAULT '[]',
    blocked_apps TEXT NOT NULL DEFAULT '[]',
    updated_at REAL NOT NULL,
    updated_by TEXT DEFAULT 'admin'
);
```

---

## Struktur Project Baru

```
labsch/
├── server/                          # FastAPI lama (DEPRECATED setelah migrasi)
├── workers/                         # BARU — Cloudflare Workers project
│   ├── package.json
│   ├── wrangler.toml
│   ├── tsconfig.json
│   ├── schema.sql
│   ├── migrations/
│   │   └── 0001_initial.sql
│   ├── src/
│   │   ├── index.ts                 # Hono app entry
│   │   ├── auth.ts                  # X-Agent-Token middleware
│   │   ├── db.ts                    # D1 query helpers
│   │   ├── handlers/
│   │   │   ├── health.ts
│   │   │   ├── heartbeat.ts
│   │   │   ├── config.ts
│   │   │   ├── events.ts
│   │   │   ├── clients.ts
│   │   │   ├── admin-config.ts
│   │   │   ├── admin-profiles.ts
│   │   │   ├── admin-command.ts
│   │   │   └── overrides.ts
│   │   ├── cron/
│   │   │   └── mark-stale.ts
│   │   └── types.ts
│   └── test/
├── agent/                           # TIDAK BERUBAH
└── skill/
    └── labschctl                    # Update SCHOOL_SERVER_URL
```

---

## Langkah Migrasi (Berurutan)

### Phase 0: Persiapan (30 menit)
- [ ] Install wrangler: `npm install -g wrangler`
- [ ] Login: `wrangler login` (browser OAuth — Fajri klik)
- [ ] Init D1: `wrangler d1 create labsch-db`
- [ ] Copy `database_id` ke `wrangler.toml`
- [ ] Set secret: `wrangler secret put SCHOOL_API_TOKEN`

### Phase 1: Schema + Boilerplate (2-3 jam)
- [ ] Setup Hono router di `src/index.ts`
- [ ] Apply schema: `wrangler d1 execute labsch-db --file=schema.sql`
- [ ] Verify: `wrangler d1 execute labsch-db --command="SELECT * FROM config"`

### Phase 2: Endpoint Migration (1 hari)
- [ ] Port handler `/api/health` + auth middleware
- [ ] Port `/api/heartbeat` (kompleks: upsert + de-dup + override)
- [ ] Port `/api/config`, `/api/event`
- [ ] Port `/api/clients*` (list, detail, override CRUD)
- [ ] Port `/api/admin/config*` (block/unblock/clear)
- [ ] Port `/api/admin/profiles*` (CRUD + activate)
- [ ] Port `/api/admin/command*` (shutdown/restart)
- [ ] **Tambah**: `pending_command_message` handling untuk `notify`

### Phase 3: Cron + Testing (3-4 jam)
- [ ] Setup cron trigger `*/5 * * * *` → `mark-stale`
- [ ] Run `wrangler dev` (local) — test semua 25 endpoint
- [ ] Bikin Vitest tests untuk handler logic
- [ ] Migration data existing dari SQLite
- [ ] Test 1 PC agent → pointing ke Workers URL
- [ ] Smoke test: heartbeat, config pull, block-site, shutdown

### Phase 4: Cutover (1 jam)
- [ ] Backup SQLite lama
- [ ] Update `SCHOOL_SERVER_URL` di `~/.hermes/.env`
- [ ] Re-bake agent zip dengan URL baru
- [ ] Push ke 1-2 PC pilot, monitor 24 jam
- [ ] Kalau stabil: push ke semua 20+ PC
- [ ] Stop `labsch-server.service` di homeserver (jangan disable dulu)

### Phase 5: Cleanup (30 menit)
- [ ] Disable `labsch-server.service` setelah 1 minggu stabil
- [ ] Update `README.md` + `docs/ARCHITECTURE.md`
- [ ] Update `skill/labschctl`

---

## Quota Math (Sanity Check)

**Skenario 20 PC aktif, polling 30 detik**:
- Heartbeat: 57.600/hari
- Config pull: 28.800/hari
- Event log: ~50/hari
- Admin CLI: ~20/hari
- **Total**: ~86.470/hari

Free tier: 100.000/hari. **Headroom**: 13.530/hari (~13%).

**Skenario 50 PC**: ~216.000/hari → upgrade ke $5/bulan atau turunkan heartbeat ke 60s.

---

## Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Agent PC gak bisa konek Workers (firewall) | Fallback: keep homeserver parallel, switch URL via config.ini |
| D1 latency lebih tinggi dari SQLite lokal | D1 rata-rata 10-30ms dari Indonesia (acceptable) |
| Cron trigger gak jalan | Workers free tier cron dijamin |
| Token leak | Encrypted di Cloudflare Secrets, gak muncul di dashboard plain |
| Data loss saat migrasi | Backup `labsch.db` dulu sebelum `wrangler d1 execute` |
| Agent lama masih pointing ke tunnel lama | Phase 4 re-bake zip + push ke PC |
| Cost naik kalau PC numpuk | Turunkan heartbeat ke 60s = covered |

---

## Rollback Plan

1. Stop agent di semua PC
2. Restore `SCHOOL_SERVER_URL` ke homeserver URL di `.env`
3. Re-bake zip dengan URL lama
4. Push ke PC, hidupin agent
5. Investigasi Workers issue (cek `wrangler tail` logs)

Total rollback time: **~15 menit** (asalkan homeserver masih standby).

---

## Effort Estimate

| Phase | Duration | Difficulty |
|-------|----------|------------|
| 0 — Persiapan | 30 min | Easy |
| 1 — Schema + Boilerplate | 2-3 hours | Easy |
| 2 — Endpoint migration | 1 day | Medium |
| 3 — Cron + Testing | 3-4 hours | Medium |
| 4 — Cutover | 1 hour | Easy |
| 5 — Cleanup | 30 min | Easy |
| **Total** | **~2-3 days** | **Medium** |

---

## Open Questions (untuk Fajri)

1. **Custom domain?** — Pakai `labsch-api.fajrisilmi.cyber.id` (kamu punya domain?) atau default `*.workers.dev`?
2. **Data retention** — Events lama (>30 hari) perlu di-archive? D1 free 5 GB.
3. **Backup strategy** — Auto-export D1 ke GitHub repo tiap minggu?
4. **`notify` feature** — perlu di-implement di Workers atau skip dulu?
5. **Multi-tenant** — perlu support >1 sekolah (token per sekolah) atau single-tenant dulu?

---

## Next Step

Mulai dari **Phase 0**:
1. Fajri authorize `wrangler login` di browser (sekali klik)
2. Aku eksekusi init D1 + set token + scaffold project
3. Report progress tiap phase selesai + share URL Workers yang bisa langsung di-test
