const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (cfg) => ipcRenderer.invoke('save-config', cfg),
  startProbe: () => ipcRenderer.invoke('start-probe'),
  stopProbe: () => ipcRenderer.invoke('stop-probe'),
  checkNow: () => ipcRenderer.invoke('check-now'),
  openDashboard: () => ipcRenderer.invoke('open-dashboard'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getLogs: () => ipcRenderer.invoke('get-logs'),
  clearLogs: () => ipcRenderer.invoke('clear-logs'),
  toggleStartup: (enable) => ipcRenderer.invoke('toggle-startup', enable),
  createScheduledTask: () => ipcRenderer.invoke('create-scheduled-task'),

  onStatus: (cb) => ipcRenderer.on('status', (e, data) => cb(data)),
  offStatus: (cb) => ipcRenderer.removeListener('status', (e, data) => cb(data)),
});
