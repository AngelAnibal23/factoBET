"""
Helpbetor API — main.py
FastAPI backend, Phase 1 MVP.

Endpoints:
  POST /api/v1/parlay/analizar   — full pipeline: OCR → validacion → analisis
  GET  /api/v1/modelo/estado     — health check + model info

Phase 1 limitations (to be added in Phase 3):
  - No LLM narrative (Groq/Llama) — only numbers
  - No image hash deduplication
  - No match timing classification
"""

import hashlib
import io
import logging
import time
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from contextlib import asynccontextmanager

from ocr import extract_parlay, OcrExtractionError, OcrParseError
from validator import validate, _load_teams, ValidationError, SyntacticError, SemanticError, RangeError
from analyzer import analyze, warm_up, ParlayAnalysis
from storage import save_analysis
from narrator import generate_narrative

# ── Startup: warm up model cache and team list ────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_teams()    # cache teams
    warm_up()       # load matches + fit Dixon-Coles (runs once, cached 6h)
    yield

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Helpbetor API",
    version="0.1.0",
    description="Auditor estadistico de parlays — Liga 1 Peruana",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_VERSION  = "v0.2"
MAX_FILE_BYTES = 5 * 1024 * 1024   # 5 MB
ALLOWED_TYPES  = {"image/jpeg", "image/png", "image/webp"}

# Teams are cached at startup so every request doesn't hit Supabase
_TEAMS_CACHE: list[dict] | None = None


def _get_teams() -> list[dict]:
    global _TEAMS_CACHE
    if _TEAMS_CACHE is None:
        _TEAMS_CACHE = _load_teams()
    return _TEAMS_CACHE


# ── Response helpers ──────────────────────────────────────────────────────────

def _ok(data: dict, duracion_ms: int) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": {
            "version_modelo": MODEL_VERSION,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "duracion_ms": duracion_ms,
        },
    }


def _err(code: str, message: str, detail: str = "", duracion_ms: int = 0) -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "detalle": detail},
        "meta": {
            "version_modelo": MODEL_VERSION,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "duracion_ms": duracion_ms,
        },
    }


# ── Serializers ───────────────────────────────────────────────────────────────

def _serialize_analysis(result: ParlayAnalysis, needs_confirmation: list[str], narrativa: str | None = None) -> dict:
    selecciones = []
    for s in result.selecciones:
        selecciones.append({
            "equipo_local":        s.equipo_local,
            "equipo_visitante":    s.equipo_visitante,
            "mercado":             s.mercado,
            "seleccion":           s.seleccion,
            "cuota":               s.cuota,
            "linea":               s.linea,
            "prob_implicita":      s.prob_implicita,
            "prob_implicita_adj":  s.prob_implicita_adj,
            "prob_modelo":         s.prob_modelo,
            "lambda_home":         s.lambda_home,
            "lambda_away":         s.lambda_away,
            "edge":                s.edge,
            "kelly_fraccion":      s.kelly_fraccion,
            "nivel_cobertura":     s.nivel_cobertura,
            "mercado_exotico":     s.mercado_exotico,
            "n_partidos_local":    s.n_partidos_local,
            "n_partidos_visitante":s.n_partidos_visitante,
            "alertas":             s.alertas,
        })

    correlaciones = []
    for c in result.correlaciones:
        correlaciones.append({
            "seleccion_idx_1": c.sel_idx_1 + 1,
            "seleccion_idx_2": c.sel_idx_2 + 1,
            "tipo":            c.tipo,
            "nota":            c.nota,
        })

    n_modeladas = sum(1 for s in result.selecciones if s.prob_modelo is not None)

    return {
        "resumen": {
            "prob_parlay_modelo":  result.prob_parlay_modelo,
            "prob_parlay_impl":    result.prob_parlay_impl,
            "cuota_total":         result.cuota_total,
            "n_selecciones":       len(result.selecciones),
            "n_modeladas":         n_modeladas,
            "casa_apuestas":       result.casa_apuestas,
            "margen_aplicado":     result.margen_aplicado,
            "nivel_confianza":     result.nivel_confianza,
            "razones_confianza":   result.razones_confianza,
            "tiene_correlaciones": len(result.correlaciones) > 0,
            "tiene_exoticos":      any(s.mercado_exotico for s in result.selecciones),
        },
        "selecciones":         selecciones,
        "correlaciones":       correlaciones,
        "confirmacion_requerida": needs_confirmation,
        "narrativa":           narrativa,
        "disclaimer": (
            "Este analisis es estadistico, no predictivo. El futbol tiene alta varianza "
            "irreducible. El valor estadistico solo se realiza en el largo plazo con "
            "disciplina de bankroll. Este sistema no garantiza resultados individuales."
        ),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/v1/parlay/analizar")
async def analizar_parlay(
    imagen: UploadFile = File(...),
    info_adicional: Optional[str] = Form(default=None),
):
    t0 = time.monotonic()

    # 1. File validation
    if imagen.content_type not in ALLOWED_TYPES:
        return JSONResponse(
            status_code=400,
            content=_err(
                "IMAGE_FORMAT_INVALID",
                f"Formato no soportado: {imagen.content_type}. Usa JPEG, PNG o WEBP.",
            ),
        )

    image_bytes = await imagen.read()

    if len(image_bytes) > MAX_FILE_BYTES:
        return JSONResponse(
            status_code=413,
            content=_err("IMAGE_TOO_LARGE", "La imagen supera el limite de 5 MB."),
        )

    image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

    # 2. OCR
    try:
        ocr_data = extract_parlay(image_bytes)
    except OcrExtractionError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err("OCR_EXTRACTION_FAILED",
                         "No se pudo extraer el parlay de la imagen. Sube una imagen mas nitida.",
                         str(e), ms),
        )
    except OcrParseError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err("OCR_PARSE_FAILED",
                         "La respuesta del OCR no era JSON valido.",
                         str(e), ms),
        )

    # 3. Validation
    try:
        teams  = _get_teams()
        parlay = validate(ocr_data, teams)
    except SyntacticError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err(e.code, e.message, e.detail, ms),
        )
    except SemanticError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err(e.code, e.message, e.detail, ms),
        )
    except RangeError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err(e.code, e.message, e.detail, ms),
        )

    # 4. Statistical analysis
    try:
        result = analyze(parlay)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=500,
            content=_err("ANALYSIS_ERROR",
                         "Error interno en el motor estadistico.",
                         str(e), ms),
        )

    # 5. Persist to Supabase (non-blocking: storage failure never kills the response)
    parlay_id = None
    try:
        parlay_id = save_analysis(result, parlay, image_hash)
    except Exception as e:
        log.error("Storage error — analysis returned but not saved: %s", e)

    # 6. Generate narrative (non-blocking: failure keeps narrativa=None)
    narrativa = None
    try:
        narrativa = generate_narrative(result)
    except Exception as e:
        log.error("Narrative generation failed: %s", e)

    ms   = int((time.monotonic() - t0) * 1000)
    data = _serialize_analysis(result, parlay.needs_confirmation, narrativa)
    data["image_hash"] = image_hash
    data["parlay_id"]  = parlay_id

    return JSONResponse(content=_ok(data, ms))


@app.get("/api/v1/modelo/estado")
async def modelo_estado():
    t0     = time.monotonic()
    teams  = _get_teams()
    ms     = int((time.monotonic() - t0) * 1000)
    return JSONResponse(content=_ok({
        "version_activa":     MODEL_VERSION,
        "ligas_cubiertas":    1,
        "liga_principal":     "Liga 1 Peruana",
        "equipos_cargados":   len(teams),
        "brier_score_actual": 0.2797,
        "target_brier":       0.25,
        "estado":             "operativo",
        "fase":               "Phase 3 — narrativa LLM activa (Gemini 2.5 Flash)",
    }, ms))


@app.get("/")
async def root():
    return {"message": "Helpbetor API v0.1 — POST /api/v1/parlay/analizar para analizar un parlay"}
