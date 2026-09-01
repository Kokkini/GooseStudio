import type { ModalCredentials, RuntimeConfig, SetupStatus } from './types.ts'

interface GooseStudioDesktop {
  getConfig(): Promise<RuntimeConfig>
  startSetup(credentials: ModalCredentials): Promise<{ state: string }>
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
