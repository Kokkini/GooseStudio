import { CheckCircle2, CircleAlert, DownloadCloud, LoaderCircle, X } from 'lucide-react'
import type { WorkflowInstallStatus, WorkflowKind } from '../types.ts'

const names: Partial<Record<WorkflowKind, string>> = {
  'lite-upscale': 'Image Upscale',
  'text-to-image': 'Text to Image',
  'image-edit': 'Image Edit',
  'try-on': 'Virtual Try-On',
  'character-swap': 'Character Swap',
  'image-to-3d': 'Image to 3D',
  'image-to-3d-v2': 'Image to 3D v2',
}

interface Props {
  workflow: WorkflowKind | null
  status: WorkflowInstallStatus
  onClose: () => void
}

export default function WorkflowInstallDialog({ workflow, status, onClose }: Props) {
  if (!workflow) return null
  const workflowName = names[workflow] || workflow
  const total = status.total || 1
  const current = status.current || 0
  const complete = status.state === 'completed'
  const failed = status.state === 'failed'
  const errorMessage = status.error || 'Installation failed. Please try again.'
  const detailLines = status.details?.length ? status.details : failed ? [`Error: ${errorMessage}`] : [status.message || 'Starting installation...']
  return <div className="dialog-backdrop"><section className="setup-dialog workflow-install-dialog">
    {status.state !== 'running' && <button className="dialog-close" onClick={onClose}><X /></button>}
    <div className={`setup-heading${failed ? ' setup-heading-error' : ''}`}><span>{complete ? <CheckCircle2 /> : failed ? <CircleAlert /> : <DownloadCloud />}</span><div><p className="kicker">Workflow setup</p><h2>{complete ? 'Ready to generate' : failed ? 'Installation failed' : `Installing ${workflowName}`}</h2></div></div>
    {complete ? <div className="setup-success"><CheckCircle2 /><p>All required models are ready in your Modal account.</p><button onClick={onClose}>Start generating</button></div> : failed ? <div className="install-failure" role="alert"><CircleAlert /><p><strong>Error:</strong> {errorMessage}</p></div> : <>
      <p className="install-explanation">Only missing models are downloaded. Models already used by another workflow are reused automatically.</p>
      <div className="setup-progress"><div><span>{status.message || 'Starting installation...'}</span><strong>{current}/{total}</strong></div><div className="progress-track"><span style={{ width: `${Math.max(6, current / total * 100)}%` }} /></div></div>
      {status.state === 'running' && <p className="install-wait"><LoaderCircle className="spin" /> Keep the app open while Modal prepares this workflow.</p>}
    </>}
    <details className="setup-details" open><summary>Technical details</summary><pre className="setup-console">{detailLines.join('\n')}</pre></details>
  </section></div>
}
