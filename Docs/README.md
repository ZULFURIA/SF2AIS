# SF2AiS Documentation Index

This directory contains the current operational and engineering documentation for the SF2AiS Secure AI Workspace.

## Start here

- [Startup Guide](STARTUP_GUIDE.md) - start/stop the backend, desktop app, scheduled probe and reverse proxy.
- [Operations Guide](OPERATIONS_GUIDE.md) - create projects, register AI identities, set file permissions, revoke tokens, audit and back up.
- [Authentication Guide](Authentication%20Guide.md) - administrator authentication, AI client tokens, project access and current limitations.
- [Connection Guide](CONNECTION_GUIDE.md) - connect a registered client and use its token.
- [Security](SECURITY.md) - security controls and enforcement.
- [Security Architecture](Security%20Architecture.md) - threat model and permission boundaries.
- [Architecture](Architecture.md) - current server, renderer and client structure.
- [HTTP API Reference](HTTP%20API%20Reference.md) - current management and workspace endpoints.
- [Test Plan](Test%20Plan.md) - regression and acceptance tests.

## Current implementation summary

- Project folders are server-side share boundaries.
- New desktop-created project shares are token-only; legacy HTTP Basic shares remain for compatibility.
- Each AI/user identity has its own revocable client token.
- New identities start with no project-file permissions.
- Read, Write, Upload, Download and Deny are separate project permissions.
- Path overrides apply to individual files/folders; Deny overrides inherited grants.
- Workspace and IDE file operations, browser operations, upload and download are checked server-side.
- CLI requires unrestricted project-root access and no path overrides; Git operations are blocked while path-specific rules exist.
- The legacy administrator-managed connection/session API is separate from project client-token issuance. Passkey, biometric and authenticator-app approval are not integrated.

## Source map

- Backend: main.py, project_access.py, workspace.py
- Desktop client and shared renderer: ../probe-app/
- Regression tests: ../tests/
- Runtime configuration and audit data: ../data/ (private; never commit)
