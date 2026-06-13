import { useRef, useState } from 'react'

const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']

function UploadIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <path d="M18 6v18M11 13l7-7 7 7" stroke="var(--sub)" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 26v3a3 3 0 003 3h22a3 3 0 003-3v-3"
        stroke="var(--sub)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

export default function UploadZone({ onFile, file, onSubmit, loading }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  function handleFiles(files) {
    const f = files[0]
    if (!f) return
    if (!ACCEPTED.includes(f.type)) {
      alert('Solo se aceptan imágenes JPG, PNG o WEBP.')
      return
    }
    if (f.size > 5 * 1024 * 1024) {
      alert('La imagen no puede superar 5 MB.')
      return
    }
    onFile(f)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }

  const previewUrl = file ? URL.createObjectURL(file) : null

  return (
    <div className="upload-wrap">
      <div
        className={`upload-zone${dragOver ? ' drag-over' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !file && inputRef.current.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={e => handleFiles(e.target.files)}
        />

        {!file ? (
          <>
            <div className="upload-league-pill">Liga 1 Peruana</div>
            <div className="upload-icon-wrap"><UploadIcon /></div>
            <div className="upload-title">Sube tu parlay</div>
            <div className="upload-sub">
              Captura la pantalla de tu app de apuestas y sube la imagen
            </div>
            <div className="upload-casas">
              Betano · Inkabet · Codere · Betsafe · Bet365
            </div>
            <div className="upload-formats">
              <span className="fmt-badge">JPG</span>
              <span className="fmt-badge">PNG</span>
              <span className="fmt-badge">WEBP</span>
              <span className="fmt-badge">máx 5 MB</span>
            </div>
            <button
              type="button"
              className="btn-cta"
              onClick={e => { e.stopPropagation(); inputRef.current.click() }}
            >
              Seleccionar imagen
            </button>
          </>
        ) : (
          <div className="upload-preview">
            <img src={previewUrl} alt="preview" className="preview-img" />
            <div className="preview-name">
              {file.name} · {(file.size / 1024).toFixed(0)} KB
            </div>
            <button
              type="button"
              className="btn-change"
              onClick={e => {
                e.stopPropagation()
                onFile(null)
                inputRef.current.value = ''
              }}
            >
              Cambiar imagen
            </button>
          </div>
        )}
      </div>

      <button
        className="btn-analizar"
        onClick={onSubmit}
        disabled={!file || loading}
      >
        {loading ? 'Analizando…' : 'Analizar parlay'}
      </button>

      <div className="model-strip">
        <div className="model-strip-cell">
          <span className="ms-value">996</span>
          <span className="ms-label">Partidos</span>
        </div>
        <div className="model-strip-cell">
          <span className="ms-value">2022–2024</span>
          <span className="ms-label">Temporadas</span>
        </div>
        <div className="model-strip-cell">
          <span className="ms-value">Dixon-Coles</span>
          <span className="ms-label">Modelo</span>
        </div>
      </div>
    </div>
  )
}
