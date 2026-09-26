import { spawn } from 'node:child_process'
import { appendFileSync, createReadStream, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { Readable } from 'node:stream'
import { app, BrowserWindow, dialog, ipcMain, protocol, safeStorage, shell } from 'electron'
import type { ModalCredentials, ModalModelPreview, ModalSetupMode, VolumeDownloadRequest } from '../src/types.ts'

protocol.registerSchemesAsPrivileged([{
  scheme: 'goose-model',
  privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true },
}])

interface SetupStatus {
  state: 'idle' | 'running' | 'completed' | 'failed'
  lines: string[]
  returncode: number | null
  progress: { stage: string; current: number; total: number; message: string } | null
  error: string | null
}

const developmentRoot = process.env.GOOSE_STUDIO_ROOT || process.env.FREE_VIDEO_GEN_ROOT || path.resolve(process.cwd(), '..')
let setupStatus: SetupStatus = { state: 'idle', lines: [], returncode: null, progress: null, error: null }
const sensitiveValues = new Set<string>()
const modelPreviewFiles = new Map<string, string>()

const APP_LOG_MAX_BYTES = 2 * 1024 * 1024
const APP_LOG_KEEP_BYTES = 1536 * 1024

function configPath() {
  return path.join(app.getPath('userData'), 'runtime-config.json')
}

function appLogPath() {
  return path.join(app.getPath('userData'), 'logs', 'goose-studio.log')
}

function redactLog(value: string) {
  let redacted = value
  for (const name of ['MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET', 'GOOSE_STUDIO_EXISTING_API_KEY', 'GOOSE_STUDIO_API_KEY']) {
    const secret = process.env[name]
    if (secret) redacted = redacted.replaceAll(secret, '[redacted]')
  }
  for (const secret of sensitiveValues) {
    if (secret) redacted = redacted.replaceAll(secret, '[redacted]')
  }
  return redacted
}

function appendAppLog(message: string) {
  const clean = redactLog(message.replaceAll('\0', '').trimEnd())
  if (!clean.trim()) return
  try {
    const destination = appLogPath()
    mkdirSync(path.dirname(destination), { recursive: true })
    appendFileSync(destination, `${new Date().toISOString()} ${clean}\n`, { encoding: 'utf8' })
    const contents = readFileSync(destination)
    if (contents.length > APP_LOG_MAX_BYTES) {
      writeFileSync(destination, contents.subarray(contents.length - APP_LOG_KEEP_BYTES))
    }
  } catch (error) {
    console.error('Could not write app log:', (error as Error).message)
  }
}

function readAppLog() {
  try {
    return readFileSync(appLogPath(), 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') console.error('Could not read app log:', (error as Error).message)
    return ''
  }
}

function readPersistedConfig() {
  try {
    return JSON.parse(readFileSync(configPath(), 'utf8')) as {
      baseUrl?: string
      encryptedApiKey?: string
      encryptedModalCredentials?: string
      modalWorkspace?: string
      modalEnvironment?: string
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') console.error('Could not read runtime configuration:', (error as Error).message)
    return null
  }
}

function readSecureConfig() {
  try {
    const stored = readPersistedConfig()
    if (!stored?.baseUrl || !stored.encryptedApiKey || !safeStorage.isEncryptionAvailable()) return null
    return {
      baseUrl: stored.baseUrl,
      apiKey: safeStorage.decryptString(Buffer.from(stored.encryptedApiKey, 'base64')),
      modalWorkspace: stored.modalWorkspace,
      modalEnvironment: stored.modalEnvironment || 'main',
      hasSavedModalCredentials: Boolean(stored.encryptedModalCredentials),
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') console.error('Could not read runtime configuration:', (error as Error).message)
    return null
  }
}

function readSavedModalCredentials(): ModalCredentials | null {
  try {
    const stored = readPersistedConfig()
    if (!stored?.encryptedModalCredentials || !safeStorage.isEncryptionAvailable()) return null
    const parsed = JSON.parse(safeStorage.decryptString(Buffer.from(stored.encryptedModalCredentials, 'base64'))) as {
      tokenId?: unknown
      tokenSecret?: unknown
    }
    if (typeof parsed.tokenId !== 'string' || typeof parsed.tokenSecret !== 'string' || !parsed.tokenId || !parsed.tokenSecret) return null
    return { tokenId: parsed.tokenId, tokenSecret: parsed.tokenSecret, workspace: stored.modalWorkspace || '' }
  } catch {
    return null
  }
}

function saveSecureConfig(
  config: { baseUrl: string; apiKey: string; modalWorkspace?: string; modalEnvironment?: string },
  credentials?: ModalCredentials,
) {
  const endpoint = new URL(config.baseUrl)
  if (endpoint.protocol !== 'https:' || !config.apiKey) throw new Error('Setup returned invalid runtime configuration')
  if (!safeStorage.isEncryptionAvailable()) {
    if (app.isPackaged) throw new Error('Windows credential encryption is unavailable')
    writeFileSync(
      path.join(developmentRoot, '.env.local'),
      `GOOSE_STUDIO_ENDPOINT=${config.baseUrl}\nGOOSE_STUDIO_API_KEY=${config.apiKey}\nGOOSE_STUDIO_WORKSPACE=${config.modalWorkspace || ''}\nGOOSE_STUDIO_ENVIRONMENT=${config.modalEnvironment || ''}\n`,
      { encoding: 'utf8', mode: 0o600 },
    )
    return false
  }
  const destination = configPath()
  const temporary = `${destination}.tmp`
  mkdirSync(path.dirname(destination), { recursive: true })
  const existing = readPersistedConfig()
  writeFileSync(temporary, JSON.stringify({
    version: 2,
    baseUrl: config.baseUrl,
    encryptedApiKey: safeStorage.encryptString(config.apiKey).toString('base64'),
    encryptedModalCredentials: credentials
      ? safeStorage.encryptString(JSON.stringify({ tokenId: credentials.tokenId, tokenSecret: credentials.tokenSecret })).toString('base64')
      : existing?.encryptedModalCredentials,
    modalWorkspace: config.modalWorkspace,
    modalEnvironment: config.modalEnvironment,
  }), { encoding: 'utf8', mode: 0o600 })
  renameSync(temporary, destination)
  return Boolean(credentials || existing?.encryptedModalCredentials)
}

function forgetSavedModalCredentials() {
  const stored = readPersistedConfig()
  if (!stored?.encryptedModalCredentials) return false
  delete stored.encryptedModalCredentials
  const destination = configPath()
  const temporary = `${destination}.tmp`
  writeFileSync(temporary, JSON.stringify(stored), { encoding: 'utf8', mode: 0o600 })
  renameSync(temporary, destination)
  appendAppLog('Forgot saved Modal account credentials on this device')
  return true
}

function runtimeConfig() {
  const secure = readSecureConfig()
  if (secure) return secure
  const config = {
    baseUrl: process.env.GOOSE_STUDIO_ENDPOINT || process.env.FREE_VIDEO_GEN_ENDPOINT || '',
    apiKey: process.env.GOOSE_STUDIO_API_KEY || process.env.FREE_VIDEO_GEN_API_KEY || '',
    modalWorkspace: process.env.GOOSE_STUDIO_WORKSPACE || '',
    modalEnvironment: process.env.GOOSE_STUDIO_ENVIRONMENT || process.env.MODAL_ENVIRONMENT || 'main',
    hasSavedModalCredentials: false,
  }
  if (app.isPackaged) return config
  try {
    for (const line of readFileSync(path.join(developmentRoot, '.env.local'), 'utf8').split(/\r?\n/)) {
      if ((line.startsWith('GOOSE_STUDIO_ENDPOINT=') || line.startsWith('FREE_VIDEO_GEN_ENDPOINT=')) && !config.baseUrl) config.baseUrl = line.split('=', 2)[1] || ''
      if (line.startsWith('GOOSE_STUDIO_API_KEY=') || line.startsWith('FREE_VIDEO_GEN_API_KEY=')) config.apiKey = line.split('=', 2)[1] || ''
      if (line.startsWith('GOOSE_STUDIO_WORKSPACE=') && !config.modalWorkspace) config.modalWorkspace = line.split('=', 2)[1] || ''
      if (line.startsWith('GOOSE_STUDIO_ENVIRONMENT=') && !config.modalEnvironment) config.modalEnvironment = line.split('=', 2)[1] || ''
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  return config
}

function appendSetupLine(line: string) {
  const clean = redactLog(line).trimEnd()
  if (!clean) return
  appendAppLog(clean)
  setupStatus.lines = [...setupStatus.lines, clean].slice(-200)
  if (clean.startsWith('[progress] ')) {
    try {
      setupStatus.progress = JSON.parse(clean.slice('[progress] '.length))
    } catch {
      // Preserve malformed progress output in technical details.
    }
  }
  if (clean.startsWith('[error] ')) setupStatus.error = clean.slice('[error] '.length).trim()
}

function startSetup(mode: ModalSetupMode, suppliedCredentials: ModalCredentials | null) {
  if (setupStatus.state === 'running') throw new Error('Setup is already running')
  if (!['setup', 'update', 'switch'].includes(mode)) throw new Error('Invalid Modal setup mode')
  if (suppliedCredentials !== null && (!suppliedCredentials || typeof suppliedCredentials.tokenId !== 'string' || typeof suppliedCredentials.tokenSecret !== 'string' || typeof suppliedCredentials.workspace !== 'string')) {
    throw new Error('Invalid Modal credentials')
  }
  const savedCredentials = mode === 'update' && !suppliedCredentials ? readSavedModalCredentials() : null
  const credentials = suppliedCredentials || savedCredentials
  if (!credentials?.tokenId.trim() || !credentials.tokenSecret.trim()) {
    if (mode === 'update') throw new Error('No saved Modal credentials are available. Paste a Modal token command to update the app.')
    throw new Error('Modal token ID and secret are required')
  }
  const setupCredentials = {
    tokenId: credentials.tokenId.trim(),
    tokenSecret: credentials.tokenSecret.trim(),
    workspace: credentials.workspace?.trim() || runtimeConfig().modalWorkspace || '',
  }
  const tokenIdForRedaction = setupCredentials.tokenId
  const tokenSecretForRedaction = setupCredentials.tokenSecret
  let credentialsToPersist: ModalCredentials | null = { ...setupCredentials }
  sensitiveValues.add(tokenIdForRedaction)
  sensitiveValues.add(tokenSecretForRedaction)
  const clearSetupCredentials = () => {
    sensitiveValues.delete(tokenIdForRedaction)
    sensitiveValues.delete(tokenSecretForRedaction)
    setupCredentials.tokenId = ''
    setupCredentials.tokenSecret = ''
    if (credentialsToPersist) {
      credentialsToPersist.tokenId = ''
      credentialsToPersist.tokenSecret = ''
      credentialsToPersist = null
    }
  }
  appendAppLog('Starting Modal setup')

  setupStatus = {
    state: 'running',
    lines: [],
    returncode: null,
    progress: { stage: 'credentials', current: 0, total: 1, message: 'Validating Modal credentials' },
    error: null,
  }
  const resourceRoot = app.isPackaged ? path.join(process.resourcesPath, 'sidecar', 'app') : developmentRoot
  const command = app.isPackaged
    ? path.join(process.resourcesPath, 'sidecar', 'setup', 'goose-studio-setup.exe')
    : process.env.GOOSE_STUDIO_PYTHON || process.env.FREE_VIDEO_GEN_PYTHON || 'python'
  const args = app.isPackaged
    ? [
        '--resource-root', resourceRoot,
        '--modal-cli', path.join(process.resourcesPath, 'sidecar', 'modal-cli', 'modal-cli.exe'),
        '--emit-config',
      ]
    : [path.join(developmentRoot, 'scripts', 'install.py'), '--emit-config']
  const environment = { ...process.env }
  delete environment.MODAL_SYNC_ENTRYPOINT
  environment.PYTHONUTF8 = '1'
  environment.PYTHONIOENCODING = 'utf-8'
  if (mode === 'update') environment.MODAL_ENVIRONMENT = runtimeConfig().modalEnvironment || 'main'
  environment.MODAL_TOKEN_ID = setupCredentials.tokenId
  environment.MODAL_TOKEN_SECRET = setupCredentials.tokenSecret
  environment.GOOSE_STUDIO_WORKSPACE = setupCredentials.workspace
  const existingConfig = runtimeConfig()
  if (existingConfig.apiKey) environment.GOOSE_STUDIO_EXISTING_API_KEY = existingConfig.apiKey
  if (suppliedCredentials) {
    suppliedCredentials.tokenId = ''
    suppliedCredentials.tokenSecret = ''
  }
  let child: ReturnType<typeof spawn>
  try {
    child = spawn(command, args, {
      cwd: resourceRoot,
      env: environment,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    clearSetupCredentials()
    delete environment.MODAL_TOKEN_ID
    delete environment.MODAL_TOKEN_SECRET
    const message = redactLog((error as Error).message || 'Could not start the setup process')
    appendSetupLine(`[error] ${message}`)
    setupStatus = { ...setupStatus, state: 'failed', returncode: 1, error: message }
    throw error
  }
  delete environment.MODAL_TOKEN_ID
  delete environment.MODAL_TOKEN_SECRET
  credentials.tokenId = ''
  credentials.tokenSecret = ''
  setupCredentials.tokenId = ''
  setupCredentials.tokenSecret = ''

  let stdoutBuffer = ''
  let stderrBuffer = ''
  let setupResult: { endpoint: string; apiKey: string; workspace: string; environment: string } | null = null
  const consumeLine = (line: string) => {
    if (line.startsWith('[result] ')) {
      try {
        const result = JSON.parse(line.slice('[result] '.length)) as { endpoint?: unknown; apiKey?: unknown; workspace?: unknown; environment?: unknown }
        if (typeof result.endpoint !== 'string' || typeof result.apiKey !== 'string') throw new Error('Invalid result')
        setupResult = {
          endpoint: result.endpoint,
          apiKey: result.apiKey,
          workspace: typeof result.workspace === 'string' ? result.workspace : '',
          environment: typeof result.environment === 'string' ? result.environment : '',
        }
      } catch {
        appendSetupLine('[error] Setup returned invalid configuration data')
      }
      return
    }
    appendSetupLine(line)
  }
  const consume = (chunk: Buffer, stderr = false) => {
    const combined = (stderr ? stderrBuffer : stdoutBuffer) + chunk.toString()
    const lines = combined.split(/\r?\n/)
    if (stderr) stderrBuffer = lines.pop() || ''
    else stdoutBuffer = lines.pop() || ''
    lines.forEach(stderr ? appendSetupLine : consumeLine)
  }
  child.stdout?.on('data', (chunk: Buffer) => consume(chunk))
  child.stderr?.on('data', (chunk: Buffer) => consume(chunk, true))
  child.on('error', (error) => {
    const message = error.message || 'Could not start the setup process'
    appendSetupLine(`[error] ${message}`)
    setupStatus = { ...setupStatus, state: 'failed', returncode: 1, error: message }
    clearSetupCredentials()
  })
  child.on('close', (code) => {
    consumeLine(stdoutBuffer)
    appendSetupLine(stderrBuffer)
    try {
      if (code === 0 && setupResult) {
        const saved = saveSecureConfig({
          baseUrl: setupResult.endpoint,
          apiKey: setupResult.apiKey,
          modalWorkspace: setupResult.workspace || credentialsToPersist?.workspace || existingConfig.modalWorkspace,
          modalEnvironment: setupResult.environment || existingConfig.modalEnvironment || 'main',
        }, credentialsToPersist || undefined)
        if (!saved) appendSetupLine('[warning] Modal access could not be saved securely in this development environment; updates and direct downloads may ask you to reconnect.')
        appendAppLog('Modal setup completed')
        setupStatus = { ...setupStatus, state: 'completed', returncode: 0, error: null }
      } else {
        if (code === 0) appendSetupLine('[error] Setup completed without returning runtime configuration')
        const error = setupStatus.error || `Setup process exited with code ${code ?? 'unknown'}`
        appendAppLog(`Modal setup failed: ${error}`)
        setupStatus = { ...setupStatus, state: 'failed', returncode: code ?? 1, error }
      }
    } catch (error) {
      const message = (error as Error).message
      appendSetupLine(`[error] ${message}`)
      appendAppLog(`Modal setup failed: ${message}`)
      setupStatus = { ...setupStatus, state: 'failed', returncode: 1, error: message }
    }
    clearSetupCredentials()
  })
  return { state: 'running' as const }
}

function validatedVolumeOutputPath(request: VolumeDownloadRequest) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(request.jobId)) {
    throw new Error('Invalid output job ID')
  }
  if (!request.relativePath || request.relativePath.includes('\\') || path.posix.isAbsolute(request.relativePath)) {
    throw new Error('Invalid output path')
  }
  const parts = request.relativePath.split('/')
  if (parts.some((part) => !part || part === '.' || part === '..') || path.posix.normalize(request.relativePath) !== request.relativePath || !parts.includes(request.jobId)) {
    throw new Error('Invalid output path')
  }
  const invalidWindowsName = /[<>:"/\\|?*]/.test(request.filename) || [...request.filename].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
  if (!request.filename || request.filename !== path.posix.basename(request.filename) || invalidWindowsName || request.filename.endsWith('.') || request.filename.endsWith(' ')) {
    throw new Error('Invalid output filename')
  }
  if (request.filename !== parts[parts.length - 1]) throw new Error('Output filename does not match its path')
  return path.posix.join('output', ...parts)
}

async function downloadModalVolumeOutput(request: VolumeDownloadRequest) {
  if (!request || typeof request.jobId !== 'string' || typeof request.relativePath !== 'string' || typeof request.filename !== 'string') {
    throw new Error('Invalid output download request')
  }
  const remotePath = validatedVolumeOutputPath(request)
  if (!readPersistedConfig()?.encryptedModalCredentials) {
    throw new Error('Modal access is not saved on this device. Choose Settings → Update Modal app once to connect it for downloads.')
  }
  const command = modalCliPath()
  const dialogOptions = { title: 'Save output from Modal', defaultPath: request.filename }
  const focusedWindow = BrowserWindow.getFocusedWindow()
  const destination = focusedWindow
    ? await dialog.showSaveDialog(focusedWindow, dialogOptions)
    : await dialog.showSaveDialog(dialogOptions)
  if (destination.canceled || !destination.filePath) return { canceled: true }
  await downloadFromModalVolume(remotePath, destination.filePath, request.jobId, request.filename, command)
  const preview = request.filename.toLowerCase().endsWith('.glb')
    ? registerModelPreview(destination.filePath)
    : undefined
  return { canceled: false, preview }
}

function modalCliPath() {
  const bundledCli = app.isPackaged
    ? path.join(process.resourcesPath, 'sidecar', 'modal-cli', 'modal-cli.exe')
    : path.join(developmentRoot, 'build', 'windows-sidecar', 'modal-cli', 'modal-cli.exe')
  const command = app.isPackaged || existsSync(bundledCli) ? bundledCli : 'modal'
  if (app.isPackaged && !existsSync(command)) throw new Error('The bundled Modal download tool is missing. Reinstall Goose Studio.')
  return command
}

function downloadFromModalVolume(remotePath: string, destinationPath: string, jobId: string, filename: string, command = modalCliPath()) {
  const credentials = readSavedModalCredentials()
  if (!credentials) throw new Error('Saved Modal access could not be decrypted. Use Settings → Update Modal app to reconnect it.')
  const tokenId = credentials.tokenId
  const tokenSecret = credentials.tokenSecret
  sensitiveValues.add(tokenId)
  sensitiveValues.add(tokenSecret)
  const environment: NodeJS.ProcessEnv = { ...process.env, MODAL_TOKEN_ID: tokenId, MODAL_TOKEN_SECRET: tokenSecret, MODAL_ENVIRONMENT: runtimeConfig().modalEnvironment || 'main', PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
  const args = ['volume', 'get', '--force', 'goose-studio-io', remotePath, destinationPath]
  appendAppLog(`Downloading Modal output ${jobId}/${filename}`)

  return new Promise<void>((resolve, reject) => {
    let stderr = ''
    let settled = false
    const clearCredentials = () => {
      sensitiveValues.delete(tokenId)
      sensitiveValues.delete(tokenSecret)
      delete environment.MODAL_TOKEN_ID
      delete environment.MODAL_TOKEN_SECRET
      credentials.tokenId = ''
      credentials.tokenSecret = ''
    }
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(command, args, { cwd: developmentRoot, env: environment, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    } catch (error) {
      clearCredentials()
      reject(new Error(redactLog((error as Error).message || 'Could not start the Modal download tool')))
      return
    }
    delete environment.MODAL_TOKEN_ID
    delete environment.MODAL_TOKEN_SECRET
    credentials.tokenId = ''
    credentials.tokenSecret = ''
    child.stdout?.on('data', () => undefined)
    child.stderr?.on('data', (chunk: Buffer) => {
      stderr = `${stderr}${redactLog(chunk.toString())}`.slice(-6000)
    })
    child.on('error', (error) => {
      if (settled) return
      settled = true
      const message = redactLog(error.message || 'Could not start the Modal download tool')
      appendAppLog(`Modal output download failed: ${message}`)
      clearCredentials()
      reject(new Error(message))
    })
    child.on('close', (code) => {
      if (settled) return
      settled = true
      if (code === 0) {
        appendAppLog(`Modal output download completed ${jobId}/${filename}`)
        clearCredentials()
        resolve()
      } else {
        const details = redactLog(stderr.trim()).slice(-1200)
        const message = details ? `Modal could not download the file: ${details}` : `Modal download failed (exit code ${code ?? 'unknown'}).`
        appendAppLog(`Modal output download failed: ${message}`)
        clearCredentials()
        reject(new Error(message))
      }
    })
  })
}

function registerModelPreview(filePath: string): ModalModelPreview {
  const previewId = randomUUID()
  modelPreviewFiles.set(previewId, filePath)
  return { previewId, src: `goose-model://${previewId}/model.glb` }
}

function releaseModalModelPreview(previewId: string) {
  if (typeof previewId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(previewId)) return false
  return modelPreviewFiles.delete(previewId)
}

function serveModelPreview(urlValue: string) {
  let url: URL
  try { url = new URL(urlValue) } catch { return new Response('Not found', { status: 404 }) }
  const filePath = url.pathname === '/model.glb' ? modelPreviewFiles.get(url.hostname) : undefined
  if (!filePath) return new Response('Not found', { status: 404 })
  const stream = Readable.toWeb(createReadStream(filePath)) as ReadableStream
  return new Response(stream as never, {
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
      'Content-Type': 'model/gltf-binary',
    },
  })
}

function cleanModelPreviews() {
  modelPreviewFiles.clear()
}

function openExternalUrl(value: string) {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return
  }
  if (url.protocol !== 'https:') return

  if (process.env.WSL_DISTRO_NAME || process.env.WSL_INTEROP) {
    const explorer = spawn('/mnt/c/Windows/explorer.exe', [url.toString()], {
      detached: true,
      stdio: 'ignore',
    })
    explorer.on('error', (error) => console.error('Could not open external URL:', error.message))
    explorer.unref()
    return
  }
  void shell.openExternal(url.toString()).catch((error) => console.error('Could not open external URL:', error.message))
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 900,
    minHeight: 650,
    backgroundColor: '#f4f3ed',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  window.once('ready-to-show', () => window.show())
  window.webContents.setWindowOpenHandler(({ url }) => {
    openExternalUrl(url)
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    if (url !== window.webContents.getURL()) {
      event.preventDefault()
      openExternalUrl(url)
    }
  })
  if (process.env.ELECTRON_RENDERER_URL) void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void window.loadFile(path.join(__dirname, '../renderer/index.html'))
}

app.whenReady().then(() => {
  protocol.handle('goose-model', (request) => serveModelPreview(request.url))
  ipcMain.handle('desktop:get-config', runtimeConfig)
  ipcMain.handle('desktop:start-setup', (_event, mode: ModalSetupMode, credentials: ModalCredentials | null) => startSetup(mode, credentials))
  ipcMain.handle('desktop:download-modal-output', (_event, request: VolumeDownloadRequest) => downloadModalVolumeOutput(request))
  ipcMain.handle('desktop:release-model-preview', (_event, previewId: string) => releaseModalModelPreview(previewId))
  ipcMain.handle('desktop:forget-modal-credentials', () => forgetSavedModalCredentials())
  ipcMain.handle('desktop:get-setup-status', () => setupStatus)
  ipcMain.handle('desktop:get-app-log', () => readAppLog())
  ipcMain.handle('desktop:append-app-log', (_event, message) => {
    if (typeof message === 'string') appendAppLog(message.slice(0, 10000))
    return { state: 'ok' }
  })
  appendAppLog('Goose Studio started')
  createWindow()
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
})

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('before-quit', cleanModelPreviews)
