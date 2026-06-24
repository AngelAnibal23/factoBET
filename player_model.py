"""Modelo por-jugador (anota/asiste) de la Capa 2.

Top-down: reparte el lambda de goles del equipo (Capa 1) entre jugadores segun su
cuota historica de goles/asistencias, estimada por metodo de momentos con
shrinkage empirico-Bayes hacia un prior igualitario (1/n_titulares). Poisson
sobre los eventos del jugador. NO lee red al importar: funciones puras.
"""

from scipy.stats import poisson

METRICAS_PLAYER = ("goal", "assist", "goal_or_assist")


def estimar_cuotas(registros: list[dict], k: float = 5.0) -> dict:
    """Estima cuota_gol y cuota_asist por jugador con shrinkage.

    registros: lista de partidos-como-titular, cada uno
      {player_id, nombre, equipo, goles_jugador, asist_jugador, goles_equipo, n_titulares}.
    k: fuerza del prior (n de "partidos virtuales" hacia el prior igualitario).

    Cuota = fraccion de goles del equipo que el jugador anoto/asistio. Los partidos
    con goles_equipo==0 se excluyen del promedio (share indefinido) pero su prior
    1/n_titulares si informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        prior = sum(1.0 / r["n_titulares"] for r in regs) / len(regs)
        shares_gol = [r["goles_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        shares_ast = [r["asist_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        cuota_gol = (sum(shares_gol) + k * prior) / (len(shares_gol) + k)
        cuota_ast = (sum(shares_ast) + k * prior) / (len(shares_ast) + k)
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_gol": cuota_gol, "cuota_asist": cuota_ast,
        }
    return out
