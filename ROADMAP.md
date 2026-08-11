# SF2AIS — Product Roadmap

_Last updated: 2026-08-11_

This roadmap tracks shipped, in-progress, and planned work for SF2AIS
(aka AI-Gateway-FTP). States follow the CreoDevo implementation-state words:
**DONE**, **IN PROGRESS**, **PLANNED**, **KNOWN ISSUE**.

---

## DONE

- **Guided setup wizard** — no hand-edited config files to get started.
- **Per-share accounts** with password-complexity enforcement (12+ chars,
  mixed case, number, special).
- **Networking modes**: custom domain, DuckDNS, static IP, or auto-updating
  probe (Windows / macOS / Linux).
- **Built-in DuckDNS updater** — probe pushes IP changes straight to a free
  DuckDNS hostname.
- **Live dashboard** — online/offline status, shareable link, DDNS status,
  active logins.
- **Opt-in per-share features**: CLI execution (bash/powershell/cmd,
  job-based, sandboxed to the share folder), temporary UPnP debug tunnels.
- **Desktop probe app (Electron)** — system-tray IP monitor with the
  dashboard download buttons **now deliver a ZIP of `dist/`** so the `.exe`
  and its dependencies stay co-located (previously the bare `.exe` failed to
  launch because it was missing sibling DLLs/locales).
- **Probe "Quit" fix** — quitting from the tray now reliably terminates the
  process even when the app is docked in the Windows notification area
  (previously `app.quit()` could leave the process running because the
  window-close handler only hid the window).
- **Windows Task Scheduler script fix** — `Startup-win.ps1` now self-elevates
  (UAC) because registering a scheduled task requires admin rights; it also
  resolves the executable path automatically. The old version failed with
  "Access is denied".
- **Root startup scripts** — `Scripts/Startup.ps1` (Windows) and
  `Scripts/start.sh` (macOS/Linux) start the server and register the probe
  task idempotently.
- **Secret hygiene** — no credentials are committed. `data/config.json`
  holds `${SF2AIS_*}` placeholders resolved from the environment at runtime;
  `.env.example` documents the variables; `data/config.json` is gitignored.

## IN PROGRESS

- **Code signing for the desktop app** — Windows SmartScreen / macOS
  Gatekeeper signing so the download isn't flagged untrusted. (Blocked on
  signing certs.)

## PLANNED

- **One-click installer** — wrap the ZIP in a proper NSIS/MSIX installer with
  a desktop + Start Menu shortcut and an uninstaller.
- **Auto-update** — the probe checks a version endpoint and offers to download
  the latest ZIP.
- **Encrypted at rest** — optional age/gpg encryption for shared files.
- **Audit log UI** — surface CLI/tunnel activity in the dashboard.
- **Docker image** — publish an official image so the gateway runs containerised.

## KNOWN ISSUES

- **macOS / Linux desktop builds** are not produced on the Windows build host
  (electron-builder can't cross-compile `.dmg`/`.AppImage` here). The download
  buttons still serve a ZIP of whatever is in `dist/`, so a maintainer must
  build those platforms separately.
- **DuckDNS token in config** is resolved from `SF2AIS_DDNS_TOKEN` env — if
  unset, the field stays as the `${...}` placeholder and DDNS is simply
  inactive (no crash).
