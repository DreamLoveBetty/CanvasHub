import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('CanvasHubDesktop', {
  isDesktopApp: true,
  platform: process.platform,
  versions: Object.freeze({
    app: process.env.CANVASHUB_APP_VERSION || '',
    electron: process.versions.electron,
    chromium: process.versions.chrome,
  }),
  openExternal: (url: string) => ipcRenderer.invoke('desktop:open-external', url),
  getUpdateStatus: () => ipcRenderer.invoke('desktop:get-update-status'),
  onUpdateStatus: (callback: (status: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, status: unknown) => callback(status);
    ipcRenderer.on('desktop:update-status', listener);
    return () => ipcRenderer.removeListener('desktop:update-status', listener);
  },
});
