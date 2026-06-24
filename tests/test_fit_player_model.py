import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fit_player_model import registros_desde_eventos

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
