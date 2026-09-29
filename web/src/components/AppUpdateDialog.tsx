import { CheckCircle2, CircleAlert, Download, LoaderCircle, RefreshCw, X } from 'lucide-react'

export type AppUpdateDialogState =
  | { state: 'checking' }
  | { state: 'available'; currentVersion: string; version: string }
  | { state: 'up-to-date'; currentVersion: string }
  | { state: 'downloading'; version: string; progress: number; transferred: number; total: number | null }
  | { state: 'verifying'; version: string }
  | { state: 'installing'; version: string }
  | { state: 'cancelled'; version: string }
  | { state: 'error'; error: string; version?: string }

interface Props {
  state: AppUpdateDialogState | null
  onClose: () => void
  onRemindLater: () => void
  onInstall: () => void
  onCancelDownload: () => void
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return '0 MB'
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

export default function AppUpdateDialog({ state, onClose, onRemindLater, onInstall, onCancelDownload }: Props) {
  if (!state) return null
  const busy = state.state === 'checking' || state.state === 'downloading' || state.state === 'verifying' || state.state === 'installing'
  const progress = state.state === 'downloading' ? Math.max(0, Math.min(100, state.progress)) : 0
  const transferred = state.state === 'downloading' ? formatBytes(state.transferred) : ''
  const total = state.state === 'downloading' && state.total ? formatBytes(state.total) : ''

  return <div className="dialog-backdrop app-update-backdrop"><section className="setup-dialog app-update-dialog" role="dialog" aria-modal="true" aria-labelledby="app-update-title">
    {!busy && <button className="dialog-close" onClick={onClose} aria-label="Close"><X /></button>}
    <div className="setup-heading">
      <span>{state.state === 'up-to-date' ? <CheckCircle2 /> : state.state === 'error' ? <CircleAlert /> : state.state === 'available' || state.state === 'cancelled' ? <Download /> : <LoaderCircle className={busy ? 'spin' : ''} />}</span>
      <div><p className="kicker">Goose Studio update</p><h2 id="app-update-title">{state.state === 'checking' ? 'Checking for updates' : state.state === 'available' ? 'Update available' : state.state === 'up-to-date' ? 'You’re up to date' : state.state === 'downloading' ? 'Downloading update' : state.state === 'verifying' ? 'Verifying update' : state.state === 'installing' ? 'Starting installer' : state.state === 'cancelled' ? 'Download cancelled' : 'Update failed'}</h2></div>
    </div>

    {state.state === 'checking' && <p className="app-update-copy">Looking for the latest version of Goose Studio...</p>}
    {state.state === 'available' && <p className="app-update-copy">Version <strong>{state.version}</strong> is ready. Download it and run the installer to update Goose Studio.</p>}
    {state.state === 'up-to-date' && <p className="app-update-copy">You’re using the latest version, {state.currentVersion}.</p>}
    {state.state === 'downloading' && <>
      <p className="app-update-copy">Downloading version <strong>{state.version}</strong>…</p>
      <div className="app-update-progress" aria-label={`Download ${Math.round(progress)} percent complete`}><span style={{ width: `${progress}%` }} /></div>
      <small className="app-update-progress-label">{Math.round(progress)}%{total ? ` · ${transferred} of ${total}` : ` · ${transferred}`}</small>
    </>}
    {state.state === 'verifying' && <p className="app-update-copy">Checking the downloaded installer before opening it…</p>}
    {state.state === 'installing' && <p className="app-update-copy">The installer is opening. Goose Studio will close so it can update safely.</p>}
    {state.state === 'cancelled' && <p className="app-update-copy">The download was cancelled. You can check again whenever you’re ready.</p>}
    {state.state === 'error' && <div className="install-failure app-update-error" role="alert"><CircleAlert /><p><strong>Error:</strong> {state.error}</p></div>}

    {state.state === 'available' && <div className="app-update-actions"><button className="app-update-secondary" onClick={onRemindLater}>Remind me later</button><button className="app-update-primary" onClick={onInstall}><Download size={16} /> Download and install</button></div>}
    {state.state === 'downloading' && <div className="app-update-actions"><button className="app-update-secondary" onClick={onCancelDownload}>Cancel download</button></div>}
    {state.state === 'error' && <div className="app-update-actions"><button className="app-update-secondary" onClick={onClose}>Close</button>{state.version && <button className="app-update-primary" onClick={onInstall}><RefreshCw size={15} /> Try again</button>}</div>}
    {state.state === 'cancelled' && <div className="app-update-actions"><button className="app-update-secondary" onClick={onClose}>Close</button>{state.version && <button className="app-update-primary" onClick={onInstall}><Download size={15} /> Download and install</button>}</div>}
    {state.state === 'up-to-date' && <div className="app-update-actions"><button className="app-update-primary" onClick={onClose}>Close</button></div>}
    {state.state === 'checking' && <div className="app-update-actions"><button className="app-update-secondary" onClick={onClose}>Close</button></div>}
  </section></div>
}
