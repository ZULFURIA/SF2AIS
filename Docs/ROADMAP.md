# SF2AiS — Product Roadmap

_Last updated: 2026-11-13_

## Current implementation status (2026-11-13)

- Per-project AI/user client identities use individual revocable tokens; new desktop-created shares disable shared Basic-auth credentials.
- New identities default to no project-file access. Root Read/Write/Upload/Download/Deny and relative file/folder overrides are saved per identity and enforced by the server.
- Upload and Download are independent. Deny on an ancestor or target path blocks descendants.
- CLI requires unrestricted root permissions with no path rules; repository-wide Git operations are blocked while path overrides exist.
- The legacy administrator-managed connection/session API remains separate from the project-token permission model. Passkey, biometric and authenticator-app approval are not integrated.

SF2AiS is evolving from a secure file bridge into an HTTP Remote Workbench:
browser-based AI clients and ordinary HTTP clients can work with an authorised
local project without MCP or provider-specific integrations.

## DONE

- Guided setup, admin account, project-share registration and networking modes. New desktop-created shares are token-only; legacy Basic-auth shares remain compatible.
- Password hashing, per-share CLI/tunnel switches and dashboard management.
- Browser-native /workbench with project tree, UTF-8 editor, binary upload and
  download, directory creation, deletion, command-job interface, Git status/diff, branch/history inspection, and browser controls for scoped Git stage, staged review, commit and HTTPS push; share-scoped API also supports separately granted Git stage, commit
  and HTTPS push operations with confirmation and audit records.
- Share-scoped HTTP workspace API for tree, read, write, upload, download,
  move, delete and directory creation.
- Path traversal and symlink checks; protected secret paths and directories;
  bounded text/file sizes; atomic text/binary writes.
- Separate AI client tokens, shown once and stored as SHA-256 hashes. New identities start with no file access. Per-identity Read/Write/Upload/Download/Deny rights and relative file/folder overrides are enforced server-side; tokens remain individually revocable.
- Metadata-only JSONL audit trail and admin audit endpoint.
- Request origin checks, browser security headers, no-store API responses,
  per-IP failed-login throttling and HTTPS enforcement for remote authenticated
  requests and probe updates.
- Docker-only CLI runner with host-shell fallback removed. Jobs run in a
  bounded, no-network container with a read-only container root, dropped
  capabilities, no-new-privileges and PID/memory/CPU/file descriptor limits.
- Secret-filtered temporary workspace snapshots for CLI: common secret files,
  .git, node_modules and virtual environments are not mounted in the container.
  New/changed/deleted safe files are synchronised back.
- Docker sandbox image and Windows/macOS/Linux build scripts.
- Dockerfile now includes the Python modules, DDNS helper and static assets.
- Tests cover workspace path security, API authorization, upload/download,
  Git inspection and scoped write workflows, AI token scopes/revocation, audit
  output and sandbox policy.

## IN PROGRESS

- Live Docker Engine and sandbox image validation on the Firefly. The Docker
  CLI is installed, but the Docker Engine was not running during this phase.
- End-to-end verification of the browser Workbench through a real TLS reverse
  proxy and an external browser-only AI client.
- Audit/fix pass across the legacy setup wizard, UPnP tunnel lifecycle,
  Electron Probe installer and cross-platform packaging.

## REMAINING DEVELOPMENT

- Persistent interactive terminal sessions, stdin support, process control and
  streaming output. Current CLI interface is asynchronous one-shot jobs with
  polling.
- Windows-native isolated execution. Current secure CLI runner uses Linux
  containers through Docker Engine; Windows PowerShell/CMD host execution is
  intentionally disabled.
- Cross-platform isolation backends for native Linux and macOS installations.
- Outbound relay service/agent for machines behind CGNAT or restrictive routers.
  This needs a reachable relay host or managed relay infrastructure; UPnP is
  not a reliable substitute.
- Optional, administrator-approved network access for sandbox package
  installation. The current default is no network to prevent workspace
  exfiltration.
- Expanded Git workflows with separately scoped staging, commit and push API actions. Each mutation requires an explicit confirmation field, is audit logged, and is unavailable to Basic share credentials. Live remote push verification remains pending.
- Persistent job/session storage, distributed rate limiting and operational
  metrics for multi-worker deployments.
- Automated integration tests against Docker Engine, Linux/macOS hosts and
  real reverse-proxy deployments.

## SECURITY NOTES

- A share should point to a project directory, not an entire drive or broad
  company root. Protected-path filtering is defence in depth, not a substitute
  for least-privilege share selection.
- Workspace writes are read-only by default and must be enabled per share.
- Remote Basic/API-token requests require HTTPS unless the administrator
  deliberately overrides the policy. Configure a trusted TLS reverse proxy.
- CLI remains unavailable unless Docker Engine and the approved image are
  verified. Never mount the Docker socket inside a sandbox.
- Docker container isolation is defence in depth, not a perfect boundary.
- The Firefly current share root is C:\CreoDevo; narrow this to individual
  project roots before granting external AI clients access.

## 2026-11-10 — Remote Workbench development update

Implemented in the current development branch:

- Persistent isolated line-oriented shell sessions over ordinary HTTP:
  - `POST /cli/sessions` creates a session.
  - `POST /cli/sessions/{id}/input` sends stdin.
  - `GET /cli/sessions/{id}/output` returns bounded incremental output.
  - `DELETE /cli/sessions/{id}` stops the container and synchronises the safe workspace snapshot.
- Sessions are scoped to the exact share login or AI-client token that opened them. Revoking a token, disabling CLI for a share, or deleting a share closes associated sessions.
- Limits: two sessions per share, four globally, 30-minute idle timeout, four-hour maximum lifetime, 20 KB input and 200 KB retained output.
- Interactive Workbench terminal now uses the persistent HTTP session API. The shell is line-oriented and does not emulate a PTY; full-screen terminal applications are not supported.
- Replaced hard-linked CLI snapshots with independent copies. This prevents sandbox file edits from modifying original host files before controlled synchronisation.
- Docker application image now includes `terminal_sessions.py`.
- Automated tests cover terminal ownership, lifecycle, input/output cursors, bounded output, isolated shell arguments, and snapshot independence.

Not yet verified on the Firefly: live Docker execution. Docker Desktop's engine was unavailable during this phase. The persistent terminal must be exercised against a running Docker Engine before enabling CLI for remote clients.

Next planned development: outbound HTTPS relay support for CGNAT environments, followed by live end-to-end browser-client tests and the full security/stability audit.
Outbound relay development:
- Added an optional native Cloudflare Tunnel supervisor for remotely managed tunnels.
- Uses `SF2AIS_CLOUDFLARED_TOKEN` from `.env`, passes it through `TUNNEL_TOKEN` in the child environment (not process arguments), redacts it from logs, retries failures, and stops on graceful application shutdown.
- Added admin relay status endpoint `/api/relay/status` and dashboard guidance for CGNAT deployment.
- Live connection is not yet verified because no Cloudflare tunnel token or cloudflared installation is configured on this Firefly.
- Added no-JavaScript persistent terminal forms under `/browse/terminal` (start, input, refresh and close), so browser-only AI clients can use a continuing shell without needing to execute JavaScript or call the JSON API directly.

## Network connectivity manager — implementation progress (2026-11-10)

- [x] SSDP multicast discovery for UPnP IGD; mDNS DNS-SD advertisement for the Sf2AiS HTTPS endpoint.
- [x] Non-mutating capability probes for UPnP IGD, NAT-PMP and PCP v2.
- [x] Explicit-consent TCP forwarding to the configured LAN HTTPS reverse proxy only.
- [x] Bounded temporary leases, administrator removal, audit events and background renewal.
- [x] PCP MAP nonce persistence and reuse for renewal/removal.
- [x] Router discovery URL/control endpoint pinned to the SSDP responder to reduce LAN SSRF risk.
- [x] TLS handshake check before creating or renewing a router mapping.
- [x] WAN/public address comparison for likely CGNAT and upstream/double NAT diagnosis.
- [x] One-time, ten-minute external HTTPS verification challenge, opened from a separate network; success is only recorded for a globally routable client address.
- [x] Manual router fallback with a direct local router link and safe forwarding instructions; router credentials remain outside Sf2AiS.
- [ ] Live compatibility tests against physical UPnP, NAT-PMP and PCP routers.
- [ ] External verification from a separate mobile network and production reverse-proxy domain.
- [ ] Vendor-specific guided router setup profiles.
- [ ] Comprehensive security/stability audit after feature development is complete.

Automatic mapping remains opt-in. Discovery and diagnostics never create router rules. No router admin credentials are requested or stored. External reachability is not inferred from a successful mapping response.

## Workspace permissions and IDE integration — 2026-11-10

- [x] Separate share-level and AI-client-token IDE permissions; default disabled.
- [x] Separate optional computer-use consent flag; no CUA provider is enabled or claimed available.
- [x] Scoped IDE API for directory listing and UTF-8 text read/write/create/move/delete; every operation stays inside the authenticated share.
- [x] VS Code virtual-workspace extension prototype using X-Sf2AiS-Token and VS Code SecretStorage.
- [x] Desktop app navigation to the server permission console and VS Code setup guide.
- [ ] Package/sign the VS Code extension and test in an installed VS Code host.
- [ ] Add supported CUA provider integration only after provider identity, capability boundaries and user consent are defined.
- [ ] Validate IDE API against a live test share and verify write-denial behavior for read-only tokens.
- [ ] Full end-to-end sandbox CLI test requires Docker Engine to be running.

## CUA Driver integration — 2026-11-10

- [x] Retrieved upstream CUA source and recorded revision/license provenance.
- [x] Added private stdio-MCP bridge with no public CUA listener.
- [x] Added bounded capability manifest and deny-by-default CUA tool policy.
- [x] Added authenticated HTTP session, observation and action routes.
- [x] Bound sessions to share/client identity; token revocation and share disable close sessions.
- [x] Added separate share-level and token-level observation/control grants.
- [x] Added desktop UI explanation and frontend permission controls.
- [ ] Complete Windows source build and verify actual CUA MCP tool schemas.
- [ ] Run live CUA desktop observation and action tests only after explicit user session consent.
- [ ] Add app-launch scopes and optional visual-perception extension only after separate review.

### CUA runtime verification update

- [x] Pinned source submodule to upstream release tag cua-driver-rs-v0.46.1 (commit 93c9b500a0d4f9daa56063d3d3e3fb3c9e6070ee).
- [x] Downloaded the official Windows x64 runtime and verified the archive SHA-256 before extraction.
- [x] Confirmed CUA Driver doctor: attached interactive desktop, UI Automation COM initialization, and visible window enumeration.
- [x] Confirmed private MCP initialize/tools-list under bounded permissions; 17 allowlisted tools and no network listener.
- [x] Disabled CUA telemetry in the isolated Sf2AiS runtime home.
- [x] Confirmed the API reports the provider as installed while keeping computer use disabled for the test share.
- [ ] Source compilation on this Firefly is blocked by missing Visual Studio MSVC Spectre-mitigated libraries; use the checksum-verified official binary until that build component is installed.
- [ ] Do not run live screen observation or mouse/keyboard actions until a user explicitly enables and starts a CUA session.

### End-to-end sandbox test share

- [x] Created local sf2ais-test share at test-share with a minimal Node.js application.
- [x] Built sf2ais-workbench:latest with Docker Desktop Engine 29.9.2.
- [x] Ran node app.js inside the Docker sandbox; the app wrote and read back its marker successfully.
- [x] CLI-only test: sandbox changes were discarded because Write was not granted.
- [x] CLI + Write test: successful job synced sandbox-output.txt back into the test share.
- [x] The VS Code extension source and IDE API routes are present; the extension has not yet been launched in a VS Code host on this machine.
