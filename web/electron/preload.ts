import { contextBridge, ipcRenderer } from 'electron'
import type { ModalCredentials, ModalSetupMode, VolumeDownloadRequest } from '../src/types.ts'

contextBridge.exposeInMainWorld('gooseStudio', {
  getConfig: () => ipcRenderer.invoke('desktop:get-config'),
  startSetup: (mode: ModalSetupMode, credentials: ModalCredentials | null) => ipcRenderer.invoke('desktop:start-setup', mode, credentials),
  downloadModalOutput: (request: VolumeDownloadRequest) => ipcRenderer.invoke('desktop:download-modal-output', request),
  forgetModalCredentials: () => ipcRenderer.invoke('desktop:forget-modal-credentials'),
  getSetupStatus: () => ipcRenderer.invoke('desktop:get-setup-status'),
  getAppLog: () => ipcRenderer.invoke('desktop:get-app-log'),
  appendAppLog: (message: string) => ipcRenderer.invoke('desktop:append-app-log', message),
})
