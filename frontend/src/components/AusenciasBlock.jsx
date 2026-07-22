// Bloque de ausencias/lesiones (Sofascore, Fase 3.4, solo Internacional).
// Mismo patron que MarcadorProbable: section-label + tarjeta, se oculta por
// completo si el backend no incluyo el campo (Liga1/legacy/demo antiguo).
export default function AusenciasBlock({ ausencias }) {
  if (!ausencias) return null

  if (ausencias.sin_dato) {
    return (
      <p className="ausencias-sin-dato">
        Sin dato de ausencias para este partido (Sofascore aún no publica).
      </p>
    )
  }

  const equipos = Object.entries(ausencias.equipos || {}).filter(([, l]) => l.length)
  const lambdas = ausencias.lambdas
  const lambdaEntries = lambdas
    ? (lambdas.antes && lambdas.despues
        ? [['', lambdas]]                        // forma plana (bet-builder): 1 partido
        : Object.entries(lambdas))                // { "Local - Visitante": {antes,despues} }
    : []

  return (
    <>
      <p className="section-label">Ausencias detectadas</p>
      <div className="ausencias-block">
        {equipos.length === 0 && (
          <p className="ausencias-empty">Sin ausentes reportados en ninguno de los dos equipos.</p>
        )}

        {equipos.map(([equipo, lista]) => (
          <div className="ausencias-team" key={equipo}>
            <strong>{equipo}</strong>
            <ul>
              {lista.map((a, i) => (
                <li key={`${a.nombre}-${i}`}>
                  <span className={a.estado === 'out' ? 'badge-out' : 'badge-duda'}>
                    {a.estado === 'out' ? 'NO JUEGA' : 'EN DUDA'}
                  </span>
                  {a.nombre}{a.motivo ? ` — ${a.motivo}` : ''}
                </li>
              ))}
            </ul>
          </div>
        ))}

        {lambdaEntries.map(([k, v]) => (
          <p className="lambda-ajuste" key={k || 'match'}>
            λ {k ? `${k}: ` : ''}{v.antes.join(' / ')} → {v.despues.join(' / ')}
          </p>
        ))}
      </div>
    </>
  )
}
