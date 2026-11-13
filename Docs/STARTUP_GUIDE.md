# SF2AiS Startup and Shutdown Guide

_Last verified: 2026-11-13_

This guide covers the current Windows server, browser workspace, desktop client and optional public reverse-proxy deployment. Keep the server bound to loopback unless a reviewed reverse proxy is in front of it.

## 1. Prerequisites

- Windows 10/11 or Windows Server with PowerShell 7 (pwsh) or Windows PowerShell.
- Python 3.12+ and the repository dependencies.
- Node.js/npm only when building or running the Electron desktop client.
- Docker Engine only for live CLI sandbox execution.
- A TLS reverse proxy and DNS name for remote access.

## 2. First-time server setup

From the repository root:

```powershell
Set-Location C:\CreoDevo\SF2AIS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Review .env and set a unique administrator password, secret key, allowed origins and any optional integration credentials. Do not commit .env, runtime configuration, database files, tokens or private keys.

If you intentionally install the optional computer-use provider, follow its separate dependency and security instructions. The repository's .venv-cua is machine-local and must not be committed.

## 3. Start the server on Windows

Recommended:

```powershell
pwsh -ExecutionPolicy Bypass -File Scripts\Startup.ps1
```

Optional parameters: -NoProbe skips registering the desktop IP probe scheduled task; -Port 8010 selects a different local listener port.

The script starts Uvicorn on 127.0.0.1, opens /workspace, and optionally registers the probe task. It checks the PID record and listener before starting to avoid duplicates. If the port is occupied by a process that does not match the saved SF2AiS PID, it stops rather than starting a second server.

Manual foreground start:

```powershell
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Open http://127.0.0.1:8000/workspace and sign in with the administrator account configured during first-time setup.

## 4. Start the server on Linux/macOS

Create and activate a virtual environment, install requirements.txt, then run:

```bash
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
```

Use a system service manager for persistent production operation. Keep the application listener private behind the TLS proxy.

## 5. Start the desktop application

Development:

```powershell
Set-Location C:\CreoDevo\SF2AIS\probe-app
npm install
npm run start
```

Build an unpacked Windows x64 test app:

```powershell
npm run build:dir
.\dist\win-unpacked\SF2AiS Secure AI Workspace.exe
```

The unpacked test app is not the installed release. Build output is written under probe-app\dist. Do not remove or overwrite the installed app while testing. Close only the test instance whose command line identifies the isolated test profile before rebuilding if Windows reports a locked Electron DLL.

## 6. Remote access through a TLS reverse proxy

- Configure DNS/DDNS to resolve to the public endpoint.
- Configure the router to forward external HTTPS to the reverse proxy's internal TLS listener.
- Configure the reverse proxy to forward to 127.0.0.1:8000.
- Preserve the original Host and forwarded-protocol headers.
- Configure the application allowed-origin list for the actual public origin.
- Keep port 8000 private; do not expose Uvicorn directly to the internet.
- Test from a genuinely separate network, such as a mobile connection with Wi-Fi disabled.

Do not change router mappings, DNS records, firewall rules or public exposure without explicit authorization. The example Caddy configuration is a template and must be adapted to the actual domain and certificate setup.

## 7. Verify service health

```powershell
Test-NetConnection 127.0.0.1 -Port 8000
```

The protected status/API routes may return HTTP 401 without administrator or client authentication. That is expected and is not evidence that the server is offline. Sign in through /workspace for an authenticated check.

Review logs/sf2ais-server.log, logs/sf2ais-server-error.log and data/audit.jsonl. Runtime data is private and must not be published.

## 8. Shutdown

For the managed server, use the PID recorded in .sf2ais-server.pid only after verifying that the process command line belongs to uvicorn main:app in this repository. Do not terminate a process based on PID alone.

For a foreground server, press Ctrl+C in its terminal.

Close the Electron desktop app normally from its window or tray menu. Stop the optional scheduled probe through Task Scheduler or its provided management script.

## 9. Troubleshooting

| Symptom | Action |
|---|---|
| Port 8000 already in use | Inspect the listener PID and command line; do not kill an unrelated process |
| Startup script refuses to start | Verify .sf2ais-server.pid and the listener; reconcile stale PID records only after confirming process ownership |
| HTTP 401 on /api/status | Expected for a protected endpoint without authentication; sign in through /workspace |
| Remote HTTPS fails | Check DNS, router forwarding, proxy certificate, allowed origins and forwarded headers |
| CLI execution unavailable | Confirm Docker Engine is running and the client has unrestricted root permissions with no path overrides |
| Desktop build reports a DLL lock | Close only the isolated build/test process and rebuild; leave the installed application untouched |

## Related documentation

- [Operations Guide](OPERATIONS_GUIDE.md)
- [Desktop Operating Guide](../probe-app/OPERATING_GUIDE.md)
- [Connection Guide](CONNECTION_GUIDE.md)
- [Security](SECURITY.md)
