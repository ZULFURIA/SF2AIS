# SF2AiS — Recovery and Completion Status

**Date:** 2026-11-12
**Workspace:** `C:\\CreoDevo\\SF2AIS`
**Branch:** `main`
**Status:** In progress — this document supersedes older completion claims where they conflict with the evidence below.

## 1. Execution baseline

- Desktop Commander connected to `MasterFireFly-nb` (device `dd8546b6-4797-4c81-8c2a-0163f2916ca2`).
- Windows x64; Node.js 26.12.1; Python 3.12.10; Desktop Commander 0.3.2.
- Repository remote: `https://github.com/ZULFURIA/SF2AIS.git`.
- Branch `main` was already dirty before this recovery pass, with numerous modified, staged, deleted and untracked files. Those existing changes were preserved.
- No commit, push, reset, checkout, rebase, or cleanup was performed.
- After the machine reboot, the old PID file was stale and no process was listening on port 8000. The backend was started successfully from the project environment: `.venv-cua\\Scripts\\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1`.
- Initial post-reboot backend process PID: **4068**. This instance was later replaced during the final navigation integration; the current launcher/worker PIDs are recorded in section 8. The backend remains bound to loopback only; no public port was opened.
- Unauthenticated local requests to `/workspace`, `/workspace/app.js`, `/api/status`, and `/dashboard` each returned HTTP 401 with the expected HTTP Basic authentication challenge. This confirms the new route and assets are mounted behind authentication; it does not establish external reachability.
- Fixed `Scripts/Startup.ps1` to prefer `.venv-cua`, use the saved PID and command line for duplicate detection, check the local TCP listener, capture stdout/stderr, and fail if startup does not become healthy. Running `powershell.exe -NoProfile -ExecutionPolicy Bypass -File Scripts\\Startup.ps1 -NoProbe` correctly reported an existing backend and opened the shared `/workspace` without starting a duplicate.
- Existing Electron desktop processes were already running after reboot. The stale 1.1.0 installation was subsequently upgraded to 1.1.1; see section 9 for installer and packaged-ASAR verification.

## 2. Verified gaps

### Desktop/web frontend parity

The Electron renderer has ten navigation pages: Overview, Workspace Shares, Access & Permissions, Network, Sandbox & CLI, IDE Integrations, Computer Use, AI Realtime Monitor, Activity & Logs, and System Settings.

- Share creation, share listing, permission updates, AI-client token creation/revocation, server connection, and local probe controls have UI handlers.
- Sandbox, IDE, and Computer Use pages are largely descriptive/guide surfaces. They do not yet provide the requested complete live CLI/IDE/CUA monitoring and control workflow.
- The shared desktop/web Network page includes HTTPS port configuration, DDNS settings, read-only router discovery, explicitly approved temporary HTTPS mapping, relay status and one-time external verification. Live external verification remains pending because no public endpoint has been approved or enabled.
- The legacy `/dashboard` route remains available for compatibility, but its navigation now points to the shared `/workspace` pages, including AI Realtime Monitor. Desktop 'Open Dashboard' and 'Open Permissions' shortcuts also target `/workspace` so they no longer send users back to the older UI.
- A new authenticated `/workspace` route now serves the same desktop `index.html`, `styles.css` and `app.js`, with a browser adapter that calls the existing same-origin authenticated desktop API. The web route uses the same glassmorphism design and hides local-only probe/window controls.
- The shared web workspace includes the same Overview, Shares, Permissions, Network, Sandbox, IDE, Computer Use, AI Realtime Monitor, Activity and Settings navigation. The web Network page uses the shared native controls; local probe/window controls are hidden in the browser.
- `/workspace` and its assets require administrator authentication and use no-store responses. The shared renderer includes the AI Realtime Monitor navigation and page in both desktop and web builds; it displays authenticated session metadata, granted capabilities and recent activity, with optional five-second polling while the page is active. It does not start or control CUA sessions.
- The Electron main-process bridge now explicitly permits only the required monitor and network routes/methods, while validating monitor query parameters; unknown routes and unsafe query strings remain blocked.
- The monitor endpoints remain administrator-authenticated. Focused workspace/monitor tests pass, including the empty/active session response shape and unauthenticated denial.
- Therefore desktop/web visual and core share/permission parity is **PARTIALLY IMPLEMENTED**, but full functional parity is **NOT COMPLETE**: network controls, sandbox lifecycle, live IDE workflow and CUA monitoring remain incomplete.

### ChatGPT integration

- The current project documentation describes an authenticated HTTPS API, but does not establish an end-to-end ChatGPT custom MCP connection.
- No end-to-end ChatGPT Desktop-to-SF2AiS API connection was demonstrated in this recovery pass.
- A private ChatGPT Desktop local plugin has now been packaged at `integrations/chatgpt-desktop-commander` and copied into the personal marketplace at `C:\\Users\\HP\\.agents\\plugins\\sf2ais-desktop-commander`.
- The personal marketplace manifest at `C:\\Users\\HP\\.agents\\plugins\\marketplace.json` is valid JSON. The machine has since rebooted and ChatGPT Desktop processes are running; actual plugin discovery and activation in the current Free account have not yet been verified.
- The plugin starts the existing Desktop Commander over local stdio MCP using a dedicated profile. A local MCP SDK smoke test passed: **25 tools discovered**, a read/list operation inside `C:\\CreoDevo\\SF2AIS\\test-share` succeeded, and a read attempt against `C:\\Windows\\win.ini` was denied by the filesystem allowlist.
- The dedicated profile is under `%LOCALAPPDATA%\\SF2AiS\\ChatGPTDesktopPluginProfile`, sets `allowedDirectories=[C:\\CreoDevo]`, and disables optional telemetry. Important: Desktop Commander's filesystem allowlist does not sandbox terminal commands; the plugin is not a security boundary for arbitrary command execution.
- Actual ChatGPT Desktop plugin discovery, installation and use remain pending verification inside the currently running desktop app and the user's Free account. The local MCP handshake test is not equivalent to a ChatGPT account test.
- Remote custom MCP connections are plan-limited. OpenAI's current documentation lists Business and Enterprise/Edu for full custom MCP support; Pro is limited to read/fetch custom MCP connections. Free is not listed as supporting remote custom MCP connections.
- Current OpenAI documentation (checked 2026-11-12) says plugins are available across ChatGPT plans, but individual plugin capabilities depend on plan and surface. Plugins containing local MCP apps can run in ChatGPT Desktop; saving one to the account does not make it available on ChatGPT web or mobile.
- Custom remote MCP server connections in ChatGPT web are currently available to Business and Enterprise/Edu workspaces; Pro supports custom MCP read/fetch access only. Free is not listed for custom remote MCP connections. A Free account therefore cannot be promised browser-based custom MCP access to SF2AiS.
- A local desktop-only MCP plugin is the viable route to test for a Free account. The local MCP smoke test passed after reboot with 25 tools, allowed-path read PASS and outside-path denial PASS, but actual plugin discovery and invocation inside the user's Free ChatGPT Desktop session remain unverified.
- ChatGPT web does not directly connect to a local stdio MCP server. Remote web connections require a supported remote HTTPS MCP endpoint or Secure MCP Tunnel and an eligible plan/workspace.
- The local plugin is not a general SSH bridge: it exposes only the specific tools in its manifest, and terminal commands must be treated as host-level privileged actions even when file operations are restricted.

### External access and testing

- No public port, router mapping, or tunnel was enabled during this pass.
- No external mobile-data/browser-only acceptance test was run.
- A local curl request, local CLI, local test client, or local MCP Inspector is not evidence of internet-side access.
- External testing remains blocked until a secure remote endpoint/tunnel is explicitly approved and independently tested from a separate network.

### Sandbox and IDE

- Docker Desktop was started after the reboot. The Docker Engine is available, and `sf2ais-workbench:latest` was built successfully from `sandbox/Dockerfile`.
- Created a persistent acceptance share named `sf2ais-acceptance` rooted at `C:\\CreoDevo\\SF2AIS\\test-share`. Its CLI, workspace-write and IDE permissions are enabled; CUA and tunnel permissions are disabled. The generated share password is stored only as a bcrypt hash in the ignored runtime config; the pre-test config backup is in the user's Temp directory.
- Live authenticated HTTP acceptance passed: share tree/list, text-file read, scoped write/read/delete, secret-file denial, path-traversal denial, IDE status/tree/read/write/delete, and CUA status/permission denial.
- Live Docker CLI acceptance passed: `node app.js` and `python3 app.py` both completed with exit code 0. Node wrote `sandbox-output.txt` in the isolated workspace snapshot and the change was applied back to the share (`workspace_sync=applied`).
- Container boundary checks passed: no Docker socket, no Windows host filesystem mount, outbound network connection blocked, and root filesystem write denied. CLI commands run in Docker; no host-shell fallback was used.
- CUA Driver 0.46.0 reports available over private stdio MCP, bounded permission mode, no network listener and telemetry disabled. It is not running a session. The acceptance share exposes no CUA tools and session start is denied until explicit observation permission is granted.
- The VS Code extension API surface passed live scoped IDE endpoint tests. A VS Code executable was not found in PATH or the standard installation locations, so extension installation and a real Extension Development Host test remain blocked.
- Added native network controls to the shared desktop/web Network page: HTTPS port and DDNS settings, read-only router discovery, explicitly approved temporary mapping creation/removal, relay status and one-time external verification links. The old web-dashboard redirects were removed from the shared workspace path.
- A read-only router discovery run found a router and UPnP IGD support; NAT-PMP and PCP were not detected. The configured HTTPS port 443 did not complete a TLS handshake, so no router mapping was attempted or created. This is the correct fail-safe result until a TLS reverse proxy is running.
- The new API refuses router mapping unless the administrator explicitly approves it, types `CREATE`, selects a detected protocol, and the configured HTTPS reverse-proxy port completes a TLS handshake. Port 8000 is never eligible for forwarding.
- The live acceptance HTTP script was rerun after the backend restart; share, IDE, CUA gating and Docker CLI tests passed. No test containers remained after completion.
- These local acceptance tests do not constitute a full external AI-client coding workflow or an internet-side acceptance test.

## 3. Security correction completed in this pass

A fail-open default was found in Computer Use (CUA) observation permissions:

- The server treated a missing `computer_use_observe_enabled` setting as enabled.
- The status endpoint advertised observation tools even when the share/client had not granted observation.
- This contradicted the stated deny-by-default policy.

Corrections:
- Missing observation permission now defaults to `false`.
- The CUA status response computes effective share and client permissions.
- Observation tools are advertised only when observation is explicitly granted.
- Input-action tools are advertised only when control is separately granted.
- Added regression tests for missing/false observation grants and the advertised tool surface.

Targeted verification after the correction:
- `pytest tests/test_computer_use_manager.py tests/test_ide_permissions.py -q` — **16 passed**.
- Full suite after the network API/UI addition: **94 passed, 1 warning, 11 subtests passed**; see the verification record below.

## 4. Current acceptance matrix

| Area | Status | Evidence / remaining gate |
|---|---|---|
| Desktop Commander access | PASS | Connected to MasterFireFly-nb |
| Existing repository preserved | PASS | No reset/clean/commit/push |
| Local API authentication | PASS | Unauthenticated local status request returned 401 |
| Updated web route on current port 8000 | PASS | Backend PID 10884 on `.venv-cua`; `/workspace` returns the expected unauthenticated 401 challenge |
| CUA observation default | FIXED / TARGETED TEST PASS | Fail-closed default and scope-filtered tool metadata |
| Full backend regression suite | PASS | 98 passed, 1 warning, 11 subtests passed (2026-11-12 network/download integration run) |
| Desktop/web UI parity | PARTIAL | Shared renderer at `/workspace` now includes router login/manual setup and Desktop Installers; local probe settings, remaining settings parity, VS Code host and CUA session workflows remain incomplete |
| Native network settings and discovery | UI IMPLEMENTED / AUTO-MAPPING BLOCKED | Router discovery, router-admin launch and manual port-forward guide are present; UPnP IGD detected, but TLS reverse proxy is not listening on 443; no rule created |
| Live sandbox CLI | PASS | Docker image built; Node/Python jobs exit 0; workspace writeback applied; host, network and rootfs boundaries verified |
| VS Code integration | API PASS / HOST BLOCKED | Scoped IDE API read/write tests pass; VS Code executable not installed in standard locations |
| CUA provider | AVAILABLE / SESSION NOT STARTED | Driver 0.46.0 available over private stdio MCP; no listener, telemetry disabled; test share has no CUA grants and session start is denied |
| ChatGPT Desktop local plugin | BUILT / LOCAL MCP PASS / CHATGPT INSTALL PENDING | 25 tools discovered; allowed test-share path passed; Windows path outside C:\\CreoDevo denied; plugin load/use and Free-account verification pending |
| Remote ChatGPT Free custom MCP | NOT LISTED / NOT SUPPORTED BY CURRENT REMOTE MCP PLAN MATRIX | Local desktop plugin is a separate path and still requires Free-account verification |
| ChatGPT Business/Enterprise custom MCP | NOT TESTED | Requires supported remote MCP/tunnel endpoint and account/workspace permissions |
| Public HTTPS / external internet | BLOCKED | No owner-approved public exposure or external network test |
| Packaged installer acceptance | BUILD / INSTALL PASS | v1.1.3 x64 and ARM64 built; x64 installed and executable version verified; interactive installer-page click-through remains pending |
| Production readiness | NOT READY | Multiple release gates remain |

## 5. Next implementation phases

1. Reconcile the original requirements from Production Readiness (4), (5), and (6) into one traceable acceptance matrix; do not infer completion from old status documents.
2. Finish the shared desktop/web renderer and browser adapter, including consistent navigation, settings, permissions, share management, audit/activity and responsive glassmorphism.
3. Validate the new native network controls through an authenticated desktop/web session; configure a TLS reverse proxy before any forwarding attempt; then verify DDNS and the one-time external challenge from an independent mobile-data connection. Keep router mapping disabled until the TLS handshake succeeds and the owner explicitly approves it.
4. Extend sandbox acceptance beyond the passing baseline: cancellation/timeouts, output truncation, concurrent-job limits, rollback/conflict handling, cleanup and resource-limit verification.
5. Install VS Code or a supported Extension Development Host, then verify extension activation, token SecretStorage, scoped file read/write, diffs and permission denial. The API surface already passes; the host application is missing.
6. Complete CUA session lifecycle with explicit observation-only approval first, then separate control-grant tests, owner binding, revocation and emergency stop. Provider health is available; no actual session was started because the acceptance share intentionally has no CUA grants.
7. Implement or validate a real remote MCP adapter only against current ChatGPT protocol and plan requirements. Keep the generic authenticated HTTP API for other AI clients.
8. Complete packaged-app, security, recovery and genuinely external browser-only acceptance testing. Keep external testing blocked until an approved remote endpoint and independent network are available.
9. Reconcile all documentation and version metadata. Keep the release marked NOT READY until every required gate has evidence.

## 6. Full-suite verification record

Command: `.venv-cua\\Scripts\\python.exe -m pytest tests -q`
Result: **94 passed, 1 warning, 11 subtests passed** (process runtime 128.12 seconds).
Also passed: Node syntax checks for the desktop renderer, web adapter and VS Code extension; Python compilation checks for the backend, CUA, network, sandbox, terminal, workspace and acceptance scripts; Windows startup helper parse and idempotency checks. The live HTTP acceptance script passed after the latest backend restart.
The pytest-asyncio fixture-scope deprecation warning was removed by setting `asyncio_default_fixture_loop_scope = function` in `pytest.ini`. The remaining warning is Starlette's deprecation notice that `httpx` with `starlette.testclient` is deprecated; it recommends `httpx2`. No tests failed.

## 7. Safety boundaries

- Do not expose backend port 8000, Docker, SSH, or router administration to the public internet.
- Do not enable port forwarding or a tunnel without explicit owner approval.
- Do not use local CLI as a substitute for the requested external browser/client acceptance test.
- Do not start a real CUA observation/control session without explicit session approval.
- Preserve the pre-existing dirty working tree and user data.
- Do not claim production readiness based solely on unit tests or generated documentation.

## 8. Post-reboot startup verification — 2026-11-12

- Desktop Commander reconnected to `MasterFireFly-nb` successfully after the machine reboot.
- The SF2AiS backend was already running after Windows startup; no duplicate server was launched. Backend launcher PID 8288 uses `C:\\CreoDevo\\SF2AIS\\.venv-cua\\Scripts\\python.exe`; its child PID 3272 runs Uvicorn from system Python 3.12 and owns the `127.0.0.1:8000` socket. The Uvicorn command line includes `--proxy-headers --forwarded-allow-ips 127.0.0.1`. A live curl request confirmed the route is responding.
- The installed Electron desktop application was upgraded during the 2026-11-12 recovery pass. The previous installed executable was **1.1.0.0** while source metadata was **1.1.1**; the mismatch was traced to stale 2026-11-11 `dist` artifacts. The 1.1.1 x64 NSIS installer was rebuilt and ran with exit code 0. The installed executable now reports **ProductVersion 1.1.1.0 / FileVersion 1.1.1**.
- The installed `resources/app.asar` was inspected directly: package version **1.1.1**, AI Realtime Monitor navigation and page present, monitor API client present, and the Electron main-process monitor allowlist present. The desktop main window is visible after upgrade. A live click-through of the monitor page and a real active AI-client session display still require runtime acceptance.
- The local probe is configured for Windows startup. Its log continued to record successful public-IP checks after reboot; the most recent captured line was 2026-11-12 16:06:51 UTC. This is an outbound IP-report check, not proof of inbound public reachability.
- Unauthenticated requests to `/workspace`, `/workspace/app.js` and `/api/status` return **401 Unauthorized** with HTTP Basic challenge and the configured security headers. This confirms that the new route is active and protected; it is not an authenticated UI acceptance result.
- The desktop agent configuration contains a saved server URL (`http://localhost:8000`), administrator username and encrypted credential file. The app source attempts to validate this saved connection on startup. A separate authenticated curl test was not completed; the Electron credential blob is versioned/encrypted and was not exposed or bypassed.
- Post-reboot full regression run: `pytest tests -q` — **94 passed, 1 warning, 11 subtests passed**. The same command chain also completed Node syntax checks for the desktop renderer, web adapter, ChatGPT Desktop plugin launcher and smoke test, plus Python compilation checks for the backend modules; process exit code was 0.
- The ChatGPT Desktop local-plugin smoke test was rerun after reboot and passed: **25 tools discovered**, allowed-path read PASS, outside-path denial PASS. This validates the local stdio MCP bridge, not plugin discovery or invocation inside the user's Free ChatGPT account.
- After the final shared-workspace navigation changes, the backend was restarted with `Scripts/Startup.ps1 -NoProbe`; launcher PID **27724** and Uvicorn child PID **21576** now run the updated `main.py` on loopback port 8000. An authenticated browser session loaded `/workspace`, its CSS, web adapter and app JS with HTTP 200, and `/api/desktop/state` plus `/api/desktop/activity` also returned HTTP 200. An unauthenticated request still returns HTTP 401. The page did request an artwork wallpaper path that returned 404; the shared workspace currently uses its CSS gradient/glass treatment instead.
- No port forwarding, public tunnel, router mapping, or external network test was started during this restart verification.
- No project files were reset or discarded. The working tree remains dirty with pre-existing and in-progress changes; no commit or push was performed.

## 9. Desktop v1.1.1 and AI Realtime Monitor integration — 2026-11-12

- Root cause: `probe-app/package.json` already declared version `1.1.1`, but `probe-app/dist` contained an older build generated on 2026-11-11 as `1.1.0`. The installed application therefore remained on the old renderer despite newer source files. The root package metadata in `package-lock.json` was also stale (`sf2ais-probe` / `1.0.0`) and has been aligned to `sf2ais-desktop` / `1.1.1`.
- Added **AI Realtime Monitor** to the shared `renderer/index.html`, `app.js` and `styles.css`. It lists AI client sessions, session identity/client/share, workspace path, granted capabilities, state, last-seen/expiry values and recent activity. It supports filtering activity by session, manual refresh and five-second polling while visible; polling stops when the user navigates away.
- Both Electron and `/workspace` use this shared renderer. The web adapter uses same-origin authenticated requests. The desktop main process uses its saved encrypted administrator credential and an explicit allowlist. Added narrowly scoped GET access to `/api/monitor/sessions` and `/api/monitor/events`, plus the exact network routes already used by the renderer; path, method and monitor query parameters are validated. The monitor page does not start CUA or grant permissions.
- Desktop `Open Dashboard` and `Open Permissions` now target the shared `/workspace` pages. The legacy dashboard's navigation also points to the shared workspace, and old `/dashboard?view=realtime` deep links redirect to `/workspace#monitor`.
- Added workspace UI and monitor API tests. Focused result after the legacy-dashboard navigation update: **10 passed, 1 warning** across the dashboard-navigation and workspace/monitor tests. A direct Node policy test passed permitted monitor/network paths and rejected unknown routes, cross-origin paths and unsafe query values. Node syntax checks passed for `main.js`, `renderer/app.js` and `renderer/web-adapter.js`.
- Full Windows x64 installer build: `npm run build:win -- --x64` — **exit code 0**. Produced `SF2AiS-Desktop-Setup-1.1.1-x64.exe` and `SF2AiS-Desktop-Portable-1.1.1-x64.exe`. Packaged ASAR inspection confirmed version 1.1.1 and all monitor UI/API/bridge changes.
- Installed the 1.1.1 x64 setup over the existing per-user installation; installer exit code **0**. Installed executable now reports ProductVersion **1.1.1.0** and FileVersion **1.1.1**. The installed application was launched and its main window is visible.
- Final full regression result for this change set: `pytest tests -q` — **96 passed, 1 warning, 11 subtests passed** in 114.86 seconds. Python compile checks and Node syntax checks for Electron main, renderer and web adapter also passed; overall command exit code 0. The focused dashboard-navigation/workspace-monitor tests were rerun after the final legacy `?view=realtime` redirect and passed **10/10**.
- Browser acceptance: opened `http://localhost:8000/workspace#monitor` in the authenticated browser. The server returned HTTP **200** for `/workspace`, its CSS, web adapter and renderer, then HTTP **200** for both `/api/monitor/sessions` and `/api/monitor/events?limit=100`. This confirms the browser page is making authenticated monitor requests. The installed desktop renderer contains the same page and its main window is running; a separate click-through of the desktop navigation and a populated live session from an independently connected AI client remain pending. Verify that polling stops when navigating away.

## 10. Router setup and desktop installer page restoration — 2026-11-12

- Reviewed the supplied audit log. It records `router_discovery` with `available: true` and gateway `192.168.1.1`, plus HTTPS-port setting updates and mDNS start events. These are discovery/advertisement events only; there is no `router_mapping_created` event in the supplied entries.
- Fresh read-only network inspection: router discovered; UPnP IGD detected; NAT-PMP and PCP not detected; no CGNAT/upstream-private-NAT or double-NAT indication; TLS reverse proxy readiness on port 443 is **false**; external reachability remains unverified. No mapping operation was invoked.
- Root cause for no automatic UPnP rule: the backend deliberately requires a successful TLS handshake on the configured LAN HTTPS reverse-proxy port before it will create a mapping. The live diagnostic found no TLS handshake on port 443. `docker-compose.yml` publishes only `127.0.0.1:8000`, and `Caddyfile.example` is a placeholder domain config, not a running Caddy service. Therefore the rule-creation endpoint correctly refuses to forward a dead/plain-HTTP endpoint. mDNS started on the configured port is not evidence that TLS is listening.
- Added an authenticated TLS-listener readiness result to `/api/desktop/state`. The shared Network page now explains when forwarding is blocked and why, disables mapping until TLS is verified, and only offers detected UPnP IGD/NAT-PMP/PCP methods.
- Added a router administration button using the discovered private gateway address and a collapsible manual setup guide. It provides the LAN address, configured HTTPS port, TCP rule shape, DHCP reservation advice and explicit warnings not to forward port 8000, Docker, SSH or router administration. The user signs in directly on the router. SF2AiS does not collect/store router credentials or attempt generic vendor-specific login automation. UPnP requests do not normally require router UI credentials; manual configuration is required if UPnP is unavailable/disabled.
- Restored a **Desktop Installers** page in the shared Electron/web renderer. Windows x64 and ARM64 downloads use the authenticated `/probe/desktop-app/{platform}` route; Electron uses a narrow IPC downloader with Basic authentication, HTTPS enforcement for remote servers and a native save dialog. Browser downloads use same-origin authenticated fetch. macOS/Linux are visibly disabled until matching packages are built.
- Bumped desktop package metadata and lockfile to **1.1.3**. Windows x64 and ARM64 NSIS installers and portable packages built successfully. Installed `SF2AiS Secure AI Workspace.exe` reports **ProductVersion 1.1.3.0 / FileVersion 1.1.3**; the desktop app was relaunched (main PID 24556).
- Restarted the backend with the updated `main.py` using `Scripts/Startup.ps1 -NoProbe`; Uvicorn PID **10884** is listening on `127.0.0.1:8000`.
- Verification: Node syntax checks for Electron main/preload, renderer and web adapter passed; Python compile checks passed; focused network/workspace tests passed **13/13**; full `pytest tests -q` passed **98 tests, 1 warning, 11 subtests**. The warning remains Starlette's deprecation notice for `httpx` in `TestClient`.
- Installer route test downloaded the exact Windows x64 artifact matching package version 1.1.3; the installed app version was checked independently. No router mapping was created, no router credentials were requested, and no public tunnel/port was enabled. A live router login, actual forwarding rule and independent mobile-data acceptance remain pending until a real TLS reverse proxy is configured and the owner explicitly approves forwarding.
- Existing repository changes were preserved. No reset, cleanup, commit or push was performed because the working tree contains extensive pre-existing work.



## 11. Live AI / CLI acceptance update — 2026-11-13

This section supersedes earlier statements that Docker Engine and public HTTPS were not configured. It does not supersede the outstanding external mobile-data/browser acceptance.

### Verified in this pass

- Full backend regression: `pytest tests -q` — **98 passed, 1 warning, 11 subtests passed** (118.16 seconds). Remaining warning: Starlette TestClient deprecation for the installed httpx integration.
- Python compile checks passed for the backend, workspace, sandbox, terminal, CUA manager, relay, network, DDNS and probe modules.
- Node syntax checks passed for Electron main/preload, shared renderer, web adapter and VS Code extension.
- Docker Engine **29.9.2** is available and `sf2ais-workbench:latest` exists (Linux/amd64).
- Real Docker sandbox execution passed: Node command completed; successful job writeback was applied; a failed job's file changes were discarded.
- Sandbox isolation verified live: `.env` and `.git` were absent; Docker socket and host Windows filesystem were inaccessible; container root filesystem was read-only; outbound network access was blocked.
- A temporary authenticated HTTP acceptance harness exercised the actual FastAPI routes with an isolated temporary share: authenticated workspace status/tree succeeded; `.env` and parent traversal were denied; a Docker-backed CLI job completed with exit code 0 and wrote back its test file; a failing CLI job discarded its writeback; audit output was created. No production share or credential was used.
- The Caddy HTTPS listener presented a certificate accepted by the local system trust store. The backend remains configured on loopback port 8000.
- The Windows Firewall rule `SF2AiS Caddy Reverse Proxy` is enabled for TCP 81 and 4444. The scheduled task `SF2AiS Public Gateway` is registered at user logon and its last run returned exit code 0.
- DuckDNS A record and observed public IP resolved to the same public address at the time of this historical check. The address is intentionally redacted from repository documentation.

### Current network blocker — do not mark external access passed

- The Firefly Wi-Fi adapter had a private LAN address and hardware MAC recorded during the check. Both identifiers are intentionally redacted from repository documentation.
- The supplied router screenshot showed both forwarding rules targeting an earlier private LAN address. That address no longer matched the Firefly's current adapter address.
- An external port probe currently reports WAN TCP 80 and 443 unreachable; translated ports 81 and 4444 and backend 8000 are filtered.
- Update both router forwarding rules to target the Firefly's current reserved LAN address (WAN 80 → LAN 81; WAN 443 → LAN 4444), then reserve that address for the current adapter in DHCP. Do not forward 8000, SSH, Docker or router administration.
- User's independent mobile-data browser test remains pending.

### AI compatibility and functional boundaries

- SF2AiS exposes an authenticated HTTP/REST API and browser workflows. Workspace/share access supports Basic authentication or scoped `X-Sf2AiS-Token` credentials. Automated tests cover token issuance, permission scopes, write denial and revocation; the live Docker CLI HTTP harness used temporary Basic share credentials.
- This is **not** a remote MCP endpoint. `integrations/chatgpt-desktop-commander` is a local stdio Desktop Commander plugin and does not give ChatGPT web/mobile remote access to SF2AiS. ChatGPT Free compatibility is not established.
- The no-JavaScript `/browse` workflow and interactive `/workbench` are covered by backend tests, but an independent external AI browser session has not been completed.
- One-shot Docker CLI jobs are live-tested. Persistent terminal API live end-to-end is still outstanding; unit/API lifecycle tests use a controlled fake process.
- VS Code extension passed syntax checks; a live Extension Development Host session and Marketplace packaging are not verified.
- CUA observation/control was not started. No screen capture or input was performed; this remains explicitly opt-in and untested.
- Desktop/web share the same renderer source and automated parity checks pass; a full manual desktop click-through remains outstanding.

### Overall status

**Local authenticated HTTP gateway and one-shot Docker CLI: tested and passing.**
**External WAN reachability: blocked by stale router destination IP.**
**External AI/browser and mobile-data acceptance: pending.**
**Persistent terminal, live VS Code and CUA control: not yet accepted.**

No Git commit or push was performed. Existing dirty worktree and local credentials were preserved.
