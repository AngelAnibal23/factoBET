export async function analizarParlay(imagenFile) {
  const body = new FormData()
  body.append('imagen', imagenFile)

  const res = await fetch('/api/v1/parlay/analizar', {
    method: 'POST',
    body,
  })

  const json = await res.json()

  if (!json.success) {
    const err = json.error || {}
    throw new ApiError(err.message || 'Error desconocido', err.code, err.detalle)
  }

  return json.data
}

export class ApiError extends Error {
  constructor(message, code, detalle) {
    super(message)
    this.code = code
    this.detalle = detalle
  }
}
