import type { ModalCredentials, ModalModelPreview, ModalSetupMode, RuntimeConfig, SetupStatus, VolumeDownloadRequest } from './types.ts'

interface GooseStudioDesktop {
  getConfig(): Promise<RuntimeConfig>
  startSetup(mode: ModalSetupMode, credentials: ModalCredentials | null): Promise<{ state: string }>
  downloadModalOutput(request: VolumeDownloadRequest): Promise<{ canceled: boolean; preview?: ModalModelPreview }>
  releaseModelPreview(previewId: string): Promise<boolean>
  forgetModalCredentials(): Promise<boolean>
  getSetupStatus(): Promise<SetupStatus>
  getAppLog(): Promise<string>
  appendAppLog(message: string): Promise<{ state: string }>
}

declare global {
  interface Window {
    gooseStudio?: GooseStudioDesktop
  }
}

export {}
