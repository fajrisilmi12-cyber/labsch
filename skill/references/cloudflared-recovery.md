# Cloudflared recovery — when the tunnel binary disappears

The LabSCH `start_tunnel.sh` script has a fallback chain to locate the
`cloudflared` binary. The common breakage: the binary was originally
shipped inside the **9Router** install at `/root/.9router/bin/cloudflared`.
If 9Router is later removed (`rm -rf /root/.9router`), the tunnel dies
with the message:

```
cloudflared not found. Install it first:
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
  sudo dpkg -i /tmp/cloudflared.deb
```

That suggested fix only works on Debian/Ubuntu. On **Arch** there is no
`dpkg`, so the install has to happen by extracting the `.deb` manually.

## Recovery recipe (works on any distro)

```bash
# 1. Download the .deb (19 MB, fast)
curl -fsSL -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb

# 2. Extract (the .deb is an ar archive containing data.tar.{xz,gz,zst})
mkdir -p /tmp/cf-deb && cd /tmp/cf-deb
ar x /tmp/cloudflared.deb
ls           # → control.tar.gz  data.tar.gz  debian-binary

# 3. Extract data.tar (try gz, then xz, then zst; recent builds use gz)
tar -xzf data.tar.gz
ls usr/bin/  # → cloudflared

# 4. Install to system PATH
install -m 0755 usr/bin/cloudflared /usr/local/bin/cloudflared
command -v cloudflared   # /usr/local/bin/cloudflared
cloudflared --version    # 2026.8.3 (or newer)

# 5. Restart the LabSCH tunnel
/opt/labsch/server/start_tunnel.sh
# → wait ~10s, then check /tmp/cloudflared-labsch.log for the new URL
```

The new URL will be **different** from the old one (quick tunnels are
random). Plan a redeploy:

1. Read the new URL from the log (`grep trycloudflare /tmp/cloudflared-labsch.log`).
2. Rebuild the agent zip with the new URL baked in (edit
   `agent/install.bat` → `set "SERVER_URL=https://..."`, bump `version`
   in the JSON written to `config.ini`).
3. Reinstall on the affected PCs.

If the user wants a stable URL across restarts, switch to a **named
tunnel** (one-time Cloudflare account setup). See the `cloudflare-tunnel`
skill for the full command sequence.

## Why 9Router shipped its own cloudflared

9Router's quick-tunnel integration uses the same Cloudflare binary.
Rather than ask the user to install it separately, the 9Router package
bundled a copy at `/root/.9router/bin/cloudflared`. When 9Router is
deleted, that copy goes with it.

**Mitigation for future installs**: when removing 9Router, copy the
binary out first:

```bash
[ -x /root/.9router/bin/cloudflared ] && \
  install -m 0755 /root/.9router/bin/cloudflared /usr/local/bin/cloudflared
```

This keeps the tunnel working even if 9Router itself is uninstalled.
