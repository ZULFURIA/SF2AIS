# SF2AiS — Development Guide

How to set up, run, test, and package SF2AiS locally.

---

## 1. Prerequisites

- **Python 3.12** (Windows: `Python312` from the Hermes environment, or a `py -3.12` venv).
- **Node 26 + npm 11** (for the desktop app).
- **Docker Engine** (optional; required only for the isolated CLI sandbox). The Docker CLI is
  installed; the Linux engine must be running for CLI tests. Without Docker, CLI is disabled
  and reports "Docker Engine unavailable."
- **npm workspaces** — the desktop app's node_modules are preinstalled in
  `probe-app/node_modules`. Do not `npm install` globally; use the project venv.

---

## 2. Configuration

Copy `.env.example` to `.env` and fill in values you actually want (probe token, DDNS,
Cloudflare tunnel). The **runtime config** is `data/config.json` (gitignored). The committed
`data/config.example.json` shows the structure without secrets.

```bat
copy .env.example .env
```

Do **not** commit real credentials. `data/config.json` holds bcrypt bcrypt password hashes
and SHA-256 client tokens; it is regenerated on first run by the setup wizard.

---

## 3. Start the backend (Windows)

Use the project virtual environment `C:\CreoDevo\SF2AIS\.venv-cua\` and its `uvicorn` and
`python` executables.

```bat
cd C:\CreoDevo\SF2AIS
set VENV=.venv-cua\Scripts
%VENV%\python.exe -m pip install -r requirements.txt
%VENV%\uvicorn.exe main:app --host 127.0.0.1 --port 8000
```

On first run the setup wizard (or `GET /`) walks you through the admin account and shares.
Without real credentials, the tests provide their own config.

> The server now runs cleanly with `bcrypt==4.0.1` pinned in `requirements.txt`,
> `passlib==1.7.4`. Earlier runs with `bcrypt>=4.0.1` (including 5.0.0) broke passlib's
> bcrypt handler because `bcrypt.__about__` was removed in 5.0.0.

Control:
- **Stop**: `Ctrl+C` in the server terminal, or `taskkill /F /IM uvicorn.exe` on Windows.
- **Health**: `curl http://127.0.0.1:8000/api/status` (401 "Authentication required." until
  you log in).

---

## 4. Start the backend (macOS / Linux)

```bash
cd /c/CreoDevo/SF2AIS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## 5. Start the desktop app (probe-app)

The desktop app ("SF2AiS Secure AI Workspace") runs from `probe-app`:

```bash
cd probe-app
npm install --ignore-scripts        # node_modules already present; skip scripts
npm run start:dev                   # or npx electron .
```

Packaged installers (Windows `.exe`) are produced by `npm run build:win` (electron-builder
24.13.x, electron 31.7.x). See also `SECURITY.md` §7 and the project `.gitignore` for what is
excluded from version control.

---

## 6. Test suite

Use the project venv's `python -m pytest` from the SF2AIS root. The suite lives in
`tests/` and is configured by `pytest.ini`.

```bat
cd C:\CreoDevo\SF2AIS
%VENV%\python.exe -m pytest tests/ -q
```

Latest full-suite result (2026-11-13): **108 passed, 2 warnings, 11 subtests passed**. The current warnings are the unknown asyncio_default_fixture_loop_scope pytest option and Starlette's httpx TestClient deprecation. The warning cleanup remains outstanding; do not treat this run as warning-free.

Covered areas:

- Python compilation / import checks
- Backend unit tests
- Authentication & authorisation (admin + share + client tokens)
- Path traversal and protected paths
- Read-only / write permission enforcement
- CLI sandbox policy
- Electron main-process `main.js` and preload `preload.js` syntax checks
- Route registration for `/api/desktop/*`, `/api/workspace/*`, `/cli/*`, `/tunnel/*`

Run the checks individually if you want to iterate faster:

```bat
%VENV%\python.exe -m pytest tests/ -q        # full suite
%VENV%\python.exe -m pytest tests/test_admin_auth.py -q
%VENV%\python.exe -m pytest tests/test_ai_client_tokens.py -q
%VENV%\python.exe -m pytest tests/test_workspace_api.py -q
```

> Desktop app / installer build and Dockerfile syntax checks are run separately (see §7).
> Python compilation (`-m compileall`) passes on the backend modules.

---

## 7. Build and package

### Backend only
```bat
%VENV%\pip install -r requirements.txt
```

### Desktop app installer (Windows)
Run inside `probe-app`:

```bat
cd probe-app
npm run build:win        # npm run build (electron-builder) for win
```

Produces installers named `SF2AiS-Desktop-Setup-<version>-<arch>.exe` and portable
`SF2AiS-Desktop-Portable-<version>-<arch>.exe` under `probe-app/dist/`.
Electron-builder is at `probe-app/node_modules/.bin/electron-builder` (24.13.3),
electron 31.7.7.

### Docker CLI image
```bat
cd C:\CreoDevo\SF2AIS
.\Scripts\build-sandbox.ps1     # or ./Scripts/build-sandbox.sh
```

---

## 8. Stopping and revoking access

- Backend: `Ctrl+C`, or `taskkill /F /IM uvicorn.exe` (Windows).
- Desktop app: close the tray window, or end the `SF2AiS Secure AI Workspace.exe` process.
- Revoking: see `CONNECTION_GUIDE.md` §6.

---

## 9. Project layout

```
SF2AIS/
  main.py                  FastAPI backend (all /api routes)
  tests/                   pytest suite
  sandbox/                 Dockerfile + sandbox tooling
  probe-app/               Electron desktop app (SF2AiS Secure AI Workspace)
  shared_files/            shared-files mount point (see docker-compose.yml)
  static/                  static assets for the browser UI
  data/                    runtime config + audit + cua-driver (gitignored)
  Scripts/                 start.sh, Startup.ps1, build-sandbox.sh/.ps1
  packaging/               installers (linux)
  probe/                   probe.py and setup-guide endpoints
```
