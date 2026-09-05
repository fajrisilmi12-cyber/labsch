# Cleanup queries — SQL for the LabSCH SQLite DB

DB location: `/opt/labsch/server/data/labsch.db`

**Always take a backup first** — even if the query looks safe:

```bash
sudo systemctl stop labsch-server.service
cp /opt/labsch/server/data/labsch.db /tmp/labsch-$(date +%F).db.bak
sudo systemctl start labsch-server.service
```

Use `sqlite3` (CLI) or any GUI that can attach the file while the server
is stopped.

## Find duplicate client records

The server is supposed to de-duplicate by `device_id`, but if clients were
registered before de-dup logic was added, or after a schema migration,
you may have multiple rows with the same MAC.

```sql
SELECT device_id, mac, display_name,
       COUNT(*) AS rows,
       GROUP_CONCAT(client_id, ' | ') AS ids,
       MAX(last_seen) AS newest
FROM clients
WHERE device_id IS NOT NULL AND device_id != ''
GROUP BY device_id
HAVING COUNT(*) > 1
ORDER BY newest DESC;
```

## Merge duplicates into one canonical row

For each duplicate group, pick the **most-recently-seen** `client_id` as
the canonical one and re-point every related table at it, then delete the
duplicates.

```sql
BEGIN TRANSACTION;

-- Step 1: per device_id, pick the winner (most recent heartbeat)
CREATE TEMP TABLE _winner AS
SELECT device_id,
       (SELECT client_id FROM clients c2
        WHERE c2.device_id = clients.device_id
        ORDER BY last_seen DESC LIMIT 1) AS keep_id
FROM clients
WHERE device_id IS NOT NULL AND device_id != ''
GROUP BY device_id
HAVING COUNT(*) > 1;

-- Step 2: re-point events + overrides at the winner
UPDATE events SET client_id = (SELECT keep_id FROM _winner WHERE _winner.device_id = clients.device_id)
FROM clients WHERE clients.client_id = events.client_id;
-- (sqlite UPDATE...FROM syntax varies; if unsupported, do it in Python.)

UPDATE client_overrides SET client_id = (SELECT keep_id FROM _winner WHERE _winner.device_id = clients.device_id)
FROM clients WHERE clients.client_id = client_overrides.client_id;

-- Step 3: delete non-winners
DELETE FROM clients
WHERE device_id IN (SELECT device_id FROM _winner)
  AND client_id NOT IN (SELECT keep_id FROM _winner);

COMMIT;
```

If `UPDATE ... FROM` doesn't parse in your SQLite build, run the merge
from Python — `scripts/merge-duplicate-clients.py` in this skill bundle
does it.

## Reset config version (force agents to re-pull)

Useful after mass-edits via SQL:

```sql
UPDATE config SET config_version = config_version + 1;
```

Agents compare `config_version` from the server against their cached
value on every 60-second pull; bumping it triggers an immediate re-apply.

## Clear all events older than 30 days

```sql
DELETE FROM events
WHERE ts < strftime('%s', 'now', '-30 days');
```

## Inspect a single client's full history

```sql
SELECT ts, event_type, target, details
FROM events
WHERE client_id = '<id>'
ORDER BY ts DESC
LIMIT 100;
```

## Export current blocklist as plain text

```sql
SELECT blocked_apps FROM config WHERE id = 1;     -- JSON array
SELECT blocked_websites FROM config WHERE id = 1; -- JSON array
```

Use `sqlite3 -json /opt/labsch/server/data/labsch.db "SELECT ..."` to
parse directly in scripts.

## Wipe everything (factory reset)

**Destructive — only if migrating to a fresh DB**:

```sql
DELETE FROM events;
DELETE FROM client_overrides;
DELETE FROM profiles;
DELETE FROM clients;
UPDATE config SET blocked_apps = '[]', blocked_websites = '[]',
                  allowed_websites = '[]', config_version = config_version + 1
WHERE id = 1;
```

Then `sudo systemctl restart labsch-server.service` to flush the in-process
config cache.