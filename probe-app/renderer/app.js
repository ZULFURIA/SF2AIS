document.addEventListener('DOMContentLoaded', async () => {
  // Elements
  const els = {
    statusBadge: document.getElementById('status-badge'),
    statusText: document.getElementById('status-text'),
    ipDisplay: document.getElementById('ip-display'),
    currentIp: document.getElementById('current-ip'),
    lastCheck: document.getElementById('last-check'),
    gatewayUrl: document.getElementById('gateway-url'),
    probeToken: document.getElementById('probe-token'),
    duckdnsSubdomain: document.getElementById('duckdns-subdomain'),
    duckdnsToken: document.getElementById('duckdns-token'),
    interval: document.getElementById('interval'),
    startWithWindows: document.getElementById('start-with-windows'),
    btnSave: document.getElementById('btn-save'),
    btnCheckNow: document.getElementById('btn-check-now'),
    btnDashboard: document.getElementById('btn-dashboard'),
    btnScheduler: document.getElementById('btn-scheduler'),
    btnCopyIp: document.getElementById('btn-copy-ip'),
    btnOpenDuckDns: document.getElementById('btn-open-duckdns'),
    logBox: document.getElementById('log-box'),
    btnRefreshLogs: document.getElementById('btn-refresh-logs'),
    btnClearLogs: document.getElementById('btn-clear-logs'),
  };

  function toast(msg, type = 'ok') {
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => t.classList.add('show'));
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 400);
    }, 2500);
  }

  async function loadConfig() {
    const cfg = await window.api.getConfig();
    els.gatewayUrl.value = cfg.gatewayUrl || '';
    els.probeToken.value = cfg.probeToken || '';
    els.duckdnsSubdomain.value = cfg.duckdnsSubdomain || '';
    els.duckdnsToken.value = cfg.duckdnsToken || '';
    els.interval.value = cfg.intervalMinutes || 5;
    els.startWithWindows.checked = !!cfg.startWithWindows;
    updateUI(cfg);
  }

  function updateUI(status) {
    const running = status.running;
    els.statusBadge.className = 'badge ' + (running ? 'online' : 'offline');
    els.statusText.textContent = running ? 'Running' : 'Stopped';
    els.ipDisplay.textContent = status.currentIp || '—';
    els.currentIp.textContent = status.currentIp || 'Waiting…';

    if (status.lastCheckAt) {
      const d = new Date(status.lastCheckAt);
      els.lastCheck.textContent = 'Last check: ' + d.toLocaleString();
    } else {
      els.lastCheck.textContent = 'Last check: never';
    }
  }

  els.btnSave.addEventListener('click', async () => {
    const cfg = {
      gatewayUrl: els.gatewayUrl.value.trim(),
      probeToken: els.probeToken.value.trim(),
      duckdnsSubdomain: els.duckdnsSubdomain.value.trim(),
      duckdnsToken: els.duckdnsToken.value.trim(),
      intervalMinutes: parseInt(els.interval.value, 10) || 5,
      startWithWindows: els.startWithWindows.checked,
    };
    await window.api.saveConfig(cfg);
    await window.api.toggleStartup(cfg.startWithWindows);
    // Create or update the scheduled task for the IP updater
    if (cfg.startWithWindows) {
      const result = await window.api.createScheduledTask();
      if (!result.ok) toast('Scheduled task: ' + (result.error || 'failed'), 'err');
    }
    toast('Settings saved');
  });

  els.btnCheckNow.addEventListener('click', async () => {
    toast('Checking now…', 'ok');
    const result = await window.api.checkNow();
    if (result.error) toast('Check failed: ' + result.error, 'err');
    else if (result.skipped) toast('Configure gateway + token first', 'err');
    else if (result.changed && result.ok) toast('IP reported OK', 'ok');
    else if (result.changed && !result.ok) toast('IP report failed', 'err');
    else toast('IP unchanged', 'ok');
    await refreshLogs();
  });

  els.btnDashboard.addEventListener('click', () => window.api.openDashboard());

  els.btnOpenDuckDns.addEventListener('click', () => {
    window.api.openExternal('https://www.duckdns.org/');
  });

  els.btnScheduler.addEventListener('click', async () => {
    toast('Creating scheduled task…', 'ok');
    const result = await window.api.createScheduledTask();
    if (result.ok) toast('Scheduled task created', 'ok');
    else toast('Task creation failed: ' + (result.error || 'unknown'), 'err');
  });

  els.btnCopyIp.addEventListener('click', () => {
    const ip = els.currentIp.textContent;
    if (ip && ip !== 'Waiting…') {
      navigator.clipboard.writeText(ip);
      toast('IP copied');
    }
  });

  async function refreshLogs() {
    const logs = await window.api.getLogs();
    if (!logs || !logs.trim()) {
      els.logBox.innerHTML = '<div class="log-placeholder">Logs will appear here once the probe starts running.</div>';
      return;
    }
    els.logBox.textContent = logs;
    els.logBox.scrollTop = els.logBox.scrollHeight;
  }

  els.btnRefreshLogs.addEventListener('click', refreshLogs);
  els.btnClearLogs.addEventListener('click', async () => {
    await window.api.clearLogs();
    await refreshLogs();
    toast('Logs cleared');
  });

  // Listen for status updates from main process
  window.api.onStatus((status) => {
    updateUI(status);
  });

  // Init
  await loadConfig();
  await refreshLogs();
});
