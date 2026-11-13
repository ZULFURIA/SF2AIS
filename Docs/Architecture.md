# SF2AiS Architecture

**SF2AiS - Secure AI Workspace**

## Overview

SF2AiS is a self-hosted HTTP workspace gateway. It lets an administrator expose selected project folders to individually registered AI/user identities without granting unrestricted host filesystem or shell access.

The server is authoritative for authentication, path containment, file permissions, capability checks and audit events. The Electron desktop client and browser interface share the renderer and visual design system.

## Runtime components

1. **FastAPI backend:** main.py owns administrator authentication, client token authentication, project-share administration, workspace APIs, network controls, sandbox integration and audit logging.
2. **Project access policy module:** project_access.py validates per-identity root permissions and relative path rules and computes effective rights.
3. **Workspace filesystem module:** workspace.py resolves project-relative paths, enforces share containment and protected-path rules, and performs file operations.
4. **Electron administration client:** probe-app/ provides the desktop UI, server connection, project/share management, client registration, permission editing, network controls, activity and local IP probe settings.
5. **Browser workspace:** the shared renderer is served by the backend for browser administration. Local-only desktop probe controls are omitted in web mode.
6. **Optional sandbox and capability providers:** CLI, IDE, Git, tunnel and computer-use features are independently scoped and are not implied by project Read/Write permissions.

## Authentication model

### Administrator

The administrator authenticates to the management plane using the administrator account. The backend stores a bcrypt password hash. The desktop main process stores its saved credential using the operating system secure credential store.

### AI/user identity

The administrator registers a named client under a project share. The server issues a random bearer token once and stores only its SHA-256 hash. The token is presented in the X-Sf2AiS-Token request header.

The display name is not proof of identity. A valid token authenticates the client but does not automatically grant project-file access.

### Legacy shares

Existing shares may retain historical HTTP Basic authentication for compatibility. New desktop-created project shares disable Basic authentication and use per-client tokens.

## Project and permission model

A project share is a server-side folder boundary. Each client identity bound to the share has a project-access policy:

- Root Read, Write, Upload, Download and Deny defaults.
- Optional path rules for individual files and subfolders.
- Per-action inheritance from the nearest parent rule.
- Explicit Deny on an ancestor or target overrides all inherited grants and blocks descendants.

Write and Upload also require the administrator-controlled share-level Workspace write master switch.

The backend checks permissions on file listing, file reads, writes, directory creation, moves, deletion, upload and download. IDE and browser workspace routes apply the same checks.

## Capability boundaries

CLI can access the mounted project as a whole. It is therefore blocked for identities with path overrides or partial root rights; it requires unrestricted root Read, Write, Upload and Download.

Git operations are repository-wide and are blocked when path-specific rules exist.

IDE file operations use the same project access policy. Tunnel and computer-use capabilities are separate from file access and require their own scopes.

## Connection lifecycle currently implemented

1. Administrator authenticates to the desktop or browser management interface.
2. Administrator creates a project folder share.
3. Administrator registers a named AI/user client.
4. Server issues a unique token once and stores its hash.
5. Administrator grants project-root and optional path-level permissions.
6. Client presents its token on API requests.
7. Server validates token, capability, path containment and requested action.
8. Audit event records the operation metadata.
9. Administrator can revoke the client token at any time.

A separate legacy administrator-managed connection/session API exists at /api/connections and /api/sessions. It creates pending request records and supports administrator approval/denial, but it is not a client-initiated trust handshake and does not automatically issue a project client token. Biometric/passkey/TOTP approval is not integrated. Do not confuse that API with the per-project client-token permission model.

## Repository layout

- main.py - FastAPI backend
- project_access.py - project permission policy evaluation
- workspace.py - path-safe project filesystem operations
- tests/ - backend regression tests
- probe-app/ - Electron client and shared renderer
- Docs/ - startup, operations, security, architecture and API documentation
- data/ - runtime configuration and audit records; never commit live runtime data

## Deployment principles

- Bind Uvicorn to 127.0.0.1 behind a local TLS reverse proxy where practical.
- Require HTTPS for remote authenticated requests.
- Never expose the internal API port directly to the public internet.
- Keep runtime configuration, tokens, certificates and audit data out of Git.
- Back up runtime data and project folders securely.
