# Sf2AiS Remote Workspace for VS Code

This development extension mounts one Sf2AiS share as a VS Code virtual workspace through the scoped /api/ide endpoints.

## Setup

1. In the Sf2AiS admin dashboard, enable IDE workspace integration for the intended share.
2. Create an AI-client token and grant IDE. Grant Write only if the IDE should modify files.
3. Open this folder in VS Code and press F5 to launch an Extension Development Host.
4. Run Sf2AiS: Configure Connection. Enter the HTTPS gateway URL and client token. The token is stored in VS Code SecretStorage, not settings.json.
5. Run Sf2AiS: Open Remote Workspace.

## Security boundary

- The extension accesses only the authenticated share through /api/ide endpoints.
- IDE permission is separate from CLI permission. No host terminal, tasks, shell, debug adapter, or arbitrary host process execution is exposed.
- Writes, creates, moves and deletes require both share-level Write and token-level Write.
- Use HTTPS except for localhost development. Revoke tokens from the dashboard.
- This first version handles UTF-8 text files only; binary assets are not supported.
- This is an unpackaged development extension and has not been published to the VS Code Marketplace.
