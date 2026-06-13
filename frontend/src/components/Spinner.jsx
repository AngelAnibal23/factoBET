export default function Spinner() {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      <span className="spinner-text">Procesando imagen con OCR…</span>
      <span className="spinner-sub">~15–20 segundos</span>
    </div>
  )
}
