"""Insert the Universal HTTP Gateway (Route B) section into README.md at the API reference / Security notes boundary."""
from pathlib import Path

p = Path("C:/CreoDevo/SF2AIS/README.md")
text = p.read_text(encoding="utf-8")

marker = "- `GET /probe/download?token=...` — download the legacy Python probe script"
section = '''
## Universal AI/Human HTTP Gateway (Route B — complete)

A standards-based HTTP bridge that allows authorised AI clients and human users to work with approved computers, files, development environments and applications — without relying on MCP.

The gateway enforces, on every request:

- **Independent client identities** — each connecting client has its own identity, credential, permission set and audit history.
- **Share-scoped permissions** — a client can read a project but not edit it, edit files but not run commands, and only access its approved workspace.
- **Sandboxed CLI** — commands run in an isolated container; host PowerShell/CMD is never invoked by a client.
- **Real-time monitoring** — live connection and session monitor across all humans and AIs.
- **Collaborative file protection** — per-file edit locks, lock renewal and expiry, and a recent-edit warning window to prevent two AIs from overwriting each other.

### Connection lifecycle

1. **Discovery** — the client reads `/api/connections/discover` (machine-readable manifest + safe HTML).
2. **Request** — the client submits identity, client type, capabilities, workspace, purpose and duration. A pending request appears in the desktop notification queue.
3. **Approval** — the owner approves or denies under the configured authentication policy (biometric / passkey-FIDO2 / device / None-with-ACCEPT). Denied clients can be blacklisted.
4. **Session** — on approval the client creates a session and receives the initialisation package.
5. **Acknowledgement** — the client acknowledges the SF2AiSLaw (`/api/sessions/{id}/ack`) before tool use.

### Universal gateway routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/connections/discover` | Safe discovery page + connection manifest |
| POST | `/api/connections` | Create a pending connection request |
| POST | `/api/connections/{id}/approve` | Approve (owner) |
| POST | `/api/connections/{id}/deny` | Deny; optionally blacklist |
| GET | `/api/sessions/{id}` | Initialisation package |
| POST | `/api/sessions/{id}/ack` | Acknowledge the SF2AiSLaw |
| GET | `/api/capabilities` | Tool and skill registry, access types |
| GET | `/api/capabilities/tools/{id}/schema` | Tool input schema |
| GET | `/api/capabilities/skills` | Discoverable skills |
| GET | `/api/files/locks` | File edit locks |
| POST | `/api/files/locks` | Acquire a file lock |
| DELETE | `/api/files/locks/{path}` | Release a lock |
| GET | `/api/monitor/sessions` | All sessions |
| GET | `/api/monitor/events` | Chronological event feed |

### Documented in this project

- `SF2AiSLaw.md` — mandatory operational and security rules every AI client must read and acknowledge.
- `HTTP API Reference.md`, `Connection Protocol.md`, `Authentication Guide.md`, `Tool Registry.md`, `Skill Registry.md`.
- `SECURITY.md`, `Product Roadmap.md`, `Product Phase todo.md`, `audit.md`.

After implementation, the standard test cycle (set out in `Test Plan.md`) was run and all backend and smoke tests passed. This is the production interface for any HTTP-capable AI client; the desktop Electron app and the web UI are mirrored against it.
'''


if marker not in text:
    print("ERROR: marker not found in README.md")
else:
    # Replace the first occurrence of the marker + the blank line after it with the marker, the new section, and the following security notes heading.
    # The marker is followed by two newlines (blank line) then "## Security notes".
    anchor = marker + "\n\n## Security notes"
    replacement = marker + "\n" + section + "\n\n## Security notes"
    new_text = text.replace(anchor, replacement, 1)
    if new_text == text:
        print("ERROR: anchor not replaced (anchor may not exist)")
    else:
        p.write_text(new_text, encoding="utf-8")
        print("Inserted universal gateway section. New README line count:")
        print(len(new_text.splitlines()))
