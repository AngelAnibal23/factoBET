import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from resolver import _calcular_acierto


def test_1x2_home_gana():
    assert _calcular_acierto("1X2", "home", None, 2, 1) is True

def test_1x2_home_pierde():
    assert _calcular_acierto("1X2", "home", None, 1, 1) is False

def test_1x2_draw_gana():
    assert _calcular_acierto("1X2", "draw", None, 1, 1) is True

def test_1x2_away_gana():
    assert _calcular_acierto("1X2", "away", None, 0, 2) is True

def test_over_gana():
    assert _calcular_acierto("over_under", "over", 2.5, 2, 1) is True

def test_over_pierde():
    assert _calcular_acierto("over_under", "over", 2.5, 1, 1) is False

def test_under_gana():
    assert _calcular_acierto("over_under", "under", 2.5, 1, 1) is True

def test_over_sin_linea_devuelve_none():
    assert _calcular_acierto("over_under", "over", None, 3, 0) is None

def test_btts_yes_gana():
    assert _calcular_acierto("btts", "yes", None, 1, 2) is True

def test_btts_yes_pierde():
    assert _calcular_acierto("btts", "yes", None, 1, 0) is False

def test_btts_no_gana():
    assert _calcular_acierto("btts", "no", None, 3, 0) is True

def test_handicap_home_con_linea_negativa_gana():
    assert _calcular_acierto("handicap", "home", -1.5, 3, 1) is True

def test_handicap_home_con_linea_negativa_pierde():
    assert _calcular_acierto("handicap", "home", -1.5, 2, 1) is False

def test_handicap_away_con_linea_positiva_gana():
    # linea=+1.5 es el handicap aplicado al HOME (home +1.5).
    # away gana el handicap si gv - linea > gl. Con 0-2: 2 - 1.5 = 0.5 > 0 -> True
    assert _calcular_acierto("handicap", "away", 1.5, 0, 2) is True

def test_marcador_none_devuelve_none():
    assert _calcular_acierto("1X2", "home", None, None, 1) is None

def test_exotic_devuelve_none():
    assert _calcular_acierto("exotic", "lo que sea", None, 2, 1) is None
