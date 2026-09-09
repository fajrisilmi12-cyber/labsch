# 0.4.0-test1 verification - 2026-09-08

Artifact: `/root/labsch/dist/labsch-pc-tes-0.4.0-test1.zip`
SHA256: `b7794e30f47eb9956abb5fa7ad05675faab663ce3f749be99372064727b867e5`
Size: 21,277,806 bytes; 685 files; ZIP CRC passes; bundled per-file manifest
hashes match. Existing configured SCHOOL_API_TOKEN exact-byte scan passed;
no config.ini/.env included. Required Python/pywin32/psutil DLL/PYD checks pass.

Commands executed:
- `/root/labsch-tests-venv/bin/python -m pytest tests/ -q`: **39 passed in 2.12s**.
- `python3 -m compileall -q agent`: exit 0.
- `node node_modules/typescript/bin/tsc -p tsconfig.json --noEmit`: exit 0.
- `npm test` (workers): **25 passed**, 7 download + 18 session tests, real local
  D1 via Cloudflare Vitest runtime.
- `git diff --check`: no errors.
- `python3 scripts/build_test_bundle.py`: archive created, manifest/CRC/secret
  checks passed. psutil/pywin32 wheel hashes checked against PyPI metadata.
- Real direct HTTPS download using actual downloader/opener from W3C dummy.pdf:
  download_state=done, execution_state=not_requested, bytes=13264,
  SHA256=3df79d34abbca99308e79cb94461c1893582604d68329a41fd4bec1885e6adb4.
  Host-only transfer; no remote PC task or execution.

Deployment:
- Additive `004-downloads.sql`: 3 queries, successful; no existing table altered.
- `wrangler deploy --dry-run`: passed.
- `wrangler deploy`: version `37bd6851-8da8-4859-a406-e8e734f209e5`
  URL `https://labsch-api.<your-subdomain>.workers.dev` (deployment-specific URL redacted)
  APP_VERSION=0.4.0-test1-workers; both existing crons retained.
- Previous deployment: `50b8fae2-7f47-4647-a3b5-ea2190da7392`.
  Source backup: `/root/labsch-production-before.txt` (private host only).
- `python3 scripts/verify_deployed_downloads.py`: health, config, profiles,
  device and clients GET 200; synthetic heartbeat 200; create -> protocol and
  target gates -> real AgentClient pending/report twice -> TTL/rollup -> cancel
  passed. Exact synthetic client/task/event cleanup verified zero rows.
  Client synthetic-download-142c517337b6, task f1df2394-a273-4cd1-89fd-329f1daf1306.

Limits: no Windows host available; no Windows execution/installer/desktop
visibility claims. Parent review and PC Tes physical acceptance required.
SYSTEM/script autorun, run_args, groups and interactive cloud share interstitials
are explicitly unsupported in this test release. See DOWNLOAD_TEST_RELEASE.md.
No real-PC task, fleet broadcast, token rotation, or public upload performed.
No commits/reset/staging performed; unrelated login-gate/session changes retained.
