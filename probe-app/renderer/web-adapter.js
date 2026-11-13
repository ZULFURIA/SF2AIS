(() => {
  "use strict";

  const request = async ({ method = "GET", path, body }) => {
    if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
      throw new Error("Invalid SF2AiS API path.");
    }
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" })
      },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const raw = await response.text();
    let payload = raw;
    try { payload = raw ? JSON.parse(raw) : null; } catch { /* keep text response */ }
    if (!response.ok) {
      const detail = payload && typeof payload === "object"
        ? (payload.detail || payload.message || payload.error)
        : payload;
      throw new Error(detail || `SF2AiS request failed (HTTP ${response.status}).`);
    }
    return payload;
  };

  const api = {
    runtime: "web",
    getConfig: async () => ({
      gatewayUrl: location.origin,
      probeToken: "",
      duckdnsSubdomain: "",
      duckdnsToken: "",
      intervalMinutes: 5,
      startWithWindows: false
    }),
    saveConfig: async () => {
      throw new Error("Local probe settings are managed by the installed desktop agent.");
    },
    connectionStatus: async () => {
      try {
        const state = await request({ method: "GET", path: "/api/desktop/state" });
        return {
          connected: true,
          backendHealthy: true,
          authenticated: true,
          serverUrl: location.origin,
          username: "Authenticated web administrator",
          checkedAt: new Date().toISOString(),
          state
        };
      } catch (error) {
        return {
          connected: false,
          backendHealthy: false,
          authenticated: false,
          serverUrl: location.origin,
          checkedAt: new Date().toISOString(),
          error: error.message
        };
      }
    },
    connectServer: async () => {
      const status = await api.connectionStatus();
      if (!status.connected) throw new Error(status.error || "SF2AiS backend is unavailable.");
      return {
        serverUrl: location.origin,
        username: status.username,
        state: status.state
      };
    },
    disconnectServer: async () => {
      throw new Error("The web session is authenticated by the server. Sign out through the browser to disconnect.");
    },
    desktopApi: request,
    downloadInstaller: async (platform, arch) => {
      if (!['windows', 'macos', 'linux'].includes(platform) || !['x64', 'arm64'].includes(arch)) throw new Error('Unsupported installer platform or architecture.');
      const response = await fetch('/probe/desktop-app/' + platform + '?arch=' + arch, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) { const raw = await response.text(); let detail = raw; try { detail = JSON.parse(raw).detail || raw; } catch {} throw new Error(detail || ('Installer request failed (HTTP ' + response.status + ').')); }
      const disposition = response.headers.get('content-disposition') || '';
      const match = disposition.match(/filename="?([^";]+)"?/i);
      const filename = (match ? match[1] : 'SF2AiS-' + platform + '-' + arch + '-installer').split(/[\\/]/).pop();
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = filename; anchor.style.display = 'none'; document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
      return { ok: true, filename, bytes: blob.size };
    },
    startProbe: async () => ({ skipped: true, error: "The local IP probe is desktop-only." }),
    stopProbe: async () => ({ skipped: true, error: "The local IP probe is desktop-only." }),
    checkNow: async () => ({ skipped: true, error: "Use the authenticated server network controls." }),
    openDashboard: (section) => {
      const target = section || "overview";
      const nav = document.querySelector('[data-page="' + target + '"]');
      if (nav) nav.click();
      else document.querySelector('[data-page="overview"]')?.click();
    },
    openLocalPermissions: () => document.querySelector('[data-page="permissions"]')?.click(),
    openIdeGuide: () => window.open("/workspace/ide-guide", "_blank", "noopener,noreferrer"),
    openExternal: (url) => {
      try {
        const parsed = new URL(url);
        if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
          throw new Error("Only HTTP and HTTPS links can be opened.");
        }
        window.open(parsed.href, "_blank", "noopener,noreferrer");
      } catch (error) {
        throw new Error(error.message || "Invalid external URL.");
      }
    },
    getLogs: async () => {
      const result = await request({ method: "GET", path: "/api/desktop/activity" });
      return (result?.events || []).map((event) => JSON.stringify(event)).join("\n");
    },
    clearLogs: async () => {
      throw new Error("Local probe logs can only be cleared in the desktop application.");
    },
    toggleStartup: async () => false,
    createScheduledTask: async () => ({
      ok: false,
      error: "Windows scheduled tasks are configured by the desktop application."
    }),
    minimizeWindow: () => {},
    toggleMaximizeWindow: () => {},
    closeWindow: () => {},
    exitApp: () => {},
    onStatus: (callback) => {
      if (typeof callback === "function") {
        api.connectionStatus().then(status => callback({
          running: false,
          backendHealthy: status.backendHealthy,
          authenticated: status.authenticated,
          gatewayUrl: location.origin,
          currentIp: null,
          lastCheckAt: status.checkedAt,
          lastReportOk: null,
          error: status.error || null
        }));
      }
    },
    offStatus: () => {}
  };

  Object.defineProperty(window, "api", {
    configurable: false,
    enumerable: false,
    writable: false,
    value: Object.freeze(api)
  });
  document.documentElement.dataset.runtime = "web";
})();
