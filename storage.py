"""
Storage layer — Phase 2
Persists each parlay analysis to Supabase after the statistical engine runs.

Tables written:
  analisis_parlays   — one row per submitted parlay
  selecciones_parlay — one row per bet line within the parlay

Call save_analysis() from main.py after analyze() succeeds.
If storage fails the exception bubbles up; main.py catches it and logs without
failing the HTTP response — the user still gets their analysis.
"""

import os
import logging
from supabase import create_client
from dotenv import load_dotenv

from analyzer import ParlayAnalysis
from validator import ValidatedParlay

load_dotenv()
log = logging.getLogger(__name__)

_sb = None


def _client():
    global _sb
    if _sb is None:
        _sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _sb


def save_analysis(
    result: ParlayAnalysis,
    parlay: ValidatedParlay,
    image_hash: str,
) -> str:
    """
    Persist a completed analysis.

    Args:
        result:     ParlayAnalysis from analyzer.analyze()
        parlay:     ValidatedParlay from validator.validate() — contains raw OCR names
        image_hash: SHA-256 prefix computed in main.py

    Returns:
        UUID of the inserted analisis_parlays row (parlay_id)
    """
    sb = _client()

    # Build a per-selection index of which correlations involve it
    corr_by_idx: dict[int, list[dict]] = {}
    for c in result.correlaciones:
        for idx, other in ((c.sel_idx_1, c.sel_idx_2), (c.sel_idx_2, c.sel_idx_1)):
            corr_by_idx.setdefault(idx, []).append({
                "tipo":                 c.tipo,
                "nota":                 c.nota,
                "otra_seleccion_idx":   other + 1,  # 1-indexed for readability
            })

    # ── 1. Insert parlay row ─────────────────────────────────────────────────
    parlay_row = {
        "prob_parlay_real":        result.prob_parlay_modelo,
        "prob_parlay_implicita":   result.prob_parlay_impl,
        "cuota_total":             result.cuota_total,
        "n_selecciones":           len(result.selecciones),
        "tiene_correlaciones":     len(result.correlaciones) > 0,
        "tiene_mercados_exoticos": any(s.mercado_exotico for s in result.selecciones),
        "nivel_confianza":         result.nivel_confianza,
        "razon_confianza":         result.razones_confianza,
        "casa_apuestas":           result.casa_apuestas,
        "imagen_hash":             image_hash,
        "resultado_parlay":        "PENDIENTE",
    }

    resp = sb.table("analisis_parlays").insert(parlay_row).execute()
    parlay_id: str = resp.data[0]["id"]
    log.info("analisis_parlays insertado: %s", parlay_id)

    # ── 2. Insert one row per selection ──────────────────────────────────────
    sel_rows = []
    for i, (sa, sv) in enumerate(zip(result.selecciones, parlay.selecciones)):
        features_snapshot = {
            "n_partidos_local":     sa.n_partidos_local,
            "n_partidos_visitante": sa.n_partidos_visitante,
            "equipo_local_id":      sa.equipo_local_id,
            "equipo_visitante_id":  sa.equipo_visitante_id,
            "version_modelo":       result.version_modelo,
            "margen_aplicado":      result.margen_aplicado,
        }

        corrs = corr_by_idx.get(i) or None   # NULL in DB if no correlations

        sel_rows.append({
            "parlay_id":               parlay_id,
            "equipo_local_raw":        sv.equipo_local_raw,
            "equipo_visitante_raw":    sv.equipo_visitante_raw or None,
            "mercado":                 sa.mercado,
            "seleccion":               sa.seleccion,
            "linea":                   sa.linea,
            "cuota":                   sa.cuota,
            "prob_implicita":          sa.prob_implicita,
            "prob_implicita_adj":      sa.prob_implicita_adj,
            "prob_modelo":             sa.prob_modelo,
            "edge":                    sa.edge,
            "kelly_fraccion":          sa.kelly_fraccion,
            "lambda_home":             sa.lambda_home,
            "lambda_away":             sa.lambda_away,
            "features_snapshot":       features_snapshot,
            "nivel_cobertura":         sa.nivel_cobertura,
            "es_mercado_exotico":      sa.mercado_exotico,
            "correlaciones_detectadas": corrs,
            "version_modelo":          result.version_modelo,
        })

    sb.table("selecciones_parlay").insert(sel_rows).execute()
    log.info("%d selecciones insertadas para parlay %s", len(sel_rows), parlay_id)

    return parlay_id
