# tests/test_fit_player_sot.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fit_player_sot import registros_desde_filas, _gate

# Dos partidos del equipo "POR" con 2 jugadores cada uno.
FILAS = [
    # partido A
    {"event_id": 1, "equipo": "POR", "player_id": "p1", "player_nombre": "Sniper",
     "sot": 4, "fue_titular": True},
    {"event_id": 1, "equipo": "POR", "player_id": "p2", "player_nombre": "Back",
     "sot": 0, "fue_titular": True},
    # partido B
    {"event_id": 2, "equipo": "POR", "player_id": "p1", "player_nombre": "Sniper",
     "sot": 3, "fue_titular": True},
    {"event_id": 2, "equipo": "POR", "player_id": "p2", "player_nombre": "Back",
     "sot": 1, "fue_titular": True},
]


def test_registros_arma_sot_equipo_y_n_titulares():
    regs = registros_desde_filas(FILAS)
    by = {(r["event_id"], r["player_id"]): r for r in regs}
    # sot_equipo del partido 1 = 4+0 = 4 ; n_titulares = 2
    assert by[(1, "p1")]["sot_equipo"] == 4
    assert by[(1, "p1")]["sot_jugador"] == 4
    assert by[(1, "p1")]["n_titulares"] == 2
    assert by[(2, "p2")]["sot_equipo"] == 4   # 3+1
    # solo titulares producen registro
    assert len(regs) == 4


def test_gate_premia_al_que_dispara():
    # Construir train/test donde p1 domina los SoT: el modelo (cuota) debe
    # batir al baseline igualitario (1/n_titulares) en Brier.
    regs = registros_desde_filas(FILAS * 5)   # 10 partidos por jugador (elegibles)
    bm, bb = _gate(regs, regs, min_partidos=2)
    assert bm < bb   # modelo mejor (Brier menor) que baseline
