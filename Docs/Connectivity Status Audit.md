# SF2AiS Connectivity Status Audit

Date: 2026-11-13

## Status model

SF2AiS must not use one generic green Online state for unrelated signals. Report these independently:

- **Authenticated session:** the current browser or desktop client has passed server authentication.
- **Backend API health:** an authenticated request to the control-plane API succeeds.
- **Local probe state:** the local IP-reporting agent is running and its last report result/time are shown separately.
- **Public IP report:** the probe successfully reported the observed public IP. This is an outbound check-in, not inbound reachability.
- **External reachability:** only a successful test initiated from a separate internet connection can mark inbound reachability verified.

## Changes in this pass

- `/dashboard` is now an authenticated compatibility redirect to `/workspace`; `?view=realtime` is preserved as `/workspace#monitor`.
- Existing `/dashboard/*` POST router-management endpoints are unchanged.
- Browser adapter `connectionStatus()` now calls authenticated `GET /api/desktop/state`; it no longer returns unconditional `connected: true`.
- Browser `onStatus()` now reports the result of that real API check and no longer fabricates a running probe, IP address, or check-in timestamp.
- Shared renderer web-mode status labels now distinguish backend API health from local probe state and external reachability.
- Shared Electron renderer no longer labels a running local probe as “All Systems Online”; its status indicator remains amber because probe execution alone does not verify backend or inbound connectivity.

## Platform coverage

The repository currently contains one Electron desktop client and one shared renderer, with declared build targets for Windows x64/ARM64, Linux x64/ARM64, and macOS Intel/Apple Silicon. These desktop targets consume the same `renderer/app.js`; therefore the status logic correction applies to all Electron desktop builds. This is a source-level parity finding, not a claim that installers were built or runtime-tested on every OS/architecture in this pass.

No native Android/ARM or iOS application project was found in the SF2AiS repository. There is consequently no mobile-specific Online indicator to inspect or certify here. Mobile browser access uses the shared `/workspace` web adapter and therefore inherits the corrected web status logic when served by the updated backend.

## Validation

- `python -m py_compile main.py`: passed.
- `node --check probe-app/renderer/app.js`: passed.
- `node --check probe-app/renderer/web-adapter.js`: passed.
- `node --check probe-app/main.js`: passed.
- `pytest tests/test_web_workspace.py tests/test_universal_gateway_smoke.py -q`: 14 passed, 2 warnings.
- Warnings: installed pytest does not recognize `asyncio_default_fixture_loop_scope`; Starlette warns that its `httpx` TestClient integration is deprecated.

## Not yet certified

- External WAN reachability from a genuinely separate network.
- Linux and macOS native runtime/build acceptance on their respective operating systems.
- Android and iOS native apps (not present in this repository).
- Full live desktop click-through on each OS/architecture.
