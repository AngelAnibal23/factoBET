import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone

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


from engine_intl_v01 import DixonColesIntl


def _modelo_dos_equipos():
    # Modelo sintético: 2 partidos entre A y B, uno en casa y otro neutral,
    # suficiente para que fit() corra. Lo importante es probar lambdas/predict.
    partidos = [
        {"home": "A", "away": "B", "gl": 2, "gv": 1, "fecha": "2024-01-01",
         "neutral": False, "resultado": "HOME"},
        {"home": "B", "away": "A", "gl": 1, "gv": 1, "fecha": "2024-02-01",
         "neutral": True, "resultado": "DRAW"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    return DixonColesIntl().fit(partidos, ref), partidos


def test_predict_suma_uno():
    model, _ = _modelo_dos_equipos()
    ph, pd, pa = model.predict("A", "B", neutral=False)
    assert abs((ph + pd + pa) - 1.0) < 1e-9

def test_ventaja_neutral_reduce_lambda_home():
    model, _ = _modelo_dos_equipos()
    lh_casa, _ = model.lambdas("A", "B", neutral=False)
    lh_neutral, _ = model.lambdas("A", "B", neutral=True)
    # con gamma >= 0, el mismo local mete >= goles en casa que en neutral
    assert lh_casa >= lh_neutral

def test_lambda_away_no_cambia_con_neutral():
    model, _ = _modelo_dos_equipos()
    _, la_casa = model.lambdas("A", "B", neutral=False)
    _, la_neutral = model.lambdas("A", "B", neutral=True)
    # la ventaja de local no afecta al visitante
    assert abs(la_casa - la_neutral) < 1e-12


import numpy as np
from scipy.optimize import check_grad

from engine_intl_v01 import (
    precompute_matches, nll_and_grad, neg_log_likelihood, time_weight,
)


def test_gradiente_analitico_coincide_con_numerico():
    # marcadores que ejercitan los 4 casos de tau (0-0,1-0,0-1,1-1) + neutral on/off
    teams = ["A", "B", "C", "D"]
    scores = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (3, 2), (0, 2), (2, 2)]
    matches = []
    for k, (gl, gv) in enumerate(scores):
        matches.append({
            "home": teams[k % 4], "away": teams[(k + 1) % 4],
            "gl": gl, "gv": gv, "fecha": "2024-01-01", "neutral": (k % 2 == 0),
        })
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    w = np.array([time_weight(m["fecha"], ref) for m in matches])
    w /= w.mean()
    pre = precompute_matches(matches, teams, w)
    n = len(teams)

    np.random.seed(0)
    x = np.random.randn(2 * n + 3) * 0.2
    x[2*n], x[2*n + 1], x[2*n + 2] = 0.2, 0.3, -0.05

    f = lambda p: neg_log_likelihood(p, pre, n)
    g = lambda p: nll_and_grad(p, pre, n)[1]

    # el valor de neg_log_likelihood y el de nll_and_grad deben coincidir
    val_only = neg_log_likelihood(x, pre, n)
    val_pair, _ = nll_and_grad(x, pre, n)
    assert abs(val_only - val_pair) < 1e-12

    # gradiente analitico vs diferencias finitas (error al nivel del ruido de FD)
    assert check_grad(f, g, x, epsilon=1.5e-8) < 1e-4


from engine_intl_v01 import baseline_tasas, predecir_baseline


def test_baseline_tasas_separa_neutral():
    partidos = [
        {"resultado": "HOME", "neutral": False},
        {"resultado": "HOME", "neutral": False},
        {"resultado": "AWAY", "neutral": False},
        {"resultado": "DRAW", "neutral": True},
        {"resultado": "AWAY", "neutral": True},
    ]
    tasas = baseline_tasas(partidos)
    # con local: 2 HOME, 0 DRAW, 1 AWAY -> P(home)=2/3
    assert abs(tasas[False][0] - 2/3) < 1e-9
    # neutral: 0 HOME, 1 DRAW, 1 AWAY -> P(home)=0
    assert abs(tasas[True][0] - 0.0) < 1e-9

def test_predecir_baseline_usa_neutral():
    tasas = {False: (0.5, 0.3, 0.2), True: (0.33, 0.34, 0.33)}
    assert predecir_baseline(tasas, neutral=False) == (0.5, 0.3, 0.2)
    assert predecir_baseline(tasas, neutral=True) == (0.33, 0.34, 0.33)
