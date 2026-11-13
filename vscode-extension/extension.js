const vscode = require("vscode");
const https = require("https");
const http = require("http");

function activate(context) {
  const scheme = "sf2ais";
  let baseUrl = context.globalState.get("sf2ais.baseUrl", "");
  async function token() { return context.secrets.get("sf2ais.apiToken"); }
  async function request(path, options) {
    options = options || {};
    const secret = await token();
    if (!baseUrl || !secret) throw new Error("Configure Sf2AiS first.");
    const url = new URL(path, baseUrl.replace(/\/+$/, "") + "/");
    const body = options.body;
    const transport = url.protocol === "https:" ? https : http;
    return new Promise((resolve, reject) => {
      const req = transport.request(url, {
        method: options.method || "GET",
        headers: Object.assign({ "X-Sf2AiS-Token": secret },
          body === undefined ? {} : { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }),
        timeout: 15000
      }, res => {
        const chunks = [];
        res.on("data", c => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          let data = {};
          try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { detail: text }; }
          if (res.statusCode < 200 || res.statusCode >= 300) reject(new Error(data.detail || ("HTTP " + res.statusCode)));
          else resolve(data);
        });
      });
      req.on("error", reject);
      req.on("timeout", () => req.destroy(new Error("Sf2AiS request timed out")));
      if (body !== undefined) req.write(body);
      req.end();
    });
  }
  function rel(uri) { return decodeURIComponent(uri.path.replace(/^\/+/, "")); }
  function uriFor(path) { return vscode.Uri.from({ scheme: scheme, path: "/" + path }); }
  function stat(type, size) { return { type: type, ctime: 0, mtime: Date.now(), size: size || 0 }; }
  const emitter = new vscode.EventEmitter();
  const provider = {
    onDidChangeFile: emitter.event,
    watch: function() { return { dispose: function() {} }; },
    async stat(uri) {
      const path = rel(uri);
      if (!path) return stat(vscode.FileType.Directory);
      try {
        const file = await request("/api/ide/file?path=" + encodeURIComponent(path));
        return stat(vscode.FileType.File, Buffer.byteLength(file.content || "", "utf8"));
      } catch (error) {
        const tree = await request("/api/ide/tree?path=" + encodeURIComponent(path) + "&depth=1");
        return stat(vscode.FileType.Directory);
      }
    },
    async readDirectory(uri) {
      const tree = await request("/api/ide/tree?path=" + encodeURIComponent(rel(uri)) + "&depth=1");
      const entries = tree.entries || tree.items || [];
      return entries.map(item => [item.name, item.type === "directory" || item.is_dir ? vscode.FileType.Directory : vscode.FileType.File]);
    },
    async readFile(uri) {
      const file = await request("/api/ide/file?path=" + encodeURIComponent(rel(uri)));
      return Buffer.from(file.content || "", "utf8");
    },
    async writeFile(uri, content) {
      await request("/api/ide/file", { method: "PUT", body: JSON.stringify({ path: rel(uri), content: Buffer.from(content).toString("utf8") }) });
    },
    async createDirectory(uri) {
      await request("/api/ide/directory", { method: "POST", body: JSON.stringify({ path: rel(uri) }) });
    },
    async delete(uri) {
      await request("/api/ide/path?path=" + encodeURIComponent(rel(uri)), { method: "DELETE" });
    },
    async rename(oldUri, newUri) {
      await request("/api/ide/move", { method: "POST", body: JSON.stringify({ source: rel(oldUri), destination: rel(newUri) }) });
    }
  };
  context.subscriptions.push(vscode.workspace.registerFileSystemProvider(scheme, provider, { isCaseSensitive: true }));
  context.subscriptions.push(vscode.commands.registerCommand("sf2ais.configure", async function() {
    const endpoint = await vscode.window.showInputBox({ prompt: "Sf2AiS HTTPS base URL", value: baseUrl, placeHolder: "https://your-sf2ais.example" });
    if (!endpoint) return;
    let parsed;
    try { parsed = new URL(endpoint); } catch (_) { vscode.window.showErrorMessage("Enter a valid URL."); return; }
    if (!["https:", "http:"].includes(parsed.protocol) || (parsed.protocol === "http:" && !["localhost", "127.0.0.1"].includes(parsed.hostname))) {
      vscode.window.showErrorMessage("Use HTTPS. HTTP is allowed only for localhost testing."); return;
    }
    const apiToken = await vscode.window.showInputBox({ prompt: "AI client token with IDE permission", password: true, ignoreFocusOut: true });
    if (!apiToken) return;
    baseUrl = parsed.toString().replace(/\/+$/, "");
    await context.globalState.update("sf2ais.baseUrl", baseUrl);
    await context.secrets.store("sf2ais.apiToken", apiToken);
    try {
      await request("/api/ide/status");
      vscode.window.showInformationMessage("Sf2AiS connection verified.");
    } catch (error) {
      await context.secrets.delete("sf2ais.apiToken");
      vscode.window.showErrorMessage("Sf2AiS permission check failed: " + error.message);
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand("sf2ais.openWorkspace", async function() {
    try {
      await request("/api/ide/status");
      await vscode.commands.executeCommand("vscode.openFolder", uriFor(""), { forceNewWindow: true });
    } catch (error) { vscode.window.showErrorMessage(error.message); }
  }));
}
function deactivate() {}
module.exports = { activate: activate, deactivate: deactivate };
