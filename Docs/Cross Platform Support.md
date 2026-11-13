# Cross-Platform Support

## Current implementation

The current desktop client is an Electron application targeting Windows x64. The backend is Python/FastAPI and can run on supported Python platforms. The browser workspace uses the shared renderer and is platform independent subject to browser support.

## Planned platform targets

- Windows desktop: current primary desktop target.
- Linux desktop: planned Electron packaging and service validation.
- macOS desktop: planned Electron packaging and signing.
- Android: future mobile client and device identity integration.
- iOS: future mobile client; native build/signing requires macOS and Xcode.

## Authentication status

The current AI/user project identity uses per-client bearer tokens. The legacy connection/session API is administrator-managed. Platform biometrics and passkeys (Windows Hello, Touch ID, Android biometric prompts, platform passkeys), TOTP authenticator-app enrollment, recovery codes and trusted-device auto-accept are not yet integrated into the client-token or connection approval flows.

Do not describe those platform authentication methods as supported until the native integrations, enrollment, recovery and server-side verification have been implemented and tested.
