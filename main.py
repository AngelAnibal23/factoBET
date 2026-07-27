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
from betbuilder import BetBuilderSinCuotaError
from storage import save_analysis
from narrator import generate_narrative
from resolver import resolver_resultados

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

def _ok(data: dict, duracion_ms: int, version_modelo: str = MODEL_VERSION) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": {
            "version_modelo": version_modelo,
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

def _bet_builder_block(result: ParlayAnalysis) -> dict | None:
    if not getattr(result, "es_bet_builder", False):
        return None
    return {
        "veredicto":            result.veredicto,
        "prob_techo":           result.prob_techo,
        "prob_impl_combinada":  result.prob_impl_combinada,
        "n_modelables":         result.n_modelables,
        "n_exoticas":           result.n_exoticas,
        "exoticas":             result.exoticas_desc,
        "faltantes":            result.faltantes_desc,
        "kelly_fraccion":       result.bet_builder_kelly,
    }


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
            "player":              s.player,
            "faltante":            s.faltante,
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
        "bet_builder":         _bet_builder_block(result),
        "marcadores_partido":  list(getattr(result, "marcadores_partido", [])),
        "ausencias":           getattr(result, "ausencias", None),
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
    except BetBuilderSinCuotaError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err("BET_BUILDER_SIN_CUOTA",
                         "El bet builder no trae cuota combinada; no se puede emitir veredicto.",
                         str(e), ms),
        )
    except ValueError as e:
        # Parlay mixto (Liga 1 + Internacional): no analizable como un solo boleto.
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=422,
            content=_err("PARLAY_MIXTO",
                         "El parlay mezcla equipos de Liga 1 y selecciones internacionales.",
                         str(e), ms),
        )
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

    return JSONResponse(content=_ok(data, ms, result.version_modelo))


_OCR_DEMO_INTL = {
    "selecciones": [
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "1X2", "seleccion": "home", "cuota": None, "linea": None},
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "player", "seleccion": "yes", "player": "Lionel Messi",
         "metric": "sot", "umbral": 1, "faltante": False,
         "cuota": None, "linea": None},
    ],
    "cuota_total": 1.87,
    "casa_apuestas": "Betano",
}

# Man City vs Arsenal, nombres tal cual los escribiría una casa de apuestas
# ("Man City" en vez de "Manchester City"): el demo también prueba que los
# aliases resuelven. Solo goles/totales: counts_v0.1 aún no está publicado
# para la Premier (parametros_modelo vacío para su liga_id), así que una pata
# `count` caería exótica sin aportar nada al gate visual.
_OCR_DEMO_PREMIER = {
    "selecciones": [
        {"equipo_local": "Man City", "equipo_visitante": "Arsenal",
         "mercado": "1X2", "seleccion": "home", "cuota": None, "linea": None},
        {"equipo_local": "Man City", "equipo_visitante": "Arsenal",
         "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 2.5},
    ],
    "cuota_total": 1.75,
    "casa_apuestas": "Betano",
}

_AUSENTES_DEMO = {"equipos": {
    "Argentina": [
        {"nombre": "Lionel Messi", "estado": "out",
         "motivo": "Injured - Muscle", "posicion": None},
        {"nombre": "Angel Di Maria", "estado": "doubtful",
         "motivo": "Knock", "posicion": None}],
    "Austria": [
        {"nombre": "David Alaba", "estado": "out",
         "motivo": "Suspended", "posicion": "D"}]},
    "url": "https://www.sofascore.com/football/match/argentina-austria/demo",
    "scrapeado_en": "2026-07-22T12:00:00"}


def _ocr_demo(case: str) -> dict:
    """Bet builder hardcoded para el endpoint /demo. `?case=premier` arma el de
    la Premier League; cualquier otro valor (incl. vacío o "ausencias") arma el
    internacional de siempre."""
    return _OCR_DEMO_PREMIER if case == "premier" else _OCR_DEMO_INTL


def _payload_ausencias_demo(case: str) -> dict:
    """Payload de ausencias a inyectar en caché. Solo `?case=ausencias` trae
    ausentes reales (para ver el AusenciasBlock); todo lo demás es `sin_dato`."""
    return _AUSENTES_DEMO if case == "ausencias" else {"sin_dato": True}


@app.get("/api/v1/parlay/demo")
async def parlay_demo(case: str = ""):
    """Verificación visual SIN Gemini: corre el motor real sobre un bet builder
    hardcoded y devuelve el mismo envelope que el análisis normal. Útil cuando
    la cuota de OCR está agotada. No persiste ni llama al OCR.

    Sin `case` (o cualquier valor no reconocido): bet builder internacional de
    ejemploBET3 (Argentina vs Austria). `?case=ausencias` inyecta ausentes reales
    sobre ese mismo slip (Messi out -> pata muerta + Di María en duda + Alaba out)
    para ver el AusenciasBlock. `?case=premier` arma un bet builder de la Premier
    League (Man City vs Arsenal, 1X2 + total de goles) para verificar la nueva
    liga de clubes.

    Siempre inyecta una caché de ausencias keyed por los equipos DEL SLIP que se
    esté sirviendo (así el demo NO dispara el scrape real de ~2 min sin importar
    qué caso se pida)."""
    import os as _os
    import ausencias_sofascore as _aus
    t0 = time.monotonic()
    ocr_data = _ocr_demo(case)
    _payload = _payload_ausencias_demo(case)
    _local = ocr_data["selecciones"][0]["equipo_local"]
    _visit = ocr_data["selecciones"][0]["equipo_visitante"]
    _cache = _aus._cache_path(_local, _visit)
    _aus._escribir_cache(_cache, _payload)
    try:
        parlay = validate(ocr_data, _get_teams())
        result = analyze(parlay)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(status_code=500,
                            content=_err("DEMO_ERROR", "No se pudo armar el demo.", str(e), ms))
    finally:
        if _os.path.exists(_cache):
            _os.remove(_cache)
    ms = int((time.monotonic() - t0) * 1000)
    data = _serialize_analysis(result, parlay.needs_confirmation, narrativa=None)
    data["image_hash"] = "demo"
    data["parlay_id"] = None
    return JSONResponse(content=_ok(data, ms, result.version_modelo))


@app.get("/api/v1/modelo/estado")
async def modelo_estado():
    t0     = time.monotonic()
    teams  = _get_teams()
    ms     = int((time.monotonic() - t0) * 1000)
    return JSONResponse(content=_ok({
        "version_activa":     MODEL_VERSION,
        "ligas_cubiertas":    2,
        "liga_principal":     "Liga 1 Peruana",
        "ligas": [
            {"nombre": "Liga 1 Peruana", "modelo": "v0.2",      "brier_score": 0.2797},
            {"nombre": "Internacional",  "modelo": "intl_v0.1", "brier_score": 0.2470},
        ],
        "equipos_cargados":   len(teams),
        "brier_score_actual": 0.2797,
        "target_brier":       0.25,
        "estado":             "operativo",
        "fase":               "Phase 5 — Mundial 2026 integrado (ruteo Liga 1 / Internacional)",
    }, ms))


@app.post("/api/v1/admin/resolver-resultados")
async def resolver_resultados_endpoint(league: str = "per.1", dry_run: bool = False):
    t0 = time.monotonic()
    try:
        resumen = resolver_resultados(league=league, dry_run=dry_run)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=502,
            content=_err("RESOLVER_ERROR",
                         "Error resolviendo resultados desde ESPN.",
                         str(e), ms),
        )
    ms = int((time.monotonic() - t0) * 1000)
    return JSONResponse(content=_ok(resumen, ms))


@app.get("/")
async def root():
    return {"message": "Helpbetor API v0.1 — POST /api/v1/parlay/analizar para analizar un parlay"}
