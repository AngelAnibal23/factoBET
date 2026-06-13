# helpBETOR Frontend Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all frontend components to match the approved spec (`docs/superpowers/specs/2026-06-13-helpbetor-frontend-design.md`): dark audit aesthetic with Figtree/IBM Plex Mono/Syne fonts, dot-grid background, sticky topbar, horizontal ticket summary, gauge-based selection cards with accent borders.

**Architecture:** 9 files total — `index.css` establishes the complete design system, `App.jsx` owns the topbar + state routing, 6 components are rewritten in place, `SummaryCard.jsx` is deleted and replaced by new `Ticket.jsx`. Logic (fetch, state machine, file validation) is preserved exactly as-is.

**Tech Stack:** React 18 + Vite, CSS custom variables (no Tailwind, no UI libraries), Google Fonts via CSS `@import`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Rewrite | `frontend/src/styles/index.css` | Full design system: variables, reset, topbar, upload, spinner, ticket, corr, selection, gauge, disclaimer |
| Rewrite | `frontend/src/App.jsx` | Topbar (SVG logo + status pill + btn-nueva), state routing to new components |
| Rewrite | `frontend/src/components/UploadZone.jsx` | Drop zone with casas strip, SVG icon, model-strip grid |
| Rewrite | `frontend/src/components/Spinner.jsx` | Mono text spinner below upload zone |
| **Create** | `frontend/src/components/Ticket.jsx` | Horizontal ticket: top bar, confidence block, 5 metrics, dashed footer |
| Rewrite | `frontend/src/components/CorrelationAlert.jsx` | Inline yellow strip with CORR badge |
| Rewrite | `frontend/src/components/SelectionCard.jsx` | Left accent border, gauge with ruler ticks, 3-cell stats |
| Rewrite | `frontend/src/components/Disclaimer.jsx` | Mono 9px strip |
| **Delete** | `frontend/src/components/SummaryCard.jsx` | Replaced by Ticket.jsx |
| No change | `frontend/src/api.js` | — |
| No change | `frontend/src/main.jsx` | — |
| No change | `frontend/vite.config.js` | — |

---

## Task 1: Design System CSS (`index.css`)

**Files:**
- Rewrite: `frontend/src/styles/index.css`

This is the foundation. All other tasks depend on it. Contains Google Fonts import, CSS variables, body/reset, and every CSS class used across all components.

- [ ] **Step 1: Rewrite `frontend/src/styles/index.css`**

```css
@import url('https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600&family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@800&display=swap');

:root {
  --bg:        #07101d;
  --card:      #0d1a2a;
  --card-deep: #091523;
  --border:    #162234;
  --border-hi: #1f3550;
  --text:      #cfe0f0;
  --sub:       #4d6f8a;
  --muted:     #213248;
  --green:     #00df72;
  --green-lo:  rgba(0,223,114,.06);
  --green-hi:  rgba(0,223,114,.18);
  --yellow:    #f5a623;
  --yellow-lo: rgba(245,166,35,.07);
  --red:       #f04444;
  --red-lo:    rgba(240,68,68,.07);
  --ui:        'Figtree', sans-serif;
  --mono:      'IBM Plex Mono', monospace;
  --brand:     'Syne', sans-serif;
  --r:         8px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: var(--ui);
  font-size: 14px;
  line-height: 1.5;
  color: var(--text);
  background-color: var(--bg);
  background-image: radial-gradient(circle, #162234 1px, transparent 1px);
  background-size: 30px 30px;
  min-height: 100vh;
}

/* ── Topbar ──────────────────────────────────────────────────── */
.topbar {
  position: sticky;
  top: 0;
  z-index: 100;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(7,16,29,.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}

.topbar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-name {
  font-family: var(--brand);
  font-size: 17px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.3px;
}

.logo-tag {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  letter-spacing: 0.3px;
  text-transform: uppercase;
  line-height: 1.3;
  display: none;
}

@media (min-width: 600px) { .logo-tag { display: block; } }

.status-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--sub);
  letter-spacing: 0.2px;
}

.status-dot {
  width: 7px;
  height: 7px;
  background: var(--green);
  border-radius: 50%;
  flex-shrink: 0;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }

.btn-new {
  font-family: var(--ui);
  font-size: 13px;
  color: var(--sub);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 5px 14px;
  cursor: pointer;
  transition: border-color .15s, color .15s;
  white-space: nowrap;
}

.btn-new:hover { border-color: var(--border-hi); color: var(--text); }

/* spacer so topbar stays balanced when btn-new is hidden */
.topbar-spacer { width: 100px; }

/* ── Upload screen ───────────────────────────────────────────── */
.upload-screen {
  min-height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px 56px;
}

.upload-wrap { width: 100%; max-width: 520px; }

.upload-zone {
  background: var(--card);
  border: 1.5px dashed var(--border-hi);
  border-radius: var(--r);
  padding: 40px 32px;
  text-align: center;
  cursor: pointer;
  transition: border-color .15s, background .15s;
}

.upload-zone:hover,
.upload-zone.drag-over {
  border-color: var(--green);
  background: var(--green-lo);
}

.upload-zone input[type='file'] { display: none; }

.upload-league-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 12px;
  margin-bottom: 20px;
}

.upload-icon-wrap { margin-bottom: 16px; }

.upload-title {
  font-family: var(--brand);
  font-size: 22px;
  font-weight: 800;
  color: var(--text);
  margin-bottom: 8px;
}

.upload-sub {
  font-size: 13px;
  color: var(--sub);
  margin-bottom: 12px;
}

.upload-casas {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  letter-spacing: 0.3px;
  margin-bottom: 16px;
}

.upload-formats {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-bottom: 20px;
}

.fmt-badge {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 7px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.btn-cta {
  font-family: var(--ui);
  font-size: 13px;
  font-weight: 600;
  color: #000;
  background: var(--green);
  border: none;
  border-radius: var(--r);
  padding: 8px 24px;
  cursor: pointer;
  transition: opacity .15s;
}

.btn-cta:hover { opacity: .85; }

/* file selected state inside upload-zone */
.upload-preview {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.preview-img {
  max-height: 160px;
  border-radius: 6px;
  border: 1px solid var(--border);
  object-fit: contain;
}

.preview-name {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--sub);
  margin-top: 8px;
}

.btn-change {
  font-family: var(--ui);
  font-size: 12px;
  color: var(--sub);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 5px 14px;
  cursor: pointer;
  margin-top: 10px;
  transition: border-color .15s, color .15s;
}

.btn-change:hover { border-color: var(--border-hi); color: var(--text); }

.btn-analizar {
  display: block;
  width: 100%;
  margin-top: 12px;
  padding: 13px;
  font-family: var(--ui);
  font-size: 15px;
  font-weight: 700;
  color: #000;
  background: var(--green);
  border: none;
  border-radius: var(--r);
  cursor: pointer;
  transition: opacity .15s;
}

.btn-analizar:hover:not(:disabled) { opacity: .85; }
.btn-analizar:disabled { opacity: .35; cursor: not-allowed; }

.model-strip {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  border: 1px solid var(--border);
  border-radius: var(--r);
  overflow: hidden;
  margin-top: 14px;
}

.model-strip-cell {
  padding: 10px 14px;
  text-align: center;
  background: var(--card-deep);
}

.model-strip-cell:not(:last-child) { border-right: 1px solid var(--border); }

.ms-value {
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  display: block;
}

.ms-label {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  margin-top: 2px;
  display: block;
}

/* ── Spinner ─────────────────────────────────────────────────── */
.spinner-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 28px 0 0;
}

.spinner {
  width: 28px;
  height: 28px;
  border: 2px solid var(--border-hi);
  border-top-color: var(--green);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

.spinner-text {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--sub);
}

.spinner-sub {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
}

/* ── Results layout ──────────────────────────────────────────── */
.results-wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 32px 56px;
}

@media (max-width: 700px) { .results-wrap { padding: 16px 16px 48px; } }

/* ── Ticket ──────────────────────────────────────────────────── */
.ticket {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--r);
  overflow: hidden;
  margin-bottom: 12px;
}

.ticket-bar { height: 2px; width: 100%; }

.ticket-body {
  display: flex;
  align-items: stretch;
  padding: 20px 24px;
  gap: 24px;
}

@media (max-width: 640px) { .ticket-body { flex-direction: column; gap: 16px; } }

.ticket-confidence {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 12px 20px;
  border-radius: 6px;
  border: 1px solid;
  min-width: 110px;
  flex-shrink: 0;
}

.ticket-conf-label {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.ticket-conf-value {
  font-family: var(--mono);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.ticket-divider {
  width: 1px;
  background: var(--border);
  flex-shrink: 0;
  align-self: stretch;
}

@media (max-width: 640px) { .ticket-divider { display: none; } }

.ticket-metrics {
  display: flex;
  align-items: center;
  flex: 1;
  flex-wrap: wrap;
}

.ticket-metric {
  flex: 1;
  padding: 8px 16px;
  min-width: 90px;
}

.ticket-metric:not(:last-child) { border-right: 1px solid var(--border); }

@media (max-width: 640px) {
  .ticket-metric { border-right: none !important; border-bottom: 1px solid var(--border); }
  .ticket-metric:last-child { border-bottom: none; }
}

.tk-label {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.tk-value {
  font-family: var(--mono);
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.ticket-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 24px;
  border-top: 1px dashed var(--border);
  font-family: var(--mono);
  font-size: 9px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

/* ── Correlation strip ───────────────────────────────────────── */
.corr-strip {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--yellow-lo);
  border: 1px solid rgba(245,166,35,.18);
  border-radius: var(--r);
  padding: 12px 16px;
  margin-bottom: 12px;
}

.corr-badge {
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 600;
  color: #000;
  background: var(--yellow);
  border-radius: 4px;
  padding: 2px 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  flex-shrink: 0;
  margin-top: 1px;
}

.corr-text {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--sub);
  line-height: 1.6;
}

.corr-item { display: block; }
.corr-item + .corr-item { margin-top: 4px; }

/* ── Section label ───────────────────────────────────────────── */
.section-label {
  font-family: var(--mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--sub);
  margin-bottom: 10px;
}

/* ── Selections grid ─────────────────────────────────────────── */
.sel-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 24px;
}

@media (max-width: 640px) { .sel-grid { grid-template-columns: 1fr; } }

/* ── Selection card ──────────────────────────────────────────── */
.sel-card {
  --accent: var(--border-hi);
  background: var(--card);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: var(--r);
  overflow: hidden;
}

.sel-inner {
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sel-header { display: flex; flex-direction: column; gap: 8px; }

.sel-matchup {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.sel-idx {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--muted);
  font-weight: 600;
  flex-shrink: 0;
}

.sel-local, .sel-away {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.sel-vs { font-size: 11px; color: var(--sub); font-weight: 400; }

.sel-badges {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}

.badge-mkt {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  background: var(--card-deep);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 7px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.badge-sel {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--text);
  background: var(--muted);
  border-radius: 4px;
  padding: 2px 7px;
}

.badge-odds {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text);
  border: 1px solid var(--border-hi);
  border-radius: 4px;
  padding: 2px 7px;
}

.badge-cob {
  font-family: var(--mono);
  font-size: 9px;
  border-radius: 4px;
  padding: 2px 7px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.badge-cob.alta  { color: var(--green);  background: var(--green-lo);  }
.badge-cob.media { color: var(--yellow); background: var(--yellow-lo); }
.badge-cob.baja  { color: var(--red);    background: var(--red-lo);    }
.badge-cob.nula  { color: var(--sub);    background: var(--card-deep); }

/* ── Gauge ───────────────────────────────────────────────────── */
.gauge-wrap { display: flex; flex-direction: column; gap: 5px; }

.gauge-labels {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.gl-impl, .gl-mod, .gl-edge {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--sub);
  line-height: 1.3;
  text-align: center;
}

.gl-impl { text-align: left; }
.gl-edge { text-align: right; }

.gl-sub {
  font-size: 8px;
  color: var(--muted);
  font-weight: 400;
  letter-spacing: 0.3px;
  text-transform: uppercase;
  display: block;
}

.gauge-ruler {
  position: relative;
  height: 8px;
}

.gauge-tick {
  position: absolute;
  top: 0;
  width: 1px;
  height: 8px;
  background: var(--border-hi);
  transform: translateX(-50%);
}

.gauge-track {
  position: relative;
  height: 6px;
  background: var(--card-deep);
  border-radius: 3px;
  overflow: hidden;
}

.gauge-fill-impl {
  position: absolute;
  top: 0; left: 0;
  height: 100%;
  background: var(--sub);
  opacity: 0.45;
}

.gauge-fill-mod {
  position: absolute;
  top: 0; left: 0;
  height: 100%;
  opacity: 0.75;
}

.gauge-pin {
  position: absolute;
  top: 0;
  width: 2px;
  height: 100%;
  transform: translateX(-50%);
}

.gauge-legend {
  display: flex;
  gap: 14px;
  font-family: var(--mono);
  font-size: 9px;
  color: var(--sub);
  align-items: center;
}

.gl-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}

/* ── Selection stats row ─────────────────────────────────────── */
.sel-stats {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1px;
  background: var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.sel-stat-cell {
  background: var(--card-deep);
  padding: 8px 10px;
}

.ss-label {
  font-family: var(--mono);
  font-size: 8px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.4px;
  margin-bottom: 3px;
}

.ss-value {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

/* ── Selection alerts ────────────────────────────────────────── */
.sel-alerts {
  background: var(--red-lo);
  border-radius: 4px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sel-alert-item {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--red);
  line-height: 1.5;
  opacity: .85;
}

/* ── Disclaimer ──────────────────────────────────────────────── */
.disclaimer {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--muted);
  line-height: 1.7;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--card-deep);
  margin-top: 4px;
}

/* ── Error banner ────────────────────────────────────────────── */
.error-banner {
  background: var(--red-lo);
  border: 1px solid var(--red);
  border-radius: var(--r);
  padding: 20px 24px;
  margin: 40px auto;
  max-width: 560px;
}

.error-banner h3 {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--red);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}

.error-banner p {
  font-size: 13px;
  color: var(--sub);
  line-height: 1.5;
}

.btn-retry {
  margin-top: 16px;
  padding: 7px 16px;
  font-family: var(--ui);
  font-size: 13px;
  color: var(--text);
  background: transparent;
  border: 1px solid var(--border-hi);
  border-radius: var(--r);
  cursor: pointer;
  transition: border-color .15s;
}

.btn-retry:hover { border-color: var(--text); }
```

- [ ] **Step 2: Commit**

```
git add frontend/src/styles/index.css
git commit -m "style: rewrite index.css — new design system, fonts, dot grid"
```

---

## Task 2: App Layout and Topbar (`App.jsx`)

**Files:**
- Rewrite: `frontend/src/App.jsx`

Adds sticky topbar (SVG bars logo + status pill + btn-nueva). Updates state routing to use new component names. Preserves fetch logic, state machine, and reset function exactly.

- [ ] **Step 1: Rewrite `frontend/src/App.jsx`**

```jsx
import { useState } from 'react'
import { analizarParlay, ApiError } from './api.js'
import UploadZone from './components/UploadZone.jsx'
import Spinner from './components/Spinner.jsx'
import Ticket from './components/Ticket.jsx'
import SelectionCard from './components/SelectionCard.jsx'
import CorrelationAlert from './components/CorrelationAlert.jsx'
import Disclaimer from './components/Disclaimer.jsx'

function LogoBars() {
  return (
    <svg width="22" height="16" viewBox="0 0 22 16" fill="none" aria-hidden="true">
      <rect x="0"  y="13" width="3" height="3"  rx="1" fill="var(--green)" opacity="0.4" />
      <rect x="5"  y="9"  width="3" height="7"  rx="1" fill="var(--green)" opacity="0.55" />
      <rect x="10" y="5"  width="3" height="11" rx="1" fill="var(--green)" opacity="0.72" />
      <rect x="15" y="2"  width="3" height="14" rx="1" fill="var(--green)" opacity="0.87" />
      <rect x="20" y="0"  width="2" height="16" rx="1" fill="var(--green)" />
    </svg>
  )
}

// States: idle | uploading | result | error
export default function App() {
  const [state, setState] = useState('idle')
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [meta, setMeta] = useState(null)
  const [apiError, setApiError] = useState(null)

  async function handleSubmit() {
    if (!file) return
    setState('uploading')
    setApiError(null)
    try {
      const rawRes = await fetch('/api/v1/parlay/analizar', {
        method: 'POST',
        body: (() => { const f = new FormData(); f.append('imagen', file); return f })(),
      })
      const json = await rawRes.json()
      if (!json.success) {
        const e = json.error || {}
        throw new ApiError(e.message || 'Error desconocido', e.code, e.detalle)
      }
      setResult(json.data)
      setMeta(json.meta)
      setState('result')
    } catch (err) {
      setApiError(err)
      setState('error')
    }
  }

  function reset() {
    setState('idle')
    setFile(null)
    setResult(null)
    setMeta(null)
    setApiError(null)
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-logo">
          <LogoBars />
          <span className="logo-name">helpBETOR</span>
          <span className="logo-tag">Auditor estadístico<br />Liga 1 Peruana</span>
        </div>

        <div className="status-pill">
          <span className="status-dot" />
          Dixon-Coles v0.2 · 996 partidos
        </div>

        {state === 'result'
          ? <button className="btn-new" onClick={reset}>← Nueva consulta</button>
          : <div className="topbar-spacer" />
        }
      </header>

      {(state === 'idle' || state === 'uploading') && (
        <div className="upload-screen">
          <UploadZone
            file={file}
            onFile={setFile}
            onSubmit={handleSubmit}
            loading={state === 'uploading'}
          />
          {state === 'uploading' && <Spinner />}
        </div>
      )}

      {state === 'error' && (
        <div className="error-banner">
          <h3>{apiError?.code ?? 'Error'}</h3>
          <p>{apiError?.message ?? 'Ocurrió un error inesperado.'}</p>
          {apiError?.detalle && (
            <p style={{ marginTop: 6, fontSize: '12px' }}>{apiError.detalle}</p>
          )}
          <button className="btn-retry" onClick={reset}>Intentar de nuevo</button>
        </div>
      )}

      {state === 'result' && result && (
        <div className="results-wrap">
          <Ticket resumen={result.resumen} meta={meta} />

          {result.resumen.tiene_correlaciones && (
            <CorrelationAlert correlaciones={result.correlaciones} />
          )}

          <p className="section-label">Selecciones ({result.selecciones.length})</p>
          <div className="sel-grid">
            {result.selecciones.map((sel, i) => (
              <SelectionCard key={i} sel={sel} index={i + 1} />
            ))}
          </div>

          <Disclaimer texto={result.disclaimer} />
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/App.jsx
git commit -m "feat: add sticky topbar with SVG logo, status pill, nueva-consulta btn"
```

---

## Task 3: Upload Zone (`UploadZone.jsx`)

**Files:**
- Rewrite: `frontend/src/components/UploadZone.jsx`

New UI: league pill, SVG upload icon, Syne title, casas list in mono, format badges, CTA button. Model strip grid below. File validation logic preserved exactly.

- [ ] **Step 1: Rewrite `frontend/src/components/UploadZone.jsx`**

```jsx
import { useRef, useState } from 'react'

const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp']

function UploadIcon() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <path d="M18 6v18M11 13l7-7 7 7" stroke="var(--sub)" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 26v3a3 3 0 003 3h22a3 3 0 003-3v-3"
        stroke="var(--sub)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

export default function UploadZone({ onFile, file, onSubmit, loading }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  function handleFiles(files) {
    const f = files[0]
    if (!f) return
    if (!ACCEPTED.includes(f.type)) {
      alert('Solo se aceptan imágenes JPG, PNG o WEBP.')
      return
    }
    if (f.size > 5 * 1024 * 1024) {
      alert('La imagen no puede superar 5 MB.')
      return
    }
    onFile(f)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFiles(e.dataTransfer.files)
  }

  const previewUrl = file ? URL.createObjectURL(file) : null

  return (
    <div className="upload-wrap">
      <div
        className={`upload-zone${dragOver ? ' drag-over' : ''}`}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !file && inputRef.current.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={e => handleFiles(e.target.files)}
        />

        {!file ? (
          <>
            <div className="upload-league-pill">Liga 1 Peruana</div>
            <div className="upload-icon-wrap"><UploadIcon /></div>
            <div className="upload-title">Sube tu parlay</div>
            <div className="upload-sub">
              Captura la pantalla de tu app de apuestas y sube la imagen
            </div>
            <div className="upload-casas">
              Betano · Inkabet · Codere · Betsafe · Bet365
            </div>
            <div className="upload-formats">
              <span className="fmt-badge">JPG</span>
              <span className="fmt-badge">PNG</span>
              <span className="fmt-badge">WEBP</span>
              <span className="fmt-badge">máx 5 MB</span>
            </div>
            <button
              type="button"
              className="btn-cta"
              onClick={e => { e.stopPropagation(); inputRef.current.click() }}
            >
              Seleccionar imagen
            </button>
          </>
        ) : (
          <div className="upload-preview">
            <img src={previewUrl} alt="preview" className="preview-img" />
            <div className="preview-name">
              {file.name} · {(file.size / 1024).toFixed(0)} KB
            </div>
            <button
              type="button"
              className="btn-change"
              onClick={e => {
                e.stopPropagation()
                onFile(null)
                inputRef.current.value = ''
              }}
            >
              Cambiar imagen
            </button>
          </div>
        )}
      </div>

      <button
        className="btn-analizar"
        onClick={onSubmit}
        disabled={!file || loading}
      >
        {loading ? 'Analizando…' : 'Analizar parlay'}
      </button>

      <div className="model-strip">
        <div className="model-strip-cell">
          <span className="ms-value">996</span>
          <span className="ms-label">Partidos</span>
        </div>
        <div className="model-strip-cell">
          <span className="ms-value">2022–2024</span>
          <span className="ms-label">Temporadas</span>
        </div>
        <div className="model-strip-cell">
          <span className="ms-value">Dixon-Coles</span>
          <span className="ms-label">Modelo</span>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/UploadZone.jsx
git commit -m "feat: redesign UploadZone — league pill, SVG icon, casas, model strip"
```

---

## Task 4: Spinner (`Spinner.jsx`)

**Files:**
- Rewrite: `frontend/src/components/Spinner.jsx`

Mono font, tighter spacing, same animation class from index.css.

- [ ] **Step 1: Rewrite `frontend/src/components/Spinner.jsx`**

```jsx
export default function Spinner() {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      <span className="spinner-text">Procesando imagen con OCR…</span>
      <span className="spinner-sub">~15–20 segundos</span>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/Spinner.jsx
git commit -m "style: update Spinner to mono text, smaller ring"
```

---

## Task 5: Ticket Component (`Ticket.jsx`)

**Files:**
- Create: `frontend/src/components/Ticket.jsx`

New file. Horizontal layout: 2px gradient top bar, confidence block (left), divider, 5 metrics (right), dashed footer. Replaces `SummaryCard`.

`nivel_confianza` drives: top bar gradient, confidence block color, and border color.

- [ ] **Step 1: Create `frontend/src/components/Ticket.jsx`**

```jsx
function pct(v) {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}

function barGradient(nivel) {
  if (nivel === 'ALTA')  return 'linear-gradient(to right,#00df72 0%,#00df72 65%,#f5a623 100%)'
  if (nivel === 'MEDIA') return 'linear-gradient(to right,#00df72 0%,#f5a623 45%,#f5a623 65%,#f04444 100%)'
  return 'linear-gradient(to right,#f5a623 0%,#f04444 100%)'
}

const CONF_COLOR = { ALTA:'var(--green)', MEDIA:'var(--yellow)', BAJA:'var(--red)' }
const CONF_BG    = { ALTA:'var(--green-lo)', MEDIA:'var(--yellow-lo)', BAJA:'var(--red-lo)' }

export default function Ticket({ resumen }) {
  const {
    prob_parlay_modelo,
    prob_parlay_impl,
    cuota_total,
    n_selecciones,
    n_modeladas,
    casa_apuestas,
    margen_aplicado,
    nivel_confianza,
  } = resumen

  const confColor = CONF_COLOR[nivel_confianza] ?? 'var(--sub)'
  const confBg    = CONF_BG[nivel_confianza]    ?? 'var(--card-deep)'

  return (
    <div className="ticket">
      <div className="ticket-bar" style={{ background: barGradient(nivel_confianza) }} />

      <div className="ticket-body">
        <div
          className="ticket-confidence"
          style={{ background: confBg, borderColor: confColor }}
        >
          <div className="ticket-conf-label">Confianza</div>
          <div className="ticket-conf-value" style={{ color: confColor }}>
            {nivel_confianza}
          </div>
        </div>

        <div className="ticket-divider" />

        <div className="ticket-metrics">
          <div className="ticket-metric">
            <div className="tk-label">Prob. modelo</div>
            <div className="tk-value">{pct(prob_parlay_modelo)}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Prob. implícita</div>
            <div className="tk-value">{pct(prob_parlay_impl)}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Cuota total</div>
            <div className="tk-value">{cuota_total ?? '—'}</div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Casa</div>
            <div className="tk-value" style={{ textTransform: 'capitalize' }}>
              {casa_apuestas ?? '—'}
            </div>
          </div>
          <div className="ticket-metric">
            <div className="tk-label">Modeladas</div>
            <div className="tk-value">{n_modeladas}/{n_selecciones}</div>
          </div>
        </div>
      </div>

      <div className="ticket-footer">
        <span>Dixon-Coles v0.2 · 996 partidos · 2022–2024</span>
        <span>Margen {(margen_aplicado * 100).toFixed(1)}% aplicado</span>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/Ticket.jsx
git commit -m "feat: add Ticket component — horizontal summary with gradient bar and metrics"
```

---

## Task 6: Correlation Strip (`CorrelationAlert.jsx`)

**Files:**
- Rewrite: `frontend/src/components/CorrelationAlert.jsx`

Yellow CORR badge + mono text. One strip per alert group (not a list with bullets).

- [ ] **Step 1: Rewrite `frontend/src/components/CorrelationAlert.jsx`**

```jsx
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
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/CorrelationAlert.jsx
git commit -m "style: redesign CorrelationAlert as inline CORR strip"
```

---

## Task 7: Selection Card with Gauge (`SelectionCard.jsx`)

**Files:**
- Rewrite: `frontend/src/components/SelectionCard.jsx`

Left accent border (3px, CSS `--accent` variable). Gauge with ruler ticks shows implícita adj vs modelo fills + 2 pins. Stats in 3-cell grid. Alert row in red-lo background.

Accent logic:
- `edge != null && edge >= 0` → `var(--green)`
- `edge != null && edge < 0` → `var(--red)`
- `edge === null` → `var(--border-hi)` (default)

Gauge only renders when `prob_implicita_adj != null || prob_modelo != null`.

- [ ] **Step 1: Rewrite `frontend/src/components/SelectionCard.jsx`**

```jsx
const MERCADO_LABEL = {
  '1X2': '1X2', over_under: 'Más/Menos', btts: 'Ambos marcan',
  handicap: 'Hándicap', exotic: 'Exótico',
}

const SEL_LABEL = {
  home: 'Local', draw: 'Empate', away: 'Visitante',
  over: 'Más', under: 'Menos', yes: 'Sí', no: 'No',
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
  const cobClass  = COB_CLASS[sel.nivel_cobertura] ?? 'nula'
  const accent    = accentColor(sel.edge)
  const modColor  = modelColor(sel.edge)
  const implPct   = sel.prob_implicita_adj != null
    ? Math.min(sel.prob_implicita_adj * 100, 100)
    : 0
  const modPct    = sel.prob_modelo != null
    ? Math.min(sel.prob_modelo * 100, 100)
    : 0
  const hasGauge  = sel.prob_implicita_adj != null || sel.prob_modelo != null

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
          <div className="sel-badges">
            <span className="badge-mkt">{mercadoLabel}{lineaStr}</span>
            <span className="badge-sel">{selLabel}</span>
            <span className="badge-odds">{sel.cuota.toFixed(2)}</span>
            <span className={`badge-cob ${cobClass}`}>{sel.nivel_cobertura}</span>
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
            <div className="ss-value">{sel.cuota.toFixed(2)}</div>
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
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/SelectionCard.jsx
git commit -m "feat: redesign SelectionCard — accent border, probability gauge, mono stats"
```

---

## Task 8: Disclaimer (`Disclaimer.jsx`)

**Files:**
- Rewrite: `frontend/src/components/Disclaimer.jsx`

Mono 9px, muted color, no emoji. Text comes from `data.disclaimer`.

- [ ] **Step 1: Rewrite `frontend/src/components/Disclaimer.jsx`**

```jsx
export default function Disclaimer({ texto }) {
  if (!texto) return null
  return <div className="disclaimer">{texto}</div>
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/components/Disclaimer.jsx
git commit -m "style: simplify Disclaimer to mono strip, remove emoji"
```

---

## Task 9: Delete SummaryCard and Final Verification

**Files:**
- Delete: `frontend/src/components/SummaryCard.jsx`
- Verify: dev server runs, all states render correctly

`SummaryCard.jsx` is no longer imported anywhere (replaced by `Ticket.jsx` in Task 2).

- [ ] **Step 1: Delete `SummaryCard.jsx`**

```bash
git rm frontend/src/components/SummaryCard.jsx
```

- [ ] **Step 2: Start dev server and verify visually**

```bash
cd frontend && npm run dev
```

Open `http://localhost:5173` and verify:

1. **idle state**: dot-grid background visible, topbar sticky with logo + status pill (no btn-nueva), upload zone centered with league pill, SVG icon, "Sube tu parlay" title, casas row, format badges, model strip below.
2. **file selected**: preview image appears inside drop zone, "Cambiar imagen" button visible, "Analizar parlay" button becomes enabled.
3. **uploading state**: upload zone shows preview (disabled), spinner with mono text appears below.
4. **result state**: topbar shows "← Nueva consulta" button, ticket with 2px top bar + confidence block + 5 metrics + dashed footer, selection cards with left accent border + gauge + stats grid.
5. **error state**: red-lo banner centered with mono error title, retry button.

- [ ] **Step 3: Commit**

```
git add -A
git commit -m "chore: remove SummaryCard.jsx — replaced by Ticket"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] §3 Tipografía — Figtree/IBM Plex Mono/Syne via `@import` in Task 1
- [x] §3 Paleta — all `--var` names match spec exactly
- [x] §3 Fondo — dot-grid `radial-gradient` in body
- [x] §4.1 Topbar — SVG bars, Syne logo, status pill center, btn-nueva right (Task 2)
- [x] §4.2 UploadZone — league pill, SVG icon, casas, formats, model strip (Task 3)
- [x] §4.3 Spinner — CSS spin, mono text, ~15-20s note (Task 4)
- [x] §4.4 Ticket — 2px bar, confidence block, 5 metrics, dashed footer (Task 5)
- [x] §4.5 CorrelationAlert — CORR badge, yellow-lo bg (Task 6)
- [x] §4.6 SelectionCard — accent border logic, gauge with ticks, stats, alerts (Task 7)
- [x] §4.7 ErrorBanner — red-lo bg, mono title, retry btn (Task 1 CSS + Task 2 JSX)
- [x] §4.8 Disclaimer — mono 9px, muted (Task 8)
- [x] §5 Layout — results-wrap max-width 1080px, sel-grid 2-col, spacing (Task 1 CSS)
- [x] §8 Traducciones — MERCADO_LABEL + SEL_LABEL in SelectionCard (Task 7)
- [x] §9 No-change files — api.js, main.jsx, vite.config.js untouched

**Type consistency:**
- `Ticket` receives `{ resumen, meta }` — App.jsx passes both ✓
- `CorrelationAlert` receives `{ correlaciones }` — array from `result.correlaciones` ✓
- `SelectionCard` receives `{ sel, index }` — same signature as before ✓
- `Disclaimer` receives `{ texto }` — `result.disclaimer` is a string ✓
- `UploadZone` receives `{ file, onFile, onSubmit, loading }` — same signature ✓

**CSS class consistency across tasks:**
- `.sel-grid` defined in Task 1, used in App.jsx Task 2 ✓
- `.results-wrap` defined in Task 1, used in App.jsx Task 2 ✓
- `.section-label` defined in Task 1, used in App.jsx Task 2 ✓
- `.error-banner` / `.btn-retry` defined in Task 1, used in App.jsx Task 2 ✓
- All gauge classes defined in Task 1, used in SelectionCard Task 7 ✓
