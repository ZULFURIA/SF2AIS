import { createRequire } from "node:module";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const pluginRoot = path.dirname(fileURLToPath(import.meta.url));
const desktopCommanderRoot = "C:\\CreoDevo\\.AI\\DesktopCommanderMCP";
const require = createRequire(path.join(desktopCommanderRoot, "package.json"));
const { Client } = require("@modelcontextprotocol/sdk/client");
const { StdioClientTransport } = require("@modelcontextprotocol/sdk/client/stdio.js");

const launcher = path.join(pluginRoot, "launcher.mjs");
const client = new Client({ name: "sf2ais-local-plugin-smoke-test", version: "0.1.0" });
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [launcher],
  cwd: pluginRoot
});

try {
  await client.connect(transport);
  const listed = await client.listTools();
  const names = new Set(listed.tools.map((tool) => tool.name));
  assert(names.has("list_directory"), "Desktop Commander list_directory tool was not exposed");
  assert(names.has("read_file"), "Desktop Commander read_file tool was not exposed");

  const inside = await client.callTool({
    name: "list_directory",
    arguments: { path: "C:\\CreoDevo\\SF2AIS\\test-share", depth: 1 }
  });
  assert(!inside.isError, "Allowed CreoDevo test-share read was rejected");

  const outside = await client.callTool({
    name: "read_file",
    arguments: { path: "C:\\Windows\\win.ini" }
  });
  assert(outside.isError, "Filesystem allowlist did not reject a path outside C:\\CreoDevo");

  process.stdout.write(JSON.stringify({
    status: "PASS",
    toolCount: listed.tools.length,
    allowedPathRead: "PASS",
    outsidePathDenied: "PASS",
    server: "Desktop Commander local stdio MCP"
  }, null, 2) + "\n");
} finally {
  await client.close();
}
