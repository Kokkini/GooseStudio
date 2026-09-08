import { ArrowRight, Box, Check, ChevronDown, ChevronLeft, ChevronRight, CircleAlert, Clock3, CloudCog, Download, ExternalLink, FlaskConical, Image, LoaderCircle, RefreshCw, Shirt, Sparkles, Trash2, Video, WandSparkles, X } from 'lucide-react'
import gooseStudioLogo from './assets/logo-abstract-orbit.svg'
import { useEffect, useRef, useState } from 'react'
import { cancelJob, checkConnection, deleteJob, downloadOutput, getJob, getWorkflowCapabilities, installWorkflow, submitJob, submitVoxelizationJob, uploadInputs } from './api.ts'
import FileDrop from './components/FileDrop.tsx'
import AppLogDialog from './components/AppLogDialog.tsx'
import SetupDialog from './components/SetupDialog.tsx'
import SettingsMenu from './components/SettingsMenu.tsx'
import WorkflowInstallDialog from './components/WorkflowInstallDialog.tsx'
import { appendAppLog, getRuntimeConfig } from './desktop.ts'
import { estimateWorkflow, formatCreditEstimate, type WorkflowEstimate } from './estimates.ts'
import type { Job, JobState, OutputFile, RuntimeConfig, VoxelizationOptions, WorkflowInstallStatus, WorkflowKind } from './types.ts'
import { characterSwap, imageEdit, imageTo3d, imageTo3dV2, liteUpscale, outputNodes, textToImage, tryOn } from './workflows.ts'

const workflows = [
  { id: 'text-to-image' as const, name: 'Text to Image', summary: 'Create an image from a prompt', icon: Image, color: 'amber' },
  { id: 'image-edit' as const, name: 'Image Edit', summary: 'Restyle, relight, or transform any image', icon: WandSparkles, color: 'amber' },
  { id: 'try-on' as const, name: 'Virtual Try-On', summary: 'Put product clothing on any person', icon: Shirt, color: 'rose' },
  { id: 'character-swap' as const, name: 'Character Swap', summary: 'Replace a person across a full video', icon: Video, color: 'cyan' },
  { id: 'image-to-3d' as const, name: 'Image to 3D', summary: 'Turn an image into a textured 3D model', icon: Box, color: 'cyan' },
  { id: 'image-to-3d-v2' as const, name: 'Image to 3D v2', summary: 'Create a detailed 3D model from an image', icon: Box, color: 'cyan' },
  { id: 'voxelize' as const, name: 'Voxelize 3D model', summary: 'Turn a GLB model into a .vox file', icon: Box, color: 'cyan' },
  { id: 'lite-upscale' as const, name: 'Image Upscale', summary: 'Upscale one image to four times its size', icon: FlaskConical, color: 'lime' },
]

const builtInWorkflows = new Set<WorkflowKind>(['voxelize'])
const HISTORY_PAGE_SIZE = 12

function workflowReady(workflow: WorkflowKind, installed: WorkflowKind[]) {
  return builtInWorkflows.has(workflow) || installed.includes(workflow)
}

function savedJobs(): Job[] {
  try {
    const jobs = localStorage.getItem('gooseStudioJobs') || localStorage.getItem('freeVideoGenJobs') || '[]'
    return JSON.parse(jobs)
  } catch { return [] }
}

function remoteName(file: File, jobId: string) {
  const extension = file.name.match(/\.[^.]+$/)?.[0] || ''
  return `${jobId}/${crypto.randomUUID().replaceAll('-', '')}${extension}`
}

function modalOverviewUrl(config: RuntimeConfig) {
  const workspace = config.modalWorkspace?.trim()
  const environment = config.modalEnvironment?.trim() || 'main'
  return workspace && environment
    ? `https://modal.com/apps/${encodeURIComponent(workspace)}/${encodeURIComponent(environment)}`
    : 'https://modal.com/apps'
}

function modalUsageUrl(config: RuntimeConfig) {
  const workspace = config.modalWorkspace?.trim()
  return workspace ? `https://modal.com/settings/${encodeURIComponent(workspace)}/usage` : 'https://modal.com/settings'
}

export default function App() {
  const [kind, setKind] = useState<WorkflowKind>('text-to-image')
  const [config, setConfig] = useState<RuntimeConfig>({ baseUrl: '', apiKey: '' })
  const [connected, setConnected] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [setupOpen, setSetupOpen] = useState(false)
  const [setupInstance, setSetupInstance] = useState(0)
  const [setupMode, setSetupMode] = useState<'setup' | 'update' | 'switch'>('setup')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [installed, setInstalled] = useState<WorkflowKind[]>([])
  const [installing, setInstalling] = useState<WorkflowKind | null>(null)
  const [installStatus, setInstallStatus] = useState<WorkflowInstallStatus>({ state: 'idle' })
  const [runs, setRuns] = useState<ActiveWorkflowRuns>({})
  const [history, setHistory] = useState(savedJobs)
  const [historyPage, setHistoryPage] = useState(0)
  const polling = useRef(new Map<string, number>())

  const loadConfig = async () => {
    appendAppLog('Checking Modal connection')
    try {
      const next = await getRuntimeConfig()
      if (!next.baseUrl || !next.apiKey) { setSetupMode('setup'); setSetupOpen(true); return false }
      await checkConnection(next)
      const capabilities = await getWorkflowCapabilities(next)
      setConfig(next)
      setInstalled(capabilities.installed)
      setInstallStatus(capabilities.installation)
      setConnected(true)
      appendAppLog('Modal connection is ready')
      return true
    } catch (error) {
      appendAppLog(`Modal connection unavailable: ${(error as Error).message}`)
      setSetupMode('setup'); setSetupOpen(true); setConnected(false); return false
    }
  }

  useEffect(() => { const timer = window.setTimeout(() => { void loadConfig().finally(() => setInitializing(false)) }, 0); return () => clearTimeout(timer) }, [])
  useEffect(() => () => { polling.current.forEach((timer) => clearInterval(timer)); polling.current.clear() }, [])
  useEffect(() => {
    if (!installing || installStatus.state !== 'running') return
    const timer = window.setInterval(async () => {
      try {
        const capabilities = await getWorkflowCapabilities(config)
        setInstalled(capabilities.installed)
        setInstallStatus(capabilities.installation)
      } catch (error) {
        setInstallStatus({ state: 'failed', workflow: installing, error: (error as Error).message })
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [config, installing, installStatus.state])

  if (initializing) return <StartupLoadingScreen />

  const updateWorkflowRun = (workflow: WorkflowKind, update: Partial<ActiveWorkflowRun>) => {
    setRuns((current) => ({ ...current, [workflow]: { ...(current[workflow] || idleWorkflowRun()), ...update } }))
  }

  const updateCurrentWorkflowRun = (workflow: WorkflowKind, jobId: string, update: Partial<ActiveWorkflowRun>) => {
    setRuns((current) => {
      const active = current[workflow]
      if (!active || active.job?.job_id !== jobId) return current
      return { ...current, [workflow]: { ...active, ...update } }
    })
  }

  const stopPolling = (jobId: string) => {
    const timer = polling.current.get(jobId)
    if (timer !== undefined) {
      clearInterval(timer)
      polling.current.delete(jobId)
    }
  }

  const startInstall = async (workflow: WorkflowKind) => {
    if (!connected) { setSetupOpen(true); return }
    appendAppLog(`Starting ${workflow} workflow installation`)
    setInstalling(workflow)
    setInstallStatus({ state: 'running', workflow, current: 0, total: 1, message: 'Starting installation...' })
    try {
      await installWorkflow(config, workflow)
      appendAppLog(`Finished ${workflow} workflow installation`)
    } catch (error) {
      appendAppLog(`${workflow} workflow installation failed: ${(error as Error).message}`)
      setInstallStatus({ state: 'failed', workflow, error: (error as Error).message })
    }
  }

  const complete = (next: Job, workflow: WorkflowKind) => {
    const stored = { ...next, workflow, completed_at: new Date().toISOString() }
    const updated = [stored, ...savedJobs().filter((item) => item.job_id !== next.job_id)].slice(0, 20)
    localStorage.setItem('gooseStudioJobs', JSON.stringify(updated))
    setHistory(updated)
    setHistoryPage(0)
    updateCurrentWorkflowRun(workflow, next.job_id, { job: stored, state: 'completed', message: 'Your creation is ready', retry: null })
    appendAppLog(`${workflow} job ${next.job_id} completed`)
  }

  const removeCreation = async (creation: Job) => {
    if (!window.confirm('Delete this creation?')) return
    try {
      if (connected) await deleteJob(config, creation.job_id)
      const updated = savedJobs().filter((item) => item.job_id !== creation.job_id)
      localStorage.setItem('gooseStudioJobs', JSON.stringify(updated))
      setHistory(updated)
      setHistoryPage((current) => Math.min(current, Math.max(0, Math.ceil(updated.length / HISTORY_PAGE_SIZE) - 1)))
      const workflow = creation.workflow || kind
      updateCurrentWorkflowRun(workflow, creation.job_id, idleWorkflowRun())
      appendAppLog(`Deleted ${creation.workflow || 'creation'} job ${creation.job_id}`)
    } catch (error) {
      appendAppLog(`Could not delete job ${creation.job_id}: ${(error as Error).message}`)
      if (!creation.workflow || creation.workflow === kind) updateWorkflowRun(kind, { message: 'Could not delete this creation' })
    }
  }

  const poll = (jobId: string, workflow: WorkflowKind) => {
    const check = async () => {
      try {
        const next = await getJob(config, jobId)
        if (next.status === 'completed') { stopPolling(jobId); complete(next, workflow) }
        else if (next.status === 'failed') { stopPolling(jobId); appendAppLog(`${workflow} job ${jobId} failed: ${next.error || 'Generation failed'}`); updateCurrentWorkflowRun(workflow, jobId, { job: next, state: 'failed', message: next.error || 'Generation failed' }) }
        else {
          const cpuJob = workflow === 'voxelize'
          updateCurrentWorkflowRun(workflow, jobId, { job: next, state: next.status === 'running' ? 'running' : 'queued', message: next.status === 'running' ? (cpuJob ? 'Converting on Modal' : 'Creating on your Modal GPU') : (cpuJob ? 'Waiting for Modal' : 'Waiting for a GPU') })
        }
      } catch (error) { stopPolling(jobId); appendAppLog(`${workflow} job ${jobId} status check failed: ${(error as Error).message}`); updateCurrentWorkflowRun(workflow, jobId, { state: 'failed', message: (error as Error).message }) }
    }
    void check()
    polling.current.set(jobId, window.setInterval(check, 5000))
  }

  const run = async (workflow: WorkflowKind, files: File[], build: (names: string[], jobId: string) => Promise<Record<string, unknown>[]>, repeat: () => void, options: RunOptions = {}) => {
    if (!connected) { setSetupOpen(true); return }
    if (!workflowReady(workflow, installed)) { await startInstall(workflow); return }
    const jobId = crypto.randomUUID()
    updateWorkflowRun(workflow, { job: { job_id: jobId, status: 'preparing', outputs: [] }, state: files.length ? 'uploading' : 'preparing', message: files.length ? 'Uploading your media directly to Modal' : 'Preparing the ComfyUI workflow', retry: repeat })
    try {
      appendAppLog(`Starting ${workflow} job ${jobId}`)
      const names = files.map((file) => remoteName(file, jobId))
      if (files.length) {
        const uploadMap = new Map(names.map((name, index) => [name.split('/')[1], files[index]]))
        await uploadInputs(config, jobId, uploadMap)
      }
      updateCurrentWorkflowRun(workflow, jobId, { state: 'preparing', message: 'Preparing the ComfyUI workflow' })
      const prepared = await build(names, jobId)
      await submitJob(config, jobId, prepared as never, outputNodes[workflow], workflow === 'character-swap' ? 'video' : 'image', options.postprocess)
      appendAppLog(`Submitted ${workflow} job ${jobId}`)
      updateCurrentWorkflowRun(workflow, jobId, { job: { job_id: jobId, status: 'queued', outputs: [] }, state: 'queued', message: 'Waiting for a GPU' })
      poll(jobId, workflow)
    } catch (error) {
      appendAppLog(`${workflow} job failed before completion: ${(error as Error).message}`)
      updateCurrentWorkflowRun(workflow, jobId, { state: 'failed', message: (error as Error).message })
    }
  }

  const runVoxelize = async (file: File, resolution: number, repeat: () => void) => {
    if (!connected) { setSetupOpen(true); return }
    const jobId = crypto.randomUUID()
    updateWorkflowRun('voxelize', { job: { job_id: jobId, status: 'preparing', outputs: [] }, state: 'uploading', message: 'Uploading your GLB directly to Modal', retry: repeat })
    try {
      const inputName = remoteName(file, jobId)
      appendAppLog(`Starting voxelize job ${jobId}`)
      await uploadInputs(config, jobId, new Map([[inputName.split('/')[1], file]]))
      updateCurrentWorkflowRun('voxelize', jobId, { state: 'preparing', message: 'Preparing voxel conversion' })
      await submitVoxelizationJob(config, jobId, inputName, resolution)
      appendAppLog(`Submitted voxelize job ${jobId}`)
      updateCurrentWorkflowRun('voxelize', jobId, { job: { job_id: jobId, status: 'queued', outputs: [] }, state: 'queued', message: 'Waiting for Modal' })
      poll(jobId, 'voxelize')
    } catch (error) {
      appendAppLog(`voxelize job failed before completion: ${(error as Error).message}`)
      updateCurrentWorkflowRun('voxelize', jobId, { state: 'failed', message: (error as Error).message })
    }
  }

  const cancel = async () => {
    const active = runs[kind]
    if (!active?.job || !['queued', 'running'].includes(active.job.status)) return
    await cancelJob(config, active.job.job_id)
    stopPolling(active.job.job_id)
    appendAppLog(`Cancelled job ${active.job.job_id}`)
    updateCurrentWorkflowRun(kind, active.job.job_id, { job: { ...active.job, status: 'failed' }, state: 'failed', message: 'Job cancelled' })
  }

  const updateCloudApp = () => {
    setSettingsOpen(false)
    setSetupMode('update')
    setSetupInstance((current) => current + 1)
    setSetupOpen(true)
  }

  const switchModalAccount = () => {
    setSettingsOpen(false)
    setSetupMode('switch')
    setSetupInstance((current) => current + 1)
    setSetupOpen(true)
  }

  const selected = workflows.find((item) => item.id === kind)!
  const selectedRun = runs[kind] || idleWorkflowRun()
  const historyPageCount = Math.max(1, Math.ceil(history.length / HISTORY_PAGE_SIZE))
  const visibleHistory = history.slice(historyPage * HISTORY_PAGE_SIZE, (historyPage + 1) * HISTORY_PAGE_SIZE)
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><img src={gooseStudioLogo} alt="" /></span><div><strong>Goose Studio</strong><small>Powered by your Modal credits</small></div></div>
        <div className="connection-state"><span className={connected ? 'online' : ''} />{connected ? 'Modal connected' : 'Setup required'}{!connected && <button className="setup-modal-button" onClick={() => { setSetupMode('setup'); setSetupOpen(true) }}><CloudCog size={16} /> Setup Modal</button>}<SettingsMenu open={settingsOpen} usageUrl={modalUsageUrl(config)} onToggle={() => setSettingsOpen((current) => !current)} onClose={() => setSettingsOpen(false)} onViewLog={() => setLogOpen(true)} onUpdateApp={updateCloudApp} onSwitchAccount={switchModalAccount} /></div>
      </header>

      <main>
        <section className="hero">
          <p className="eyebrow">Private AI studio</p>
          <h1>Create product content<br /><em>without a subscription.</em></h1>
          <p>Your files go straight to your own Modal workspace. Pick a tool and start creating.</p>
        </section>

        <section className="tool-picker">
          {workflows.map((item) => <button key={item.id} className={`tool-card ${item.color} ${kind === item.id ? 'active' : ''}`} onClick={() => setKind(item.id)}><span className="tool-icon"><item.icon /></span><span><strong>{item.name}</strong><small>{item.summary}</small>{connected && <em className={`install-badge ${workflowReady(item.id, installed) ? 'installed' : ''}`}>{workflowReady(item.id, installed) ? 'Installed' : 'Install required'}</em>}</span><ArrowRight className="tool-arrow" /></button>)}
        </section>

        <section className="studio">
          <div className="studio-heading"><div><p className={`tool-label ${selected.color}`}><selected.icon size={15} /> {selected.name}</p><h2>{selected.summary}</h2></div><span className="private-badge"><Check size={14} /> Runs privately in Modal</span></div>
          <div className="studio-grid">
            <div className="controls">
              {kind === 'image-edit' && <ImageEditForm run={run} installed={installed.includes(kind)} install={() => startInstall(kind)} />}
              {kind === 'lite-upscale' && <LiteForm run={run} installed={installed.includes(kind)} install={() => startInstall(kind)} />}
              {kind === 'text-to-image' && <TextToImageForm run={run} installed={installed.includes(kind)} install={() => startInstall(kind)} />}
              {kind === 'try-on' && <TryOnForm run={run} installed={installed.includes(kind)} install={() => startInstall(kind)} />}
              {kind === 'character-swap' && <CharacterSwapForm run={run} installed={installed.includes(kind)} install={() => startInstall(kind)} />}
              {kind === 'image-to-3d' && <ImageTo3DForm run={run} installed={workflowReady(kind, installed)} install={() => startInstall(kind)} />}
              {kind === 'image-to-3d-v2' && <ImageTo3DForm workflow="image-to-3d-v2" run={run} installed={workflowReady(kind, installed)} install={() => startInstall(kind)} />}
              {kind === 'voxelize' && <VoxelizeForm run={runVoxelize} />}
            </div>
            <ResultPanel state={selectedRun.state} message={selectedRun.message} job={selectedRun.job} config={config} onCancel={cancel} onRetry={selectedRun.retry} />
          </div>
        </section>

        <section className="history-section"><div className="section-title"><div><p className="eyebrow">Recent work</p><h2>Your creations</h2></div><Clock3 /></div>{history.length ? <><div className="history-grid">{visibleHistory.map((item) => <HistoryCard key={item.job_id} item={item} config={config} onOpen={() => { const workflow = item.workflow || 'text-to-image'; setKind(workflow); updateWorkflowRun(workflow, { job: item, state: 'completed', message: 'Loaded from history', retry: null }) }} onDelete={() => { void removeCreation(item) }} />)}</div>{historyPageCount > 1 && <nav className="history-pagination" aria-label="Your creations pages"><button type="button" onClick={() => setHistoryPage((current) => Math.max(0, current - 1))} disabled={historyPage === 0} aria-label="Previous creations page"><ChevronLeft size={16} /></button><span>Page {historyPage + 1} of {historyPageCount}</span><button type="button" onClick={() => setHistoryPage((current) => Math.min(historyPageCount - 1, current + 1))} disabled={historyPage === historyPageCount - 1} aria-label="Next creations page"><ChevronRight size={16} /></button></nav>}</> : <div className="empty-history"><Image /><span>Your finished images, videos, and 3D models will appear here.</span></div>}</section>
      </main>
      <footer><span>Goose Studio</span><span>Files stay in your Modal account</span></footer>
      <SetupDialog key={setupInstance} open={setupOpen} fullScreen mandatory={!connected} mode={setupMode} onClose={() => setSetupOpen(false)} onComplete={loadConfig} />
      <AppLogDialog open={logOpen} onClose={() => setLogOpen(false)} />
      <WorkflowInstallDialog workflow={installing} status={installStatus} onClose={() => { setInstalling(null); setInstallStatus({ state: 'idle' }) }} />
    </div>
  )
}

type RunOptions = { postprocess?: VoxelizationOptions }
type Run = (workflow: WorkflowKind, files: File[], build: (names: string[], id: string) => Promise<Record<string, unknown>[]>, repeat: () => void, options?: RunOptions) => Promise<void>
type InstallableFormProps = { run: Run; installed: boolean; install: () => void }
type VoxelizeRun = (file: File, resolution: number, repeat: () => void) => Promise<void>
type ActiveWorkflowRun = { job: Job | null; state: JobState; message: string; retry: null | (() => void) }
type ActiveWorkflowRuns = Partial<Record<WorkflowKind, ActiveWorkflowRun>>

function idleWorkflowRun(): ActiveWorkflowRun {
  return { job: null, state: 'idle', message: 'Ready when you are', retry: null }
}

function StartupLoadingScreen() {
  return <main className="startup-loading" aria-live="polite" aria-busy="true"><div className="startup-loading-content"><LoaderCircle className="spin" size={32} /><strong>Loading Goose Studio...</strong></div></main>
}

function HistoryCard({ item, config, onOpen, onDelete }: { item: Job; config: RuntimeConfig; onOpen: () => void; onDelete: () => void }) {
  const label = item.workflow?.replaceAll('-', ' ') || 'creation'
  const output = item.outputs[0]
  return <article className="history-card"><button className="history-card-open" type="button" onClick={onOpen}>{output && isImageOutput(output) ? <OutputThumbnail output={output} jobId={item.job_id} config={config} /> : output && isModelOutput(output) ? <div className="model-thumb"><Box /></div> : <div className="video-thumb"><Video /></div>}<span><strong>{label}</strong><small>{item.completed_at ? new Date(item.completed_at).toLocaleString() : 'Completed'}</small></span></button><button className="history-delete" type="button" onClick={onDelete} aria-label={`Delete ${label} creation`} title="Delete creation"><Trash2 size={15} /></button></article>
}

function WorkflowButton({ installed, disabled, install, generate, estimate, children }: { installed: boolean; disabled: boolean; install: () => void; generate: () => void; estimate?: WorkflowEstimate | null; children: React.ReactNode }) {
  return <button className="generate-button" disabled={installed && disabled} onClick={installed ? generate : install}><span className="generate-content">{installed ? children : <><Download /> Install this workflow to start generating</>}</span>{estimate && <small className="credit-estimate">Estimated credit {formatCreditEstimate(estimate.credits)}</small>}<ArrowRight className="generate-arrow" /></button>
}

function LiteForm({ run, installed, install }: InstallableFormProps) {
  const [file, setFile] = useState<File | null>(null)
  const submit = () => { if (!file) return; run('lite-upscale', [file], (names, id) => liteUpscale(names[0], id) as never, submit) }
  const estimate = file ? estimateWorkflow('lite-upscale') : null
  return <div className="workflow-form"><div className="lite-callout"><FlaskConical /><div><strong>Fast image upscaling</strong><small>Uses one small model in your Modal account.</small></div></div><FileDrop label="Image to upscale" hint="Any JPG, PNG, or WebP image" accept="image/*" file={file} onChange={setFile} /><WorkflowButton installed={installed} disabled={!file} install={install} generate={submit} estimate={estimate}><Sparkles /> Upscale image 4×</WorkflowButton></div>
}

function ImageTo3DForm({ workflow = 'image-to-3d', run, installed, install }: InstallableFormProps & { workflow?: 'image-to-3d' | 'image-to-3d-v2' }) {
  const [file, setFile] = useState<File | null>(null)
  const [model, setModel] = useState<'trellis2' | 'pixal3d'>('trellis2')
  const [voxelize, setVoxelize] = useState(false)
  const [resolution, setResolution] = useState(128)
  const submit = () => { if (!file) return; run(workflow, [file], (names, id) => (workflow === 'image-to-3d-v2' ? imageTo3dV2(names[0], id, model) : imageTo3d(names[0], id)) as never, submit, voxelize ? { postprocess: { type: 'voxelize', resolution } } : undefined) }
  const estimate = file ? estimateWorkflow(workflow, { voxelize, voxelResolution: resolution }) : null
  return <div className="workflow-form"><div className="lite-callout"><Box /><div><strong>{workflow === 'image-to-3d-v2' ? 'Detailed 3D model' : 'Textured 3D model'}</strong><small>Upload one clear image and Goose Studio will create a downloadable 3D model.</small></div></div><FileDrop label="Image to turn into 3D" hint="A clear product image works best" accept="image/*" file={file} onChange={setFile} />{workflow === 'image-to-3d-v2' && <ModelSwitch model={model} setModel={setModel} />}<Toggle label="Also create a voxel model" checked={voxelize} setChecked={setVoxelize} />{voxelize && <VoxelResolution value={resolution} setValue={setResolution} />}<WorkflowButton installed={installed} disabled={!file} install={install} generate={submit} estimate={estimate}><Box /> Create 3D model</WorkflowButton></div>
}

function VoxelizeForm({ run }: { run: VoxelizeRun }) {
  const [file, setFile] = useState<File | null>(null)
  const [resolution, setResolution] = useState(128)
  const submit = () => { if (!file) return; run(file, resolution, submit) }
  const estimate = file ? estimateWorkflow('voxelize', { voxelResolution: resolution }) : null
  return <div className="workflow-form"><div className="lite-callout"><Box /><div><strong>Voxel model</strong><small>Upload a GLB model and Goose Studio will create a MagicaVoxel .vox file.</small></div></div><FileDrop label="3D model to voxelize" hint="Upload a .glb file" accept=".glb,model/gltf-binary" file={file} onChange={setFile} /><VoxelResolution value={resolution} setValue={setResolution} /><WorkflowButton installed disabled={!file} install={() => undefined} generate={submit} estimate={estimate}><Box /> Create .vox file</WorkflowButton></div>
}

function VoxelResolution({ value, setValue }: { value: number; setValue: (value: number) => void }) {
  const update = (raw: string) => {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) setValue(Math.max(1, Math.min(256, Math.round(parsed))))
  }
  return <label className="voxel-resolution"><span><strong>Voxel resolution</strong><small>Longest side of the object</small></span><input className="voxel-resolution-number" type="number" min="1" max="256" step="1" value={value} onChange={(event) => update(event.target.value)} aria-label="Voxel resolution" /><input type="range" min="1" max="256" value={value} onChange={(event) => update(event.target.value)} aria-label="Voxel resolution slider" /></label>
}

function TextToImageForm({ run, installed, install }: InstallableFormProps) {
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState<'square' | 'portrait' | 'landscape'>('square')
  const dimensions = size === 'portrait' ? [768, 1152] : size === 'landscape' ? [1152, 768] : [1024, 1024]
  const submit = () => { if (!prompt.trim()) return; run('text-to-image', [], (_names, id) => textToImage({ prompt, width: dimensions[0], height: dimensions[1], steps: 8, seed: 0 }, id) as never, submit) }
  const estimate = prompt.trim() ? estimateWorkflow('text-to-image', { width: dimensions[0], height: dimensions[1] }) : null
  return <div className="workflow-form"><div className="lite-callout"><Sparkles /><div><strong>Text to image</strong><small>Describe what you want to see, and Goose Studio will create it.</small></div></div><label className="field-label">Describe the image<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={6} placeholder="Example: Close-up portrait of a beautiful woman, smiling, with sunlight on her face" /></label><div className="size-switch"><button className={size === 'square' ? 'active' : ''} onClick={() => setSize('square')}>Square<small>1024 × 1024</small></button><button className={size === 'portrait' ? 'active' : ''} onClick={() => setSize('portrait')}>Portrait<small>768 × 1152</small></button><button className={size === 'landscape' ? 'active' : ''} onClick={() => setSize('landscape')}>Landscape<small>1152 × 768</small></button></div><WorkflowButton installed={installed} disabled={!prompt.trim()} install={install} generate={submit} estimate={estimate}><WandSparkles /> Generate image</WorkflowButton></div>
}

function ImageEditForm({ run, installed, install }: InstallableFormProps) {
  const [files, setFiles] = useState<(File | null)[]>([null, null, null])
  const [prompt, setPrompt] = useState('')
  const [negativePrompt, setNegative] = useState('')
  const [mode, setMode] = useState<'speed' | 'quality'>('speed')
  const submit = () => { if (!files[0] || !prompt.trim()) return; const actual = files.filter(Boolean) as File[]; run('image-edit', actual, (names, id) => imageEdit({ prompt, negativePrompt, mode, speedSteps: 6, qualitySteps: 20, seed: 0 }, names, id) as never, submit) }
  const estimate = files[0] && prompt.trim() ? estimateWorkflow('image-edit') : null
  return <div className="workflow-form"><div className="drop-row three">{files.map((file, index) => <FileDrop key={index} compact label={index ? `Optional image ${index + 1}` : 'Main image'} hint={index ? 'Add another reference' : 'Drop or choose an image'} accept="image/*" file={file} onChange={(next) => setFiles((current) => current.map((value, i) => i === index ? next : value))} />)}</div><label className="field-label">What should change?<textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} placeholder="Example: Put this product on a clean marble counter with soft morning light..." /></label><ModeSwitch mode={mode} setMode={setMode} /><details className="advanced"><summary>Advanced settings <ChevronDown /></summary><label className="field-label">Negative prompt<textarea value={negativePrompt} onChange={(e) => setNegative(e.target.value)} rows={2} placeholder="Things to avoid" /></label></details><WorkflowButton installed={installed} disabled={!files[0] || !prompt.trim()} install={install} generate={submit} estimate={estimate}><WandSparkles /> Generate image</WorkflowButton></div>
}

function TryOnForm({ run, installed, install }: InstallableFormProps) {
  const [person, setPerson] = useState<File | null>(null), [clothes, setClothes] = useState<File | null>(null)
  const [mode, setMode] = useState<'speed' | 'quality'>('quality'), [count, setCount] = useState(1)
  const submit = () => { if (!person || !clothes) return; run('try-on', [person, clothes], (names, id) => tryOn({ mode, speedSteps: 6, qualitySteps: 20, count }, names, id) as never, submit) }
  const estimate = person && clothes ? estimateWorkflow('try-on', { count }) : null
  return <div className="workflow-form"><div className="drop-row"><FileDrop label="Person photo" hint="Front-facing works best" accept="image/*" file={person} onChange={setPerson} /><div className="plus">+</div><FileDrop label="Clothing photo" hint="Use a clear product image" accept="image/*" file={clothes} onChange={setClothes} /></div><ModeSwitch mode={mode} setMode={setMode} /><label className="field-label count-field">Number of variations <span className="count-control"><button onClick={() => setCount(Math.max(1, count - 1))}>−</button><strong>{count}</strong><button onClick={() => setCount(Math.min(6, count + 1))}>+</button></span></label><WorkflowButton installed={installed} disabled={!person || !clothes} install={install} generate={submit} estimate={estimate}><Shirt /> Try on clothing</WorkflowButton></div>
}

function CharacterSwapForm({ run, installed, install }: InstallableFormProps) {
  const [video, setVideo] = useState<File | null>(null), [character, setCharacter] = useState<File | null>(null), [voice, setVoice] = useState<File | null>(null)
  const [upscale, setUpscale] = useState(true), [characterOnly, setCharacterOnly] = useState(true)
  const duration = useVideoDuration(video)
  const submit = () => { if (!video || !character) return; const files = [video, character, ...(voice ? [voice] : [])]; run('character-swap', files, (names, id) => characterSwap({ width: 480, height: 848, steps: 4, seed: 42, maskGrow: 8, objectDescription: 'bag', characterOnly, upscale }, names, id) as never, submit) }
  const estimate = video && character ? estimateWorkflow('character-swap', { durationSeconds: duration, upscale, voice: Boolean(voice) }) : null
  return <div className="workflow-form"><div className="drop-row"><FileDrop label="Source video" hint="The movement to preserve" accept="video/*" file={video} onChange={setVideo} /><div className="plus">+</div><FileDrop label="New character" hint="A clear full-body image" accept="image/*" file={character} onChange={setCharacter} /></div><FileDrop compact label="Optional voice sample" hint="Add audio to convert the original voice" accept="audio/*" file={voice} onChange={setVoice} /><div className="toggle-row"><Toggle label="Upscale final video" checked={upscale} setChecked={setUpscale} /><Toggle label="Keep the object the person is holding" checked={characterOnly} setChecked={setCharacterOnly} /></div><WorkflowButton installed={installed} disabled={!video || !character} install={install} generate={submit} estimate={estimate}><Video /> Generate video</WorkflowButton></div>
}

function useVideoDuration(file: File | null) {
  const [metadata, setMetadata] = useState<{ file: File; duration: number } | null>(null)
  useEffect(() => {
    if (!file) return

    let active = true
    const source = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'metadata'
    const onMetadata = () => {
      if (active && Number.isFinite(video.duration) && video.duration > 0) setMetadata({ file, duration: video.duration })
    }
    video.addEventListener('loadedmetadata', onMetadata)
    video.src = source
    video.load()
    return () => {
      active = false
      video.removeEventListener('loadedmetadata', onMetadata)
      video.removeAttribute('src')
      video.load()
      URL.revokeObjectURL(source)
    }
  }, [file])
  return file && metadata?.file === file ? metadata.duration : null
}

function ModeSwitch({ mode, setMode }: { mode: 'speed' | 'quality'; setMode: (mode: 'speed' | 'quality') => void }) { return <div className="mode-switch"><button className={mode === 'speed' ? 'active' : ''} onClick={() => setMode('speed')}><Sparkles size={15} /> Speed</button><button className={mode === 'quality' ? 'active' : ''} onClick={() => setMode('quality')}><WandSparkles size={15} /> Quality</button></div> }

function ModelSwitch({ model, setModel }: { model: 'trellis2' | 'pixal3d'; setModel: (model: 'trellis2' | 'pixal3d') => void }) { return <div className="model-choice"><label>3D model</label><div className="mode-switch model-switch"><button className={model === 'trellis2' ? 'active' : ''} onClick={() => setModel('trellis2')}>Trellis 2</button><button className={model === 'pixal3d' ? 'active' : ''} onClick={() => setModel('pixal3d')}>Pixal3D</button></div></div> }
function Toggle({ label, checked, setChecked }: { label: string; checked: boolean; setChecked: (value: boolean) => void }) { return <label className="toggle"><button className={checked ? 'on' : ''} onClick={() => setChecked(!checked)}><span /></button>{label}</label> }

function useOutputSource(config: RuntimeConfig, jobId: string, outputId: string) {
  const [source, setSource] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    downloadOutput(config, jobId, outputId).then((blob) => {
      if (!active) return
      objectUrl = URL.createObjectURL(blob)
      setSource(objectUrl)
    }).catch((reason) => { if (active) setError((reason as Error).message) })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [config, jobId, outputId])
  return { source, error }
}

function OutputThumbnail({ output, jobId, config }: { output: OutputFile; jobId: string; config: RuntimeConfig }) {
  const { source } = useOutputSource(config, jobId, output.id)
  return source ? <img src={source} alt="" /> : <div className="video-thumb"><LoaderCircle className="spin" /></div>
}

function isImageOutput(output: OutputFile) { return output.content_type.startsWith('image/') }

function isModelOutput(output: OutputFile) { return output.content_type.startsWith('model/') || /\.(glb|gltf|obj|fbx|stl|3mf|dae|usdz|vox|zip)$/i.test(output.filename) }

function isVoxelPackage(output: OutputFile) { return output.filename.toLowerCase().endsWith('.zip') }

function OutputMedia({ output, jobId, config }: { output: OutputFile; jobId: string; config: RuntimeConfig }) {
  const { source, error } = useOutputSource(config, jobId, output.id)
  return <div className="output-media">{source ? <>{isImageOutput(output) ? <img src={source} alt="Generated output" /> : isModelOutput(output) ? <div className="model-output"><Box /><strong>{isVoxelPackage(output) ? '3D package ready' : '3D model ready'}</strong><small>{output.filename}</small></div> : <video src={source} controls />}<a href={source} download={output.filename}><Download size={16} /> Download</a></> : <div className="result-placeholder">{error ? <CircleAlert className="error-icon" /> : <LoaderCircle className="spin" />}<small>{error || 'Loading output...'}</small></div>}</div>
}

function ResultPanel({ state, message, job, config, onCancel, onRetry }: { state: JobState; message: string; job: Job | null; config: RuntimeConfig; onCancel: () => void; onRetry: (() => void) | null }) {
  const busy = ['uploading', 'preparing', 'queued', 'running'].includes(state)
  const canCancel = Boolean(job && ['queued', 'running'].includes(job.status))
  return <aside className={`result-panel ${state}`}><div className="result-title"><span>Output</span>{job && <small>{job.job_id.slice(0, 8)}</small>}</div>{state === 'completed' && job?.outputs.length ? <div className="output-stack">{job.outputs.map((output) => <OutputMedia key={output.id} output={output} jobId={job.job_id} config={config} />)}</div> : <div className="result-placeholder">{busy ? <LoaderCircle className="spin large" /> : state === 'failed' ? <CircleAlert className="error-icon" /> : <Sparkles className="placeholder-icon" />}<strong>{message}</strong><small>{busy ? 'You can leave this page open. We will update it automatically.' : state === 'idle' ? 'Your result will appear here.' : ''}</small>{canCancel && <div className="job-actions"><a className="cancel-button modal-job-link" href={modalOverviewUrl(config)} target="_blank" rel="noreferrer"><ExternalLink size={15} /> View job on Modal</a><button className="cancel-button" onClick={onCancel}><X size={15} /> Cancel job</button></div>}{state === 'failed' && onRetry && <button className="retry-button" onClick={onRetry}><RefreshCw size={15} /> Try again</button>}</div>}</aside>
}
