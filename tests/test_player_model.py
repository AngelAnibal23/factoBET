import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_model import estimar_cuotas

# 3 jugadores del equipo "POR". Cada registro = un partido como titular.
# goles_equipo = goles totales del equipo ese partido.
REGISTROS = [
    {"player_id": "p1", "nombre": "Ronaldo",  "equipo": "Portugal",
     "goles_jugador": 2, "asist_jugador": 0, "goles_equipo": 3, "n_titulares": 11},
    {"player_id": "p1", "nombre": "Ronaldo",  "equipo": "Portugal",
     "goles_jugador": 1, "asist_jugador": 1, "goles_equipo": 2, "n_titulares": 11},
    {"player_id": "p2", "nombre": "B Fernandes", "equipo": "Portugal",
     "goles_jugador": 0, "asist_jugador": 2, "goles_equipo": 3, "n_titulares": 11},
    {"player_id": "p3", "nombre": "Suplente",  "equipo": "Portugal",
     "goles_jugador": 0, "asist_jugador": 0, "goles_equipo": 2, "n_titulares": 11},
]


def test_estimar_cuotas_estructura_y_rango():
    out = estimar_cuotas(REGISTROS, k=2.0)
    assert set(out) == {"p1", "p2", "p3"}
    assert out["p1"]["nombre"] == "Ronaldo"
    assert out["p1"]["equipo"] == "Portugal"
    # Ronaldo mete muchos goles -> cuota_gol alta; B Fernandes asiste -> cuota_asist alta
    assert out["p1"]["cuota_gol"] > out["p2"]["cuota_gol"]
    assert out["p2"]["cuota_asist"] > out["p1"]["cuota_asist"]
    # cuotas son fracciones en (0,1)
    for v in out.values():
        assert 0.0 < v["cuota_gol"] < 1.0
        assert 0.0 <= v["cuota_asist"] < 1.0


def test_shrinkage_acerca_al_prior_con_pocos_datos():
    # p3 (suplente, 1 partido, 0 goles): con k alto su cuota_gol se pega al prior 1/11
    flojo  = estimar_cuotas(REGISTROS, k=0.1)
    fuerte = estimar_cuotas(REGISTROS, k=50.0)
    prior = 1.0 / 11
    assert abs(fuerte["p3"]["cuota_gol"] - prior) < abs(flojo["p3"]["cuota_gol"] - prior)
