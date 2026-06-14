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
