import { contextBridge, ipcRenderer } from 'electron'
import type { ModalCredentials } from '../src/types.ts'

contextBridge.exposeInMainWorld('gooseStudio', {
  getConfig: () => ipcRenderer.invoke('desktop:get-config'),
  startSetup: (credentials: ModalCredentials) => ipcRenderer.invoke('desktop:start-setup', credentials),
  getSetupStatus: () => ipcRenderer.invoke('desktop:get-setup-status'),
  getAppLog: () => ipcRenderer.invoke('desktop:get-app-log'),
  appendAppLog: (message: string) => ipcRenderer.invoke('desktop:append-app-log', message),
})
