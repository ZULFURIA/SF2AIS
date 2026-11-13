# Test Plan

SF2AiS test plan. Tests run in the order specified below. All tests use the project's real test suite and real HTTP client; no external credentials, tokens, or personal files are used for destructive acceptance tests.

## Phase A — Baseline and regression

1. Inspect the existing test suite (`tests/`).
2. Run all existing tests:
   ```powershell
   pytest tests/ -q
   ```
3. Record the current full-suite result: **108 passed, 2 warnings, 11 subtests passed** (2026-11-13).
4. Add tests for every new feature (universal gateway routes, session initialisation, file locking, monitor, connection lifecycle and per-identity project permissions).
5. Run frontend tests and backend tests together.
6. Run security tests.
7. Resolve regressions.

## Phase B — Authorization testing

- Legacy connection API: administrator creates a pending connection record and verifies its pending state.
- Legacy connection API: administrator approves or denies the record; verify the resulting status and audit event.
- Project identity: administrator creates a per-share AI client token; verify the token is shown once and only its hash is stored.
- Project identity: verify new clients have no project-file access until an explicit policy is saved.
- Keep legacy connection/session approval separate from per-project client-token issuance.
- Future work only: approval using Windows Hello, platform passkey/FIDO2 or another device authenticator. This is not part of the current implemented acceptance flow.
- Denial (agent denies).
- Blacklist creation and expiry.
- Expired authorization request: auto-rejected by cleanup.
- Repeated connection attempts (rate limits).
- Credential revocation.
- Unauthorized permission escalation: denied.
- Project permission regression suite: new client defaults to no file access; Read/Write/Upload/Download are independent; path overrides inherit; Deny blocks descendants; CLI/Git cannot bypass granular restrictions.
- Session expiration: auto-expired after idle/timeout.
- Emergency lock: suspends new connections, revokes active sessions.

## Phase C — Initialization and discovery

- Approved connection receives the initialisation package (SF2AiSLaw, connection manifest, permissions manifest, access types, tool discovery, skill discovery, workspace manifest, system capabilities).
- SF2AiSLaw is delivered verbatim.
- Permissions manifest is accurate.
- Access methods are discoverable.
- Tool registry is accessible and tool schemas are valid.
- Skills are discoverable.
- Workspace discovery is permission-filtered.
- Acknowledgement is required before operational access.
- Unauthorized capabilities remain unavailable.
- Revoked permissions disappear immediately.
- Session expiry disables access.

## Phase D — Multi-client testing

Connect one to five independent clients and verify:
- Independent identities and credentials.
- Separate permissions and session activity.
- Maximum connection limits.
- Connection queue behaviour.
- AI-only, human-only, and both modes.
- Session isolation.
- Per-workspace and per-identity limits.

## Phase E — Collaborative file testing

In a dedicated test share:
1. AI A obtains a file edit lock.
2. AI B attempts to edit the same file → receives a lock conflict.
3. AI B receives the recent-edit notification (2-minute window).
4. AI B can inspect the latest file and diff.
5. Approval permits the controlled edit; denial prevents it.
6. Expired locks are recovered safely.
7. Concurrent writes cannot corrupt files.
8. Version/hash checks detect stale edits.
9. Different files can be edited concurrently.
10. Human and AI edit conflicts are handled safely.

## Phase F — Live monitoring

Verified via `/api/monitor/sessions` and `/api/monitor/events` (HTTP polling, with SSE fallback):
- Every connected session appears.
- Activity updates in real time.
- File operations, terminal activity, IDE activity tracked.
- Session termination and permission changes reflected.
- Audit timeline visible.
- Monitoring privacy controls respected.

## Phase G — Frontend parity

Compare the desktop (Electron) and web frontend:
- Matching glassmorphism design, light and dark themes.
- Navigation, settings, forms, dialogs, notifications, tables.
- Connection monitor, permission management, connection monitor.
- Change a setting in one interface and confirm the other reflects it.

## External HTTPS acceptance test (Phase H)

Conducted from a genuinely separate network/machine:
1. SF2AiS host bound to a public hostname with valid TLS.
2. Verify internal ports remain private; only intended public endpoints exposed.
3. Independent external HTTP client (not importing SF2AiS backend modules) drives the full connection lifecycle.
4. Multiple external clients run concurrently; file locking and conflicts verified.
5. ChatGPT compatibility test: separate determination of what ChatGPT can actually do (see `CONNECTION_GUIDE.md` and `External Testing Guide.md`).

## Known test dependencies

The following require external resources and were **NOT** run in this local acceptance pass:
- Remote HTTPS deployment with a real domain, TLS certificate, and firewall.
- ChatGPT end-to-end integration (requires ChatGPT Business/Enterprise web, a hosted or tunneled MCP endpoint, and user approval).
- Docker-sandboxed CLI execution on the developer machine (in this environment Docker was not running).

## Test records

- `/api/audit` exposes the server-side audit trail for each test run.
- Each test run records `admin`, `client`, and `connection` state in `data/config.json` and `tests/.pytest_cache` (no secrets stored).
