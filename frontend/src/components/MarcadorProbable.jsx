import { useState } from 'react'

function pct(v) {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}

// Marcador más probable del partido (producto principal). El detalle técnico
// (top-5 + 1X2) queda colapsado tras "ver detalle". Solo selecciones por ahora.
export default function MarcadorProbable({ marcadores = [] }) {
  if (!marcadores.length) return null
  return (
    <>
      <p className="section-label">Marcador más probable</p>
      {marcadores.map((m, i) => (
        <MarcadorCard key={i} m={m} />
      ))}
    </>
  )
}

function MarcadorCard({ m }) {
  const [open, setOpen] = useState(false)
  const {
    equipo_local,
    equipo_visitante,
    goles_local,
    goles_visitante,
    probabilidad,
    detalle,
  } = m

  return (
    <div className="marcador">
      <div className="marcador-bar" />
      <div className="marcador-body">
        <div className="marcador-teams">
          <span className="marcador-team">{equipo_local}</span>
          <span className="marcador-score">
            {goles_local}<span className="marcador-dash">-</span>{goles_visitante}
          </span>
          <span className="marcador-team">{equipo_visitante}</span>
        </div>

        <div className="marcador-prob">
          Probabilidad <b>{pct(probabilidad)}</b>
        </div>

        {detalle && (
          <>
            <button
              type="button"
              className="marcador-toggle"
              onClick={() => setOpen(!open)}
            >
              {open ? 'ocultar detalle ▴' : 'ver detalle ▾'}
            </button>
            {open && (
              <MarcadorDetalle
                detalle={detalle}
                local={equipo_local}
                visitante={equipo_visitante}
              />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function MarcadorDetalle({ detalle, local, visitante }) {
  const { top = [], resultado = {} } = detalle
  const max = top.length ? top[0].probabilidad : 1

  return (
    <div className="marcador-detalle">
      <div className="marcador-detalle-label">Top 5 marcadores</div>
      <div className="marcador-top">
        {top.map((t, i) => (
          <div className="marcador-top-row" key={i}>
            <span className="marcador-top-score">{t.marcador}</span>
            <span className="marcador-top-track">
              <span
                className="marcador-top-fill"
                style={{ width: `${max ? (t.probabilidad / max) * 100 : 0}%` }}
              />
            </span>
            <span className="marcador-top-pct">{pct(t.probabilidad)}</span>
          </div>
        ))}
      </div>

      <div className="marcador-detalle-label">Resultado (1X2)</div>
      <div className="marcador-1x2-bar">
        <span className="seg seg-local" style={{ width: `${(resultado.local ?? 0) * 100}%` }} />
        <span className="seg seg-draw" style={{ width: `${(resultado.empate ?? 0) * 100}%` }} />
        <span className="seg seg-away" style={{ width: `${(resultado.visitante ?? 0) * 100}%` }} />
      </div>
      <div className="marcador-1x2-legend">
        <span><i className="dot dot-local" />{local} {pct(resultado.local)}</span>
        <span><i className="dot dot-draw" />Empate {pct(resultado.empate)}</span>
        <span><i className="dot dot-away" />{visitante} {pct(resultado.visitante)}</span>
      </div>
    </div>
  )
}
