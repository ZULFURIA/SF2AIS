# SF2AiS Product Roadmap

_Last updated: 2026-11-13_

SF2AiS is a self-hosted project workspace that gives each registered AI/user identity separately controlled access to selected local project folders over authenticated HTTP.

## Current release capabilities

- Guided setup, administrator account, project-share registration and networking modes (custom domain, DDNS, static IP and current-IP probe).
- New desktop-created project shares are token-only. Existing legacy Basic-auth shares remain compatible.
- Individual AI/user client tokens are shown once and stored as SHA-256 hashes; tokens can be revoked individually.
- New identities default to no project-file access.
- Per-identity root Read, Write, Upload, Download and Deny permissions.
- Relative file/folder overrides with inherited rights and absolute Deny precedence.
- Server-side enforcement for workspace and IDE file operations, browser workspace operations, upload and download.
- Separate capability scopes for CLI, IDE, Git, tunnels and computer-use.
- CLI requires unrestricted root Read, Write, Upload and Download with no path overrides.
- Repository-wide Git operations are blocked when path-specific rules exist.
- Metadata-only JSONL audit trail and administrator audit endpoint.
- Origin validation, security headers, no-store API responses, failed-login throttling and HTTPS enforcement for remote authenticated requests.
- Docker-only CLI runner with bounded resource limits and no-network sandbox.
- Electron desktop application with shared web renderer, glassmorphism appearance settings, project administration and per-identity permission manager.

## Security and connection work

- Legacy /api/connections and /api/sessions endpoints support administrator-created pending records and administrator approval/denial.
- The legacy connection/session API is not a client-initiated trust handshake and is not wired to project client-token issuance.
- Windows Hello, platform passkeys, biometric approval, TOTP authenticator apps, recovery codes and trusted-device auto-accept are not integrated yet.

## Next implementation priorities

1. Integrate client-initiated connection requests with the existing per-project client-token identity model.
2. Add strong approval confirmation using platform passkeys/biometrics, with password fallback where appropriate.
3. Add authenticator-app TOTP enrollment, recovery codes, device revocation and explicit trusted-device auto-accept rules.
4. Make connection approval create or bind the correct per-project identity and permission policy without granting access implicitly.
5. Add end-to-end tests for request, approval, denial, expiry, replay, token issuance, revocation and permission inheritance.
6. Continue external-network validation, installer cleanup, signed release packaging and repository release hygiene.

## Permission model acceptance criteria

- Every new identity starts with no project-file permissions.
- Read, Write, Upload and Download are independently evaluated.
- Deny on any ancestor or target path blocks access to the path and descendants.
- A path override cannot escape its project share or target protected system paths.
- The backend enforces access; renderer controls are not trusted.
- CLI and Git cannot bypass narrower path restrictions.
- Revoking a token prevents subsequent API requests from authenticating.
