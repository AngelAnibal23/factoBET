"""Funciones puras del gate de goles por liga (sin red ni Supabase)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


def _m(resultado, fecha):
    return {"resultado": resultado, "fecha": fecha,
            "equipo_local_id": "A", "equipo_visitante_id": "B",
            "goles_local": 1, "goles_visitante": 0}


def test_baseline_tasas_son_las_frecuencias_del_train():
    from gate_goles_liga import baseline_tasas
    train = [_m("HOME", "2022-01-01"), _m("HOME", "2022-01-02"),
             _m("DRAW", "2022-01-03"), _m("AWAY", "2022-01-04")]
    ph, pd, pa = baseline_tasas(train)
    assert (ph, pd, pa) == (0.5, 0.25, 0.25)


def test_baseline_tasas_sin_partidos_es_uniforme():
    from gate_goles_liga import baseline_tasas
    ph, pd, pa = baseline_tasas([])
    assert ph == pytest.approx(1 / 3) and pd == pytest.approx(1 / 3)


def test_split_temporal_respeta_la_fecha():
    from gate_goles_liga import split_temporal
    partidos = [_m("HOME", f"2022-01-{d:02d}") for d in range(1, 11)]
    train, test = split_temporal(list(reversed(partidos)), test_frac=0.30)
    assert len(train) == 7 and len(test) == 3
    assert train[0]["fecha"] == "2022-01-01"
    assert test[-1]["fecha"] == "2022-01-10"


def test_gate_pasa_con_mejora_suficiente():
    from gate_goles_liga import decidir_gate
    mejora, ok = decidir_gate(bs_modelo=0.20, bs_baseline=0.25)
    assert ok and mejora == pytest.approx(0.20)


def test_gate_no_pasa_con_mejora_chica():
    from gate_goles_liga import decidir_gate
    mejora, ok = decidir_gate(bs_modelo=0.2450, bs_baseline=0.2500)
    assert not ok and mejora == pytest.approx(0.02)


def test_gate_no_pasa_si_el_modelo_es_peor():
    from gate_goles_liga import decidir_gate
    _, ok = decidir_gate(bs_modelo=0.30, bs_baseline=0.25)
    assert not ok


def test_brier_perfecto_es_cero():
    from gate_goles_liga import brier
    # Predicción de 1.0 en el resultado real -> Brier 0.
    assert brier([(1.0, 0.0, 0.0, "HOME")]) == pytest.approx(0.0)


def test_brier_uniforme():
    from gate_goles_liga import brier
    # (1/3-1)^2 + (1/3-0)^2 + (1/3-0)^2 = 4/9 + 1/9 + 1/9 = 6/9 = 2/3; /2 = 1/3.
    esperado = ((1 / 3 - 1) ** 2 + (1 / 3) ** 2 + (1 / 3) ** 2) / 2
    assert brier([(1 / 3, 1 / 3, 1 / 3, "HOME")]) == pytest.approx(esperado)
    assert esperado == pytest.approx(1 / 3)
