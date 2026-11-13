# SF2AiS Operations Guide

## 1. Daily operating model

SF2AiS has three distinct parts:

1. **Server:** FastAPI owns authentication, project-folder boundaries, permission checks and audit events.
2. **Desktop administration client:** Electron connects as an administrator and manages projects, client identities, capabilities and network settings.
3. **AI/user client:** a registered identity uses its own bearer token. Tokens are never shared between unrelated AI agents.

The administrator password used by the desktop client is not a project-folder password and is not given to AI clients.

## 2. Add a project folder

1. Open the desktop app and connect to the SF2AiS server.
2. Open **Workspace Shares**.
3. Enter the server-side folder path and create the project share.
4. Decide whether the project-level **Workspace write** master switch should be enabled. Leave it off for read-only projects.
5. The new share is token-only. The desktop app does not create a shared folder username/password.

Choose the narrowest project root that contains the files the AI needs. Do not share an entire drive, user profile or broad company directory.

## 3. Register an AI or user identity

1. Open **Access & Permissions** and select the project.
2. Enter a descriptive connection name, such as Hermes - Firefly or ChatGPT - Project review.
3. Select only the non-file capabilities the client needs (CLI, IDE, Git, tunnel or computer-use capabilities).
4. Create the identity.
5. Copy the token immediately and store it in the connecting client’s secret store. The server stores only its hash; the token is shown once.
6. Select the new identity in the **Connected user / AI** dropdown.

Every new identity begins with no project-file permissions. Registration does not automatically grant Read or Write.

## 4. Configure project permissions

### Root permissions

The project folder defaults provide:

- **Read:** list the permitted project paths and read file contents.
- **Write:** create, edit, move and delete files.
- **Deny:** block this project root and every descendant path.
- **Upload:** send files into the project.
- **Download:** retrieve files from the project.

Write and Upload also require the project-level Workspace write master switch. The master switch cannot grant access by itself; the identity must also have the corresponding permission.

### Path overrides

1. Select the connected identity.
2. In **Specific file / folder override**, select **Choose file / folder**.
3. Browse the server-side project tree. Use **Open** to enter a folder or **Use** to select a file/folder.
4. Tick the desired permissions for that path.
5. Select **Add path permission**.
6. Repeat for other paths and then select **Save identity project access**.

Path rules are relative to the project root. They cannot escape the share root or target protected system paths. More-specific rules override inherited Read/Write/Upload/Download values where explicitly set.

**Deny is absolute:** a Deny rule on a path blocks that path and all descendants even if a parent folder grants access. To remove the block, remove the Deny rule or update it from the administrator interface.

A rule with all action boxes off and Deny off explicitly removes inherited rights for that path.

## 5. Permission behaviour and capability limits

| Operation | Required permission |
|---|---|
| Browse a folder / read a file | Read |
| Create, edit, move or delete a file/folder | Write |
| Upload a file | Upload |
| Download a file | Download |
| Any operation below a denied path | Denied |

The backend checks permissions on every supported workspace and IDE API request, browser workspace operation, upload and download. The UI is not the security boundary.

### CLI and Git

CLI commands can access the mounted project as a whole. For that reason, CLI is allowed only when the identity has unrestricted root Read, Write, Upload and Download and has no path overrides. This prevents a shell command from bypassing a narrower file policy.

Git status, diff, stage, commit and push can operate across repository-wide metadata or files. Git operations are blocked when path-specific rules exist. Keep Git permissions separate and grant only the scopes needed.

## 6. Revoke an identity

1. Open **Access & Permissions**.
2. Find the identity under **Clients on selected share**.
3. Select **Revoke** and confirm.
4. The token is invalidated immediately. Associated terminal sessions are closed by the server.

Revoke and reissue a token if it may have been copied to an unintended system. Do not attempt to reuse an exposed token.

## 7. Audit and monitoring

Use **AI Realtime Monitor** to inspect registered clients, recent sessions and events. Use **Activity & Logs** to refresh the server audit view.

Audit entries may include the client identity, share, remote address, operation and path. File contents, administrator passwords and raw AI tokens must not be placed in audit details.

## 8. Backup and recovery

Back up the following securely:

- Runtime configuration under data/ (contains administrator and legacy credential hashes, share paths, client token hashes and network configuration).
- Audit records under data/.
- TLS certificates and reverse-proxy configuration if managed outside the repository.
- Project folders themselves, using the normal project backup process.

Do not put runtime secrets or project data into Git. Store backups encrypted and limit access to administrators. After restoring configuration to a new host, verify the share paths, file permissions, TLS endpoint, probe configuration and scheduled tasks before enabling remote access.

## 9. Updating

1. Stop the running server cleanly.
2. Back up runtime configuration and audit data.
3. Update source code from the approved Git revision.
4. Install Python requirements and desktop dependencies as appropriate.
5. Run Python compile checks, the pytest suite, the renderer syntax check and the Electron build.
6. Start the server and verify local login, desktop connection, project listing, permissions and audit logging.
7. Run the external HTTPS check from a separate network if remote access is enabled.

Do not delete a running executable or replace installed files while the desktop app is using them. Close the application first and retain the latest known-good installer until the new build is verified.

## 10. Current connection-authentication status

The current project workflow registers an identity in the administrator interface and issues a unique token. A separate legacy /api/connections and /api/sessions API supports administrator-created pending records and administrator approval/denial, but it is not a client-initiated approval handshake and is not wired to project-token issuance. Windows Hello/passkeys, biometric confirmation, TOTP authenticator apps, recovery codes and trusted-device auto-accept are not integrated. Treat them as planned security enhancements, not current controls.
