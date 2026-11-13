# SF2AiS Release Readiness Status

_Updated: 2026-11-13_

## Current implementation

- Electron desktop package version: 1.1.3.
- FastAPI backend and shared desktop/web renderer are in the repository.
- Project shares created by the desktop app use per-client token authentication; legacy Basic-auth shares remain supported for compatibility.
- Each connected AI/user identity has its own revocable token and starts with no project-file access.
- Read, Write, Upload, Download and Deny are separately configurable at project root and through relative file/folder overrides.
- Server-side checks protect workspace and IDE file operations, browser workspace operations, uploads and downloads.
- CLI requires unrestricted root permissions and no path overrides; repository-wide Git operations are blocked when path-specific rules exist.
- The legacy administrator-managed connection/session API is separate from per-project client-token issuance. Passkeys, biometric approval, TOTP authenticator apps, recovery codes and trusted-device auto-accept are not integrated.
- Startup and operations documentation has been updated to describe the current behavior and known limitations.

## Verification completed

- Full backend test suite: **108 passed, 2 warnings, 11 subtests passed**.
- Python compile check: main.py, project_access.py, workspace.py and computer_use_manager.py passed.
- JavaScript syntax checks: probe-app/main.js, probe-app/preload.js and probe-app/renderer/app.js passed.
- Electron packaging: npm run build:dir and npm run build:win completed successfully with electron-builder 24.13.3 / Electron 31.7.7, product version 1.1.3. Windows x64 and ARM64 unpacked builds, NSIS installers and portable executables were generated.
- The current packaged Electron app launched successfully from the isolated test profile and rendered the current interface.
- Fresh desktop and server interface screenshots were captured under Docs/Images and referenced near the top of README.md.
- Older generated installers and unpacked builds were removed from probe-app/dist before the current rebuild. Only 1.1.3 Windows installers and portable executables remain there. The installed Windows application was not touched.

## Warnings

- pytest reports an unknown asyncio_default_fixture_loop_scope configuration option in the currently selected Python environment.
- Starlette reports that its TestClient integration with httpx is deprecated and recommends httpx2.

## Remaining release gates

1. Complete a manual visual and functional acceptance review of project creation, per-identity root permissions, path overrides, Deny inheritance, save/reload and revocation.
2. Complete external HTTPS testing from a genuinely separate network; local loopback checks do not prove public reachability.
3. Repeat the live CLI sandbox smoke test after any final backend changes. Docker Engine 29.9.2 and the sf2ais-workbench:latest linux/amd64 image are currently available; prior live sandbox acceptance is recorded in the acceptance report.
4. Complete a production security review of configuration, token lifecycle, reverse proxy/TLS, sandbox isolation, backups and audit retention.
5. Review the final Git staging area for secrets, local data, virtual environments, generated installers and accidental backup files before commit.

## Repository presentation

- README.md places the project banner and two interface screenshots before the main description and documentation.
- GitHub repository social-preview artwork is a separate repository setting and is not changed by README content alone.

## Release assessment

**Not yet declared production-ready.** Automated tests, source syntax checks, Windows packaging and an isolated packaged-app launch pass. Manual acceptance, live sandbox validation, external-network validation and the remaining security review are still required before a production release.

No commit or push is recorded in this status document until the final Git operations are verified.
