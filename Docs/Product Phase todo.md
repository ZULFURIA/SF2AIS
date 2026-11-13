# SF2AiS Product Phase Todo

_Last updated: 2026-11-13_

## Phase 1 - Foundations and current runtime

- [x] FastAPI backend and authenticated management API.
- [x] Electron desktop client with shared browser renderer.
- [x] Windows startup helper and optional desktop probe scheduled task.
- [x] Project share registration and server-side path containment.
- [x] Runtime configuration and audit data excluded from Git.
- [x] Updated README, startup, operations, authentication, connection, architecture and security documentation.

## Phase 2 - Project identity and file permissions

- [x] Per-project AI/user identities with unique revocable bearer tokens.
- [x] Token hash stored server-side; raw token displayed once.
- [x] New identities default to no project-file access.
- [x] Root Read, Write, Upload, Download and Deny checkboxes per identity.
- [x] Server-side file/folder picker and relative path override rules.
- [x] Explicit Deny overrides inherited grants and blocks descendants.
- [x] Write/Upload require both share master switch and identity/path permission.
- [x] Workspace, IDE, browser, upload and download routes enforce per-path permissions.
- [x] CLI blocked for partial/path-restricted identities.
- [x] Repository-wide Git operations blocked when path overrides exist.
- [x] Permission regression tests for inheritance, Deny, independent actions, default-deny and API enforcement.

## Phase 3 - CLI, sandbox and Git

- [x] Docker-only CLI runner and bounded sandbox policy.
- [x] CLI access is restricted to identities with full project-root permissions and no path overrides.
- [x] Git read/mutation operations require appropriate root permissions and no path overrides.
- [ ] Run live CLI sandbox tests on a host with Docker Engine available.
- [ ] Complete sandbox writeback and rollback tests with a dedicated full-access test identity.

## Phase 4 - Desktop client and packaging

- [x] Electron main process, preload and renderer syntax checks.
- [x] Glassmorphism controls for background opacity, card opacity, frost tint and neon borders.
- [x] System Settings intro moved to the top of the settings page.
- [x] Per-identity project access manager added to shared renderer.
- [x] Electron unpacked Windows build completed successfully.
- [ ] Manual visual acceptance of desktop and browser layouts at supported display sizes.
- [ ] Verify installed upgrade/uninstall and clean-machine install behaviour.
- [ ] Complete code signing and final installer validation.

## Phase 5 - Connection approval and stronger authentication

- [x] Legacy administrator-managed connection/session API exists for pending records and admin approval/denial.
- [ ] Integrate client-initiated connection requests with project client-token identity creation.
- [ ] Add Windows Hello/platform passkey/biometric approval.
- [ ] Add authenticator-app TOTP enrollment, recovery codes and device revocation.
- [ ] Add explicit trusted-device auto-accept policy with scoped expiry.
- [ ] Test replay, expiry, brute-force limits, revocation and authorization downgrade.

## Phase 6 - Remote deployment and production verification

- [ ] Test external HTTPS access from an independent network.
- [ ] Verify TLS certificate renewal, reverse-proxy headers and firewall policy.
- [ ] Verify router mapping behaviour only with explicit approval.
- [ ] Complete backup/restore test for runtime config, audit records and project data.
- [ ] Complete independent security review and release acceptance.

## Verification record

- Full Python test suite: 108 passed, 2 warnings, 11 subtests passed (2026-11-13).
- Python compile check: main.py, project_access.py and permission tests passed.
- Renderer JavaScript syntax: node --check passed.
- Electron build: npm run build:dir completed successfully.
- Remaining pytest warnings: unknown pytest asyncio config option and Starlette/httpx TestClient deprecation.
