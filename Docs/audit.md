# SF2AiS — Audit Trail

SF2AiS records a minimal, JSONL audit trail of all authenticated operations. This document
describes where it lives, its format, what is and is not captured, and how to rotate or
inspect it.

---

## 1. Location and rotation

- **Path**: `data/audit.jsonl` (absolute location depends on `CONFIG_PATH`).
- **Rotation**: when the file exceeds **10 MB**, the oldest record is rotated to
  `data/audit.jsonl.1` (one generation kept; the old file is unlinked).
- **Locking**: a per-file `AUDIT_LOCK` is held while writing, so concurrent writers cannot
  corrupt the log.
- The log file is **not** part of version control (`data/audit.jsonl*` is in `.gitignore`).

## 2. Record format

Every record is one JSON object per line:

```json
{
  "at": "2026-11-10T19:23:41.123456",
  "action": "workspace.list",
  "share_id": "4e418852-686b-44a7-b822-bee84543d182",
  "share_username": "creodevo",
  "client_id": "<client-token id, if an AI client token was used>",
  "client_name": "AI client name",
  "remote_ip": "192.168.1.50",
  "path": "/api/workspace/tree",
  "detail": {}
}
```

- `action`: a string taken from a fixed vocabulary — `admin.login`, `share.login`,
  `workspace.list`, `workspace.read`, `workspace.write`, `workspace.upload`, `workspace.move`,
  `workspace.delete`, `cli.job.start`, `cli.job.complete`, `cli.session.open`,
  `cli.session.close`, `client.create`, `client.revoke`, `tunnel.open`, `tunnel.close`,
  `router.map`, `router.unmap`, `admin.audit`, and others as the app grows.
- `share_id` / `share_username`: the project share the operation was scoped to. For new token-only shares, `share_username` is a display label, not a shared login.
- `client_id`: the AI-client token id (when a token, not a share login, opened the
  operation). Absent for share-logins.
- `client_name`: human-readable label for the client (e.g. "ChatGPT browser").
- `remote_ip`: the peer that made the request.
- `path`: the request path or operation key.
- `detail`: structured, operation-specific context. **Never contains passwords, tokens,
  file contents, or secrets.**

## 3. What is intentionally NOT logged

- **Credentials** — administrator passwords, legacy share passwords and client tokens are never written to the audit log. New desktop-created shares do not use shared folder passwords.
- **File contents** — read/write/upload payloads are not stored in the audit log.
- **Full command output** — CLI stdout/stderr is bounded and not persisted to the audit
  log.

## 4. Inspect the audit trail

The admin audit endpoint (`GET /api/desktop/activity`) returns the audit trail.
`GET /api/status` reports the server health.

Example (administrator authentication required):

```bash
curl -u "admin:<password>" http://127.0.0.1:8000/api/desktop/activity
```

The file can also be inspected directly:

```bash
tail -n 50 data/audit.jsonl
jq -s length data/audit.jsonl   # number of records
```

## 5. Security notes

- The audit log is **append-only** from the application's perspective; it is not a
  tamper-proof system audit. Treat it as an operational record, not a legal-grade log.
- Rotate it if it grows beyond 10 MB; monitor its size in production.
- Keep write access to `data/` restricted; the log chain can be bypassed only if an
  attacker compromises the server process itself.

## 6. Clean shutdown and recovery

- On graceful shutdown (SIGINT/SIGTERM), the server completes in-flight writes and exits
  cleanly. Background tasks (Cloudflare relay, mDNS, IP probe) are stopped.
- On unexpected exit, the next start re-creates `audit.jsonl` if missing and continues the
  append-only stream.

## 7. Test coverage for audit behaviour

`tests/test_workspace_api.py` (`test_workspace_operations_write_jsonl_audit_events`)
asserts that a workspace listing produces exactly one audit record with the correct action
and without leaking content.
