function pct(v) {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}

// Color + texto por veredicto. Reusa las CSS vars del sistema.
const VERDICT_META = {
  SIN_VALOR:      { color: 'var(--red)',    bg: 'var(--red-lo)',    label: 'SIN VALOR' },
  NO_CONCLUYENTE: { color: 'var(--yellow)', bg: 'var(--yellow-lo)', label: 'NO CONCLUYENTE' },
  VALOR:          { color: 'var(--green)',  bg: 'var(--green-lo)',  label: 'VALOR' },
  NO_EVALUABLE:   { color: 'var(--sub)',    bg: 'var(--card-deep)', label: 'NO EVALUABLE' },
}

export default function BetBuilderVerdict({ data }) {
  const {
    veredicto,
    prob_techo,
    prob_impl_combinada,
    n_modelables,
    n_exoticas,
    exoticas = [],
    faltantes = [],
    kelly_fraccion,
  } = data

  const meta = VERDICT_META[veredicto] ?? { color: 'var(--sub)', bg: 'var(--card-deep)', label: veredicto }

  return (
    <div className="bb-verdict">
      <div className="bb-verdict-bar" style={{ background: meta.color }} />

      <div className="bb-verdict-body">
        <div className="bb-verdict-head">
          <span className="bb-verdict-kicker">Bet Builder · veredicto por techo</span>
          <span
            className="bb-verdict-chip"
            style={{ background: meta.bg, borderColor: meta.color, color: meta.color }}
          >
            {meta.label}
          </span>
        </div>

        <div className="bb-verdict-metrics">
          <div className="bb-metric">
            <div className="bb-metric-label">Techo (mejor caso)</div>
            <div className="bb-metric-value">{pct(prob_techo)}</div>
          </div>
          <div className="bb-metric">
            <div className="bb-metric-label">La casa pide</div>
            <div className="bb-metric-value">{pct(prob_impl_combinada)}</div>
          </div>
          <div className="bb-metric">
            <div className="bb-metric-label">Patas modeladas</div>
            <div className="bb-metric-value">{n_modelables}/{n_modelables + n_exoticas}</div>
          </div>
          {kelly_fraccion != null && (
            <div className="bb-metric">
              <div className="bb-metric-label">Kelly (20%)</div>
              <div className="bb-metric-value">{(kelly_fraccion * 100).toFixed(1)}%</div>
            </div>
          )}
        </div>

        {n_exoticas > 0 && (
          <div className="bb-exoticas">
            <div className="bb-exoticas-label">Patas no modeladas ({n_exoticas})</div>
            <ul className="bb-exoticas-list">
              {exoticas.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
            <p className="bb-exoticas-note">
              El techo es una cota superior: estas patas solo pueden bajar la probabilidad real.
            </p>
          </div>
        )}

        {faltantes.length > 0 && (
          <div className="faltantes-box">
            <h4>Datos pendientes ({faltantes.length})</h4>
            <ul>
              {faltantes.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
            <p className="hint">
              Mercado conocido (tiros al arco por jugador) aún sin fuente de datos.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
