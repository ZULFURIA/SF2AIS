# Deployment Guide

How to deploy and run SF2AiS in development and production.

## Prerequisites

- Python 3.12+ with a virtualenv (see `requirements.txt`).
- Node 22.12+ and npm (for the desktop application build).
- Docker (required for the isolated CLI sandbox). Docker is not required for filesystem/IDE HTTP features, but CLI execution is unavailable without it.
- For remote (internet) access: a domain name, a TLS certificate, and a reverse proxy (the repository includes a `Caddyfile.example`).

## Development

1. Create the virtualenv and install dependencies:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   Dependency note: `bcrypt==4.0.1` is pinned because passlib+bcrypt 5.0.0 is incompatible (5.0.0 removed `__about__`, which breaks passlib's bcrypt handler).
2. Copy the example environment file and configure:
   ```powershell
   copy .env.example .env
   # edit .env with your values
   ```
3. Start the backend:
   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```
   The backend is localhost-bound by default. It enforces HTTPS for remote authenticated access; on remote addresses it returns 426 if you connect over plain HTTP without `SF2AIS_ALLOW_INSECURE_REMOTE=1`.
4. Run the test suite:
   ```powershell
   pytest tests/ -q
   ```
5. Start the desktop application (Electron):
   ```powershell
   cd probe-app
   npm start
   ```

## Production

1. Configure `data/config.json` (admin password hash, shares, settings). The file is generated on first run with randomly created secrets; do not commit it.
2. Generate a bcrypt password hash for the admin user and place it in `data/config.json` under `admin.password_hash`.
3. Run behind a reverse proxy that terminates TLS. The repository includes a `Caddyfile.example`. The backend must **not** be exposed on port 8000 to the internet directly.
4. Set the environment variable `SF2AIS_ALLOW_INSECURE_REMOTE=1` only if you have a documented reason to allow plaintext HTTP, and never for untrusted networks.
5. Rebuild the desktop installer from the current package metadata (version 1.1.0). Use `electron-builder` (see `probe-app/package.json` scripts).
6. Verify internal ports remain private (firewall rules), only intended public endpoints are exposed, and TLS certificates validate.

## Backup and recovery

- `data/config.json` contains admin credentials and share configuration. Back this up.
- `data/audit.jsonl` is the append-only audit trail.
- Do not back up or distribute credentials, tokens, or secrets in plaintext.

## Stopping services

- Backend: send `SIGTERM` to the uvicorn process, or use the desktop application's disconnect control.
- Desktop application: close the window; the app disconnects from the backend on shutdown.

## Revoking access

- Use the desktop or web application to revoke client tokens and sessions immediately.
- The owner can also lock the system via the emergency-lock action, which suspends new connections and revokes active sessions.
