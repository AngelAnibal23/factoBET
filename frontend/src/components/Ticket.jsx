function pct(v) {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}

function barGradient(nivel) {
  if (nivel === 'ALTA')  return 'linear-gradient(to right,var(--green) 0%,var(--green) 65%,var(--yellow) 100%)'
  if (nivel === 'MEDIA') return 'linear-gradient(to right,var(--green) 0%,var(--yellow) 45%,var(--yellow) 65%,var(--red) 100%)'
  return 'linear-gradient(to right,var(--yellow) 0%,var(--red) 100%)'
}

const CONF_COLOR = { ALTA: 'var(--green)', MEDIA: 'var(--yellow)', BAJA: 'var(--red)' }
const CONF_BG    = { ALTA: 'var(--green-lo)', MEDIA: 'var(--yellow-lo)', BAJA: 'var(--red-lo)' }

// Etiqueta del modelo según la versión real del parlay (meta.version_modelo).
const MODEL_LABEL = {
  'intl_v0.1': 'Dixon-Coles intl v0.1 · Selecciones',
  'v0.2':      'Dixon-Coles v0.2 · Liga 1 Perú',
}

export default function Ticket({ resumen, meta }) {
  const {
    prob_parlay_modelo,
    prob_parlay_impl,
    cuota_total,
    n_selecciones,
    n_modeladas,
    casa_apuestas,
    margen_aplicado,
    nivel_confianza,
  } = resumen

  const confColor = CONF_COLOR[nivel_confianza] ?? 'var(--sub)'
  const confBg    = CONF_BG[nivel_confianza]    ?? 'var(--card-deep)'

  return (
    <div className="ticket">
      <div className="ticket-bar" style={{ background: barGradient(nivel_confianza) }} />

      <div className="ticket-body">
        <div
          className="ticket-confidence"
          style={{ background: confBg, borderColor: confColor }}
        >
          <div className="ticket-conf-label">Confianza</div>
          <div className="ticket-conf-value" style={{ color: confColor }}>
            {nivel_confianza}
          </div>
        </div>

        <div className="ticket-divider" />

        <div className="ticket-metrics">
          <div className="ticket-metric">
            <div className="tk-label">Prob. modelo</div>
            <div className="tk-value">{pct(prob_parlay_modelo)}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Prob. implícita</div>
            <div className="tk-value">{pct(prob_parlay_impl)}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Cuota total</div>
            <div className="tk-value">{cuota_total ?? '—'}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Casa</div>
            <div className="tk-value" style={{ textTransform: 'capitalize' }}>
              {casa_apuestas ?? '—'}
            </div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Modeladas</div>
            <div className="tk-value">{n_modeladas}/{n_selecciones}</div>
          </div>
        </div>
      </div>

      <div className="ticket-footer">
        <span>
          {MODEL_LABEL[meta?.version_modelo]
            ?? `Dixon-Coles ${meta?.version_modelo ?? ''}`.trim()}
        </span>
        {margen_aplicado != null && (
          <span>Margen {(margen_aplicado * 100).toFixed(1)}% aplicado</span>
        )}
      </div>
    </div>
  )
}
