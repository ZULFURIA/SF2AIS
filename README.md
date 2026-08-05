# Sf2AiS (aka: AI-Gateway-FTP) — Secure Files to AI Server 🤖📂

A password-protected, self-hosted bridge that lets web-browsing AI chatbots
(ChatGPT, Claude, Gemini, Copilot, etc.) — or another person — securely
browse, read, and download files on your own computer or home server, run
debugging/test commands, and even temporarily view a running dev server.
No API keys or MCP support required on the AI's side.

Also works as a plain workspace-sharing tool between people — like an FTP
server that happens to share over HTTP. All the AI companies went the MCP
route and forgot there's a much simpler way to do this for a quick session.
Not as locked-down as a proper MCP integration, but built for a focused
hours-to-a-few-days work/debug session — not meant to run 24/7 as
production infrastructure. Every capability beyond plain file browsing is
opt-in per share and off by default.

## What you get

- A guided, glassmorphism-themed **setup wizard** — no config files to hand-edit
- **Password-complexity enforcement** on every account (12+ chars, mixed case,
  number, special character)
- Support for a **custom domain**, **dynamic DNS**, a **static IP**, or your
  **current IP with an auto-updating probe** (works on Windows, macOS, Linux)
- A built-in **DuckDNS updater** — the probe pushes your current IP straight
  to a free DuckDNS hostname whenever it changes, no separate script needed
- A **live dashboard**: online/offline status, your current shareable link,
  DDNS status, and which logins are actively connected
- A **desktop Electron probe app** with system tray, glassmorphism UI,
  DuckDNS config, and Windows Task Scheduler integration for background IP
  monitoring
- **Multiple shares**: give different folders their own separate
  username/password pairs, added anytime from the dashboard, each with its
  own independent CLI/tunnel permissions

### Per-share optional features

Each share can independently turn on:

- **CLI execution** — run `bash`, `powershell`, or `cmd` commands scoped to
  that share's folder, for actual debugging/testing rather than just reading
  files. Async job model (`POST /cli/jobs` → poll `GET /cli/jobs/{id}`), so
  long test runs don't block on one HTTP request. Hard runtime cap, output
  truncation, sandboxed to the share's folder the same way file downloads are.
- **Temporary debug tunnels** — briefly expose a local dev server (e.g. a
  Vite/webpack dev server) to the public internet via your router's UPnP, so
  an AI or a reviewer can actually see what was built. Auto-expires (30 min
  default, 2 hour hard cap); can be closed early. Optional `verify: true`
  does a reachability check using whichever public address source you've
  already configured (domain/static/DDNS/probe), instead of guessing.
- **Isolation mode (Windows only, for now)** — instead of forwarding your
  router's port straight to your real machine, a tunnel can bind a throwaway
  `/32` alias IP, scope Windows Firewall rules to that alias + port + an
  explicit remote allowlist, and relay bytes to your dev server over
  loopback. The rest of the machine stays invisible even to other devices on
  your own LAN. All native (`ctypes` IP Helper API + `pywin32` COM firewall
  calls) — no `.ps1` scripts, no shelling out to `netsh`. Live-tested,
  round-trip validated (alias IP + firewall rules added, verified, and torn
  down cleanly).

## Running it

### With Python
```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
On Windows, also `pip install pywin32` if you want isolation mode available
(everything else works without it — isolation just reports unsupported).

### With Docker
```bash
docker-compose up -d
```
If you plan to share folders that live elsewhere on your host machine, add a
volume line for each one in `docker-compose.yml` before starting the wizard
(see the comments in that file). Note: CLI execution, tunnels, and isolation
mode all need real access to the host — they lose capability (or don't work
at all) once containerized, since they're built to reach outside the
sandbox by design. File-only sharing works fine in Docker; treat the rest as
a native-install feature for now.

### Linux (tarball + systemd) — no distro package manager needed

Works identically across Debian/Ubuntu/Mint/KDE neon/Kali, Arch, and
Fedora/RHEL/CentOS/SUSE — one build, no `.deb`/`.rpm`/`PKGBUILD` juggling,
since there's nothing distro-specific for a dependency manager to resolve
here in the first place.

```bash
# build the distributable tarball (from packaging/linux/)
./packaging/linux/build-tarball.sh

# on the target machine
tar xzf sf2ais-linux.tar.gz
cd sf2ais-linux
sudo ./install.sh
```

This creates a dedicated `sf2ais` system user, a Python venv under
`/opt/sf2ais`, and a `systemd` unit granting `CAP_NET_ADMIN`/`CAP_NET_RAW`
(needed once the isolation layer is ported to Linux's `iptables`, not yet
built). Manage it the normal way:

```bash
systemctl status sf2ais
journalctl -u sf2ais -f
sudo ./uninstall.sh   # asks before touching your shared_files/config
```

### Windows installer / macOS .app

Not built yet — discussed as a `PyInstaller` + Inno Setup/NSIS pass for
Windows, and `PyInstaller --windowed` + `.dmg` for macOS. For now, run it
directly with Python as above on both.

The **Sf2AiS Probe** desktop app (system tray IP monitor) IS available as a
prebuilt Electron package — download it from the SF2AIS dashboard under
"Desktop Probe App", or find installers in `probe-app/dist/`.

---

Then open `http://localhost:8000` (or your server's address) in a browser.

## First-run walkthrough

1. **Welcome screen** — Sf2AiS branding, one click to begin.
2. **Dashboard login** — choose the username/password *you* will use to manage
   the server. Must meet the password policy (checked live as you type).
3. **Network setup** — tell it how your AI will reach this machine:
   - **Custom domain** — you already point a domain here
   - **Dynamic DNS** — you use a DuckDNS/No-IP style hostname
   - **Static IP** — your public IP never changes
   - **Current IP + probe** (recommended if you're not sure) — Sf2AiS gives you
     a small script for whichever computer stays on; it checks your public IP
     every 5 minutes and updates your link automatically if it changes, and
     will push that update to DuckDNS too if you've set a token on the
     dashboard.
4. **Choose folders** — add one or more folders to share. Each one
   automatically gets its own generated username and password, shown once on
   the finish screen — save them! You can also allow CLI execution and/or
   temporary debug tunnels for the whole batch here, or fine-tune per-share
   later from the dashboard.
5. **Dashboard** — shows your live shareable link, an online/offline status
   badge, DDNS status with a form to set/update your DuckDNS subdomain and
   token, a table of all shares with connection status and independent
   CLI/Tunnel toggles, and a **+ Add Share** button to create more
   username/password pairs (with their own CLI/tunnel permissions) at any time.

## The IP Probe — Desktop App

Sf2AiS now ships with a dedicated **Electron desktop probe app** — a native
system-tray application that watches your public IP and keeps it updated
on your gateway automatically.

The Electron app provides:
- **System tray icon** with real-time IP status and quick controls
- **Glassmorphism settings UI** — configure gateway URL, probe token,
  check interval, and startup behavior
- **DuckDNS integration** — enter your DuckDNS subdomain + token directly
  in the app; the probe pushes your IP to DuckDNS on every check
- **Background operation** — runs silently in the notification area,
  checks every 5 minutes (configurable), and auto-starts on Windows login
- **Windows Task Scheduler** — one click creates a scheduled task that
  launches the probe at logon and repeats the IP check every 5 minutes
- **Direct download** — the SF2AIS web dashboard offers a "Download Desktop
  Probe App" section with installers for Windows (.exe), macOS (.dmg), and
  Linux (.AppImage)

### Downloading from the Dashboard

1. Open `http://localhost:8000/dashboard` in your browser
2. Scroll to the **Desktop Probe App** section
3. Click the download link for your platform
4. Run the installer (or drag to Applications on macOS, make executable on Linux)
5. The app will appear in your system tray — click it to open settings

### Configuring the Probe

In the app's settings window:
- **Gateway URL** — your SF2AIS server address (e.g. `http://192.168.1.5:8000`
  or your DDNS domain)
- **Probe Token** — from the Sf2AiS dashboard setup (shown once during setup)
- **DuckDNS Subdomain** — your free subdomain at `duckdns.org` (optional)
- **DuckDNS Token** — your DuckDNS token (optional)
- **Check interval** — how often to check (default: 5 minutes)
- **Start with Windows** — also creates a Windows Task Scheduler entry

Click **🌐 Open duckdns.org** to register a free DuckDNS hostname if you
don't have one yet.

### Using the Python Script (legacy)

The original cross-platform Python script (`probe.py`) is still available
as a lightweight alternative — works on Windows/macOS/Linux with Python 3
installed, you just point it at your gateway and schedule it:

- **Windows** — Task Scheduler, "repeat every 5 minutes"
- **macOS / Linux** — `cron` entry (`*/5 * * * * python3 /path/to/probe.py`)

Download it from the dashboard's **Setup Complete** page, or from
`/probe/download?token=YOUR_TOKEN`. Full instructions are at
`/probe/setup-guide`.

## API reference (for AI assistants / scripting)

All endpoints below require the share's Basic Auth credentials and are only
available if the relevant feature is turned on for that share.

**Files** (always available):
- `GET /files` and download routes — browse/read the share's folder

**CLI** (needs `cli_enabled` on the share):
- `POST /cli/jobs` — `{"command": "...", "shell": "bash"|"powershell"|"cmd"|"auto", "cwd": "optional/subpath"}` → `{"job_id", "status"}`
- `GET /cli/jobs/{job_id}` — poll for `status`/`stdout`/`stderr`/`exit_code`
- `GET /cli/jobs` — last 50 jobs for that share

**Tunnels** (needs `tunnel_enabled` on the share):
- `GET /tunnel/interfaces` — list local network interfaces (for isolation mode's alias-IP picker)
- `POST /tunnel/open` — `{"local_port", "protocol": "TCP"|"UDP", "ttl_seconds", "external_port", "verify": bool, "isolate": bool, "alias_ip", "interface_index", "trusted_remotes": ["1.2.3.4", "10.0.0.0/24"]}` → `{"tunnel_id", "public_url", "expires_in_seconds", "verify_result", "isolated"}`
- `POST /tunnel/{tunnel_id}/close` — close early
- `GET /tunnel` — list open/recent tunnels for that share

**Dashboard** (admin credentials, not share credentials):
- `POST /dashboard/ddns` — set DuckDNS `domain`/`token`
- `POST /dashboard/shares/{id}/toggle-cli`, `.../toggle-tunnel` — flip per-share permissions

## Security notes

- Every password (yours and each share's) is hashed with bcrypt — plaintext is
  never stored, other than the auto-generated share passwords shown once on
  the finish screen.
- **Use HTTPS in production.** Basic Auth sends credentials on every request —
  put this behind a TLS-terminating reverse proxy (Caddy, nginx, Cloudflare
  Tunnel) rather than exposing plain HTTP directly, especially for the static
  IP / current-IP options.
- Anyone with a share's username/password can read every file in that share's
  folder — only add folders you're comfortable with an external AI service
  reading. If CLI execution is also on for that share, they can run arbitrary
  commands scoped to that folder — treat that credential like a limited shell
  account, not just a file-read password.
- **Tunnels are real, if temporary, internet exposure.** A dev server wasn't
  built to be internet-facing — keep exposure windows short (the defaults
  do this for you) and prefer isolation mode where it's available.
- Isolation mode is Windows-only right now; on Linux/macOS a tunnel still
  works, just without the alias-IP/firewall scoping layer.
- Path traversal protection is included, but this project hasn't had a
  professional security audit — use it at your own risk on a home server.
- To reset your dashboard login or start over, stop the server and delete
  `data/config.json`, then restart.

#Licence: 🤖📂

[![License: Sf2AiS v1.0](https://shields.io)](LICENSE.md)
[![GitHub Sponsor](https://shields.io)](https://github.com)

An open-source-style, source-available secure file gateway...

...

## ⚖️ License

This project is licensed under the **Sf2AiS Noncommercial License v1.0**. 

* **Hobbyists, Students, and Home Labs:** 100% Free to use, modify, and distribute for personal or educational purposes.
* **Commercial Entities / Monetization:** Any commercial use, SaaS bundling, or monetization requires written permission from the copyright holder (Wayne).

See the full terms in [LICENSE.md](LICENSE.md). For commercial licensing inquiries, please open an issue or contact the maintainer directly.
