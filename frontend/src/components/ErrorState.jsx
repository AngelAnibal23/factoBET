// Mapa código de backend → contenido amigable. Códigos reales de main.py (_err).
// retry: reintentar con la MISMA imagen puede funcionar.
const ERRORES = {
  IMAGE_FORMAT_INVALID: {
    titulo: 'Formato de imagen no soportado',
    cuerpo: 'Sube el ticket en JPG, PNG o WEBP.',
    retry: false,
  },
  IMAGE_TOO_LARGE: {
    titulo: 'La imagen pesa demasiado',
    cuerpo: 'El máximo es 5 MB. Prueba con una captura de pantalla en vez de una foto.',
    retry: false,
  },
  OCR_EXTRACTION_FAILED: {
    titulo: 'No pudimos leer el ticket',
    cuerpo: 'El OCR no logró extraer el parlay de la imagen.',
    tips: [
      'Usa una captura de pantalla, no una foto de la pantalla',
      'Que se vea el ticket completo, sin recortes',
      'Evita reflejos y baja iluminación',
    ],
    retry: true,
  },
  OCR_PARSE_FAILED: {
    titulo: 'Fallo interno leyendo el ticket',
    cuerpo: 'La lectura del OCR llegó corrupta. Suele resolverse reintentando.',
    retry: true,
  },
  BET_BUILDER_SIN_CUOTA: {
    titulo: 'El bet builder no trae cuota combinada',
    cuerpo: 'Sin la cuota combinada no se puede emitir veredicto. Sube una captura donde se vea la cuota total.',
    retry: false,
  },
  PARLAY_MIXTO: {
    titulo: 'Parlay mixto no soportado',
    cuerpo: 'El ticket mezcla equipos de Liga 1 con selecciones internacionales. Analiza cada parte por separado.',
    retry: false,
  },
  ANALYSIS_ERROR: {
    titulo: 'Error interno del motor',
    cuerpo: 'Algo falló en el análisis estadístico. Suele resolverse reintentando.',
    retry: true,
  },
}

const SIN_CONEXION = {
  titulo: 'No hay conexión con el servidor',
  cuerpo: '¿Está corriendo el backend? Verifica el servidor local y reintenta.',
  retry: true,
}

const DESCONOCIDO = {
  titulo: 'Ocurrió un error inesperado',
  cuerpo: 'Puedes reintentar el análisis o subir otra imagen.',
  retry: true,
}

export default function ErrorState({ error, onRetry, onReset }) {
  const info = error?.code
    ? (ERRORES[error.code] ?? DESCONOCIDO)
    : SIN_CONEXION
  const canRetry = info.retry && onRetry

  return (
    <div className="error-state" role="alert">
      <h3 className="error-title">{info.titulo}</h3>
      <p className="error-body">{info.cuerpo}</p>

      {info.tips && (
        <ul className="error-tips">
          {info.tips.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      )}

      {(error?.code || error?.detalle || error?.message) && (
        <details className="error-detail">
          <summary>Detalle técnico</summary>
          <p>
            {error?.code && <span className="error-detail-code">{error.code}</span>}
            {error?.message && <> {error.message}</>}
            {error?.detalle && <> — {error.detalle}</>}
          </p>
        </details>
      )}

      <div className="error-actions">
        {canRetry && (
          <button className="btn-cta" onClick={onRetry}>Reintentar</button>
        )}
        <button className="btn-retry" onClick={onReset}>Subir otra imagen</button>
      </div>
    </div>
  )
}
