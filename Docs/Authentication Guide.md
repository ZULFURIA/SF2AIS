# SF2AiS Authentication Guide

This guide documents the authentication that is implemented in the current repository. It distinguishes the administrator control plane from project-folder access and non-file capabilities.

## Administrator authentication

- The desktop administration interface and management API use the administrator account.
- The backend stores the administrator password as a bcrypt hash in the runtime configuration.
- The Electron main process stores its saved administrator credential using Windows secure credential storage. The renderer does not receive the saved password.
- Failed administrator authentication is rate-limited.
- Remote authenticated requests require HTTPS. HTTP is intended for loopback development.

## AI/user client authentication

An administrator registers each AI/user identity under a selected project share. The server creates a random token and returns it once.

- Each identity has its own token and client ID.
- The server stores a SHA-256 hash of the token, not the raw token.
- The client sends the token in the X-Sf2AiS-Token request header.
- The token is revocable. Revocation immediately prevents further authentication with that token.
- New identities receive no project-file access until an administrator saves a project-access policy.

The display name is a label for the administrator's convenience; it is not proof of identity. The token is the credential that authenticates the client.

## Project-file permissions

Project access is separate from identity authentication. A valid token does not imply permission to read a project.

Each identity has project-root defaults and optional path overrides:

- Read: browse and read allowed paths.
- Write: create, edit, move and delete allowed paths.
- Upload: upload into allowed paths.
- Download: download from allowed paths.
- Deny: block a path and its descendants, overriding inherited grants.

Unspecified path rights inherit from the nearest parent/root policy. Explicit Deny on any ancestor or target path is absolute. A project-level Workspace write switch is an additional master gate for Write and Upload.

The policy is enforced by the backend on supported workspace and IDE operations, browser workspace actions, uploads and downloads. The renderer is not trusted to enforce access.

## Capability scopes

Non-file capabilities are separate from project-file rights. Examples include CLI, IDE, Git stage/commit/push, tunnels and computer use.

CLI is allowed only for an identity with unrestricted root Read, Write, Upload and Download and no path overrides. This is necessary because shell commands can access the mounted project as a whole.

Git operations are repository-wide and are blocked while path-specific rules exist.

## Legacy share authentication

Existing legacy shares may continue to accept their old HTTP Basic credentials. New project shares created through the desktop app disable Basic authentication and use per-identity tokens instead.

The desktop administrator credential is never a substitute for an AI client token and must not be given to an AI client.

## Not yet implemented

A legacy administrator-managed connection/session API is present at /api/connections and /api/sessions. Creating and approving those requests requires administrator authentication; it is not a client-initiated trust/approval handshake and it does not automatically issue a per-project client token. Windows Hello, platform passkeys, biometric approval, authenticator-app TOTP, recovery codes and trusted-device auto-accept are not integrated. The current project-file access flow remains administrator-issued per-client tokens plus the granular project policy.
