"""Modelo por-jugador (anota/asiste) de la Capa 2.

Top-down: reparte el lambda de goles del equipo (Capa 1) entre jugadores según su
cuota histórica de goles/asistencias, estimada por método de momentos con
shrinkage empírico-Bayes hacia un prior igualitario (1/n_titulares). Poisson
sobre los eventos del jugador. NO lee red al importar: funciones puras.
"""

from scipy.stats import poisson

METRICAS_PLAYER = ("goal", "assist", "goal_or_assist")


def estimar_cuotas(registros: list[dict], k: float = 5.0) -> dict:
    """Estima cuota_gol y cuota_asist por jugador con shrinkage.

    registros: lista de partidos-como-titular, cada uno
      {player_id, nombre, equipo, goles_jugador, asist_jugador, goles_equipo, n_titulares}.
    k: fuerza del prior (n de "partidos virtuales" hacia el prior igualitario).

    Cuota = fracción de goles del equipo que el jugador anotó/asistió. Los partidos
    con goles_equipo==0 se excluyen del promedio (share indefinido) pero su prior
    1/n_titulares sí informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        prior = sum(1.0 / max(r["n_titulares"], 1) for r in regs) / len(regs)
        shares_gol = [r["goles_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        shares_ast = [r["asist_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]

        def _cuota(shares):
            denom = len(shares) + k
            return (sum(shares) + k * prior) / denom if denom > 0 else prior

        cuota_gol = _cuota(shares_gol)
        cuota_ast = _cuota(shares_ast)
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_gol": cuota_gol, "cuota_asist": cuota_ast,
        }
    return out
