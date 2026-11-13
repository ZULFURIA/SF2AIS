# SF2AiS Connection Guide

This guide describes the current connection path for a human or AI client.

## 1. Prerequisites

1. Start the SF2AiS backend. The default development endpoint is http://127.0.0.1:8000.
2. Complete the initial setup wizard and create the administrator account.
3. Configure a TLS reverse proxy before allowing remote authenticated connections.
4. Register a project folder from the desktop administration client.

Use a project directory, not a drive root or broad user/company directory.

## 2. Register a client identity

1. Open the desktop app and connect to the server using the administrator account.
2. Open Access & Permissions and select the project share.
3. Register a named AI/user identity.
4. Select only the non-file capabilities required.
5. Create the token and copy it immediately. The raw token is shown once; the server stores only its SHA-256 hash.
6. Select the identity in the Connected user / AI dropdown and grant the minimum project-file permissions.

A new identity starts with no Read, Write, Upload or Download rights.

## 3. Configure project access

The administrator can grant project-root Read, Write, Upload, Download and Deny rights. The Choose file / folder button browses the server-side project tree and creates a relative path override for an individual file or folder.

Deny overrides inherited grants and blocks descendants. Write and Upload also require the project-level Workspace write switch.

The client sends the token in the X-Sf2AiS-Token header to the authenticated workspace API. Supported API paths include:

- GET /api/workspace/tree
- GET /api/workspace/file
- PUT /api/workspace/file
- POST /api/workspace/directory
- POST /api/workspace/move
- DELETE /api/workspace/path
- POST /api/workspace/upload
- GET /api/workspace/download

The backend checks the identity's path/action policy for each request. A client must not assume that a valid token grants access to every file in the project.

## 4. Legacy browser access

Existing legacy shares may still accept their historical Basic-auth credentials for backward compatibility. New desktop-created project shares disable Basic authentication and require a registered client token. Do not give the administrator password to an AI client.

## 5. Remote access

- Remote authenticated requests require HTTPS.
- Keep Uvicorn bound to loopback behind the TLS reverse proxy where possible.
- Do not expose port 8000 directly to the internet.
- Confirm DNS, TLS, firewall and reverse-proxy routing before testing from mobile data or another external network.
- Router discovery does not create a mapping. A mapping requires explicit administrator confirmation.

## 6. Capability-specific restrictions

- CLI requires unrestricted root Read, Write, Upload and Download and no path overrides.
- Git operations are blocked when path-specific rules exist.
- IDE file operations use the same project permission checks.
- Tunnel and computer-use capabilities remain separate from file permissions and require their own explicit scopes.

## 7. Revocation

Open Access & Permissions, locate the client under Clients on selected share, and select Revoke. The token is invalidated immediately and associated terminal sessions are closed.

## 8. Current authentication limitation

The current project identity flow is administrator registration plus a per-client bearer token. A separate legacy /api/connections and /api/sessions API supports administrator-created pending requests and administrator approval, but it is not a client-initiated approval handshake and does not automatically issue the project token. Biometric/passkey approval, TOTP authenticator enrollment, recovery codes and trusted-device auto-accept remain future security work.
