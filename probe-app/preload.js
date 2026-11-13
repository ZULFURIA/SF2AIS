const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (cfg) => ipcRenderer.invoke('save-config', cfg),
  connectionStatus: () => ipcRenderer.invoke('connection-status'),
  connectServer: (details) => ipcRenderer.invoke('connect-server', details),
  disconnectServer: () => ipcRenderer.invoke('disconnect-server'),
  desktopApi: (request) => ipcRenderer.invoke('desktop-api', request),
  downloadInstaller: (platform, arch) => ipcRenderer.invoke('download-installer', { platform, arch }),
  startProbe: () => ipcRenderer.invoke('start-probe'),
  stopProbe: () => ipcRenderer.invoke('stop-probe'),
  checkNow: () => ipcRenderer.invoke('check-now'),
  openDashboard: (section) => ipcRenderer.invoke('open-dashboard', section),
  openLocalPermissions: () => ipcRenderer.invoke('open-local-permissions'),
  openIdeGuide: () => ipcRenderer.invoke('open-ide-guide'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getLogs: () => ipcRenderer.invoke('get-logs'),
  clearLogs: () => ipcRenderer.invoke('clear-logs'),
  toggleStartup: (enable) => ipcRenderer.invoke('toggle-startup', enable),
  createScheduledTask: () => ipcRenderer.invoke('create-scheduled-task'),
  minimizeWindow: () => ipcRenderer.invoke('window-minimize'),
  toggleMaximizeWindow: () => ipcRenderer.invoke('window-toggle-maximize'),
  closeWindow: () => ipcRenderer.invoke('window-close'),
  exitApp: () => ipcRenderer.invoke('window-exit'),

  onStatus: (cb) => ipcRenderer.on('status', (e, data) => cb(data)),
  offStatus: (cb) => ipcRenderer.removeListener('status', (e, data) => cb(data)),
});
