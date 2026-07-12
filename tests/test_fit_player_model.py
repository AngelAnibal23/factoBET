import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import math

import fit_player_model
from fit_player_model import registros_desde_eventos, _gate

# Dos partidos. event A: equipo "POR" mete 2 goles (p1 1 gol + p2 1 gol), p1 titular.
EVENTOS = [
    {"event_id": "A", "equipo": "POR", "player_id": "p1", "player_nombre": "R",
     "tipo": "Goal", "fue_titular": True},
    {"event_id": "A", "equipo": "POR", "player_id": "p2", "player_nombre": "B",
     "tipo": "Goal", "fue_titular": True},
    {"event_id": "A", "equipo": "POR", "player_id": "p2", "player_nombre": "B",
     "tipo": "Assistance", "fue_titular": True},
]
# titulares del equipo POR en event A (para n_titulares y para incluir a los que no anotaron)
TITULARES = {("A", "POR"): {"p1": "R", "p2": "B", "p3": "C"}}


def test_registros_cuenta_goles_y_titulares():
    regs = registros_desde_eventos(EVENTOS, TITULARES)
    by = {(r["event_id"], r["player_id"]): r for r in regs}
    # p1 anotó 1 de los 2 goles del equipo, fue titular, 3 titulares
    assert by[("A", "p1")]["goles_jugador"] == 1
    assert by[("A", "p1")]["goles_equipo"] == 2
    assert by[("A", "p1")]["n_titulares"] == 3
    # p2 anotó 1 y asistió 1
    assert by[("A", "p2")]["goles_jugador"] == 1
    assert by[("A", "p2")]["asist_jugador"] == 1
    # p3 fue titular pero no anotó -> registro con 0 goles (entra al reparto)
    assert by[("A", "p3")]["goles_jugador"] == 0
    assert by[("A", "p3")]["goles_equipo"] == 2


# Flashscore etiqueta el penal convertido como tipo "Penalty" y el autogol como
# "Own goal" (codigos IE 10/4 vs 3 del gol normal). El penal SI es "el jugador anota"
# (las estrellas patean penales = los jugadores que la casa ofrece); el autogol NO.
EVENTOS_PEN = [
    {"event_id": "B", "equipo": "ESP", "player_id": "q1", "player_nombre": "Pen",
     "tipo": "Penalty", "fue_titular": True},
    {"event_id": "B", "equipo": "ESP", "player_id": "q2", "player_nombre": "Og",
     "tipo": "Own goal", "fue_titular": True},
]
TITULARES_PEN = {("B", "ESP"): {"q1": "Pen", "q2": "Og"}}


def test_penal_cuenta_autogol_no():
    regs = registros_desde_eventos(EVENTOS_PEN, TITULARES_PEN)
    by = {(r["event_id"], r["player_id"]): r for r in regs}
    # el penal convertido cuenta como gol del jugador y del equipo
    assert by[("B", "q1")]["goles_jugador"] == 1
    # el autogol NO se le acredita al que lo metió
    assert by[("B", "q2")]["goles_jugador"] == 0
    # solo el penal entra al total del equipo (autogol fuera)
    assert by[("B", "q1")]["goles_equipo"] == 1


def _reg(pid, gol, n_tit=11):
    return {"player_id": pid, "nombre": pid, "equipo": "T",
            "goles_jugador": gol, "asist_jugador": 0,
            "goles_equipo": 1, "n_titulares": n_tit}


def test_gate_ignora_jugadores_no_elegibles():
    # 'star' tiene 2 partidos en train (elegible con min_partidos=2);
    # 'sub' tiene 1 (no elegible). El gate solo debe puntuar a los elegibles:
    # agregar la fila de 'sub' al test NO debe cambiar el Brier del modelo.
    train = [_reg("star", 1), _reg("star", 1), _reg("sub", 1)]
    test_base = [_reg("star", 0)]
    test_con_sub = test_base + [_reg("sub", 1)]
    bm1, _ = _gate(train, test_base, "goal", min_partidos=2)
    bm2, _ = _gate(train, test_con_sub, "goal", min_partidos=2)
    assert bm1 == bm2  # 'sub' (no elegible) no entra en la evaluación


def test_gate_sin_elegibles_devuelve_nan():
    # nadie alcanza el umbral -> no hay nada que puntuar.
    train = [_reg("sub", 1)]
    test = [_reg("sub", 1)]
    bm, bb = _gate(train, test, "goal", min_partidos=5)
    assert math.isnan(bm)


def test_lambda_proxy_calibrado_a_tasa_real():
    # Tras el fix de datos la tasa real es ~1.05 goles/equipo; el proxy del gate
    # debe reflejarla (no el 1.35 viejo que sobre-predecía ~1.8x).
    assert fit_player_model.LAMBDA_PROXY <= 1.1


def test_k_shrink_calibrado_a_cola_elite():
    # Grid 2026-07-11 (con lambda por-equipo): k=5 dejaba gap +2.8 pts en el decil
    # elite (D10) y k=3 lo cierra (+0.3) con Brier goal igual; k>=8 lo agranda.
    # Decisión de Angel: k=3.
    assert fit_player_model.K_SHRINK == 3.0


# --- λ por-equipo en la medición (cola elite, Paso A) ---------------------
# El proxy plano sub-predice a los elite (equipos que anotan >1.0/partido) y
# sobre-predice a los de equipos débiles. lambdas_por_equipo estima la tasa
# real de cada selección desde train, con shrinkage hacia la media global.

from fit_player_model import lambdas_por_equipo


def _reg_ev(eid, pid, equipo, gol, goles_eq, n_tit=11):
    return {"event_id": eid, "player_id": pid, "nombre": pid, "equipo": equipo,
            "goles_jugador": gol, "asist_jugador": 0,
            "goles_equipo": goles_eq, "n_titulares": n_tit}


def test_lambdas_por_equipo_media_sin_shrink():
    # k=0 -> media exacta por equipo; filas repetidas del MISMO partido (una por
    # titular) cuentan como UN partido, no once.
    regs = [_reg_ev("A", "p1", "FRA", 1, 3), _reg_ev("A", "p2", "FRA", 0, 3),
            _reg_ev("B", "p1", "FRA", 0, 1),
            _reg_ev("C", "q1", "PAN", 0, 0)]
    lams, lam_global = lambdas_por_equipo(regs, k=0.0)
    assert lams["FRA"] == 2.0        # (3+1)/2, el partido A no se duplica por p2
    assert lams["PAN"] == 0.0
    assert abs(lam_global - 4 / 3) < 1e-9   # (3+1+0)/3 partidos


def test_lambdas_por_equipo_shrink_hacia_global():
    # Un equipo con 1 solo partido de 4 goles queda ENTRE la media global y su
    # media propia, y con k grande se pega a la global.
    regs = [_reg_ev(f"E{i}", "p", "MED", 0, 1) for i in range(8)]
    regs.append(_reg_ev("X", "q", "NUEVO", 0, 4))
    lams_k1, g = lambdas_por_equipo(regs, k=1.0)
    lams_k9, _ = lambdas_por_equipo(regs, k=9.0)
    assert g < lams_k9["NUEVO"] < lams_k1["NUEVO"] < 4.0


def test_lambdas_por_equipo_vacio_cae_al_proxy():
    lams, lam_global = lambdas_por_equipo([], k=5.0)
    assert lams == {}
    assert lam_global == fit_player_model.LAMBDA_PROXY


def test_gate_distingue_equipo_fuerte_de_debil():
    # Dos estrellas con la MISMA cuota (anotan todos los goles de su equipo),
    # pero FUERTE mete 2/partido y DEBIL 1/partido. En test ambas anotan: la de
    # FUERTE debía tener prob mayor -> Brier menor. Con el proxy plano ambas
    # puntuarían igual. Aplica al modelo Y al baseline (comparación justa).
    train = ([_reg_ev(f"F{i}", "star_f", "FUERTE", 2, 2) for i in range(6)]
             + [_reg_ev(f"D{i}", "star_d", "DEBIL", 1, 1) for i in range(6)])
    test_f = [_reg_ev("TF", "star_f", "FUERTE", 1, 2)]
    test_d = [_reg_ev("TD", "star_d", "DEBIL", 1, 1)]
    bm_f, bb_f = _gate(train, test_f, "goal", min_partidos=2)
    bm_d, bb_d = _gate(train, test_d, "goal", min_partidos=2)
    assert bm_f < bm_d
    assert bb_f < bb_d
