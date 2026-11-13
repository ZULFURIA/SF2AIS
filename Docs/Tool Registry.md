# Tool Registry

SF2AiS publishes a centrally managed, permission-filtered tool registry via the capability API. A tool is **discoverable** but never executes unless the client's permissions allow it.

## Tool registry

| Tool ID | Name | Category | Level |
|---|---|---|---|
| `fs_read` | Read file | filesystem | read |
| `fs_write` | Write file | filesystem | write |
| `fs_metadata` | File metadata | filesystem | read |
| `fs_move` | Move file | filesystem | write |
| `fs_delete` | Delete file | filesystem | write |
| `cli_execute` | Execute command | cli | execute |
| `cli_list_jobs` | List CLI jobs | cli | read |
| `ide_tree` | Project tree | ide | read |
| `ide_file` | Read file | ide | read |
| `git_status` | Git status | git | read |
| `git_diff` | Git diff | git | read |
| `git_stage` | Git stage | git | write |
| `browser_status` | Browser status | browser | read |
| `desktop_status` | Desktop status | desktop | read |
| `service_status` | Service status | services | read |

## Tool schema

Each tool has a JSON schema describing its inputs and outputs:

- `GET /api/capabilities/tools/{tool_id}/schema`

Supported tools include filesystem operations, CLI sandbox execution, IDE file/project access, git inspection, browser status, desktop status, and service status.

## Permission enforcement

The backend enforces every tool independently of the client's instructions:

- The tool must be enabled in the client's capability set.
- The permission level must be sufficient (e.g., `fs_write` requires `read-write`).
- The target must be inside the approved share.
- Destructive operations require separate authorization where configured.

## Warning

A tool registry entry never grants permission. The backend is authoritative.
