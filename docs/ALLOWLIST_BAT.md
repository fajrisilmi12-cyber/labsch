# Reference: FULL ALLOWLIST WEB v4 BAT

The browser policy module in `agent/browser_policy.py` is a Python
port of the [FULL ALLOWLIST WEB v4](https://example.com) Windows BAT
script that ships as a USB installer in some Indonesian schools. Both
implement the same approach:

1. **Block all** — set `URLBlocklist=*` so every URL is blocked by default
2. **Allow specific** — set `URLAllowlist` to a list of allowed domains
3. **Disable DoH** — set `DnsOverHttpsMode=off` to prevent Secure DNS bypass
4. **Disable Incognito** — set `InPrivateModeAvailability=1` and
   `IncognitoModeAvailability=1` (but note: the BAT sets these to `1` which
   DISABLES — confusing naming; we use the same convention for compatibility)
5. **IFEO block** for desktop apps (Roblox in the v4 BAT)

## Why registry policy > hosts file alone

| Method | Bypass risk |
|--------|-------------|
| Hosts file only | Browser DoH bypasses hosts. Student installs Firefox + enables DoH = bypassed. |
| Registry policy (Edge/Chrome/Brave) | DoH disabled by policy. Bypass requires modifying registry = needs admin. |
| Registry policy + Incognito off | Student can't open a clean profile to reset extensions/settings. |
| All three + IFEO for apps | Near-impossible to bypass without booting a different OS. |

## Differences from the BAT

| BAT behavior | LabSCH equivalent |
|--------------|-------------------|
| 4 Roblox exe blocked via IFEO | `labschctl config block-app <exe>` → applied to all |
| Manual USB deployment | `install.bat` over network (Cloudflare tunnel) |
| Single config (no profiles) | Named profiles (Rules Lab, Ujian, dll) |
| No central logging | All events logged to SQLite, viewable via `labschctl events` |
| No remote update | Config pulled every 60s, agent auto-updates |

## The original BAT scripts

We bundle the two reference BAT scripts in the repo at
`docs/original-bat/` for historical reference. The Python module
`browser_policy.py` implements the same logic but with a runtime
configuration pulled from the LabSCH server.

## Author note

The BAT scripts were originally contributed by an anonymous Indonesian
IT admin. The LabSCH Python implementation is by Fajri (Muhammad
Al-Fajri Silmi), Medan, 2026. License: MIT.
