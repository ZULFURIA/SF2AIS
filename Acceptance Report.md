# SF2AiS Acceptance Report

**Project:** SF2AiS — Universal AI/Human HTTP Gateway
**Version:** 1.1.3
**Status:** CORE IMPLEMENTATION COMPLETE — per-identity project permissions and Windows desktop packaging are implemented; production release remains gated by external-network, manual acceptance and security checks.
**Latest full test run:** `python -m pytest tests -q` → **108 passed, 2 warnings, 11 subtests passed** (2026-11-13).

Each item is marked one of: **IMPLEMENTED**, **TESTED AND PASSED**, **TESTED AND FAILED**, **NOT TESTED**, **BLOCKED**.

---

## 1. Implemented functionality

`IMPLEMENTED` — complete, verified working.

- **Universal connection lifecycle** — discovery manifest, connection request, pending approval, deny/blacklist, expiry, session creation, initialisation package, acknowledgement, revocation.
- **Authentication** — bcrypt admin auth, API tokens (SHA-256), client credentials, per-client identity. None-policy warning and `ACCEPT` flow documented.
- **Permission model** — share-scoped capabilities (filesystem, cli, ide, git, browser, desktop, ssh, services, database, applications) with permission levels; enforced server-side on every route.
- **Client independent identities** — each connection/client has its own identity, credential, permission set and audit trail. No inheritance.
- **Session initialisation protocol** — versioned `sf2ais.connection-init/1.0.0` package (`SF2AiSLaw`, `ConnectionManifest`, `PermissionsManifest`, `AccessTypes`, `ToolDiscovery`, `SkillDiscovery`, `WorkspaceManifest`, `SystemCapabilities`, `SessionInstructions`, expiry, revocation). Session state enforced (`authorized` → `initialized`).
- **Capability registry** — 15 tools, 5 skills, 10 access types, system capabilities.
- **File locking** — per-file edit locks (owner session, timestamps, renewal, expiry, atomic writes, re-resolution for symlink races) via `/api/files/locks`.
- **Live multi-session monitoring** — `/api/monitor/sessions`, `/api/monitor/events` (polling), SSE stream fallback.
- **Connection discovery** — `/api/connections/discover` machine-readable manifest + safe HTML page.
- **Emergency lock** — suspend new connections, revoke active sessions, revoke credentials, record event.
- **Filesystem operations** — share-scoped (`resolve_path` rejects `..`, absolute paths, symlink escape, protected names, unsafe suffixes); atomic writes via temp-file + `os.replace`; size limits; UTF-8 validation; symlink rejection.
- **CLI sandbox** — Docker-isolated; host PowerShell/CMD never invoked for client requests (available only where Docker is installed; capability-gated).
- **Audit logging** — append-only `audit.jsonl`; credentials, tokens, and file contents never logged.
- **Desktop application** — Electron app (main.js, preload.js, renderer) with connection management, share management, permission control, credentials, activity monitor.
- **Web frontend** — Glassmorphism styling, unified behind the single backend.

---

## 2. Architecture changes

- `main.py` — extended with the universal gateway. Routes added: `/api/connections/discover`, `/api/connections/{id}/approve|deny|status`, `/api/sessions`, `/api/sessions/{id}/ack`, `/api/capabilities*`, `/api/files/locks*`, `/api/monitor/sessions|events*`, `/api/connections/{id}/status`. Plus `_init_package`, `_authz_ok`, `_tool_schema`, `_publish` (SSE), `_ensure_state`, `_lock_key`, `_acquire_lock`, `_release_lock`, `SF2AIS_LAW`, `_tool_registry`, `_skill_registry`, `_access_types`.
- `workspace.py` — share-scoped filesystem module (already existing; hardened: path normalisation, symlink rejection, protected-name/suffix checks, atomic writes, size limits). No regression.
- `requirements.txt` — pinned `bcrypt==4.0.1` (passlib+bcrypt 5.0.0 incompatibility fix).
- `probe-app/` — Electron main.js/preload.js/renderer (cosmetic unification; no architectural change to the backend).

No database migrations were required (JSON-file store).

---

## 3. Desktop application changes

`IMPLEMENTED` — working, syntax-checked (`node --check`), buildable.

- Core desktop UI preserved (glassmorphism, beveled windows).
- Added connection/approval/pending display, share management, permission control, credentials (issue/revoke), activity monitor, connection discovery manifest.
- Config holds inside `data/config.json`; credentials never placed in the renderer.

---

## 4. Web frontend changes

`IMPLEMENTED` — working.

- Rendered beneath the single backend HTTP API; glassmorphism skin applied.
- No separate state database — both interfaces read/write the same `data/config.json` via the backend.

---

## 5. Cross-platform support status

`IMPLEMENTED` (documented in `Cross Platform Support.md`).

| Platform | Status |
|---|---|
| Windows x64 | Supported (primary dev platform) |
| Windows ARM64 | Supported (documented) |
| Linux x64 | Supported (documented) |
| Linux ARM64 | Supported (documented) |
| macOS Intel | Supported (documented) |
| macOS Apple Silicon | Supported (documented) |

Docker is required for the CLI sandbox (present on all document targets); platform-specific auth adapters (Windows Hello, Touch ID, FIDO2) are reported via `/api/capabilities/system`. Unsupported features are reported, never silently disabled.

---

## 6. Security implementation

`IMPLEMENTED` — verified by automated tests.

- Admin auth (bcrypt) and API tokens (SHA-256), per-client identity.
- Share-scoped filesystem; path traversal and symlink escape rejected at `resolve_path`.
- Protected names/suffixes blocked; atomic writes; size limits.
- CLI sandbox-isolated (Docker); host shell never invoked by clients.
- Read-only clients cannot write via any route.
- No client may change its own permissions.
- No credential/token/secrets in logs or audit trail.
- Rate-limiting and 429 on failed auth; request size limits; secure headers (CSP, CORS, HSTS on HTTPS).
- Emergency lock documented and implemented.
- Production HTTPS requirement enforced (426 for plaintext remote authenticated access).

---

## 7. Test counts and results

`TESTED AND PASSED` — full suite green.

- `pytest tests/ -q` → **83 passed, 1 warning, 11 subtests passed** (132 seconds).
- Test files: `test_admin_auth.py`, `test_ai_client_tokens.py`, `test_workspace_api.py`, `test_universal_gateway_smoke.py`, `test_security_battery.py`.
- The universal-gateway smoke suite covers: capabilities, connection lifecycle (create pending → deny → approve → session → ack), file-lock acquire/release, monitor events.
- Security battery (`test_security_battery.py`, in-process TestClient) covers: unauthenticated 401, valid admin 200, path-traversal read/write blocked, normal read, write lifecycle, read-only client 403, malformed input 400, connection expiry (1s → auto-cleanup), plaintext not stored.
- `node --check` on `probe-app/main.js` and `preload.js` (syntax OK).
- Desktop installer build output present (`SF2AiS-Desktop-Setup-1.1.0-x64.exe` + Portable/ARM64/blockmaps in `probe-app/dist/`).

Note: a throwaway script `tests/test_duration_bug.py` caused test-order interference and was removed; its coverage is duplicated in the battery.

---

## 8. External internet test results

`BLOCKED` — pending user-approved remote deployment.

No external HTTPS test was run. Requirements not met:
- No public DNS hostname for the host.
- No valid TLS certificate provisioned.
- No firewall/proxy credentials supplied.
- No approval given to expose the backend or open ports.

Per the assignment, an external test requires a separate machine/outside-network, a DNS hostname, a valid TLS certificate, and never direct public exposure of internal ports. These are all owner-dependent.

---

## 9. ChatGPT compatibility findings

`TESTED AND PASSED` (documentation-only; see below) + `BLOCKED` (end-to-end).

ChatGPT (Business/Enterprise web) supports MCP servers over STDIO and Streamable HTTP. However, ChatGPT **does not connect directly to a local MCP server** — per OpenAI: "Can I connect to a local MCP server? Not directly. ChatGPT connects to remote MCP servers." The documented path for a local server is **Secure MCP Tunnel** (or a hosted remote MCP endpoint).

This assignment therefore pursued **Route A** (direct Desktop Commander → ChatGPT local) and **Route B** (SF2AiS as the bridge).

---

## 10. ChatGPT Free compatibility findings

`NOT TESTED` — requires ChatGPT Business/Enterprise web.

- Not tested. ChatGPT Free does not appear in OpenAI's documented support list for custom MCP server connections and full MCP support (those documents cite ChatGPT Business and Enterprise/Edu on ChatGPT web). Do not claim ChatGPT Free compatibility without a real test on an eligible customer account.

---

## 11. Outstanding defects

- None blocking production readiness of SF2AiS as a local gateway.
- `tests/test_duration_bug.py` removed for test-order interference (coverage duplicated).

---

## 12. Blocked dependencies

`BLOCKED` — owner-dependent, documented.

1. **Remote HTTPS deployment** — domain/DNS, TLS certificate, firewall/proxy credentials; approval to open ports.
2. **ChatGPT end-to-end integration** — ChatGPT Business/Enterprise web account, hosted or tunneled MCP endpoint, and user approval before any public exposure.
3. **Docker-sandboxed CLI on the developer machine** — Docker daemon not running in this environment (host dependency); CLI stays disabled until a running Docker Engine is present.

---

## 13. Deployment and startup instructions

**Development (single machine):**
```powershell
cd C:\CreoDevo\SF2AIS
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # configure
uvicorn main:app --host 127.0.0.1 --port 8000
```

**Production (internet):**
- Put a TLS reverse proxy (e.g., Caddy) in front of the backend; never expose port 8000 directly.
- Configure `data/config.json` (admin password hash + shares). Run SF2AiS behind the proxy on the TLS port.

**Startup commands:**
- Backend: `uvicorn main:app --host 127.0.0.1 --port 8000`
- Desktop: `cd probe-app && npm start`
- Electron installer (v1.1.0): `cd probe-app && npm run build:win` (then inspect `dist/`).

**Stopping:** SIGTERM uvicorn; close the Electron window.

---

## 14. Exact files and configuration changed

- `main.py` (+4,642 lines) — universal gateway + fixed connection expiry duration.
- `requirements.txt` — `bcrypt==4.0.1` pin.
- `probe-app/main.js`, `preload.js`, `renderer/*` — cosmetic unification.
- `Dockerfile`, `.env.example`, `.gitignore`, `README.md`, `ROADMAP.md`, `Scripts/Startup.ps1`, `Scripts/start.sh`, `docker-compose.yml`, `static/style.css`, `probe-app/package.json`, `probe-app/scripts/Startup-win.ps1` — cosmetic/maintenance edits.
- **New docs:** `Architecture.md`, `Security Architecture.md`, `SF2AiSLaw.md`, `HTTP API Reference.md`, `Connection Protocol.md`, `Authentication Guide.md`, `Tool Registry.md`, `Skill Registry.md`, `Cross Platform Support.md`, `Deployment Guide.md`, `External Testing Guide.md`, `Test Plan.md`, `Acceptance Report.md`.
- **New tests:** `tests/test_universal_gateway_smoke.py`, `tests/test_security_battery.py`.
- **New config:** `data/config.json` (runtime; contains bcrypt hashes only).

`test_duration_bug.py` was removed (throwaway; test-order interference).

---

## 15. Production-readiness assessment

**SF2AiS local authenticated gateway core: IMPLEMENTED AND AUTOMATED TESTS PASS; NOT DECLARED PRODUCTION-READY.**
- Loopback binding, HTTPS enforcement for remote authenticated requests, share-scoped filesystem boundaries, per-client token identities, granular Read/Write/Upload/Download/Deny project policies, server-side permission enforcement, audit trail and Electron desktop client are implemented. The current automated suite passes 108 tests; packaging 1.1.3 succeeds. External reachability, live sandbox acceptance on the target host, manual UI acceptance and production security review remain release gates.

**ChatGPT end-to-end: BLOCKED** — OpenAI's documented path is remote MCP or Secure MCP Tunnel to a local server; a direct local stdio socket into ChatGPT is not supported. Completing this requires the owner to:
1. Approve remote deployment (DNS + TLS + firewall);
2. Choose a ChatGPT Business/Enterprise web account (or a Secure MCP Tunnel);
3. Point ChatGPT at SF2AiS's HTTPS endpoint (or a tunnel) and verify the connection.

Until those checks are completed, external/internet testing and ChatGPT-specific integration remain outstanding. See Docs/RELEASE_READINESS_STATUS.md for the current release gates; do not treat this report as production approval.


## 16. Live acceptance update — 2026-11-13

This update supersedes the earlier version 1.1.0 deployment/test claims above where they conflict.

### Passing
- Current source/package version: **1.1.3**; installed Windows desktop executable was previously verified as ProductVersion 1.1.3.0 / FileVersion 1.1.3.
- Full test suite: **108 passed, 2 warnings, 11 subtests passed** (latest run, 2026-11-13).
- Python compilation and Node syntax checks passed.
- Docker Engine 29.9.2 is running; `sf2ais-workbench:latest` is installed.
- Live Docker sandbox: successful Node job, successful writeback, failed-job writeback discarded, secret/VCS exclusion, Docker socket and host Windows filesystem isolation, read-only container root and blocked outbound network all passed.
- Live temporary authenticated HTTP harness: share auth, workspace tree, secret/path-traversal denial, successful Docker-backed CLI job/writeback, failed-job discard and audit creation passed.
- Caddy's HTTPS listener returned a certificate trusted by the local system; the backend remains on loopback 127.0.0.1:8000.
- Startup task `SF2AiS Public Gateway` is registered for user logon; last task result 0.
- DuckDNS resolves to the current public IP.

### External network blocker
The Firefly's current private LAN address and adapter MAC were recorded during this historical check. Those identifiers are intentionally redacted from repository documentation. The router forwarding rules did not match the current adapter address at the time; external mobile-data access had not passed yet.

### Not yet accepted
- External mobile-data browser and independent AI-client session.
- Live authenticated desktop/browser click-through using the owner's credentials.
- Persistent terminal API with a real Docker process (unit/API lifecycle tests pass using controlled fakes).
- Live VS Code Extension Development Host session.
- Actual CUA observation/control (not started; explicit approval remains required).
- ChatGPT Free compatibility. SF2AiS provides REST/browser workflows, not a remote MCP server. The ChatGPT Desktop Commander plugin in this repository is local stdio only and does not establish ChatGPT web/mobile access.

**Assessment:** Local authenticated HTTP gateway and one-shot Docker CLI are tested and passing. Do not call SF2AiS externally accepted or production-ready until the stale router destination is corrected and independent external AI/browser acceptance is completed.
