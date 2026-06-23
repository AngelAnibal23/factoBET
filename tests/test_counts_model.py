import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from counts_model import estimar_metrica

# 4 partidos, equipos A,B,C,D. A genera muchos corners de local; D pocos.
# Cada partido = dict {home, away, val_home, val_away}.
PARTIDOS = [
    {"home": "A", "away": "B", "val_home": 10, "val_away": 4},
    {"home": "A", "away": "C", "val_home": 8,  "val_away": 5},
    {"home": "B", "away": "A", "val_home": 5,  "val_away": 7},
    {"home": "D", "away": "C", "val_home": 2,  "val_away": 6},
]


def test_estimar_metrica_bases_y_multiplicadores():
    est = estimar_metrica(PARTIDOS, k=2.0)
    # base local = media de val_home; base visitante = media de val_away
    assert round(est["base_home"], 4) == round((10 + 8 + 5 + 2) / 4, 4)
    assert round(est["base_away"], 4) == round((4 + 5 + 7 + 6) / 4, 4)
    # multiplicadores existen para cada equipo visto
    assert set(est["atk"]) == {"A", "B", "C", "D"}
    assert set(est["def"]) == {"A", "B", "C", "D"}
    # A genera por encima de la media -> atk > 1 ; D por debajo -> atk < 1
    assert est["atk"]["A"] > 1.0
    assert est["atk"]["D"] < 1.0


def test_shrinkage_acerca_a_uno_con_pocos_datos():
    # D tiene 1 solo partido: con k alto, su atk se pega a 1.0
    est_flojo = estimar_metrica(PARTIDOS, k=0.1)
    est_fuerte = estimar_metrica(PARTIDOS, k=50.0)
    assert abs(est_fuerte["atk"]["D"] - 1.0) < abs(est_flojo["atk"]["D"] - 1.0)
