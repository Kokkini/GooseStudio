import type { ModalCredentials, RuntimeConfig, SetupStatus } from './types.ts'

export async function getRuntimeConfig(): Promise<RuntimeConfig> {
  if (window.gooseStudio) return window.gooseStudio.getConfig()
  const response = await fetch('/runtime-config.json', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load runtime configuration')
  return response.json()
}

export async function startModalSetup(credentials: ModalCredentials) {
  if (window.gooseStudio) return window.gooseStudio.startSetup(credentials)
  const response = await fetch('/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || 'Could not start setup')
  return result
}

export async function getModalSetupStatus(): Promise<SetupStatus> {
  if (window.gooseStudio) return window.gooseStudio.getSetupStatus()
  const response = await fetch('/setup-status', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not read setup status')
  return response.json()
}

export async function getAppLog(): Promise<string> {
  if (window.gooseStudio) return window.gooseStudio.getAppLog()
  const response = await fetch('/app-log', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not read app log')
  const result = await response.json() as { content?: unknown }
  return typeof result.content === 'string' ? result.content : ''
}

export function appendAppLog(message: string) {
  if (!message.trim()) return
  if (window.gooseStudio) {
    void window.gooseStudio.appendAppLog(message)
    return
  }
  void fetch('/app-log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }).catch(() => undefined)
}
