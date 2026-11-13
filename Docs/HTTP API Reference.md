# HTTP API Reference

**SF2AiS universal gateway** — standards-based HTTP interface.
Base URL: the SF2AiS HTTP address (e.g. `http://127.0.0.1:8000` locally).

All authenticated routes require an `Authorization: Basic <base64(admin:password)>` header for admin operations. Client-scoped routes use an approved share and a token bound to a session.

## Server discovery

| Method | Path | Description |
|---|---|---|
| GET | `/api/connections/discover` | Safe HTML discovery page + machine-readable connection manifest. |

## Connection management

| Method | Path | Description |
|---|---|---|
| POST | `/api/connections` | Create a pending connection request. |
| GET | `/api/connections` | List connections. |
| GET | `/api/connections/{connection_id}` | Connection detail. |
| POST | `/api/connections/{connection_id}/approve` | Approve (owner). |
| POST | `/api/connections/{connection_id}/deny` | Deny (owner). |
| POST | `/api/connections/{connection_id}/status` | Update status (renderer/admin). |

Request body (`/api/connections`): `client_type`, `client_app`, `client_version`, `identity`, `identity_verified`, `client_credential`, `capabilities`, `workspace`, `purpose`, `duration_seconds`.

## Session lifecycle

| Method | Path | Description |
|---|---|---|
| POST | `/api/sessions` | Create a session for an approved connection. |
| GET | `/api/sessions/{session_id}` | Session initialisation package. |
| POST | `/api/sessions/{session_id}/ack` | Acknowledge SF2AiSLaw. |

## Capability discovery

| Method | Path | Description |
|---|---|---|
| GET | `/api/capabilities` | Capabilities summary. |
| GET | `/api/capabilities/tools` | Tool registry. |
| GET | `/api/capabilities/tools/{tool_id}/schema` | Tool input schema. |
| GET | `/api/capabilities/skills` | Skill registry. |
| GET | `/api/capabilities/workspaces` | Approved workspaces. |
| GET | `/api/capabilities/access-types` | Access methods. |
| GET | `/api/capabilities/system` | System capabilities. |

## File locking

| Method | Path | Description |
|---|---|---|
| GET | `/api/files/locks` | List locks held by this client. |
| POST | `/api/files/locks` | Acquire a file edit lock. |
| DELETE | `/api/files/locks/{file_path:path}` | Release a lock. |
| POST | `/api/files/locks/{file_path:path}/renew` | Renew a lock expiry. |

## Live monitoring

| Method | Path | Description |
|---|---|---|
| GET | `/api/monitor/sessions` | List sessions. |
| GET | `/api/monitor/events` | Event feed (polled). |
| GET | `/api/monitor/events/stream` | SSE fallback stream. |
| POST | `/api/monitor/events` | Record a monitor activity event. |

## Shared routes (existing SF2AiS)

`/api/desktop/`, `/api/ip-update`, `/api/relay/status`, `/api/network/status`, `/api/computer-use/`, `/api/ide/`, `/api/workspace/`, `/api/status`, `/api/audit`, `/api/connections/{id}/status`.

## Error conventions

- `400` — malformed request / unrecognised parameter.
- `401` — unauthenticated or invalid credentials.
- `403` — authenticated but permission denied.
- `404` — resource not found.
- `409` — state conflict (e.g., session already initialised, connection not approved).
- `423` — resource locked by another client.
- `426` — remote plaintext HTTP; HTTPS required.
- `429` — rate limited.
- `500` — server error (no internal details).

## Authentication headers

| Header | Purpose |
|---|---|
| `Authorization: Basic ...` | Admin authentication for management routes. |
| `X-Sf2AiS-Session` | Current session identifier (file locks, etc). |
| `X-Sf2AiS-Identity` | Client display identity (file locks, etc). |

## Request size limits

The backend enforces a maximum request body size to prevent oversized-payload abuse.


## Project identity and granular file permissions (current)

### Create a project share

POST /api/desktop/shares is an administrator-authenticated operation. The desktop client sends the server-side folder path and share-level capability toggles. It no longer asks for a shared folder username/password. New desktop-created shares set legacy_auth_disabled=true and accept individual AI client tokens only.

Example body:

```json
{
  "folder": "D:/Projects/CreoDevo",
  "workspace_write_enabled": true,
  "cli_enabled": false,
  "ide_enabled": true,
  "tunnel_enabled": false
}
```

### Register a connected AI/user identity

POST /api/desktop/shares/{share_id}/clients creates a unique identity and returns the raw bearer token once. The server stores only the token hash. New identities have all project-file permissions disabled.

### Browse a project tree as administrator

GET /api/desktop/shares/{share_id}/tree?path=relative/path returns a one-level server-side listing for the administrator's file/folder picker. Paths are relative to the selected share root.

### Save per-identity project permissions

PATCH /api/desktop/shares/{share_id}/clients/{client_id}/project-access

Example body:

```json
{
  "project_access": {
    "read": true,
    "write": true,
    "upload": true,
    "download": true,
    "deny": false,
    "rules": [
      {
        "path": "Documentation",
        "read": true,
        "write": false,
        "upload": false,
        "download": true,
        "deny": false
      },
      {
        "path": "Private",
        "deny": true
      }
    ]
  }
}
```

Root fields are booleans. Path rules use relative paths and may set any subset of Read, Write, Upload, Download and Deny. Unspecified action values inherit from the nearest parent/root policy. An explicit Deny on any ancestor or the target path blocks that path and descendants. Duplicate paths, absolute paths, traversal segments and protected system paths are rejected.

The share-level Workspace write switch remains a master gate for Write and Upload. The client must also have the corresponding project permission.

### Client request header

AI clients authenticate using:

```http
X-Sf2AiS-Token: <per-client-token>
```

A valid token authenticates the identity; it does not imply file access. The server checks the requested path and action on each supported workspace/IDE operation, browser file operation, upload and download.

### Permission matrix

| API operation | Required project permission |
|---|---|
| GET /api/workspace/tree | Read on requested directory; returned entries are filtered by Read |
| GET /api/workspace/file | Read on file |
| PUT /api/workspace/file | Write on file |
| POST /api/workspace/directory | Write on new directory |
| POST /api/workspace/move | Write on source and destination |
| DELETE /api/workspace/path | Write on target |
| POST /api/workspace/upload | Upload on destination |
| GET /api/workspace/download | Download on file |

CLI requires unrestricted root Read, Write, Upload and Download and no path overrides because shell commands can access the mounted project as a whole. Repository-wide Git operations are blocked when path-specific rules exist.
