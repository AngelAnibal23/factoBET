import { useState } from 'react'
import { ApiError } from './api.js'
import UploadZone from './components/UploadZone.jsx'
import Spinner from './components/Spinner.jsx'
import Ticket from './components/Ticket.jsx'
import SelectionCard from './components/SelectionCard.jsx'
import CorrelationAlert from './components/CorrelationAlert.jsx'
import Disclaimer from './components/Disclaimer.jsx'

function LogoBars() {
  return (
    <svg width="22" height="16" viewBox="0 0 22 16" fill="none" aria-hidden="true">
      <rect x="0"  y="13" width="3" height="3"  rx="1" fill="var(--green)" opacity="0.4" />
      <rect x="5"  y="9"  width="3" height="7"  rx="1" fill="var(--green)" opacity="0.55" />
      <rect x="10" y="5"  width="3" height="11" rx="1" fill="var(--green)" opacity="0.72" />
      <rect x="15" y="2"  width="3" height="14" rx="1" fill="var(--green)" opacity="0.87" />
      <rect x="20" y="0"  width="2" height="16" rx="1" fill="var(--green)" />
    </svg>
  )
}

// States: idle | uploading | result | error
export default function App() {
  const [state, setState] = useState('idle')
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [meta, setMeta] = useState(null)
  const [apiError, setApiError] = useState(null)

  async function handleSubmit() {
    if (!file) return
    setState('uploading')
    setApiError(null)
    try {
      const rawRes = await fetch('/api/v1/parlay/analizar', {
        method: 'POST',
        body: (() => { const f = new FormData(); f.append('imagen', file); return f })(),
      })
      const json = await rawRes.json()
      if (!json.success) {
        const e = json.error || {}
        throw new ApiError(e.message || 'Error desconocido', e.code, e.detalle)
      }
      setResult(json.data)
      setMeta(json.meta)
      setState('result')
    } catch (err) {
      setApiError(err)
      setState('error')
    }
  }

  function reset() {
    setState('idle')
    setFile(null)
    setResult(null)
    setMeta(null)
    setApiError(null)
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-logo">
          <LogoBars />
          <span className="logo-name">helpBETOR</span>
          <span className="logo-tag">Auditor estadístico<br />Liga 1 Peruana</span>
        </div>

        <div className="status-pill">
          <span className="status-dot" />
          Dixon-Coles v0.2 · 996 partidos
        </div>

        {state === 'result'
          ? <button className="btn-new" onClick={reset}>← Nueva consulta</button>
          : <div className="topbar-spacer" />
        }
      </header>

      {(state === 'idle' || state === 'uploading') && (
        <div className="upload-screen">
          <UploadZone
            file={file}
            onFile={setFile}
            onSubmit={handleSubmit}
            loading={state === 'uploading'}
          />
          {state === 'uploading' && <Spinner />}
        </div>
      )}

      {state === 'error' && (
        <div className="error-banner">
          <h3>{apiError?.code ?? 'Error'}</h3>
          <p>{apiError?.message ?? 'Ocurrió un error inesperado.'}</p>
          {apiError?.detalle && (
            <p style={{ marginTop: 6, fontSize: '12px' }}>{apiError.detalle}</p>
          )}
          <button className="btn-retry" onClick={reset}>Intentar de nuevo</button>
        </div>
      )}

      {state === 'result' && result && (
        <div className="results-wrap">
          <Ticket resumen={result.resumen} meta={meta} />

          {result.resumen.tiene_correlaciones && (
            <CorrelationAlert correlaciones={result.correlaciones} />
          )}

          <p className="section-label">Selecciones ({result.selecciones.length})</p>
          <div className="sel-grid">
            {result.selecciones.map((sel, i) => (
              <SelectionCard key={i} sel={sel} index={i + 1} />
            ))}
          </div>

          <Disclaimer texto={result.disclaimer} />
        </div>
      )}
    </>
  )
}
