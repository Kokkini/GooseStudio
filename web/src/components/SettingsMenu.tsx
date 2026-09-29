import { ExternalLink, FileText, KeyRound, RefreshCw, Settings as SettingsIcon, UserRound } from 'lucide-react'
import { useEffect, useRef } from 'react'

interface Props {
  open: boolean
  usageUrl: string
  onToggle: () => void
  onClose: () => void
  onViewLog: () => void
  onCheckAppUpdates: () => void
  canCheckAppUpdates: boolean
  onUpdateApp: () => void
  onSwitchAccount: () => void
  hasSavedModalCredentials: boolean
  onForgetModalAccess: () => void
}

export default function SettingsMenu({ open, usageUrl, onToggle, onClose, onViewLog, onCheckAppUpdates, canCheckAppUpdates, onUpdateApp, onSwitchAccount, hasSavedModalCredentials, onForgetModalAccess }: Props) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) onClose()
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open, onClose])

  return (
    <div className="settings-menu" ref={menuRef}>
      <button className="settings-button" onClick={onToggle} aria-haspopup="menu" aria-expanded={open}>
        <SettingsIcon size={16} /> <span>Settings</span>
      </button>
      {open && <div className="settings-panel" role="menu">
        <button role="menuitem" onClick={() => { onViewLog(); onClose() }}><FileText size={16} /> View app log</button>
        {canCheckAppUpdates && <button role="menuitem" onClick={() => { onCheckAppUpdates(); onClose() }}><RefreshCw size={16} /> Check for app updates</button>}
        <button role="menuitem" onClick={() => { onUpdateApp(); onClose() }}><RefreshCw size={16} /> Update Modal app</button>
        <button role="menuitem" onClick={() => { onSwitchAccount(); onClose() }}><UserRound size={16} /> Switch Modal account</button>
        {hasSavedModalCredentials && <button role="menuitem" onClick={() => { onForgetModalAccess(); onClose() }}><KeyRound size={16} /> Forget saved Modal access</button>}
        <a role="menuitem" href={usageUrl} target="_blank" rel="noreferrer" onClick={onClose}><ExternalLink size={16} /> View Modal's usage</a>
      </div>}
    </div>
  )
}
