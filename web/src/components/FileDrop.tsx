import { Box, ImagePlus, Upload, Video, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

interface Props {
  label: string
  hint: string
  accept: string
  file: File | null
  onChange: (file: File | null) => void
  compact?: boolean
}

export default function FileDrop({ label, hint, accept, file, onChange, compact }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const preview = useMemo(() => file ? URL.createObjectURL(file) : '', [file])

  const receive = (next?: File) => {
    if (next) onChange(next)
    setDragging(false)
  }

  return (
    <div
      className={`file-drop ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''} ${compact ? 'compact' : ''}`}
      onClick={() => !file && input.current?.click()}
      onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); receive(event.dataTransfer.files[0]) }}
    >
      <input ref={input} type="file" accept={accept} hidden onChange={(event) => receive(event.target.files?.[0])} />
      {file ? (
        <>
          {file.type.startsWith('video/') ? <video src={preview} muted /> : file.type.startsWith('image/') ? <img src={preview} alt="" /> : <div className="file-preview-generic"><Box /></div>}
          <div className="file-caption"><span>{file.name}</span><small>{(file.size / 1_048_576).toFixed(1)} MB</small></div>
          <button className="remove-file" type="button" aria-label="Remove file" onClick={(event) => { event.stopPropagation(); onChange(null) }}><X size={16} /></button>
        </>
      ) : (
        <div className="drop-empty">
          <span className="drop-icon">{accept.includes('video') ? <Video /> : compact ? <ImagePlus /> : <Upload />}</span>
          <strong>{label}</strong>
          <small>{hint}</small>
        </div>
      )}
    </div>
  )
}
