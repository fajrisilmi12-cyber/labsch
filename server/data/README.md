# Server data

This directory contains the SQLite database. It is excluded from git
(gitignored via `data/*.db` in `.gitignore`).

## On a fresh deploy

The database is created automatically on first server start. No manual
SQL needed.

## Backup

```bash
cp /opt/labsch/server/data/labsch.db /backup/labsch-$(date +%Y%m%d).db
```

## Restore

```bash
cp /backup/labsch-20260830.db /opt/labsch/server/data/labsch.db
# Restart the server
systemctl restart labsch-server  # or whatever you use
```

## Schema migrations

Schema migrations are automatic. See `db.py`:
1. CREATE TABLE IF NOT EXISTS (compatible)
2. PRAGMA table_info() to inspect
3. ALTER TABLE to add missing columns
