import { useEffect, useState } from 'react'

const STAGES = [
  { at: 0,  label: 'Subiendo imagen…' },
  { at: 2,  label: 'Leyendo el ticket (OCR)…' },
  { at: 9,  label: 'Identificando equipos y mercados…' },
  { at: 13, label: 'Corriendo modelo Dixon-Coles…' },
  { at: 18, label: 'Cruzando probabilidades…' },
]

export default function Spinner() {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setElapsed(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  const current = STAGES.reduce((acc, s, i) => (elapsed >= s.at ? i : acc), 0)
  // Avance asintótico: nunca llega a 100%, desaparece cuando responde el fetch.
  const progress = (1 - Math.exp(-elapsed / 9)) * 90

  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      <div className="loader-bar-track">
        <div className="loader-bar-fill" style={{ width: `${progress}%` }} />
      </div>
      <ul className="loader-stages">
        {STAGES.map((s, i) => (
          <li
            key={s.at}
            className={
              i < current ? 'stage done' : i === current ? 'stage current' : 'stage'
            }
          >
            <span className="stage-mark">{i < current ? '✓' : i === current ? '›' : '·'}</span>
            {s.label}
          </li>
        ))}
      </ul>
      <span className="spinner-sub">{elapsed}s</span>
    </div>
  )
}
