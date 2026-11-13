# SF2AiS Secure AI Workspace - Desktop Operating Guide

## What the desktop app does

The Electron desktop client provides the SF2AiS administration interface and local probe controls. It connects to the FastAPI server, manages project folders and AI client identities, configures access policies, displays server activity and controls local probe settings.

The browser workspace uses the same renderer and design system. Local-only probe and Windows startup controls remain desktop-specific.

## Start the desktop client

### Development

```powershell
Set-Location C:\CreoDevo\SF2AIS\probe-app
npm install
npm run start
```

### Build and run an unpacked Windows test build

```powershell
npm run build:dir
.\dist\win-unpacked\SF2AiS Secure AI Workspace.exe
```

The build output is not the installed application. Close the test build before rebuilding if Windows has locked Electron DLLs. The installed copy is separate and is not replaced by build:dir.

## Connect to the server

1. Open **System Settings**.
2. Enter the server URL, administrator username and administrator password.
3. Remote authenticated connections require HTTPS. HTTP is allowed for localhost development.
4. Select **Connect and verify**.
5. The administrator password is stored by the Electron main process using Windows secure credential storage; it is not exposed to renderer JavaScript.

Disconnect from the server to remove the saved connection credential from the desktop client.

## Create a project folder

1. Open **Workspace Shares**.
2. Enter the full path as it exists on the server.
3. Select the share-level capabilities required for the project.
4. Select **Create share on server**.

New desktop-created projects do not use shared folder usernames/passwords. Existing legacy shares can continue using their older Basic-auth configuration, but new projects use individual AI client tokens.

## Register an AI/user identity

1. Open **Access & Permissions** and select the project.
2. Enter a connection name that identifies the AI or user.
3. Select only the additional capabilities needed (CLI, IDE, Git, tunnel or computer use).
4. Create the scoped client token.
5. Copy the token immediately. It is displayed once and must be stored securely by the client using it.
6. Select the identity in the **Connected user / AI** dropdown.

A new identity has no project-file permissions until the administrator grants them.

## Configure project-file permissions

The **Connected identity permissions** panel has:

- A top dropdown for the registered AI/user identity.
- Project-root checkboxes for Read, Write, Deny, Upload and Download.
- A **Choose file / folder** button that browses the server-side project tree.
- The same five checkboxes for each selected file/folder override.
- A path-rule list where individual overrides can be removed.
- **Save identity project access** to persist the policy.

Write and Upload controls are available only when the project-level Workspace write master switch is enabled. This is an additional gate; it does not grant the identity permission by itself.

Deny blocks the selected path and all descendants, even when a parent path grants access. A path rule with all permissions off removes inherited rights at that path.

## Capability notes

- **Read:** browse and read allowed files.
- **Write:** create, edit, move and delete allowed files/folders.
- **Upload:** upload files independently of Download.
- **Download:** download files independently of Upload.
- **CLI:** requires unrestricted root Read, Write, Upload and Download and no path overrides, because shell commands can access the entire mounted project.
- **Git:** repository-wide Git operations are disabled when path-specific rules exist.
- **IDE:** uses the same server-side file permission checks.
- **Computer use:** separate from project-file permissions and remains subject to its own share/client scopes.

## Appearance

System Settings includes the glass-effect controls:

- Window background opacity.
- Card opacity.
- Primary and secondary card frost tint.
- Purple/blue window and card neon border colours.

Changes preview immediately and save automatically. Text contrast remains shaded to help maintain legibility over transparent backgrounds.

## Local probe and startup

The local probe reports public IP changes and can update a configured DuckDNS hostname. It is separate from the SF2AiS server. The Windows startup helper and scheduled task are documented in the Startup Guide.

## Troubleshooting

| Problem | Action |
|---|---|
| Server connection fails | Check the URL, HTTPS certificate, admin credentials and server availability |
| Project folder cannot be created | Confirm the folder path exists or that the server account can create it |
| AI token receives 403 | Confirm the identity is selected and the requested path/action is granted; inspect Deny and parent rules |
| Write/Upload checkboxes disabled | Enable the share-level Workspace write master switch, then save and reopen permissions |
| CLI unavailable | Confirm share/client CLI scope, sandbox availability and unrestricted root project permissions |
| Git unavailable | Remove path-specific rules only if full-repository access is appropriate and explicitly intended |
| Build fails with DLL lock | Close the isolated test app and retry; do not terminate unrelated Electron processes |
| Installed app remains older | Install the newly verified package separately; build:dir does not update the installed copy |

## Security reminders

Never share the administrator password with an AI client. Issue one token per identity, grant the minimum file permissions, and revoke tokens that are no longer required. The legacy connection/session API is administrator-managed and separate from project-token registration. Passkey/biometric approval and authenticator-app pairing are not yet integrated.
