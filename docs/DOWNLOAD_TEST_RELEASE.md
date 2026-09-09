# LabSCH 0.4.0-test1 - PC Tes acceptance build

NOT a fleet release. Windows execution has NOT been exercised on this Linux
build host. No tasks have been queued to PC Tes or any real PC by this release.

## Upgrade on DESKTOP-3D1KNVB (PC Tes)
1. Extract the entire ZIP, preferably C:\Temp\labsch-test (not directly over an
   existing installation). Windows 10/11 x64 is required. Python 3.12.10 x64,
   psutil 7.0.0 and pywin32 311 are included; no pip/download step required.
2. Right-click upgrade.bat -> Run as administrator. There is NO auto-elevation.
3. Existing C:\ProgramData\LabSCHAgent\config.ini is REQUIRED and reused
   unchanged (server, secret, client ID, display name, test flag). No shared
   token is in this ZIP. Do not delete config.ini or downloads.json.
4. Installer refuses an existing LabSCH Windows service. If detected, remove
   that old service manually first; this avoids racing its recovery manager.
5. Upgrade removes named legacy LabSCH startup tasks/Run entry, stops only
   recognizable LabSCH processes, copies code/runtime to Program Files, locks
   state to SYSTEM/Administrators, and starts ONE SYSTEM scheduled task named
   LabSCHAgent. No Task Manager policy changes are made by this upgrade.
   User helper processes are short-lived and are NOT additional agents.
6. Verify in Administrator PowerShell:
   Get-ScheduledTask -TaskName LabSCHAgent
   Get-ScheduledTaskInfo -TaskName LabSCHAgent
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'labsch_agent.py' } | Select-Object ProcessId,CommandLine
   Expected: one agent PID and a running task. Verify PC heartbeat in admin CLI.
   If upgrade fails, read the error; do not manually launch a second agent.

## Admin commands (run on homeserver, NOT automatically by installer)
Use /root/labsch/skill/labschctl against the production Workers API.

python3 skill/labschctl download https://HOST/worksheet.pdf --name worksheet.pdf --sha256 EXPECTED_64_HEX --clients Tes
python3 skill/labschctl downloads
python3 skill/labschctl download-cancel TASK_UUID

Autorun is DEFAULT. SHA-256 is mandatory for autorun, including documents.
Download-only: add --no-run (alias --no-autorun). Select explicit client IDs or
exact display names with --clients; there is NO implicit broadcast. Tasks
explicitly targeting a test PC include that PC. No group targeting yet.
Use --dest desktop|documents, --max-size-mb 1..2048, --ttl-seconds 60..604800.
Task status shows download and execution separately. 'done' only means file
saved; execution=launched means Windows accepted the open/launch request, NOT
that the application finished successfully or was visibly verified by us.

Files are in Public Desktop or Public Documents, inside one read-only
LabSCH-<task hash> folder per task (no filename overwrite between tasks).
Documents may require Save As to edit outside that protected folder.

## Supported execution and links
- Documents/media in the agent allowlist and standalone .exe: logged-in
  ACTIVE CONSOLE user's non-elevated token. SYSTEM uses documented WTS token
  + CreateProcessAsUser handoff; helper invokes normal Windows ShellExecute.
  No UAC bypass; an installer requesting elevation may display normal UAC.
- No console user, elevated-only agent, unavailable file association, or
  helper error => failed_launch, never silently session-0 execution.
- RDP-only/multi-user selection is NOT supported. Locked console visibility
  waits for unlock and is not guaranteed by a 'launched' status.
- SYSTEM autorun, MSI/BAT/CMD/PS1 and other script/installer autorun, run_args,
  custom destinations, groups, and folder/multi-file links are UNSUPPORTED.
  Downloads can still be saved with --no-run; unsupported launch is explicit.
- Direct public HTTPS on port 443 only, with public-address validation at
  actual connect time and on redirects. Proxies disabled. Never forwards the
  LabSCH authentication header to file hosts.
- Google Drive single-file /file/d/ links and OneDrive share URLs are converted
  to direct URL forms, but ONLY work when the host returns a file without
  login, confirmation or HTML. Drive virus-scan confirmation, gofile webpage,
  SharePoint login and HTML interstitials fail explicitly. Prefer a real direct
  HTTPS download URL. These providers have NOT been live-account tested.

## Reliability semantics
One bounded background worker; no queued thread backlog. Poll every 30 seconds,
0..30s jitter; three transfer attempts with 60s delay. Heartbeats continue.
Cancellation/expiry prevents new starts; a transfer already started finishes
and may launch (cancel is NOT a process-kill operation). Terminal outcomes
are durably journaled and reports replay after network failure, even if task
is cancelled. Terminal server reports cannot regress. Interrupted tasks fail
closed; an interrupted launch is UNKNOWN and NEVER retried. Create a new task
only after checking the PC. This is at-most-once dispatch, not exactly-once
application completion. Journal corruption stops downloads instead of resetting.

## Physical acceptance required before wider rollout
- Logged-in user: small PDF with correct hash visibly opens in default app.
- During a larger download, heartbeat remains online and only one agent runs.
- Wrong hash never opens; no user session reports failed_launch, not launched.
- Reboot/re-delivery/report network loss do not open the same task twice.
- Verify existing browser/device policies and existing config identity survive.
- Verify standalone trusted EXE with normal UAC behavior separately if needed.

Workers-only repository: local FastAPI was removed in existing commit 962d1cd;
this test release does not reintroduce it. Existing sessions/login-gate work is
preserved but not enabled or installed by this upgrade.
