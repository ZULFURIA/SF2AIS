const { app, BrowserWindow, Tray, Menu, ipcMain, shell, dialog } = require('electron');
const path = require('path');
const fs = require('fs');
const https = require('https');
const http = require('http');
const { exec } = require('child_process');
const os = require('os');

// ---------------------------------------------------------------------------
// Paths & Config
// ---------------------------------------------------------------------------
const CONFIG_DIR = path.join(os.homedir(), '.sf2ais-probe');
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');
const LOG_PATH = path.join(CONFIG_DIR, 'probe.log');

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
      lastPublicIp: null,
      lastCheckAt: null,
      lastReportOk: null,
    };
  }
}

function saveConfig(cfg) {
  ensureConfigDir();
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
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
    log('Skipped check — gateway or token not configured');
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
  const statusText = isRunning ? `🟢 Running — ${currentPublicIp || 'checking...'}` : `🔴 Stopped`;
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
    { label: 'Open Dashboard…', click: () => openDashboard() },
    { label: 'Open Settings', click: () => showWindow() },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        stopLoop();
        // Force a real exit. On Windows, when the app is "docked" in the
        // notification area the window-close handler hides the window instead
        // of closing it, so a plain app.quit() can leave the process running.
        // Destroy the window + tray reference first, then quit hard.
        if (win && !win.isDestroyed()) { try { win.destroy(); } catch {} }
        win = null;
        if (tray) { try { tray.destroy(); } catch {} tray = null; }
        app.exit(0);
      },
    },
  ];
  tray.setContextMenu(Menu.buildFromTemplate(template));
}

// ---------------------------------------------------------------------------
// Window
// ---------------------------------------------------------------------------
function createWindow() {
  if (win) { win.focus(); return; }
  win = new BrowserWindow({
    width: 520,
    height: 720,
    show: false,
    resizable: false,
    titleBarStyle: 'hiddenInset',
    vibrancy: 'under-window',
    visualEffectState: 'active',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
    icon: fs.existsSync(path.join(__dirname, 'assets', 'icon.png')) ? path.join(__dirname, 'assets', 'icon.png') : undefined,
  });

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  win.once('ready-to-show', () => {
    win.show();
    win.webContents.send('status', buildStatus());
  });

  win.on('close', (e) => {
    if (config.minimizeToTray !== false) {
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

function openDashboard() {
  const url = config.gatewayUrl ? config.gatewayUrl.replace(/\/$/, '') + '/dashboard' : '';
  if (url) shell.openExternal(url);
  else dialog.showMessageBox(win || undefined, { type: 'warning', message: 'Gateway URL is not configured. Set it in Settings first.' });
}

// ---------------------------------------------------------------------------
// IPC Handlers
// ---------------------------------------------------------------------------
ipcMain.handle('get-config', () => loadConfig());

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
ipcMain.handle('open-dashboard', () => openDashboard());
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

// Create Windows Task Scheduler entry via bundled PowerShell script
ipcMain.handle('create-scheduled-task', async () => {
  if (process.platform !== 'win32') {
    return { ok: false, error: 'Task Scheduler is only available on Windows.' };
  }
  const psPath = path.join(__dirname, 'scripts', 'Startup-win.ps1');
  if (!fs.existsSync(psPath)) {
    return { ok: false, error: 'PowerShell script not found: ' + psPath };
  }
  // For packaged apps, process.execPath is the .exe; for dev, wrap with electron
  const appPath = process.execPath;
  const appDir = __dirname;
  return new Promise((resolve) => {
    const cmd = `powershell -ExecutionPolicy Bypass -NoProfile -File "${psPath}" -AppPath "${appPath}" -AppDir "${appDir}" -ConfigDir "${CONFIG_DIR}"`;
    exec(cmd, { timeout: 30000 }, (err, stdout, stderr) => {
      if (err) {
        log(`Task scheduler script failed: ${err.message}\n${stderr}`);
        resolve({ ok: false, error: stderr || err.message });
      } else {
        log(`Task scheduler script output: ${stdout}`);
        resolve({ ok: true, output: stdout });
      }
    });
  });
});

// ---------------------------------------------------------------------------
// App Lifecycle
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  createTray();
  createWindow();
  // Auto-start if configured
  if (config.startWithWindows && !app.getLoginItemSettings().wasOpenedAtLogin) {
    startLoop();
  }
});

app.on('window-all-closed', () => {
  // Keep running for tray on all platforms
});

app.on('activate', () => showWindow());

app.on('before-quit', () => {
  stopLoop();
});

// Guarantee the process actually terminates even if a window is still alive
// (e.g. the tray is the only visible surface). Without this, Electron can
// keep running after Quit when minimised-to-tray is enabled.
app.on('will-quit', () => {
  stopLoop();
});
