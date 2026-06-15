"""
Motor Estadistico Internacional v0.1 — Dixon-Coles para selecciones.
Espejea engine_v02.py pero:
  - Ajusta desde un CSV (martj42/international_results), no Supabase.
  - La ventaja de local (gamma) solo aplica cuando neutral == False.

Train: 2018-2024 | Test: 2025+
Gate: superar al baseline ingenuo (tasas globales neutral-aware) por >= 3% relativo.
"""

import csv
import math
import warnings
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

warnings.filterwarnings("ignore")

MAX_GOALS = 10
XI = 0.004   # mismo decay que Liga 1 v0.2
CSV_PATH = "intl_results.csv"
TRAIN_HASTA = "2024-12-31"
TEST_DESDE = "2025-01-01"


# ── Loader CSV ────────────────────────────────────────────────────────────────

def cargar_csv(path=CSV_PATH):
    """Lee el CSV filtrado y devuelve la lista de partidos normalizados."""
    partidos = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        gl = int(r["home_score"])
        gv = int(r["away_score"])
        if gl > gv:
            res = "HOME"
        elif gl == gv:
            res = "DRAW"
        else:
            res = "AWAY"
        partidos.append({
            "home":      r["home_team"],
            "away":      r["away_team"],
            "gl":        gl,
            "gv":        gv,
            "fecha":     r["date"],
            "neutral":   r["neutral"].strip().upper() == "TRUE",
            "resultado": res,
        })
    return partidos


# ── Time weighting ────────────────────────────────────────────────────────────

def time_weight(fecha_str, ref_date, xi=XI):
    dt = datetime.fromisoformat(fecha_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (ref_date - dt).days)
    return math.exp(-xi * days)


# ── Dixon-Coles correction ────────────────────────────────────────────────────

def tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0:
        return 1 + la * rho
    elif x == 0 and y == 1:
        return 1 + lh * rho
    elif x == 1 and y == 1:
        return max(1e-10, 1 - rho)
    return 1.0


# ── Brier Score (normalizado 0-1) ─────────────────────────────────────────────

def brier_score(predictions):
    total = 0.0
    for ph, pd, pa, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (ph - o_h)**2 + (pd - o_d)**2 + (pa - o_a)**2
    return (total / len(predictions)) / 2
