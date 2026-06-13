export default function Disclaimer({ texto }) {
  if (!texto) return null
  return <div className="disclaimer">{texto}</div>
}
