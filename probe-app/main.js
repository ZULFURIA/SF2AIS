const { app, BrowserWindow, Tray, Menu, ipcMain, shell, dialog, screen, safeStorage } = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { exec, execFile } = require('child_process');
const os = require('os');

// ---------------------------------------------------------------------------
// Paths & Config
// ---------------------------------------------------------------------------
const CONFIG_DIR = path.join(os.homedir(), '.sf2ais-probe');
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');
const LOG_PATH = path.join(CONFIG_DIR, 'probe.log');
const ADMIN_SECRET_PATH = path.join(CONFIG_DIR, 'server-admin.enc');

function ensureConfigDir() {
  if (!fs.existsSync(CONFIG_DIR)) fs.mkdirSync(CONFIG_DIR, { recursive: true });
}

function loadConfig() {
  ensureConfigDir();
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  } catch {
    return {
      gatewayUrl: '',
      probeToken: '',
      duckdnsSubdomain: '',
      duckdnsToken: '',
      intervalMinutes: 5,
      startWithWindows: false,
      minimizeToTray: true,
      serverUrl: '',
      adminUsername: '',
      lastPublicIp: null,
      lastCheckAt: null,
      lastReportOk: null,
    };
  }
}

function saveConfig(cfg) {
  ensureConfigDir();
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2), { mode: 0o600 });
}

function saveAdminSecret(password) {
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure credential storage is unavailable.');
  const encrypted = safeStorage.encryptString(password);
  fs.writeFileSync(ADMIN_SECRET_PATH, encrypted, { mode: 0o600 });
}

function readAdminSecret() {
  if (!fs.existsSync(ADMIN_SECRET_PATH)) return '';
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Windows secure credential storage is unavailable.');
  return safeStorage.decryptString(fs.readFileSync(ADMIN_SECRET_PATH));
}

function clearAdminSecret() {
  try { fs.unlinkSync(ADMIN_SECRET_PATH); } catch (error) { if (error.code !== 'ENOENT') throw error; }
}

function desktopApiPath(value) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    throw new Error('Desktop API path is not permitted.');
  }
  const parsed = new URL(value, 'http://sf2ais.local');
  if (parsed.origin !== 'http://sf2ais.local' || parsed.username || parsed.password || parsed.hash) {
    throw new Error('Desktop API path is not permitted.');
  }
  const pathname = parsed.pathname;
  const sharePath = /^\/api\/desktop\/shares(?:\/[a-f0-9-]+(?:\/clients(?:\/[a-f0-9-]+)?)?)?$/.test(pathname);
  const exactPaths = new Set([
    '/api/desktop/state',
    '/api/desktop/activity',
    '/api/desktop/network',
    '/api/desktop/network/ddns',
    '/api/desktop/network/mapping',
    '/api/desktop/network/discover',
    '/api/desktop/network/verification',
    '/api/monitor/sessions',
    '/api/monitor/events'
  ]);
  if (!exactPaths.has(pathname) && !sharePath) {
    throw new Error('Desktop API path is not permitted.');
  }
  const queryKeys = [...parsed.searchParams.keys()];
  if (pathname === '/api/monitor/events') {
    if (queryKeys.some(key => !['limit', 'session_id', 'since'].includes(key))) {
      throw new Error('Desktop API query parameter is not permitted.');
    }
    const limit = parsed.searchParams.get('limit');
    if (limit !== null && (!/^\d{1,3}$/.test(limit) || Number(limit) < 1 || Number(limit) > 200)) {
      throw new Error('Monitor event limit must be between 1 and 200.');
    }
    const sessionId = parsed.searchParams.get('session_id');
    if (sessionId !== null && !/^[a-z0-9_-]{1,128}$/i.test(sessionId)) {
      throw new Error('Invalid monitor session identifier.');
    }
    const since = parsed.searchParams.get('since');
    if (since !== null && (since.length > 64 || Number.isNaN(Date.parse(since)))) {
      throw new Error('Invalid monitor event timestamp.');
    }
  } else if (queryKeys.length) {
    throw new Error('Query parameters are not permitted for this desktop API path.');
  }
  return pathname + parsed.search;
}

async function callDesktopApi(method, apiPath, body) {
  const base = String(config.serverUrl || '').replace(/\/$/, '');
  const username = String(config.adminUsername || '');
  const password = readAdminSecret();
  if (!base || !username || !password) throw new Error('Connect this desktop app to an SF2AiS server first.');
  const safePath = desktopApiPath(apiPath);
  const target = new URL(safePath, base);
  const sharePath = /^\/api\/desktop\/shares(?:\/[a-f0-9-]+(?:\/clients(?:\/[a-f0-9-]+)?)?)?$/.test(target.pathname);
  const allowedMethods = {
    '/api/desktop/state': ['GET'],
    '/api/desktop/activity': ['GET'],
    '/api/desktop/network': ['PATCH'],
    '/api/desktop/network/ddns': ['PATCH'],
    '/api/desktop/network/mapping': ['POST', 'DELETE'],
    '/api/desktop/network/discover': ['POST'],
    '/api/desktop/network/verification': ['POST'],
    '/api/monitor/sessions': ['GET'],
    '/api/monitor/events': ['GET']
  };
  if (!(sharePath ? ['GET', 'POST', 'PATCH', 'DELETE'] : (allowedMethods[target.pathname] || [])).includes(method)) {
    throw new Error('Desktop API method is not permitted for this path.');
  }
  if (target.origin !== new URL(base).origin) throw new Error('Cross-origin desktop API requests are blocked.');
  const headers = { Authorization: 'Basic ' + Buffer.from(username + ':' + password).toString('base64'), Accept: 'application/json' };
  const options = { method, headers, signal: AbortSignal.timeout(15000) };
  if (body !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
  const response = await fetch(target, options);
  const raw = await response.text();
  let payload = {};
  try { payload = raw ? JSON.parse(raw) : {}; } catch { payload = { detail: raw.slice(0, 500) }; }
  if (!response.ok) throw new Error(payload.detail || ('Server returned HTTP ' + response.status));
  return payload;
}

async function connectServer({ serverUrl, username, password }) {
  const base = String(serverUrl || '').trim().replace(/\/$/, '');
  const isLocalHttp = /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(base);
  if (!base.toLowerCase().startsWith('https://') && !isLocalHttp) {
    throw new Error('Use HTTPS for remote servers. HTTP is permitted only for localhost.');
  }
  if (!username || !password) throw new Error('Administrator username and password are required.');
  const parsed = new URL(base);
  if (parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error('Do not put credentials, query strings or fragments in the server URL.');
  if (!safeStorage.isEncryptionAvailable()) throw new Error('Secure credential storage is unavailable on this Windows account.');
  const previous = config;
  const previousSecret = fs.existsSync(ADMIN_SECRET_PATH) ? fs.readFileSync(ADMIN_SECRET_PATH) : null;
  config = { ...config, serverUrl: base, adminUsername: String(username).trim() };
  saveAdminSecret(password);
  try {
    const state = await callDesktopApi('GET', '/api/desktop/state');
    saveConfig(config);
    log('Connected to SF2AiS control plane: ' + base);
    return { connected: true, serverUrl: base, username: config.adminUsername, state };
  } catch (error) {
    config = previous;
    if (previousSecret) fs.writeFileSync(ADMIN_SECRET_PATH, previousSecret, { mode: 0o600 });
    else clearAdminSecret();
    throw error;
  }
}

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  ensureConfigDir();
  fs.appendFileSync(LOG_PATH, line);
  console.log(line.trim());
}

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
let tray = null;
let win = null;
let checkTimer = null;
let currentPublicIp = null;
let isRunning = false;
let isQuitting = false;
let config = loadConfig();

// ---------------------------------------------------------------------------
// Public IP + Reporting
// ---------------------------------------------------------------------------
function fetchPublicIp() {
  return new Promise((resolve, reject) => {
    https.get('https://api.ipify.org', { timeout: 15000 }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data.trim()));
    }).on('error', reject).on('timeout', () => reject(new Error('ipify timeout')));
  });
}

function reportToDuckDns(ip) {
  return new Promise((resolve) => {
    if (!config.duckdnsSubdomain || !config.duckdnsToken) {
      resolve({ skipped: true });
      return;
    }
    const url = new URL('https://www.duckdns.org/update');
    url.searchParams.set('domains', config.duckdnsSubdomain);
    url.searchParams.set('token', config.duckdnsToken);
    url.searchParams.set('ip', ip);
    https.get(url.toString(), { timeout: 15000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        const ok = data.trim() === 'OK';
        resolve({ ok, statusCode: res.statusCode, body: data });
      });
    }).on('error', (err) => {
      resolve({ ok: false, error: err.message });
    }).on('timeout', () => {
      resolve({ ok: false, error: 'duckdns timeout' });
    });
  });
}

function reportIp(ip) {
  return new Promise((resolve, reject) => {
    const url = new URL(config.gatewayUrl.replace(/\/$/, '') + '/api/ip-update');
    const payload = JSON.stringify({ token: config.probeToken, ip });
    const client = url.protocol === 'https:' ? https : http;
    const req = client.request(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
      },
      timeout: 15000,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const ok = res.statusCode >= 200 && res.statusCode < 300;
        resolve({ ok, statusCode: res.statusCode, body: data });
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('report timeout')); });
    req.write(payload);
    req.end();
  });
}

async function doCheck(force = false) {
  if (!config.gatewayUrl || !config.probeToken) {
    log('Skipped check â€” gateway or token not configured');
    return { skipped: true };
  }

  try {
    const ip = await fetchPublicIp();
    currentPublicIp = ip;

    if (!force && ip === config.lastPublicIp) {
      log(`IP unchanged (${ip})`);
      config.lastCheckAt = new Date().toISOString();
      saveConfig(config);
      broadcast('status', buildStatus());
      return { changed: false, ip };
    }

    const result = await reportIp(ip);
    // Also report to DuckDNS if configured
    if (config.duckdnsSubdomain && config.duckdnsToken) {
      const ddnsResult = await reportToDuckDns(ip);
      if (!ddnsResult.ok && !ddnsResult.skipped) {
        log(`DuckDNS update failed: ${ddnsResult.error || ddnsResult.body}`);
      }
    }
    if (result.ok) {
      config.lastPublicIp = ip;
      config.lastCheckAt = new Date().toISOString();
      config.lastReportOk = true;
      saveConfig(config);
      log(`IP changed -> ${ip} (reported OK)`);
    } else {
      config.lastCheckAt = new Date().toISOString();
      config.lastReportOk = false;
      saveConfig(config);
      log(`IP changed -> ${ip} (report FAILED ${result.statusCode})`);
    }
    broadcast('status', buildStatus());
    return { changed: true, ip, ok: result.ok };
  } catch (err) {
    config.lastCheckAt = new Date().toISOString();
    config.lastReportOk = false;
    saveConfig(config);
    log(`Check error: ${err.message}`);
    broadcast('status', buildStatus());
    return { error: err.message };
  }
}

function startLoop() {
  stopLoop();
  if (!config.intervalMinutes || config.intervalMinutes < 1) config.intervalMinutes = 5;
  const ms = config.intervalMinutes * 60 * 1000;
  isRunning = true;
  log(`Probe loop started (every ${config.intervalMinutes} min)`);
  doCheck(true); // immediate check
  checkTimer = setInterval(() => doCheck(), ms);
  broadcast('status', buildStatus());
  updateTrayMenu();
}

function stopLoop() {
  if (checkTimer) { clearInterval(checkTimer); checkTimer = null; }
  isRunning = false;
  log('Probe loop stopped');
  broadcast('status', buildStatus());
  updateTrayMenu();
}

function buildStatus() {
  return {
    running: isRunning,
    currentIp: currentPublicIp,
    lastPublicIp: config.lastPublicIp,
    lastCheckAt: config.lastCheckAt,
    lastReportOk: config.lastReportOk,
    intervalMinutes: config.intervalMinutes,
    gatewayUrl: config.gatewayUrl,
    duckdnsSubdomain: config.duckdnsSubdomain,
    duckdnsConfigured: !!(config.duckdnsSubdomain && config.duckdnsToken),
    startWithWindows: config.startWithWindows,
    minimizeToTray: config.minimizeToTray,
  };
}

// ---------------------------------------------------------------------------
// Tray
// ---------------------------------------------------------------------------
function createTray() {
  if (tray) return;
  // Use a simple colored icon (we'll create it in assets, fallback to default)
  const iconPath = path.join(__dirname, 'assets', 'tray-icon.png');
  const fallbackIcon = path.join(__dirname, 'assets', 'tray-icon-template.png');
  const useIcon = fs.existsSync(iconPath) ? iconPath : (fs.existsSync(fallbackIcon) ? fallbackIcon : null);
  tray = new Tray(useIcon || undefined);
  tray.setToolTip('Sf2AiS Probe');
  updateTrayMenu();
  tray.on('click', () => showWindow());
}

function updateTrayMenu() {
  if (!tray) return;
  const statusText = isRunning ? `ðŸŸ¢ Running â€” ${currentPublicIp || 'checking...'}` : `ðŸ”´ Stopped`;
  const template = [
    { label: 'Sf2AiS Probe', enabled: false },
    { type: 'separator' },
    { label: statusText, enabled: false },
    {
      label: isRunning ? 'Stop Probe' : 'Start Probe',
      click: () => isRunning ? stopLoop() : startLoop(),
    },
    { label: 'Check Now', click: () => doCheck(true) },
    { type: 'separator' },
    { label: 'Open Dashboardâ€¦', click: () => openDashboard() },
    { label: 'Open Settings', click: () => showWindow() },
    { type: 'separator' },
    {
      label: 'Exit SF2AiS',
      click: () => { isQuitting = true; stopLoop(); app.quit(); },
    },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------
function createWindow() {
  if (win) { win.focus(); return; }
  const workArea = screen.getPrimaryDisplay().workAreaSize;
  const windowWidth = Math.max(720, Math.min(1180, workArea.width - 48));
  const windowHeight = Math.max(460, Math.min(760, workArea.height - 48));
  win = new BrowserWindow({
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    backgroundMaterial: 'none',
    center: true,
    width: windowWidth,
    height: windowHeight,
    show: true,
    minWidth: 720,
    minHeight: 460,
    resizable: true,
    titleBarStyle: 'hidden',
    visualEffectState: 'active',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
    icon: fs.existsSync(path.join(__dirname, 'assets', 'icon.png')) ? path.join(__dirname, 'assets', 'icon.png') : undefined,
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  win.webContents.on('did-fail-load', (_event, code, description, url) => {
    log('Renderer load failed (' + code + '): ' + description + ' - ' + url);
  });
  win.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    if (level >= 2) log('Renderer console error: ' + message + ' (' + sourceId + ':' + line + ')');
  });
  win.webContents.once('did-finish-load', () => {
    if (win && !win.isVisible()) win.show();
  });

  win.once('ready-to-show', () => {
    win.show();
    win.webContents.send('status', buildStatus());
  });

  win.on('close', (e) => {
    if (!isQuitting && config.minimizeToTray !== false) {
      e.preventDefault();
      win.hide();
      if (tray) tray.displayBalloon({
        iconType: 'info',
        title: 'Sf2AiS Probe',
        content: 'Running in the background. Click the tray icon to reopen.',
      });
    }
  });

  win.on('closed', () => { win = null; });
}

function showWindow() {
  if (!win) createWindow();
  else { win.show(); win.focus(); }
}

function broadcast(channel, data) {
  if (win && !win.isDestroyed()) {
    win.webContents.send(channel, data);
  }
}

function openDashboard(section = 'dashboard') {
  const routes = { dashboard: '/workspace', shares: '/workspace#shares', permissions: '/workspace#permissions', network: '/workspace#network', sandbox: '/workspace#sandbox', ide: '/workspace#ide', 'computer-use': '/workspace#computer-use', monitor: '/workspace#monitor', downloads: '/workspace#downloads' };
  const base = (config.gatewayUrl || 'http://127.0.0.1:8000').replace(/\/$/, '');
  shell.openExternal(base + (routes[section] || routes.dashboard));
}
async function downloadInstaller(platform, arch) {
  const allowedPlatforms = new Set(['windows', 'macos', 'linux']);
  const allowedArchitectures = new Set(['x64', 'arm64']);
  platform = String(platform || '').toLowerCase();
  arch = String(arch || '').toLowerCase();
  if (!allowedPlatforms.has(platform) || !allowedArchitectures.has(arch)) {
    throw new Error('Unsupported installer platform or architecture.');
  }
  const base = String(config.serverUrl || '').replace(/\/$/, '');
  const username = String(config.adminUsername || '');
  const password = readAdminSecret();
  if (!base || !username || !password) {
    throw new Error('Connect this desktop app to an authenticated SF2AiS server first (System Settings).');
  }
  const baseUrl = new URL(base);
  const localHttp = baseUrl.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(baseUrl.hostname);
  if (baseUrl.protocol !== 'https:' && !localHttp) throw new Error('Remote installer downloads require HTTPS.');
  if (baseUrl.username || baseUrl.password || baseUrl.search || baseUrl.hash) throw new Error('The saved server URL contains unsupported components.');
  const target = new URL('/probe/desktop-app/' + platform + '?arch=' + arch, baseUrl);
  if (target.origin !== baseUrl.origin) throw new Error('Installer download origin is not permitted.');
  const response = await fetch(target, {
    headers: { Authorization: 'Basic ' + Buffer.from(username + ':' + password).toString('base64') },
    signal: AbortSignal.timeout(120000)
  });
  if (!response.ok) {
    const message = await response.text();
    let detail = message;
    try { detail = JSON.parse(message).detail || message; } catch {}
    throw new Error(detail || ('Installer server returned HTTP ' + response.status));
  }
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const fallback = 'SF2AiS-' + platform + '-' + arch + '-installer';
  const filename = path.basename(match ? match[1] : fallback).replace(/[<>:"\/\\|?*]/g, '_');
  const filters = platform === 'windows' ? [{ name: 'Windows installer', extensions: ['exe'] }]
    : platform === 'macos' ? [{ name: 'macOS installer', extensions: ['dmg', 'zip'] }]
    : [{ name: 'Linux installer', extensions: ['AppImage', 'deb'] }];
  const choice = await dialog.showSaveDialog(win, { defaultPath: filename, filters });
  if (choice.canceled || !choice.filePath) return { canceled: true };
  const bytes = Buffer.from(await response.arrayBuffer());
  await fs.promises.writeFile(choice.filePath, bytes, { flag: 'wx' }).catch(async error => {
    if (error.code !== 'EEXIST') throw error;
    await fs.promises.writeFile(choice.filePath, bytes);
  });
  return { ok: true, filename: path.basename(choice.filePath), path: choice.filePath, bytes: bytes.length };
}

// IPC Handlers
// ---------------------------------------------------------------------------
ipcMain.handle('download-installer', async (_event, details) => downloadInstaller(details?.platform, details?.arch));
ipcMain.handle('get-config', () => loadConfig());
ipcMain.handle('connection-status', () => ({ connected: !!(config.serverUrl && config.adminUsername && fs.existsSync(ADMIN_SECRET_PATH)), serverUrl: config.serverUrl || '', username: config.adminUsername || '' }));
ipcMain.handle('connect-server', async (_event, details) => connectServer(details || {}));
ipcMain.handle('disconnect-server', () => { clearAdminSecret(); config.serverUrl = ''; config.adminUsername = ''; saveConfig(config); log('Disconnected from SF2AiS control plane'); return { connected: false }; });
ipcMain.handle('desktop-api', async (_event, request) => {
  const method = String(request && request.method || 'GET').toUpperCase();
  if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(method)) throw new Error('Unsupported desktop API method.');
  return callDesktopApi(method, request.path, request.body);
});

ipcMain.handle('save-config', (e, newCfg) => {
  const oldInterval = config.intervalMinutes;
  const wasRunning = isRunning;
  config = { ...config, ...newCfg };
  saveConfig(config);
  if (wasRunning && oldInterval !== config.intervalMinutes) {
    startLoop(); // restart with new interval
  }
  broadcast('status', buildStatus());
  return config;
});

ipcMain.handle('start-probe', () => { startLoop(); return buildStatus(); });
ipcMain.handle('stop-probe', () => { stopLoop(); return buildStatus(); });
ipcMain.handle('check-now', async () => doCheck(true));
ipcMain.handle('open-dashboard', (e, section) => openDashboard(section));
ipcMain.handle('window-minimize', () => { if (win) win.minimize(); });
ipcMain.handle('window-toggle-maximize', () => { if (win) { if (win.isMaximized()) win.unmaximize(); else win.maximize(); } });
ipcMain.handle('window-close', () => { if (win) win.close(); });
ipcMain.handle('window-exit', () => { isQuitting = true; stopLoop(); app.quit(); });
ipcMain.handle('open-local-permissions', () => shell.openExternal('http://127.0.0.1:8000/workspace#permissions'));
ipcMain.handle('open-ide-guide', () => shell.openPath(path.join(__dirname, '..', 'vscode-extension', 'README.md')));
ipcMain.handle('open-external', (e, url) => shell.openExternal(url));

ipcMain.handle('get-logs', () => {
  try {
    if (!fs.existsSync(LOG_PATH)) return '';
    const lines = fs.readFileSync(LOG_PATH, 'utf-8').split('\n').filter(Boolean);
    return lines.slice(-200).join('\n'); // last 200 lines
  } catch (e) { return 'Error reading logs: ' + e.message; }
});

ipcMain.handle('clear-logs', () => {
  try {
    fs.writeFileSync(LOG_PATH, '');
    return true;
  } catch (e) { return false; }
});

// Windows startup toggle via registry / task
ipcMain.handle('toggle-startup', async (e, enable) => {
  config.startWithWindows = enable;
  saveConfig(config);
  if (process.platform === 'win32') {
    return new Promise((resolve) => {
      const appPath = process.execPath;
      const key = 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
      if (enable) {
        exec(`reg add "${key}" /v Sf2AiSProbe /t REG_SZ /d "${appPath}" /f`, (err) => {
          resolve(!err);
        });
      } else {
        exec(`reg delete "${key}" /v Sf2AiSProbe /f`, (err) => {
          resolve(true); // deleting nonexistent key errors, that's fine
        });
      }
    });
  }
  return true;
});

// Create Windows Task Scheduler entry from a real file outside app.asar.
ipcMain.handle('create-scheduled-task', async () => {
  if (process.platform !== 'win32') return { ok: false, error: 'Task Scheduler is only available on Windows.' };
  const psPath = app.isPackaged ? path.join(process.resourcesPath, 'scripts', 'Startup-win.ps1') : path.join(__dirname, 'scripts', 'Startup-win.ps1');
  if (!fs.existsSync(psPath)) { const message = 'PowerShell script not found: ' + psPath; log(message); return { ok: false, error: message }; }
  const args = ['-ExecutionPolicy','Bypass','-NoProfile','-NonInteractive','-File',psPath,'-AppPath',process.execPath,'-AppDir',path.dirname(process.execPath),'-ConfigDir',CONFIG_DIR];
  return new Promise((resolve) => execFile('powershell.exe', args, { timeout: 30000, windowsHide: true }, (err, stdout, stderr) => {
    if (err) { log('Task scheduler script failed: ' + err.message + '\n' + (stderr || '')); resolve({ ok: false, error: stderr || err.message }); }
    else { log('Task scheduler script output: ' + stdout); resolve({ ok: true, output: stdout }); }
  }));
});
// App Lifecycle: keep one instance even if both startup mechanisms are enabled.
const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) { app.quit(); }
else { app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.show(); win.focus(); } else showWindow(); }); }
if (hasSingleInstanceLock) app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createTray();
  createWindow();
  // Auto-start if configured
  if (config.startWithWindows) {
    startLoop();
  }
});

app.on('window-all-closed', () => {
  // Keep running for tray on all platforms
});

app.on('activate', () => showWindow());

app.on('before-quit', () => {
  isQuitting = true;
  stopLoop();
});
