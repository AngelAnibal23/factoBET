const MERCADO_LABEL = {
  '1X2': '1X2', over_under: 'Más/Menos', btts: 'Ambos marcan',
  handicap: 'Hándicap', count: 'Conteo', player: 'Jugador', exotic: 'Exótico',
  double_chance: 'Doble oportunidad',
}

const SEL_LABEL = {
  home: 'Local', draw: 'Empate', away: 'Visitante',
  over: 'Más', under: 'Menos', yes: 'Sí', no: 'No',
  home_draw: 'Local o Empate', draw_away: 'Empate o Visitante', home_away: 'Local o Visitante',
}

const COB_CLASS = { ALTA: 'alta', MEDIA: 'media', BAJA: 'baja', NULA: 'nula' }

function pct(v) { return v == null ? '—' : (v * 100).toFixed(1) + '%' }

function edgeFmt(v) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
}

function accentColor(edge) {
  if (edge == null) return 'var(--border-hi)'
  return edge >= 0 ? 'var(--green)' : 'var(--red)'
}

function modelColor(edge) {
  return (edge == null || edge >= 0) ? 'var(--green)' : 'var(--red)'
}

export default function SelectionCard({ sel, index }) {
  const mercadoLabel = MERCADO_LABEL[sel.mercado] ?? sel.mercado
  const selLabel     = SEL_LABEL[sel.seleccion]   ?? sel.seleccion
  const lineaStr     = sel.linea != null
    ? ` ${sel.linea > 0 ? '+' : ''}${sel.linea}`
    : ''
  const cobClass = COB_CLASS[sel.nivel_cobertura] ?? 'nula'
  const accent   = accentColor(sel.edge)
  const modColor = modelColor(sel.edge)
  const implPct  = sel.prob_implicita_adj != null
    ? Math.min(sel.prob_implicita_adj * 100, 100)
    : 0
  const modPct   = sel.prob_modelo != null
    ? Math.min(sel.prob_modelo * 100, 100)
    : 0
  const hasGauge = sel.prob_implicita_adj != null || sel.prob_modelo != null

  return (
    <div className="sel-card" style={{ '--accent': accent }}>
      <div className="sel-inner">

        {/* Header */}
        <div className="sel-header">
          <div className="sel-matchup">
            <span className="sel-idx">#{String(index).padStart(2, '0')}</span>
            <span className="sel-local">{sel.equipo_local}</span>
            {sel.equipo_visitante && <span className="sel-vs">vs</span>}
            {sel.equipo_visitante && <span className="sel-away">{sel.equipo_visitante}</span>}
          </div>
          {sel.mercado === 'player' && sel.player && (
            <div className="sel-player">{sel.player}</div>
          )}
          <div className="sel-badges">
            <span className="badge-mkt">{mercadoLabel}{lineaStr}</span>
            <span className="badge-sel">{selLabel}</span>
            {sel.cuota != null && <span className="badge-odds">{sel.cuota.toFixed(2)}</span>}
            <span className={`badge-cob ${cobClass}`}>{sel.nivel_cobertura}</span>
            {sel.faltante && (
              <span className="badge-cob nula" title="Mercado conocido, datos pendientes">
                pendiente
              </span>
            )}
          </div>
        </div>

        {/* Gauge */}
        {hasGauge && (
          <div className="gauge-wrap">
            <div className="gauge-labels">
              <span className="gl-impl">
                {pct(sel.prob_implicita_adj)}
                <span className="gl-sub">impl. adj.</span>
              </span>
              <span className="gl-mod">
                {pct(sel.prob_modelo)}
                <span className="gl-sub">modelo</span>
              </span>
              <span className="gl-edge" style={{ color: accent }}>
                {edgeFmt(sel.edge)}
                <span className="gl-sub">edge</span>
              </span>
            </div>

            <div className="gauge-ruler">
              {[0, 25, 50, 75, 100].map(v => (
                <div
                  key={v}
                  className="gauge-tick"
                  style={{ left: v === 100 ? 'calc(100% - 1px)' : v + '%' }}
                />
              ))}
            </div>

            <div className="gauge-track">
              {sel.prob_implicita_adj != null && (
                <div className="gauge-fill-impl" style={{ width: implPct + '%' }} />
              )}
              {sel.prob_modelo != null && (
                <div
                  className="gauge-fill-mod"
                  style={{ width: modPct + '%', background: modColor }}
                />
              )}
              {sel.prob_implicita_adj != null && (
                <div
                  className="gauge-pin"
                  style={{ left: implPct + '%', background: 'var(--sub)' }}
                />
              )}
              {sel.prob_modelo != null && (
                <div
                  className="gauge-pin"
                  style={{ left: modPct + '%', background: modColor }}
                />
              )}
            </div>

            <div className="gauge-legend">
              <span>
                <span className="gl-dot" style={{ background: 'var(--sub)' }} />
                Impl. adj.
              </span>
              <span>
                <span className="gl-dot" style={{ background: modColor }} />
                Modelo
              </span>
            </div>
          </div>
        )}

        {/* Stats */}
        <div className="sel-stats">
          <div className="sel-stat-cell">
            <div className="ss-label">Cuota</div>
            <div className="ss-value">{sel.cuota != null ? sel.cuota.toFixed(2) : '—'}</div>
          </div>
          <div className="sel-stat-cell">
            <div className="ss-label">Kelly 20%</div>
            <div
              className="ss-value"
              style={{ color: sel.kelly_fraccion != null ? 'var(--yellow)' : 'var(--muted)' }}
            >
              {sel.kelly_fraccion != null
                ? (sel.kelly_fraccion * 100).toFixed(1) + '%'
                : '—'}
            </div>
          </div>
          <div className="sel-stat-cell">
            <div className="ss-label">Partidos L · V</div>
            <div className="ss-value">
              {sel.n_partidos_local} · {sel.n_partidos_visitante}
            </div>
          </div>
        </div>

        {/* Alerts */}
        {sel.alertas && sel.alertas.length > 0 && (
          <div className="sel-alerts">
            {sel.alertas.map((a, i) => (
              <div key={i} className="sel-alert-item">{a}</div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}
