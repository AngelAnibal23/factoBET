# helpBETOR Frontend — Design Spec
**Date:** 2026-06-13  
**Stack:** React + Vite, CSS custom variables, sin Tailwind, sin librerías UI  
**Estado:** Aprobado por Angel

---

## 1. Contexto

helpBETOR es un auditor estadístico de parlays para Liga 1 Peruana. El usuario sube una captura de pantalla de su app de apuestas y recibe un análisis Dixon-Coles v0.2 por selección. No es un predictor — es una herramienta de auditoría.

**Flujo:** Upload imagen → OCR ~15–20s → Validación → Análisis estadístico → Resultado

**API:** `POST /api/v1/parlay/analizar` (multipart/form-data, campo `imagen`)  
**Proxy Vite:** `/api` → `http://localhost:8000`

---

## 2. Estados de la app

```
idle → uploading → result
                 ↘ error
```

- **idle**: pantalla de upload
- **uploading**: upload zone + spinner (OCR en progreso)
- **result**: ticket + correlaciones + selecciones
- **error**: banner de error + botón retry

---

## 3. Sistema visual

### Tipografía
```css
--ui:    'Figtree', sans-serif          /* UI, labels, texto general */
--mono:  'IBM Plex Mono', monospace     /* números, datos, badges, disclaimer */
--brand: 'Syne', sans-serif             /* logo, título upload */
```
Google Fonts via `@import` en `index.css`.

### Paleta de colores
```css
--bg:        #07101d     /* fondo base */
--card:      #0d1a2a     /* cards */
--card-deep: #091523     /* fondos secundarios dentro de cards */
--border:    #162234     /* bordes normales */
--border-hi: #1f3550     /* bordes destacados, ticks del gauge */
--text:      #cfe0f0     /* texto principal */
--sub:       #4d6f8a     /* texto secundario */
--muted:     #213248     /* texto muy apagado, labels */
--green:     #00df72     /* acento positivo / edge favorable */
--green-lo:  rgba(0,223,114,.06)  /* fondos verdes */
--green-hi:  rgba(0,223,114,.18)
--yellow:    #f5a623     /* Kelly, alertas medias */
--yellow-lo: rgba(245,166,35,.07)
--red:       #f04444     /* edge negativo, alertas */
--red-lo:    rgba(240,68,68,.07)
```

### Fondo
Dot grid de 30px sobre `--bg`:
```css
background-image: radial-gradient(circle, #162234 1px, transparent 1px);
background-size: 30px 30px;
```

### Border-radius
`--r: 8px` uniforme en cards, botones, badges.

---

## 4. Componentes

### 4.1 Topbar (sticky)
- Altura 52px, `backdrop-filter: blur(12px)`, `border-bottom: 1px solid var(--border)`
- **Izquierda:** Logo — 5 barras SVG ascendentes + `helpBETOR` (Syne 800) + tag "Auditor estadístico / Liga 1 Peruana"
- **Centro:** Status pill — punto verde pulsante + "Dixon-Coles v0.2 · 996 partidos" en `--mono`
- **Derecha:** Botón "← Nueva consulta" (solo visible en estado `result`)

### 4.2 UploadZone
- Centrado verticalmente en viewport (`min-height: calc(100vh - 52px)`)
- Drop zone: `max-width 520px`, `border: 1.5px dashed var(--border-hi)`, borde cambia a `--green` en hover/drag-over
- Contenido: pill "Liga 1 Peruana", ícono SVG upload, título `Syne 800 24px`, subtítulo, casas listadas en `--mono`, badges de formato, botón CTA
- **Casas:** Betano · Inkabet · Codere · Betsafe · Bet365
- **Formatos aceptados:** JPG, PNG, WEBP, máx 5 MB
- **Strip inferior:** grilla 3 celdas — "996 partidos / 2022–2024 / Dixon-Coles" en `--mono`

### 4.3 Spinner
- Aparece debajo del UploadZone durante el estado `uploading`
- Spinner circular (CSS `border-top-color: var(--green)`) + texto "Procesando imagen con OCR…" + nota "~15–20 segundos"

### 4.4 Ticket (resumen del parlay)
- Barra superior de 2px: degradado verde→amarillo→rojo proporcional a selecciones con/sin valor/exóticas
- Body: flex horizontal — confianza (izquierda, separada por divider vertical) + 5 métricas: prob. modelo, prob. implícita, cuota total, casa, modeladas
- Footer dashed: "Dixon-Coles v0.2 · 996 partidos · 2022–2024" + "Margen X% aplicado"
- Tipografía: labels en `--mono 9px uppercase`, valores en `--mono 15px 600`
- `nivel_confianza`: ALTA → `--green`, MEDIA → `--yellow`, BAJA → `--red`

### 4.5 CorrelationAlert (inline strip)
- Solo visible si `resumen.tiene_correlaciones === true`
- Badge `CORR` en `--yellow` + texto descriptivo de cada correlación detectada
- Background `--yellow-lo`, border `rgba(245,166,35,.18)`

### 4.6 SelectionCard
Borde izquierdo de 3px como indicador de estado:
- `edge != null && edge >= 0` → verde (`--green`)
- `edge != null && edge < 0` → rojo (`--red`)
- `edge === null` (exótico o sin visitante) → `--border-hi` apagado

**Header:** `#01` en mono + nombre del partido + badges (mercado, selección, cuota, cobertura)

**Gauge:**
- Labels: impl. adj. (izquierda) · modelo (centro) · edge en grande (derecha, coloreado)
- Regla: 5 tick marks de referencia (0/25/50/75/100%)
- Track: fondo oscuro + fill base (implícita) + fill modelo (coloreado) + 2 pins verticales
- Legend: dot implícita (gris) + dot modelo (verde o rojo)

**Stats row:** 3 celdas — Cuota / Kelly 20% / Partidos L·V (todos en `--mono`)
- Kelly: color `--yellow` si tiene valor, `--muted` si es `null`

**Alert row:** solo si `sel.alertas.length > 0`, fondo `--red-lo`, font `--mono 9px`

### 4.7 ErrorBanner
- Fondo `--red-lo`, borde `--red`
- Muestra `error.code` (título) + `error.message` + `error.detalle` (si existe)
- Botón "Intentar de nuevo" → reset al estado `idle`

### 4.8 Disclaimer
- `--mono 9px`, color `--muted`, `line-height 1.7`
- Texto fijo del backend (campo `data.disclaimer`)

---

## 5. Layout de resultados

```
[TOPBAR sticky 52px]
[TICKET — full width]
[CORRELATION STRIP — condicional]
[SECTION LABEL "Selecciones (N)"]
[SEL GRID — 2 columnas, gap 10px]
[DISCLAIMER]
```

- `max-width: 1080px`, `margin: 0 auto`, `padding: 24px 32px 56px`
- Grilla de selecciones: `grid-template-columns: 1fr 1fr`

---

## 6. Estructura de archivos

```
frontend/src/
  main.jsx
  App.jsx
  api.js
  styles/
    index.css          ← variables, reset, topbar, layout, upload, spinner, error, disclaimer
  components/
    UploadZone.jsx
    Spinner.jsx
    Ticket.jsx         ← renombrado de SummaryCard
    CorrelationAlert.jsx
    SelectionCard.jsx
    Disclaimer.jsx
```

> Los componentes existentes (`SummaryCard` → `Ticket`, estilos) se reescriben completamente. La lógica de `App.jsx` y `api.js` se mantiene.

---

## 7. Mapeo API → UI

| Campo API | Dónde aparece |
|---|---|
| `resumen.nivel_confianza` | Ticket: valor principal + color |
| `resumen.prob_parlay_modelo` | Ticket: "Prob. modelo" |
| `resumen.prob_parlay_impl` | Ticket: "Prob. implícita" |
| `resumen.cuota_total` | Ticket: "Cuota total" |
| `resumen.casa_apuestas` | Ticket: "Casa" |
| `resumen.n_modeladas / n_selecciones` | Ticket: "Modeladas" |
| `resumen.margen_aplicado` | Ticket footer |
| `resumen.tiene_correlaciones` | Toggle CorrelationAlert |
| `correlaciones[]` | CorrelationAlert: lista |
| `selecciones[].equipo_local/visitante` | SelectionCard header |
| `selecciones[].mercado` | Badge mercado (traducido) |
| `selecciones[].seleccion` | Badge selección (traducido) |
| `selecciones[].cuota` | Badge cuota + stats |
| `selecciones[].nivel_cobertura` | Badge cobertura + color acento |
| `selecciones[].prob_implicita_adj` | Gauge: pin implícita |
| `selecciones[].prob_modelo` | Gauge: fill modelo |
| `selecciones[].edge` | Gauge: label derecha + color acento |
| `selecciones[].kelly_fraccion` | Stats: Kelly 20% |
| `selecciones[].n_partidos_local/visitante` | Stats: Partidos L/V |
| `selecciones[].alertas[]` | Alert row |
| `data.disclaimer` | Disclaimer |

---

## 8. Traducciones de dominio

```js
const MERCADO = { '1X2': '1X2', over_under: 'Más/Menos', btts: 'Ambos marcan', handicap: 'Hándicap', exotic: 'Exótico' }
const SELECCION = { home: 'Local', draw: 'Empate', away: 'Visitante', over: 'Más', under: 'Menos', yes: 'Sí', no: 'No' }
```

---

## 9. Lo que NO cambia

- `api.js` — fetch + `ApiError` (sin cambios)
- Lógica de estados en `App.jsx` (`idle | uploading | result | error`) — sin cambios
- Validaciones de archivo en `UploadZone` (tipo + tamaño) — sin cambios
- `vite.config.js` proxy — sin cambios
- `package.json` deps — solo agregar Google Fonts via CSS `@import`
