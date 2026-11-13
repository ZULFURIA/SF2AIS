# SF2AiS — Security Documentation

_Sf2AiS (Secure Files to AI Server)_ — password-protected, self-hosted bridge that lets
web-browsing AI chatbots (ChatGPT, Claude, Gemini, Copilot, etc.) securely read, write and
interact with an authorised local workspace. No API keys or MCP support required on the
AI client's side.

---

## 1. Security model overview

Sf2AiS is an **authenticated local gateway**. It does **not** expose the local machine to
the public internet by default, and it never grants arbitrary filesystem or shell access.

Every request is scoped to one of:

| Scope | Who | What it can do |
|---|---|---|
| **Admin** | Dashboard login (you) | Manage shares, clients, permissions, network, tunnels, audit |
| **Legacy share login** (Basic) | Existing legacy share-specific username + password | Backward compatibility only; new desktop-created project shares disable Basic authentication |
| **AI client token** (`X-Sf2AiS-Token`) | Per-identity, revocable credential | Project-root and per-path Read/Write/Upload/Download/Deny rules plus separately granted capabilities |

**Deny-by-default is the default for new AI identities.** A newly registered identity has no project-file access until an administrator grants it. Read, Write, Upload and Download are independent. Deny overrides inherited path grants. The share-level Workspace write switch is an additional master gate for writes/uploads. CLI and tunnel are off by default; Git mutation scopes are independently granted and require explicit confirmation.

---

## 2. Authentication & credential handling

### Administrator and legacy share passwords
- The administrator password is stored as a bcrypt hash (`$2b$` via passlib). The legacy plaintext value is transparently upgraded to bcrypt after a successful login.
- Password policy is enforced on administrator account creation.
- Existing legacy shares may retain their Basic-auth credentials for backward compatibility. New desktop-created project shares do not create or expose a shared folder password and reject Basic authentication.

### Client tokens (`X-Sf2AiS-Token`)
- Generated per client on the dashboard. Shown **once**, then never shown again.
- Stored **only as SHA-256 hashes** on the server.
- Each token has an independent project-access policy: `read`, `write`, `upload`, `download`, `deny`, and relative path rules. New tokens start with every project permission disabled.
- Non-file capabilities such as `CLI`, `IDE`, `tunnel`, `Git stage`, `Git commit`, `Git push` and computer-use scopes are separate.
- **Revocation** invalidates the token immediately; any request with a revoked token is
  rejected (401). Revoking a token, disabling CLI for a share, or deleting a share closes
  associated CLI sessions.

### What is never exposed to renderer/JavaScript
- No administrative credentials or writable secrets are placed in renderer JavaScript.
- The admin password hash, legacy share password hashes and client token hashes live in `data/config.json` (gitignored) and are processed server-side only. New desktop-created shares do not store a share password hash.

---

## 3. Path & privilege enforcement (server-side)

Every filesystem operation is validated **server-side**:

- **Containment**: the resolved path must stay inside the authenticated share's folder. `..` traversal, absolute paths outside the share, and symlink targets escaping the share are rejected (403 / 404).
- **Per-identity path policy**: every supported browse/read/write/move/delete/upload/download operation checks the AI identity's effective rights for the requested relative path. Root rights are inherited; explicit path rules override individual rights; Deny on an ancestor or target blocks the path and descendants.
- **Separate file actions**: Read, Write, Upload and Download are independently checked. Upload is not implied by Download, and Download is not implied by Upload.
- **Protected paths**: sensitive paths (`.env*` files, `.git`, `node_modules`,
  virtual environments, `data/**/config.json`, private keys, credentials) are excluded from
  exposure and write targets.
- **Dotfiles**: `GET /files/download/.env` and similar are rejected (403).
- **Cross-origin writes**: `PUT /api/workspace/file` with a non-matching `Origin` is rejected (403). AI token writes and uploads require both the share-level `workspace_write_enabled` master switch and the matching per-identity permission for the requested path.
- **CLI sandbox**: CLI only runs inside an isolated Docker container with the network disabled, a read-only root filesystem, dropped capabilities, `no-new-privileges`, and PID/memory/CPU/fd limits. Host-shell execution is removed. Because commands can access the entire mounted project, AI identities with path-specific rules or partial file permissions are not allowed to use CLI.
- **Git scope**: repository-wide Git operations are blocked for identities with path-specific overrides.

### What the sandbox does **not** do
- It is **not** a substitute for choosing a narrowly-scoped share. A share must point to a
  project directory, not a drive root or broad company root.
- Container isolation is defence in depth, not a perfect boundary.

---

## 4. Forbidden operations (rejected server-side)

| Attempt | Result |
|---|---|
| Read/write outside approved share | 403/404 |
| Path traversal (`../outside.txt`) | 403/404 |
| Read a protected file (`.env`, `.git/...`) | 403/404 |
| Read/write/upload/download outside the identity's granted path policy | 403 |
| Write through a read-only client | 403 |
| Upload without Upload permission | 403 |
| Download without Download permission | 403 |
| Use Deny-blocked path | 403 |
| Use CLI with path-specific rules | 403 |
| Use Git with path-specific rules | 403 |
| Change a client's own permissions | not allowed (admin only) |
| Terminal command escaping sandbox | prevented by Docker isolation |
| Arbitrary admin or host PowerShell | disabled by design |
| Cross-origin state change | 403 |
| Unisolated tunnel without explicit consent | 403 |

---

## 5. Audit logging

Every authenticated operation appends a minimal, immutable-seeming JSONL record to
`data/audit.jsonl` (rotated at 10 MB). Records contain action, share, client identity,
remote IP, path, and a detail dict. **Credentials and file contents are never logged.**

Example record: `{"at": "...", "action": "workspace.list", "share_id": "...", "client_id": "..."}`

The admin audit endpoint (`GET /api/desktop/activity`) returns the audit trail.

---

## 6. Network & remote exposure

- **Localhost only by default.** The dev server binds to `127.0.0.1:8000`.
- **Remote authenticated requests require HTTPS.** Plain HTTP is rejected for remote
  authenticated API requests and IP-probe updates (426). Use a trusted TLS reverse proxy
  and set `SF2AIS_TRUSTED_PROXY_IPS` to its IPs.
- **Automatic port mapping** (UPnP/NAT-PMP/PCP) is opt-in and only for the explicit remote
  allowlist. Discovery never creates router rules or stores credentials.
- **Outbound relay** (Cloudflare Tunnel) is optional, administrator-approved, and no
  better than a manual reverse proxy for a two-day session.
- The **probe app** reports its public IP to the gateway; it never sends file contents or
  credentials.

### Connection rules (for AI clients)
- New desktop-created project shares: issue an AI client token from the administrator interface and send it in the `X-Sf2AiS-Token` header to the workspace API.
- Existing legacy shares may continue to accept their pre-existing Basic-auth credentials until migrated. New project shares disable Basic authentication.
- **Never** expose the backend to the public internet without explicit administrator
  approval and a secure deployment design (TLS, firewall allowlist, observability).

---

## 7. Electron desktop app (SF2AiS Secure AI Workspace)

- Source: `probe-app/` (Electron).
- The tray app monitors the public IP and reports it to the gateway; it holds no
  credentials in plaintext (admin secret is encrypted with `safeStorage`).
- The app connects to the **local backend** at the gateway URL configured in the probe.
- Never enable remote computer-use/control from the desktop UI without explicit consent
  and a verified, scoped session.

---

## 8. Threat model & known limitations

- **CUA/computer-use**: the CUA MCP bridge is private (stdio), deny-by-default, and bound
  to the authenticated share. It is **not** a remote browser to the public internet, and
  no provider is claimed available or authorized until a user explicitly enables and
  starts a session. Live screen observation/actions require explicit user consent.
- **Docker sandbox** is not a VM; host escape via the container runtime is out of scope.
- **mDNS/UPnP/relay** are convenience; they are opt-in and never required for local use.
- **Windows native firewall** rules are scoped to the alias IP + port + remote allowlist
  in isolation mode, but only when native support and an explicit alias are chosen.
- **Probe token / DuckDNS token** are stored in `data/config.json` (gitignored) and
  exported by the probe script; treat them as sensitive.
- **SSL/TLS termination** is the operator's responsibility (reverse proxy / Caddy).
