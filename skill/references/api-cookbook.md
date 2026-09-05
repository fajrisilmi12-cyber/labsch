# API cookbook — direct curl recipes

For when you need to script LabSCH without going through `labschctl`
(bulk operations, webhooks, one-off integrations, or just quick
shell-based admin). All admin endpoints require the `X-Agent-Token`
header — return `401` without it.

## Setup

```bash
# Load the token once per shell session
TOKEN=$(grep '^SCHOOL_API_TOKEN=' /root/.hermes/.env | cut -d= -f2-)
BASE=http://127.0.0.1:8080
AUTH=(-H "X-Agent-Token: $TOKEN")
```

The server's full OpenAPI schema is also available at
`curl -s http://127.0.0.1:8080/openapi.json` — useful for discovering
exact parameter shapes (in-path vs query vs body) before scripting.

## List clients (resolve display_name → client_id)

```bash
curl -s "${AUTH[@]}" $BASE/api/clients | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    print(f\"{c['display_name']:12s}  {c['client_id']:35s}  {c['status']:7s}  ip={c['ip']}\")
"
```

`client_id` looks like `desktop-kr3sroq-faa73481` (long, includes
hostname prefix). Display names like `Lab8`, `TesPC`, `PC-LAB-01` are
what the user thinks in — always resolve via this lookup first, since
`client_id` is not human-stable across reinstalls (only `device_id`
and `mac` are truly stable).

## Queue a remote command (shutdown / restart / cancel)

**The `command` parameter is a QUERY PARAM, not a JSON body.** Sending
`{"command":"shutdown"}` as a body returns `422` with
`"missing query command"`. This is the most common footgun when
scripting directly.

```bash
# 1. Resolve display_name → client_id
CID=$(curl -s "${AUTH[@]}" $BASE/api/clients | \
  python3 -c "import json,sys; print(next(c['client_id'] for c in json.load(sys.stdin) if c['display_name']=='Lab8'))")

# 2. Queue shutdown (note: ?command=, NOT body)
curl -s -X POST "${AUTH[@]}" "$BASE/api/admin/command/$CID?command=shutdown"
# → {"ok":true,"client_id":"...","command":"shutdown","message":null}
```

Same shape for `restart` and `cancel` — just change the `command=`
value. `cancel` removes a queued-but-not-yet-picked-up command; once
the agent has executed `shutdown /s /t 5`, the cancel cannot reverse
the in-flight Windows shutdown (user would have to run `shutdown /a`
within 5 seconds).

## Verify a command is queued

```bash
curl -s "${AUTH[@]}" $BASE/api/clients | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    if c['pending_command']:
        print(f\"{c['display_name']}: pending={c['pending_command']!r}  status={c['status']}\")
"
```

Or to inspect one client:

```bash
curl -s "${AUTH[@]}" "$BASE/api/clients/$CID" | python3 -m json.tool
```

## Bulk queue (e.g. shutdown an entire lab room)

```bash
curl -s "${AUTH[@]}" $BASE/api/clients | python3 -c "
import json, sys
clients = json.load(sys.stdin)
targets = [c for c in clients if c['display_name'].startswith('Lab')
           and not c.get('is_test')]
for c in targets:
    print(c['client_id'], c['display_name'], c['status'])
" | while read CID NAME STATUS; do
  echo "→ $NAME ($STATUS)"
  curl -s -X POST "${AUTH[@]}" "$BASE/api/admin/command/$CID?command=shutdown"
  echo
done
```

Or — if you have `labschctl` available — just use
`labschctl command-all shutdown --online-only --yes` (added in
v0.2.1), which does the same thing with confirmation.

## Cancel ALL pending commands (rollback before students come back)

```bash
for CID in $(curl -s "${AUTH[@]}" $BASE/api/clients | \
  python3 -c "import json,sys; [print(c['client_id']) for c in json.load(sys.stdin) if c['pending_command']]"); do
  curl -s -X DELETE "${AUTH[@]}" "$BASE/api/admin/command/$CID"
  echo "  cleared $CID"
done
```

## Watch the heartbeat log for execution confirmation

```bash
sudo tail -f /var/log/labsch-server.log | grep --line-buffered pending_command
```

Successful pickup looks like a `POST /api/heartbeat` 200 followed
shortly by a `shutdown` event in `/api/events`. The agent clears its
own `pending_command` after running it — the next heartbeat response
will show `pending_command: null` again.

## OpenAPI as ground truth

When a 422 / 401 is mysterious, the schema is the source of truth:

```bash
curl -s $BASE/openapi.json | python3 -c "
import json, sys
d = json.load(sys.stdin)
for path, methods in sorted(d['paths'].items()):
    for verb, spec in methods.items():
        if verb in ('parameters',): continue
        params = [p['name'] for p in spec.get('parameters', [])]
        print(f'{verb.upper():6s} {path:50s}  params={params}')
"
```

The `in: query` vs `in: body` distinction in the schema is what
tells you whether to use `?command=` or a `-d '{"command":...}'` body.
