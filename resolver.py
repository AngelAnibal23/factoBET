"""
Resolver — Phase 4 (Job Nocturno)
Marca el resultado real de cada selección de parlay consultando ESPN.
Fuente: ESPN hidden API. Sin cambios de schema en Supabase.
"""

import os
import logging
from datetime import datetime, timezone

import requests
from rapidfuzz import fuzz
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
MATCH_UMBRAL = 0.80   # mismo umbral que validator.py


# ── Lógica de acierto por mercado ─────────────────────────────────────────────

def _calcular_acierto(mercado, seleccion, linea, gl, gv):
    """Retorna True/False si la selección acertó, o None si no es resoluble."""
    if gl is None or gv is None:
        return None

    if mercado == "1X2":
        if seleccion == "home": return gl > gv
        if seleccion == "draw": return gl == gv
        if seleccion == "away": return gl < gv

    elif mercado == "over_under":
        if linea is None:
            return None
        total = gl + gv
        if seleccion == "over":  return total > linea
        if seleccion == "under": return total < linea

    elif mercado == "btts":
        ambos = gl > 0 and gv > 0
        if seleccion == "yes": return ambos
        if seleccion == "no":  return not ambos

    elif mercado == "handicap":
        if linea is None:
            return None
        if seleccion == "home": return gl + linea > gv
        if seleccion == "away": return gv - linea > gl

    return None


# ── Mapeo de estado ESPN ──────────────────────────────────────────────────────

_STATUS_FINALIZADO = {"STATUS_FULL_TIME", "STATUS_FINAL"}
_STATUS_ESPECIAL = {
    "STATUS_FINAL_PEN", "STATUS_POSTPONED", "STATUS_CANCELED",
    "STATUS_CANCELLED", "STATUS_ABANDONED", "STATUS_SUSPENDED",
}


def _mapear_status(status_name):
    """FINALIZADO (resoluble) | PENDIENTE (no jugado/en curso) | ESPECIAL (anulado/penales)."""
    if status_name in _STATUS_FINALIZADO:
        return "FINALIZADO"
    if status_name in _STATUS_ESPECIAL:
        return "ESPECIAL"
    return "PENDIENTE"


# ── Resultado del parlay (por precedencia) ────────────────────────────────────

def _resultado_parlay(estados):
    """
    estados: lista de estado por selección NO exótica, cada uno en
    {GANADA, PERDIDA, PENDIENTE, ESPECIAL}.
    Precedencia: PERDIDA > PENDIENTE > ESPECIAL > GANADA.
    """
    if not estados:
        return "PENDIENTE"
    if "PERDIDA" in estados:
        return "PERDIDO"
    if "PENDIENTE" in estados:
        return "PENDIENTE"
    if "ESPECIAL" in estados:
        return "ANULADO"
    return "GANADO"


# ── Parseo de la respuesta ESPN ───────────────────────────────────────────────

def _score_int(competitor):
    s = competitor.get("score")
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _parse_eventos(espn_json):
    """Convierte el JSON del scoreboard ESPN en una lista de eventos normalizados."""
    eventos = []
    for e in espn_json.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        eventos.append({
            "local":            home["team"]["displayName"],
            "visitante":        away["team"]["displayName"],
            "goles_local":      _score_int(home),
            "goles_visitante":  _score_int(away),
            "status_name":      e.get("status", {}).get("type", {}).get("name", ""),
            "fecha":            e.get("date", ""),
        })
    return eventos
