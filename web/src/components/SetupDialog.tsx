import { CheckCircle2, CircleAlert, Cloud, ExternalLink, LoaderCircle, Terminal, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { getModalSetupStatus, startModalSetup } from '../desktop.ts'
import { parseModalTokenCommand } from '../tokenCommand.ts'
import type { SetupStatus } from '../types.ts'

interface Props {
  open: boolean
  fullScreen?: boolean
  mandatory?: boolean
  onClose: () => void
  onComplete: () => Promise<boolean>
}

export default function SetupDialog({ open, fullScreen = false, mandatory = false, onClose, onComplete }: Props) {
  const [tokenCommand, setTokenCommand] = useState('')
  const [workspace, setWorkspace] = useState('')
  const [status, setStatus] = useState<SetupStatus>({ state: 'idle', lines: [] })
  const [error, setError] = useState('')
  const connectionCheck = useRef<Promise<boolean> | null>(null)

  const ensureConnection = useCallback(() => {
    if (!connectionCheck.current) {
      connectionCheck.current = onComplete().catch(() => false)
    }
    return connectionCheck.current
  }, [onComplete])

  useEffect(() => {
    if (status.state !== 'running') return
    const timer = window.setInterval(async () => {
      try {
        const next = await getModalSetupStatus()
        setStatus(next)
        if (next.state === 'completed') void ensureConnection()
      } catch (error) {
        setError((error as Error).message)
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [status.state, ensureConnection])

  useEffect(() => {
    if (!open || !fullScreen) return
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = overflow }
  }, [open, fullScreen])

  if (!open) return null

  const install = async () => {
    setError('')
    const credentials = parseModalTokenCommand(tokenCommand)
    if (!credentials) {
      setError('Paste the complete “modal token set ...” command from Modal, including its --profile value.')
      return
    }
    try {
      setWorkspace(credentials.workspace)
      connectionCheck.current = null
      await startModalSetup(credentials)
      setTokenCommand('')
      setStatus({ state: 'running', lines: ['Starting setup...'] })
    } catch (error) {
      setError((error as Error).message)
    }
  }

  const finish = () => {
    setError('')
    onClose()
    void ensureConnection()
  }

  const failureMessage = 'See Technical details for more information.'
  const completed = status.state === 'completed'

  return (
    <div className={`dialog-backdrop ${fullScreen ? 'setup-page-backdrop' : ''}`}>
      <section className={`setup-dialog ${fullScreen ? 'setup-page' : ''}`} role="dialog" aria-modal="true" aria-labelledby={completed ? 'setup-success-title' : 'setup-title'}>
        {!mandatory && <button className="dialog-close" onClick={onClose} aria-label="Close setup"><X /></button>}
        <div className="setup-page-inner">
          {!completed && <div className="setup-heading"><span><Cloud /></span><div><p className="kicker">One-time setup</p><h2 id="setup-title">Connect your Modal account</h2></div></div>}
          {completed ? (
            <div className="setup-success">
              <CheckCircle2 />
              <h3 id="setup-success-title">Succeeded!</h3>
              <p>Goose Studio is connected and ready to generate.</p>
              <div className="setup-next-step">
                <h4>Unlock the full $30 monthly credit (optional)</h4>
                <p>Modal starts new users with $1 in free monthly credit. Add your payment information to unlock the full $30, or start generating now with the $1 credit.</p>
                <div className="setup-success-actions">
                  <a href={`https://modal.com/settings/${encodeURIComponent(workspace)}/usage`} target="_blank">Modal's billing page <ExternalLink size={16} /></a>
                </div>
              </div>
              {error && <p className="form-error">{error}</p>}
              <button className="setup-start-button" onClick={finish}>Start generating</button>
            </div>
          ) : (
            <div className="setup-page-grid">
              <div className="setup-context">
                <aside className="setup-important">
                  <strong>Important! Read first</strong>
                  <p>Goose Studio uses <a href="https://modal.com" target="_blank">Modal.com</a> underneath to run the cloud GPUs that generate your images and videos. Modal offers a <a href="https://modal.com/pricing" target="_blank">free Starter plan</a> that gives users <b>$30 in free credits each month</b>. That's how Goose Studio can generate for free. To set up the app, you will need to create a Modal account and connect it below.</p>
                </aside>
              </div>
              <div className="setup-instructions">
                <ol className="setup-steps">
                  <li><span>1</span><div><strong>Create a free Modal account</strong><a href="https://modal.com/signup" target="_blank">Create Modal account <ExternalLink size={15} /></a></div></li>
                  <li><span>2</span><div><strong>Create an API token</strong><a href="https://modal.com/settings/profile" target="_blank">Open Modal profile settings <ExternalLink size={15} /></a><ul className="setup-token-steps"><li>Choose <b>API Tokens &amp; Service Users</b>.</li><li>Select <b>New Token</b>.</li><li>Give the token any name.</li></ul></div></li>
                  <li><span>3</span><div><strong>Copy the command Modal gives you</strong><small>Copy the entire line beginning with <code>modal token set</code>. You do not need to run the command yourself.</small></div></li>
                </ol>
                <label className="command-field"><span><Terminal size={17} /> Paste the complete token command</span><textarea value={tokenCommand} onChange={(e) => setTokenCommand(e.target.value)} rows={4} spellCheck={false} placeholder="modal token set --token-id ak-... --token-secret as-... --profile=my-workspace" /></label>
                <p className="credential-note">Your token is used only for this setup and is cleared from the browser as soon as installation starts.</p>
                {error && <p className="form-error">{error}</p>}
                {status.state === 'failed' && <div className="setup-failure" role="alert"><CircleAlert size={22} /><div><strong>Setup failed</strong><p>{failureMessage}</p></div></div>}
                {status.state === 'running' && status.progress ? <div className="setup-progress"><div><span>{status.progress.message}</span><strong>{status.progress.current}/{status.progress.total}</strong></div><div className="progress-track"><span style={{ width: `${Math.max(6, status.progress.current / status.progress.total * 100)}%` }} /></div></div> : null}
                {status.state === 'running' || status.state === 'failed' ? <details className="setup-details" open><summary>Technical details</summary><pre className="setup-console">{status.lines.join('\n')}</pre></details> : null}
                <button className="primary-button" disabled={!tokenCommand.trim() || status.state === 'running'} onClick={install}>{status.state === 'running' ? <><LoaderCircle className="spin" /> Installing in Modal...</> : status.state === 'failed' ? 'Try setup again' : 'Install to my Modal account'}</button>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
