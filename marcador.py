"""
Marcador más probable — derivados de la matriz de marcadores Dixon-Coles.

Post-procesamiento PURO de `scoreline_matrix()`: no toca el motor ni la base de
datos. Expone el marcador más probable del partido (argmax) como producto al
usuario, más el top-N y el 1X2 para la vista "ver detalle" opcional.
"""

import numpy as np

from betbuilder import scoreline_matrix

TOP_N = 5


def most_likely_scoreline(matrix: np.ndarray) -> tuple[int, int, float]:
    """Marcador con mayor probabilidad puntual: (goles_local, goles_vis, prob)."""
    i, j = np.unravel_index(np.argmax(matrix), matrix.shape)
    return int(i), int(j), float(matrix[i, j])


def top_scorelines(matrix: np.ndarray, n: int = TOP_N) -> list[tuple[int, int, float]]:
    """Los n marcadores más probables, de mayor a menor probabilidad."""
    flat = matrix.ravel()
    order = np.argsort(flat)[::-1][:n]
    cols = matrix.shape[1]
    return [(int(k // cols), int(k % cols), float(flat[k])) for k in order]


def outcome_probs(matrix: np.ndarray) -> tuple[float, float, float]:
    """Probabilidad 1X2 (gana local, empate, gana visitante) desde la matriz."""
    I, J = np.indices(matrix.shape)
    ph = float(matrix[I > J].sum())
    pd = float(matrix[I == J].sum())
    pa = float(matrix[I < J].sum())
    return ph, pd, pa


def marcador_partido(lh: float, la: float, rho: float,
                     local: str, visitante: str) -> dict:
    """Arma el bloque 'marcador más probable' de un partido para la respuesta.

    El campo plano (marcador/probabilidad) es el producto primario; `detalle`
    alimenta la vista opcional (top-5 + barras 1X2).
    """
    M = scoreline_matrix(lh, la, rho)
    gl, ga, prob = most_likely_scoreline(M)
    ph, pd, pa = outcome_probs(M)
    return {
        "equipo_local":     local,
        "equipo_visitante": visitante,
        "goles_local":      gl,
        "goles_visitante":  ga,
        "marcador":         f"{gl}-{ga}",
        "probabilidad":     round(prob, 4),
        "detalle": {
            "top": [
                {"marcador": f"{i}-{j}", "goles_local": i,
                 "goles_visitante": j, "probabilidad": round(p, 4)}
                for i, j, p in top_scorelines(M, TOP_N)
            ],
            "resultado": {
                "local":     round(ph, 4),
                "empate":    round(pd, 4),
                "visitante": round(pa, 4),
            },
        },
    }
