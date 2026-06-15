import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine_intl_v01 import tau, brier_score, cargar_csv


def test_tau_caso_neutro():
    # marcadores que no son 0-0/1-0/0-1/1-1 devuelven 1.0
    assert tau(3, 2, 1.5, 1.2, -0.05) == 1.0

def test_tau_0_0():
    # 1 - lh*la*rho con rho negativo => > 1
    assert tau(0, 0, 1.5, 1.2, -0.05) > 1.0

def test_tau_1_1():
    # 1 - rho con rho negativo => > 1
    assert tau(1, 1, 1.5, 1.2, -0.05) == 1 - (-0.05)


def test_brier_prediccion_perfecta_es_cero():
    preds = [(1.0, 0.0, 0.0, "HOME"), (0.0, 0.0, 1.0, "AWAY")]
    assert brier_score(preds) == 0.0

def test_brier_un_tercio():
    # Predictor uniforme 1/3,1/3,1/3 con normalizacion /2 (misma que Liga 1 v0.2):
    # ((1/3-1)^2 + (1/3)^2 + (1/3)^2) / 2 = (6/9)/2 = 0.3333
    preds = [(1/3, 1/3, 1/3, "HOME")]
    bs = brier_score(preds)
    assert abs(bs - 0.3333) < 0.001


def test_cargar_csv_normaliza(tmp_path):
    csv_content = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2019-06-01,France,Brazil,2,1,Friendly,Paris,France,FALSE\n"
        "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,TRUE\n"
    )
    p = tmp_path / "mini.csv"
    p.write_text(csv_content, encoding="utf-8")
    partidos = cargar_csv(str(p))
    assert len(partidos) == 2
    m0 = partidos[0]
    assert m0["home"] == "France"
    assert m0["gl"] == 2 and m0["gv"] == 1
    assert m0["neutral"] is False
    assert m0["resultado"] == "HOME"
    m1 = partidos[1]
    assert m1["neutral"] is True
    assert m1["resultado"] == "DRAW"
