# SF2AiS Security Architecture

## Threat model

SF2AiS protects selected local project folders from hostile or misconfigured AI/user clients. It assumes clients may try to exceed their grants, traverse outside the share, reuse another identity's token or invoke alternate routes to bypass the interface.

The model does not protect against a fully trusted administrator with physical access or compromise of the host operating system.

## Core properties

### 1. Separate administrator and client authentication

- Management routes require administrator authentication.
- Each AI/user identity receives its own random bearer token.
- The server stores only a SHA-256 token hash.
- New desktop-created project shares disable legacy HTTP Basic authentication.
- Existing legacy shares may continue to accept Basic authentication until migrated.

### 2. Deny-by-default project access

A newly registered identity receives no project-file permissions. The administrator must explicitly grant rights for the project root or a path override.

Read, Write, Upload and Download are separate actions. A grant for one does not imply another.

### 3. Path inheritance and Deny precedence

Project access rules use relative paths under the share root. Unspecified rights inherit from the nearest parent/root policy. A path rule may explicitly grant or remove an action.

Deny on the root, an ancestor or the target path blocks access to that path and all descendants. A more-specific allow does not override an ancestor Deny.

### 4. Server-side enforcement

The backend enforces the policy on supported workspace and IDE operations, browser workspace operations, uploads and downloads. UI controls are only an administrative convenience and are not the security boundary.

Path traversal, absolute paths outside the share, symlink escape and protected system paths are rejected.

### 5. Capability separation

CLI, IDE, Git, tunnels and computer-use scopes are separate from file permissions.

CLI can access the entire mounted project, so it is blocked for identities with path-specific rules or partial root permissions. It requires unrestricted root Read, Write, Upload and Download.

Git operations are repository-wide and are blocked when path-specific rules exist.

### 6. Credential protection

- Administrator password: bcrypt hash in runtime configuration.
- Client token: SHA-256 hash in runtime configuration; plaintext shown once.
- Desktop administrator credential: stored through operating-system secure credential storage.
- Tokens, passwords and file contents must never be written to audit logs.

### 7. Audit and revocation

Operations record action, share, client identity, remote address and path metadata. A client token can be revoked immediately. Revocation also closes associated terminal sessions.

### 8. Network boundaries

- Uvicorn should bind to loopback behind a TLS reverse proxy.
- Remote authenticated requests require HTTPS.
- Do not expose the backend port directly to the public internet.
- Router discovery is read-only. Port mapping requires explicit administrator confirmation.
- External reachability must be tested from an independent network.

## Known limitations and planned work

- A legacy administrator-managed connection/session API exists, but its requests and approvals require administrator authentication and it is separate from per-project client-token issuance. Windows Hello, platform passkeys, biometric confirmation, TOTP authenticator apps, recovery codes and trusted-device auto-accept are not integrated.
- CLI is intentionally incompatible with granular path restrictions because a shell can traverse the mounted project.
- Git operations are intentionally incompatible with path overrides because repository-wide metadata can reveal paths beyond an individual file grant.
- TLS certificates, DNS, firewall rules and router configuration remain deployment responsibilities.
- Docker isolation is defence in depth, not a substitute for a narrow project share.
