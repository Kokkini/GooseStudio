import { contextBridge, ipcRenderer } from 'electron'
import type { AppUpdateCheckResult, AppUpdateProgress, ModalAppVersionStatus, ModalCredentials, ModalSetupMode, VolumeDownloadRequest } from '../src/types.ts'

contextBridge.exposeInMainWorld('gooseStudio', {
  getConfig: () => ipcRenderer.invoke('desktop:get-config'),
  checkForAppUpdate: () => ipcRenderer.invoke('desktop:check-app-update') as Promise<AppUpdateCheckResult>,
  checkModalAppVersion: () => ipcRenderer.invoke('desktop:check-modal-app-version') as Promise<ModalAppVersionStatus>,
  downloadAndInstallAppUpdate: () => ipcRenderer.invoke('desktop:download-install-app-update') as Promise<void>,
  cancelAppUpdateDownload: () => ipcRenderer.invoke('desktop:cancel-app-update-download') as Promise<void>,
  onAppUpdateProgress: (listener: (progress: AppUpdateProgress) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: AppUpdateProgress) => listener(progress)
    ipcRenderer.on('desktop:app-update-progress', handler)
    return () => ipcRenderer.removeListener('desktop:app-update-progress', handler)
  },
  startSetup: (mode: ModalSetupMode, credentials: ModalCredentials | null) => ipcRenderer.invoke('desktop:start-setup', mode, credentials),
  downloadModalOutput: (request: VolumeDownloadRequest) => ipcRenderer.invoke('desktop:download-modal-output', request),
  releaseModelPreview: (previewId: string) => ipcRenderer.invoke('desktop:release-model-preview', previewId),
  forgetModalCredentials: () => ipcRenderer.invoke('desktop:forget-modal-credentials'),
  getSetupStatus: () => ipcRenderer.invoke('desktop:get-setup-status'),
  getAppLog: () => ipcRenderer.invoke('desktop:get-app-log'),
  appendAppLog: (message: string) => ipcRenderer.invoke('desktop:append-app-log', message),
})
