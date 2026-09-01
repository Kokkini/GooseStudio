import { LoaderCircle, RefreshCw, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { getAppLog } from '../desktop.ts'

interface Props {
  open: boolean
  onClose: () => void
}

export default function AppLogDialog({ open, onClose }: Props) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const logRef = useRef<HTMLPreElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setContent(await getAppLog())
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [open, load])

  useEffect(() => {
    if (open && content) {
      requestAnimationFrame(() => {
        if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
      })
    }
  }, [open, content])

  if (!open) return null

  return (
    <div className="dialog-backdrop log-backdrop">
      <section className="setup-dialog app-log-dialog" role="dialog" aria-modal="true" aria-labelledby="app-log-title">
        <button className="dialog-close" onClick={onClose} aria-label="Close app log"><X /></button>
        <div className="app-log-heading"><div><p className="kicker">Diagnostics</p><h2 id="app-log-title">App log</h2></div><button className="log-refresh" onClick={() => void load()} disabled={loading} aria-label="Refresh app log">{loading ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}</button></div>
        <p className="app-log-description">The viewer opens at the newest entries. Scroll up to review earlier activity.</p>
        <pre className="app-log-content" ref={logRef}>{loading && !content ? 'Loading app log...' : error || content || 'No app log entries yet.'}</pre>
      </section>
    </div>
  )
}
