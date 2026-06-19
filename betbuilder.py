"""
Bet Builder — Fase 1
Motor de probabilidad conjunta para same-game multis.

Calcula la conjunta EXACTA de las patas de goles sobre la matriz de marcadores
Dixon-Coles (no multiplica marginales: respeta la correlación del mismo partido),
y emite un veredicto por techo. Agnóstico del engine: recibe (lh, la, rho).
"""

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10
KELLY_FRACTION = 0.20

# Mercados que la familia "goles" puede valorar desde la matriz de marcadores.
GOAL_MARKETS = {"1X2", "over_under", "btts", "handicap", "resultado_exacto"}


def scoreline_matrix(lh: float, la: float, rho: float) -> np.ndarray:
    """P(local=i, visitante=j) para i,j en {0..MAX_GOALS}, normalizada a suma 1.

    Aplica la corrección Dixon-Coles tau a las cuatro celdas de marcador bajo.
    """
    i = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(i, lh)
    pa = poisson.pmf(i, la)
    M = np.outer(ph, pa)
    M[0, 0] *= max(1e-10, 1 - lh * la * rho)
    M[1, 0] *= 1 + la * rho
    M[0, 1] *= 1 + lh * rho
    M[1, 1] *= max(1e-10, 1 - rho)
    return M / M.sum()


def parse_exact_score(seleccion) -> tuple[int, int]:
    """'1-3' -> (1, 3). ValueError si está mal formado o fuera de rango."""
    parts = str(seleccion).replace(" ", "").split("-")
    if len(parts) != 2:
        raise ValueError(f"Resultado exacto mal formado: {seleccion!r}")
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"Resultado exacto no numérico: {seleccion!r}")
    if not (0 <= a <= MAX_GOALS and 0 <= b <= MAX_GOALS):
        raise ValueError(f"Resultado exacto fuera de rango [0,{MAX_GOALS}]: {seleccion!r}")
    return a, b
