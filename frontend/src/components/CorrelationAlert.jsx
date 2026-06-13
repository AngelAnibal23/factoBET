export default function CorrelationAlert({ correlaciones }) {
  if (!correlaciones || correlaciones.length === 0) return null

  return (
    <div className="corr-strip">
      <span className="corr-badge">CORR</span>
      <div className="corr-text">
        {correlaciones.map((c, i) => (
          <span key={i} className="corr-item">
            Sel. {c.seleccion_idx_1} + Sel. {c.seleccion_idx_2}
            {' '}— {c.tipo.replace(/_/g, ' ')}: {c.nota}
          </span>
        ))}
      </div>
    </div>
  )
}
