import { spawn } from 'node:child_process'
import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { app, BrowserWindow, ipcMain, safeStorage, shell } from 'electron'

interface SetupStatus {
  state: 'idle' | 'running' | 'completed' | 'failed'
  lines: string[]
  returncode: number | null
  progress: { stage: string; current: number; total: number; message: string } | null
  error: string | null
}

const developmentRoot = process.env.GOOSE_STUDIO_ROOT || process.env.FREE_VIDEO_GEN_ROOT || path.resolve(process.cwd(), '..')
let setupStatus: SetupStatus = { state: 'idle', lines: [], returncode: null, progress: null, error: null }

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

function readSecureConfig() {
  try {
    const stored = JSON.parse(readFileSync(configPath(), 'utf8')) as { baseUrl?: string; encryptedApiKey?: string; modalWorkspace?: string; modalEnvironment?: string }
    if (!stored.baseUrl || !stored.encryptedApiKey || !safeStorage.isEncryptionAvailable()) return null
    return {
      baseUrl: stored.baseUrl,
      apiKey: safeStorage.decryptString(Buffer.from(stored.encryptedApiKey, 'base64')),
      modalWorkspace: stored.modalWorkspace,
      modalEnvironment: stored.modalEnvironment || 'main',
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') console.error('Could not read runtime configuration:', (error as Error).message)
    return null
  }
}

function saveSecureConfig(config: { baseUrl: string; apiKey: string; modalWorkspace?: string; modalEnvironment?: string }) {
  const endpoint = new URL(config.baseUrl)
  if (endpoint.protocol !== 'https:' || !config.apiKey) throw new Error('Setup returned invalid runtime configuration')
  if (!safeStorage.isEncryptionAvailable()) {
    if (app.isPackaged) throw new Error('Windows credential encryption is unavailable')
    writeFileSync(
      path.join(developmentRoot, '.env.local'),
      `GOOSE_STUDIO_ENDPOINT=${config.baseUrl}\nGOOSE_STUDIO_API_KEY=${config.apiKey}\nGOOSE_STUDIO_WORKSPACE=${config.modalWorkspace || ''}\nGOOSE_STUDIO_ENVIRONMENT=${config.modalEnvironment || ''}\n`,
      { encoding: 'utf8', mode: 0o600 },
    )
    return
  }
  const destination = configPath()
  const temporary = `${destination}.tmp`
  mkdirSync(path.dirname(destination), { recursive: true })
  writeFileSync(temporary, JSON.stringify({
    version: 1,
    baseUrl: config.baseUrl,
    encryptedApiKey: safeStorage.encryptString(config.apiKey).toString('base64'),
    modalWorkspace: config.modalWorkspace,
    modalEnvironment: config.modalEnvironment,
  }), { encoding: 'utf8', mode: 0o600 })
  renameSync(temporary, destination)
}

function runtimeConfig() {
  const secure = readSecureConfig()
  if (secure) return secure
  const config = {
    baseUrl: process.env.GOOSE_STUDIO_ENDPOINT || process.env.FREE_VIDEO_GEN_ENDPOINT || '',
    apiKey: process.env.GOOSE_STUDIO_API_KEY || process.env.FREE_VIDEO_GEN_API_KEY || '',
    modalWorkspace: process.env.GOOSE_STUDIO_WORKSPACE || '',
    modalEnvironment: process.env.GOOSE_STUDIO_ENVIRONMENT || process.env.MODAL_ENVIRONMENT || 'main',
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
  const clean = line.trimEnd()
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

function startSetup(credentials: { tokenId: string; tokenSecret: string; workspace?: string }) {
  if (setupStatus.state === 'running') throw new Error('Setup is already running')
  if (!credentials.tokenId.trim() || !credentials.tokenSecret.trim()) throw new Error('Modal token ID and secret are required')
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
  environment.MODAL_TOKEN_ID = credentials.tokenId.trim()
  environment.MODAL_TOKEN_SECRET = credentials.tokenSecret.trim()
  environment.GOOSE_STUDIO_WORKSPACE = typeof credentials.workspace === 'string' ? credentials.workspace.trim() : ''
  const existingConfig = runtimeConfig()
  if (existingConfig.apiKey) environment.GOOSE_STUDIO_EXISTING_API_KEY = existingConfig.apiKey
  credentials.tokenId = ''
  credentials.tokenSecret = ''
  const child = spawn(command, args, {
    cwd: resourceRoot,
    env: environment,
    shell: false,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

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
  child.stdout.on('data', (chunk: Buffer) => consume(chunk))
  child.stderr.on('data', (chunk: Buffer) => consume(chunk, true))
  child.on('error', (error) => {
    const message = error.message || 'Could not start the setup process'
    appendSetupLine(`[error] ${message}`)
    setupStatus = { ...setupStatus, state: 'failed', returncode: 1, error: message }
  })
  child.on('close', (code) => {
    consumeLine(stdoutBuffer)
    appendSetupLine(stderrBuffer)
    try {
      if (code === 0 && setupResult) {
        saveSecureConfig({ baseUrl: setupResult.endpoint, apiKey: setupResult.apiKey, modalWorkspace: setupResult.workspace, modalEnvironment: setupResult.environment })
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
  })
  return { state: 'running' as const }
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
  ipcMain.handle('desktop:get-config', runtimeConfig)
  ipcMain.handle('desktop:start-setup', (_event, credentials) => startSetup(credentials))
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
