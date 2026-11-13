# Remote Workspace and Workbench

## Purpose

The remote workspace exposes selected server-side project folders to authenticated AI/user clients. The server, not the renderer, owns authorization and filesystem boundaries.

## Authentication

- Administrator management routes use the administrator account.
- Each AI/user identity receives a unique bearer token.
- The client sends its token in the X-Sf2AiS-Token header.
- The server stores the token hash and supports immediate revocation.
- New desktop-created project shares disable Basic authentication. Existing legacy shares may continue to use their older Basic credentials.

## Project permissions

Each client identity has an independent project_access policy:

- read
- write
- upload
- download
- deny
- rules: relative path overrides

New identities receive no project-file permissions. Root permissions are inherited by descendants unless a path rule explicitly overrides an action. Deny on an ancestor or target path blocks that path and its descendants.

The project-level Workspace write switch is a master gate for Write and Upload. A client must have both the master switch and the corresponding identity permission.

## Server enforcement

The backend checks permissions for:

- Project tree listings and returned entries.
- File reads and writes.
- Directory creation.
- File/folder moves and deletes.
- File uploads and downloads.
- IDE file operations.
- Browser workspace operations.

Path traversal, absolute paths outside the share, protected system paths and symlink escapes are rejected.

## Capability restrictions

CLI commands can access the entire mounted project. CLI is therefore unavailable to identities with partial root permissions or path overrides. It requires unrestricted Read, Write, Upload and Download.

Git operations are repository-wide and are blocked when path-specific rules exist. This avoids exposing repository-wide file/path metadata or changing files outside the identity's grants.

IDE file operations use the same project permission checks. Tunnels and computer-use are separate capabilities.

## Administration

Use the desktop app's Access & Permissions page:

1. Select a project share.
2. Register a client identity.
3. Select the identity in the Connected user / AI dropdown.
4. Set root permissions.
5. Use Choose file / folder to add per-path overrides.
6. Save the policy.
7. Revoke identities that are no longer trusted.

## Connection approval status

The legacy /api/connections and /api/sessions endpoints support administrator-created pending records and administrator approval/denial. They are not a client-initiated approval handshake and are not wired to project token issuance. Windows Hello, platform passkeys, biometric confirmation, authenticator-app TOTP and trusted-device auto-accept remain unimplemented.
