"""Modelo por-jugador (anota/asiste) de la Capa 2.

Top-down: reparte el lambda de goles del equipo (Capa 1) entre jugadores según su
cuota histórica de goles/asistencias, estimada por método de momentos con
shrinkage empírico-Bayes hacia un prior igualitario (1/n_titulares). Poisson
sobre los eventos del jugador. NO lee red al importar: funciones puras.
"""

from scipy.stats import poisson

METRICAS_PLAYER = ("goal", "assist", "goal_or_assist")


def _shrink_share(shares: list[float], prior: float, k: float) -> float:
    """Media bayesiana de `shares` hacia `prior` con fuerza `k`. Si no hay shares
    (denom==0 con k==0) cae al prior."""
    denom = len(shares) + k
    return (sum(shares) + k * prior) / denom if denom > 0 else prior


def estimar_cuotas(registros: list[dict], k: float = 5.0,
                   min_partidos: int = 1) -> dict:
    """Estima cuota_gol y cuota_asist por jugador con shrinkage.

    registros: lista de partidos-como-titular, cada uno
      {player_id, nombre, equipo, goles_jugador, asist_jugador, goles_equipo, n_titulares}.
    k: fuerza del prior (n de "partidos virtuales" hacia el prior igualitario).
    min_partidos: solo se publican jugadores con al menos esta cantidad de partidos
      como titular. Con pocos partidos la cuota es ruido (no se distingue del 1/11)
      y las casas solo ofrecen props de jugadores establecidos; por eso filtramos.

    Cuota = fracción de goles del equipo que el jugador anotó/asistió. Los partidos
    con goles_equipo==0 se excluyen del promedio (share indefinido) pero su prior
    1/n_titulares sí informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        if len(regs) < min_partidos:
            continue
        prior = sum(1.0 / max(r["n_titulares"], 1) for r in regs) / len(regs)
        shares_gol = [r["goles_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        shares_ast = [r["asist_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]

        cuota_gol = _shrink_share(shares_gol, prior, k)
        cuota_ast = _shrink_share(shares_ast, prior, k)
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_gol": cuota_gol, "cuota_asist": cuota_ast,
        }
    return out


def estimar_cuotas_sot(registros: list[dict], k: float = 5.0,
                       min_partidos: int = 1) -> dict:
    """Estima cuota_sot por jugador con shrinkage hacia 1/n_titulares.

    registros: partidos-como-titular {player_id, nombre, equipo, sot_jugador,
      sot_equipo, n_titulares}. cuota_sot = fracción de los SoT del equipo que hizo
      el jugador. Partidos con sot_equipo==0 se excluyen del promedio (share
      indefinido); su prior 1/n_titulares sí informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        if len(regs) < min_partidos:
            continue
        prior = sum(1.0 / max(r["n_titulares"], 1) for r in regs) / len(regs)
        shares = [r["sot_jugador"] / r["sot_equipo"]
                  for r in regs if r["sot_equipo"] > 0]
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_sot": _shrink_share(shares, prior, k),
        }
    return out


from rapidfuzz import fuzz

RESOLVER_UMBRAL = 80.0   # token_set_ratio mínimo para aceptar un match de nombre


class PlayerModel:
    """Predictor por-jugador con params congelados. Solo contiene las métricas que
    pasaron el gate (en params['metricas']) y los jugadores con cuotas publicadas."""

    @classmethod
    def from_params(cls, params: dict) -> "PlayerModel":
        m = cls()
        m.metricas = set(params.get("metricas", []))
        m.jugadores = params.get("jugadores", {})
        return m

    def tiene(self, player_id: str, metric: str) -> bool:
        if player_id not in self.jugadores:
            return False
        if metric == "goal_or_assist":
            return {"goal", "assist"} <= self.metricas
        return metric in self.metricas

    def equipo_de(self, player_id: str) -> str | None:
        j = self.jugadores.get(player_id)
        return j["equipo"] if j else None

    def resolver(self, nombre: str) -> str | None:
        """Resuelve un nombre de jugador (del boleto) a player_id por fuzzy match."""
        if not nombre:
            return None
        mejor_id, mejor_score = None, 0.0
        for pid, j in self.jugadores.items():
            score = fuzz.token_set_ratio(nombre.lower(), j["nombre"].lower())
            if score > mejor_score:
                mejor_id, mejor_score = pid, score
        return mejor_id if mejor_score >= RESOLVER_UMBRAL else None

    def prob(self, player_id: str, metric: str, lambda_equipo: float,
             umbral: int = 1) -> float:
        """P(el jugador alcanza `umbral` eventos | es titular), Poisson top-down."""
        j = self.jugadores[player_id]
        if metric == "goal":
            lam = lambda_equipo * j["cuota_gol"]
        elif metric == "assist":
            lam = lambda_equipo * j["cuota_asist"]
        elif metric == "goal_or_assist":
            lam = lambda_equipo * (j["cuota_gol"] + j["cuota_asist"])
        else:
            raise ValueError(f"métrica player inválida: {metric!r}")
        return float(1.0 - poisson.cdf(umbral - 1, lam))
