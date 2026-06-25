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
