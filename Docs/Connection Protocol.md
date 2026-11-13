# SF2AiS Connection Protocol

## Current project-client protocol

The current file-access protocol is based on a registered client identity and a per-client bearer token.

1. The administrator creates a project share.
2. The administrator registers an AI/user identity under that share.
3. The server generates a unique random token and returns it once.
4. The server stores only the SHA-256 token hash.
5. The administrator assigns root and path-level project permissions.
6. The AI client sends the token in the X-Sf2AiS-Token header.
7. The backend validates the token, capability, path containment and requested action.
8. The administrator may revoke the token at any time.

New client identities start with no project-file access. Read, Write, Upload, Download and Deny are independent. Path overrides are relative to the project root; Deny overrides inherited grants.

## Legacy connection/session API

The backend also exposes an administrator-managed connection/session API:

- POST /api/connections - create a pending connection record (administrator authenticated).
- GET /api/connections - list connection records (administrator authenticated).
- POST /api/connections/{id}/approve - approve a pending record (administrator authenticated).
- POST /api/connections/{id}/deny - deny a pending record (administrator authenticated).
- Session endpoints under /api/sessions manage sessions associated with approved records.

This is not a client-initiated trust handshake. Approval is an administrator-authenticated action and does not automatically create a per-project AI client token or assign project-file permissions. The two systems remain separate.

## Security limitations

The current implementation does not integrate Windows Hello, platform passkeys, biometric approval, authenticator-app TOTP, recovery codes or trusted-device auto-accept. These are future security enhancements, not active controls.

## Transport

- Remote authenticated requests require HTTPS.
- Keep Uvicorn bound to loopback behind a TLS reverse proxy where practical.
- Do not expose the backend port directly to the public internet.
- Tokens must be stored by client applications in an appropriate secret store and must never be logged.
