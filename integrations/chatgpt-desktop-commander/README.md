# SF2AiS Desktop Access — ChatGPT Desktop local plugin

This package provides a local stdio MCP connection from the ChatGPT desktop app to the existing Desktop Commander installation.

## What it does

- Uses the installed source at `C:\\CreoDevo\\.AI\\DesktopCommanderMCP`.
- Launches the MCP server locally through `launcher.mjs`.
- Uses a dedicated profile under `%LOCALAPPDATA%\\SF2AiS\\ChatGPTDesktopPluginProfile`.
- Restricts Desktop Commander's filesystem tools to `C:\\CreoDevo`.
- Disables optional Desktop Commander telemetry for this dedicated profile.
- Leaves the existing Desktop Commander profile and remote Desktop Commander connection untouched.

## Important security boundary

Desktop Commander's `allowedDirectories` setting restricts filesystem tools, **not terminal commands**. The MCP server includes terminal/process tools; a command can therefore access locations outside the filesystem allowlist. This plugin is not a sandbox. Treat command execution as privileged and approve only commands you intend to run. Use SF2AiS Docker sandboxing for untrusted or AI-generated commands once that workflow has passed its own acceptance tests.

The dedicated profile refuses to start if its filesystem allowlist or telemetry setting has been weakened.

## Install as a private personal marketplace plugin

The personal marketplace is stored at:

`%USERPROFILE%\\.agents\\plugins\\marketplace.json`

Copy this plugin directory to:

`%USERPROFILE%\\.agents\\plugins\\sf2ais-desktop-commander`

Add this entry to the marketplace:

```json
{
  "name": "creodevo-local-tools",
  "interface": { "displayName": "CreoDevo Local Tools" },
  "plugins": [
    {
      "name": "sf2ais-desktop-commander",
      "source": { "source": "local", "path": "./sf2ais-desktop-commander" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Developer Tools"
    }
  ]
}
```

Restart ChatGPT Desktop, open Plugins, choose the personal marketplace, and install **SF2AiS Desktop Access**. This is a desktop-only local plugin and does not provide access from ChatGPT web or mobile.

Availability of local MCP plugins depends on the ChatGPT desktop client and account plan. Successful local MCP startup does not itself prove that a Free account can use the plugin; verify that in the actual ChatGPT Desktop account.

Public submission of desktop-only local MCP plugins is a separate process and is limited to approved partners. This package is intended for private local testing only.
