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


def goal_leg_mask(mercado: str, seleccion: str, linea) -> np.ndarray:
    """Máscara booleana 11x11 de las celdas (i,j) donde esta pata es VERDADERA."""
    I, J = np.indices((MAX_GOALS + 1, MAX_GOALS + 1))
    if mercado == "1X2":
        if seleccion == "home": return I > J
        if seleccion == "draw": return I == J
        if seleccion == "away": return I < J
    elif mercado == "over_under":
        total = I + J
        if seleccion == "over":  return total > linea
        if seleccion == "under": return total < linea
    elif mercado == "btts":
        yes = (I > 0) & (J > 0)
        return yes if seleccion == "yes" else ~yes
    elif mercado == "handicap":
        win_home = (I + linea - J) > 0
        return win_home if seleccion == "home" else ~win_home
    elif mercado == "resultado_exacto":
        a, b = parse_exact_score(seleccion)
        return (I == a) & (J == b)
    raise ValueError(f"Pata no modelable en familia goles: {mercado}/{seleccion}")


def marginal_prob(matrix: np.ndarray, leg: tuple) -> float:
    """Probabilidad marginal de una sola pata (contexto informativo)."""
    return float(matrix[goal_leg_mask(*leg)].sum())


def joint_ceiling(matrix: np.ndarray, legs: list[tuple]) -> float:
    """Conjunta de varias patas del mismo partido = techo de la prob real."""
    mask = np.ones(matrix.shape, dtype=bool)
    for leg in legs:
        mask &= goal_leg_mask(*leg)
    return float(matrix[mask].sum())


def _fractional_kelly(prob: float, cuota: float):
    b = cuota - 1.0
    q = 1.0 - prob
    full = (b * prob - q) / b
    if full <= 0:
        return None
    return round(full * KELLY_FRACTION, 4)


def verdict(ceiling, cuota_total, n_modelables: int, n_exoticas: int):
    """Devuelve (veredicto, kelly_fraccion).

    SIN_VALOR     : ceiling <= 1/cuota -> EV<=0 garantizado (prob_real <= ceiling).
    NO_CONCLUYENTE: ceiling > 1/cuota con patas exóticas (techo = cota superior).
    VALOR         : ceiling > 1/cuota sin exóticas (ceiling = prob real) + Kelly.
    NO_EVALUABLE  : ninguna pata modelable.
    """
    if n_modelables == 0:
        return "NO_EVALUABLE", None
    p = 1.0 / cuota_total
    if ceiling <= p:
        return "SIN_VALOR", None
    if n_exoticas == 0:
        return "VALOR", _fractional_kelly(ceiling, cuota_total)
    return "NO_CONCLUYENTE", None


def bb_confidence(veredicto: str, n_modelables: int, n_exoticas: int):
    """Confianza = cuánto confiar en el VEREDICTO."""
    if veredicto == "SIN_VALOR":
        return "ALTA", ["Sin valor garantizado: incluso el mejor caso (techo) no supera la cuota."]
    if veredicto == "VALOR":
        return "ALTA", ["Todas las patas modelables: el techo es la probabilidad real."]
    if veredicto == "NO_EVALUABLE":
        return "BAJA", ["Ninguna pata es modelable: no se puede formar un techo."]
    # NO_CONCLUYENTE
    total = n_modelables + n_exoticas
    if n_exoticas <= 2:
        return "MEDIA", [f"{n_exoticas} pata(s) no modelable(s): el techo es una cota superior; el resultado depende de ellas."]
    return "BAJA", [f"{n_exoticas} de {total} patas no modelables: el techo es muy flojo."]


class BetBuilderSinCuotaError(ValueError):
    """Bet builder sin cuota_total: no se puede formar el veredicto."""


def analyze_bet_builder(parlay, lh, la, rho, version_modelo: str, margin: float):
    """Ensambla el análisis de un bet builder en un ParlayAnalysis.

    lh/la/rho: del partido (lh None si los equipos no están en el modelo).
    Import local de analyzer para evitar ciclo de import a nivel de módulo.
    """
    from analyzer import SelectionAnalysis, ParlayAnalysis

    if not parlay.cuota_total:
        raise BetBuilderSinCuotaError("Bet builder sin cuota_total: no se puede formar el veredicto.")

    covered = lh is not None
    matrix = scoreline_matrix(lh, la, rho) if covered else None

    analyses = []
    goal_legs = []
    exoticas_desc = []
    for sel in parlay.selecciones:
        is_goal = sel.mercado in GOAL_MARKETS
        modelable = covered and is_goal
        if modelable:
            leg = (sel.mercado, sel.seleccion, sel.linea)
            prob_mod = round(marginal_prob(matrix, leg), 6)
            goal_legs.append(leg)
            nivel_cov, alertas = "ALTA", []
        elif not is_goal:
            prob_mod = None
            exoticas_desc.append(sel.seleccion)
            nivel_cov, alertas = "NULA", ["Mercado exótico: el modelo no puede validar esta selección."]
        else:  # goles pero sin cobertura de equipos
            prob_mod = None
            nivel_cov, alertas = "BAJA", ["Equipos sin datos en el modelo: no se puede calcular probabilidad."]

        analyses.append(SelectionAnalysis(
            equipo_local=sel.local_match.canonical,
            equipo_visitante=sel.visitante_match.canonical if sel.visitante_match else None,
            equipo_local_id=sel.local_match.equipo_id,
            equipo_visitante_id=sel.visitante_match.equipo_id if sel.visitante_match else None,
            mercado=sel.mercado, seleccion=sel.seleccion,
            cuota=None, linea=sel.linea,
            prob_implicita=None, prob_implicita_adj=None,
            prob_modelo=prob_mod,
            lambda_home=round(lh, 4) if covered else None,
            lambda_away=round(la, 4) if covered else None,
            edge=None, kelly_fraccion=None,
            nivel_cobertura=nivel_cov, mercado_exotico=sel.mercado_exotico,
            n_partidos_local=0, n_partidos_visitante=0, alertas=alertas,
        ))

    n_modelables = len(goal_legs)
    n_exoticas = len(parlay.selecciones) - n_modelables
    ceiling = joint_ceiling(matrix, goal_legs) if (covered and n_modelables > 0) else None

    vered, kelly = verdict(ceiling, parlay.cuota_total, n_modelables, n_exoticas)
    nivel_conf, razones = bb_confidence(vered, n_modelables, n_exoticas)
    p_impl = round(1.0 / parlay.cuota_total, 6)

    # Marcador más probable del partido (solo selecciones por ahora). La matriz ya
    # está calculada; el bet builder es un único partido entre dos selecciones.
    marcadores = []
    if covered and version_modelo == "intl_v0.1":
        from marcador import marcador_partido
        match_sel = next((s for s in parlay.selecciones if s.visitante_match), None)
        if match_sel:
            marcadores = [marcador_partido(
                lh, la, rho,
                match_sel.local_match.canonical,
                match_sel.visitante_match.canonical,
            )]

    return ParlayAnalysis(
        selecciones=analyses, prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=parlay.cuota_total, casa_apuestas=parlay.casa_apuestas,
        nivel_confianza=nivel_conf, razones_confianza=razones, correlaciones=[],
        version_modelo=version_modelo, margen_aplicado=margin,
        es_bet_builder=True, veredicto=vered,
        prob_techo=round(ceiling, 6) if ceiling is not None else None,
        prob_impl_combinada=p_impl, n_modelables=n_modelables, n_exoticas=n_exoticas,
        bet_builder_kelly=kelly, exoticas_desc=exoticas_desc,
        marcadores_partido=marcadores,
    )
