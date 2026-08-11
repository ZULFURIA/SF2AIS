# Sf2AiS Probe — Operating Guide

## Overview

The Sf2AiS Probe is a desktop Electron application that monitors your public
IP address and reports changes to your Sf2AiS server. It runs in the system
tray and can optionally update DuckDNS hostnames.

## Installation

### Option 1: Download from the Sf2AiS Dashboard (Recommended)

1. Start your Sf2AiS server:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
2. Open `http://localhost:8000/dashboard` and log in with your admin credentials.
3. Scroll to the **Desktop Probe App** section.
4. Click the download link for your platform:
   - **Windows**: Download `.zip` (self-contained — the `.exe` plus all its
     dependencies are bundled, so just extract and run)
   - **macOS**: Download `.zip`
   - **Linux**: Download `.zip`
5. Extract the ZIP and run the app. It will appear in your system tray.

> Why a ZIP and not a bare `.exe`? The Electron executable needs its sibling
> DLLs/locales (in `dist/`) to run. Sending only the `.exe` made the app fail
> to launch. The dashboard now serves the whole `dist/` folder as a ZIP so the
> executable and its dependencies stay co-located.

### Option 2: Build from source

```bash
cd probe-app
npm install
npx electron-builder --win --x64   # or --mac --x64, --linux --x64
```

The built artifacts appear in `dist/`.

## Configuration

Open the app window by clicking the tray icon. In the settings window:

| Field | Description |
|-------|-------------|
| **Gateway URL** | Your Sf2AiS server address (e.g. `http://192.168.1.5:8000` or your DDNS domain) |
| **Probe Token** | Authentication token from the Sf2AiS dashboard (shown once during setup) |
| **DuckDNS Subdomain** | Your free DuckDNS subdomain (e.g. `wayne-debug`) — optional |
| **DuckDNS Token** | Your DuckDNS token from `duckdns.org` — optional |
| **Check interval** | How often to check public IP (default: 5 minutes, min: 1) |
| **Start with Windows** | Auto-start at Windows login + create Task Scheduler entry |

Click **🌐 Open duckdns.org** to register a free DuckDNS hostname if you
don't have one yet.

## How It Works

1. Every `N` minutes (default 5), the probe fetches your public IP from
   `api.ipify.org`.
2. If the IP has changed since the last check, the probe POSTs the new IP to
   `POST /api/ip-update` on your Sf2AiS gateway with your probe token.
3. If DuckDNS is configured, the probe also calls
   `https://www.duckdns.org/update?domains=...&token=...&ip=...` to update
   your DuckDNS hostname.
4. The probe log is stored at `~/.sf2ais-probe/probe.log` and is viewable
   from the app window.

## Windows Task Scheduler Integration

When you check **"Start with Windows"** and click **Save Settings**, the app
runs a PowerShell script (`scripts/Startup-win.ps1`) that:

- **Self-elevates** with a UAC prompt if not already running as administrator
  (registering a scheduled task requires admin rights — this was the cause of
  the previous "Access is denied" failure)
- Locates the probe executable automatically (searches the common install and
  build locations) if `-AppPath` isn't supplied
- Creates (or cleanly replaces) a Windows Task Scheduler entry named
  **"Sf2AiS Probe"**
- Sets two triggers: **At log on** and **Every 5 minutes**
- Configures the task to run with highest privileges and restart on failure

This ensures the IP monitor survives reboots and runs on the documented
5-minute schedule even if the app wasn't already running.

### Manual scheduler creation

```powershell
# Run from an elevated PowerShell, or let the script prompt for elevation
powershell -ExecutionPolicy Bypass -NoProfile -File "scripts/Startup-win.ps1"
```

## System Tray Controls

Right-click the tray icon for quick actions:
- **Start/Stop Probe** — toggle the background check loop
- **Check Now** — trigger an immediate IP check
- **Open Dashboard** — open your Sf2AiS web dashboard in browser
- **Quit** — fully exits the app. Closing the window (or using the tray to
  hide it) keeps the app running in the background; **Quit** from the tray menu
  is what actually terminates the process. This was fixed so Quit reliably
  closes the app even when it is docked in the notification area.
- **Open Settings** — open the Electron app window
- **Quit** — stop the probe and exit

## Troubleshooting

### The probe says "Stopped"
Make sure the Gateway URL is correct and the Sf2AiS server is running. The
probe token must match what was shown during Sf2AiS setup.

### DuckDNS update fails
- Verify your subdomain and token at `https://www.duckdns.org/`
- Check the live log in the app for error details
- Ensure your firewall allows outbound HTTPS (port 443)

### Task Scheduler didn't create
- Run `create-task.ps1` manually with PowerShell to see the error
- Ensure you're running the app as a user with permission to create scheduled tasks
- The task is created under your current Windows user account

### The app won't start
- Try deleting `%USERPROFILE%\.sf2ais-probe\config.json` to reset settings
- Re-download from the Sf2AiS dashboard if the binary is corrupted

## File Locations

| File | Path |
|------|------|
| Config | `%USERPROFILE%\.sf2ais-probe\config.json` |
| Logs | `%USERPROFILE%\.sf2ais-probe\probe.log` |
| App source | `probe-app/` |
| Build output | `probe-app/dist/` |
| Source code | `probe-app/main.js`, `probe-app/preload.js`, `probe-app/renderer/` |
| Scheduler script | `Scripts/Startup-win.ps1` (root) and `probe-app/scripts/Startup-win.ps1` |
