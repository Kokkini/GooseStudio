import type { ModalCredentials, ModalModelPreview, ModalSetupMode, OutputFile, RuntimeConfig, SetupStatus, VolumeDownloadRequest } from './types.ts'
import { downloadOutput } from './api.ts'

export async function getRuntimeConfig(): Promise<RuntimeConfig> {
  if (window.gooseStudio) return window.gooseStudio.getConfig()
  const response = await fetch('/runtime-config.json', { cache: 'no-store' })
  if (!response.ok) throw new Error('Could not load runtime configuration')
  return response.json()
}

export async function startModalSetup(mode: ModalSetupMode, credentials: ModalCredentials | null) {
  if (window.gooseStudio) {
    try {
      return await window.gooseStudio.startSetup(mode, credentials)
    } finally {
      if (credentials) {
        credentials.tokenId = ''
        credentials.tokenSecret = ''
      }
    }
  }
  if (!credentials) throw new Error('This browser setup needs the Modal token command again.')
  const body = JSON.stringify(credentials)
  credentials.tokenId = ''
  credentials.tokenSecret = ''
  const response = await fetch('/setup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  })
  const result = await response.json()
  if (!response.ok) throw new Error(result.error || 'Could not start setup')
  return result
}

export async function downloadOutputToDisk(config: RuntimeConfig, jobId: string, output: OutputFile) {
  const request: VolumeDownloadRequest = {
    jobId,
    relativePath: output.relative_path,
    filename: output.filename,
  }
  if (window.gooseStudio) return window.gooseStudio.downloadModalOutput(request)

  const blob = await downloadOutput(config, jobId, output.id)
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = output.filename
  anchor.click()
  if (output.filename.toLowerCase().endsWith('.glb')) {
    return { canceled: false, preview: { previewId: null, src: objectUrl } }
  }
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  return { canceled: false }
}

export async function releaseModelPreview(preview: ModalModelPreview) {
  if (preview.previewId && window.gooseStudio) {
    await window.gooseStudio.releaseModelPreview(preview.previewId)
    return
  }
  if (preview.src.startsWith('blob:')) URL.revokeObjectURL(preview.src)
}

export async function forgetSavedModalCredentials() {
  if (window.gooseStudio) return window.gooseStudio.forgetModalCredentials()
  return false
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
