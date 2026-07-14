import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

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


import math


def test_from_params_predict_suma_uno():
    attack = {"A": 0.5, "B": -0.3}
    defense = {"A": -0.2, "B": 0.1}
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack=attack, defense=defense)
    ph, pd, pa = model.predict("A", "B", neutral=False)
    assert abs((ph + pd + pa) - 1.0) < 1e-9
    assert model.converged is True


def test_from_params_lambdas_explicitas():
    # con valores conocidos, lambdas debe coincidir con la formula a mano
    attack = {"A": 0.5, "B": -0.3}
    defense = {"A": -0.2, "B": 0.1}
    mu, gamma = 0.2, 0.3
    model = DixonColesIntl.from_params(mu=mu, gamma=gamma, rho=-0.05,
                                       attack=attack, defense=defense)
    lh, la = model.lambdas("A", "B", neutral=False)
    # lh = exp(mu + alpha_A + beta_B + gamma); la = exp(mu + alpha_B + beta_A)
    assert abs(lh - math.exp(mu + 0.5 + 0.1 + gamma)) < 1e-9
    assert abs(la - math.exp(mu + (-0.3) + (-0.2))) < 1e-9


def test_from_params_neutral_quita_gamma():
    attack = {"A": 0.5, "B": -0.3}
    defense = {"A": -0.2, "B": 0.1}
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack=attack, defense=defense)
    lh_casa, _ = model.lambdas("A", "B", neutral=False)
    lh_neutral, _ = model.lambdas("A", "B", neutral=True)
    assert lh_casa > lh_neutral
    assert abs(lh_neutral - math.exp(0.2 + 0.5 + 0.1)) < 1e-9


def test_from_params_equipo_desconocido_cae_a_mu():
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.5}, defense={"A": -0.2})
    # "Z" no existe -> fallback a exp(mu) (+gamma en local)
    lh, la = model.lambdas("Z", "Y", neutral=True)
    assert abs(lh - math.exp(0.2)) < 1e-9
    assert abs(la - math.exp(0.2)) < 1e-9


def test_from_params_equipo_fuera_del_fit_usa_elo():
    model = DixonColesIntl.from_params(
        mu=0.2, gamma=0.3, rho=-0.05,
        attack={"A": 0.5}, defense={"A": -0.2},
        elo_z={"A": 1.0, "Z": 1.5, "Y": -1.5}, prior_scale=0.4,
    )
    # Z e Y no están en el fit pero SÍ tienen ELO: alpha=c*z, beta=-c*z
    lh, la = model.lambdas("Z", "Y", neutral=True)
    assert abs(lh - math.exp(0.2 + 0.4 * 1.5 + (-0.4 * -1.5))) < 1e-9
    assert abs(la - math.exp(0.2 + 0.4 * -1.5 + (-0.4 * 1.5))) < 1e-9
    assert lh > la   # el de mejor ELO mete más


def test_from_params_sin_elo_conserva_fallback_promedio():
    # Sin tabla ELO, el desconocido cae a exp(mu) como siempre (cero regresión).
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.5}, defense={"A": -0.2})
    lh, la = model.lambdas("Z", "Y", neutral=True)
    assert abs(lh - math.exp(0.2)) < 1e-9
    assert abs(la - math.exp(0.2)) < 1e-9


def test_from_params_equipo_en_fit_ignora_elo():
    # Si el equipo está en el fit, manda su alpha ajustado, no el ELO.
    model = DixonColesIntl.from_params(
        mu=0.2, gamma=0.0, rho=-0.05,
        attack={"A": 0.5, "B": -0.3}, defense={"A": -0.2, "B": 0.1},
        elo_z={"A": -5.0, "B": 5.0}, prior_scale=0.4,   # ELO absurdo a propósito
    )
    lh, la = model.lambdas("A", "B", neutral=True)
    assert abs(lh - math.exp(0.2 + 0.5 + 0.1)) < 1e-9


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


# ── ELO prior (Fase 3) ────────────────────────────────────────────────────────

from engine_intl_v01 import escala_c_desde_v01


def test_gradiente_analitico_con_prior_elo():
    # Mismo setup que test_gradiente_analitico_coincide_con_numerico pero con
    # anclas alpha0/beta0 no-cero y l2 fuerte: el gradiente del prior también
    # tiene que coincidir con diferencias finitas.
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
    a0 = np.array([0.3, -0.1, 0.2, 0.0])
    b0 = np.array([-0.3, 0.1, -0.2, 0.0])
    pre = precompute_matches(matches, teams, w, a0=a0, b0=b0)
    n = len(teams)

    np.random.seed(0)
    x = np.random.randn(2 * n + 3) * 0.2
    x[2*n], x[2*n + 1], x[2*n + 2] = 0.2, 0.3, -0.05

    f = lambda p: neg_log_likelihood(p, pre, n, 2.0)   # l2_prior fuerte
    g = lambda p: nll_and_grad(p, pre, n, 2.0)[1]
    assert check_grad(f, g, x, epsilon=1.5e-8) < 1e-4


def test_precompute_sin_anclas_es_cero():
    # Backward compat: sin a0/b0, las anclas son 0 (comportamiento actual).
    matches = [{"home": "A", "away": "B", "gl": 1, "gv": 0,
                "fecha": "2024-01-01", "neutral": False}]
    pre = precompute_matches(matches, ["A", "B"], np.array([1.0]))
    assert np.allclose(pre["a0"], 0.0) and np.allclose(pre["b0"], 0.0)


def test_fit_con_prior_fuerte_ancla_equipos_con_pocos_datos():
    # 2 partidos y un prior fortísimo: los alphas quedan pegados al ancla c*z.
    partidos = [
        {"home": "A", "away": "B", "gl": 1, "gv": 1, "fecha": "2024-01-01",
         "neutral": True, "resultado": "DRAW"},
        {"home": "B", "away": "A", "gl": 1, "gv": 1, "fecha": "2024-02-01",
         "neutral": True, "resultado": "DRAW"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    elo_z = {"A": 2.0, "B": -2.0}
    model = DixonColesIntl().fit(partidos, ref, elo_z=elo_z,
                                 prior_scale=0.5, l2_prior=50.0)
    ia, ib = model.idx["A"], model.idx["B"]
    assert abs(model.alphas[ia] - 1.0) < 0.1    # ancla = 0.5*2.0
    assert abs(model.alphas[ib] + 1.0) < 0.1
    assert abs(model.betas[ia] + 1.0) < 0.1     # beta0 = -c*z
    assert model.prior_scale == 0.5
    assert model.elo_z == elo_z


def test_fit_sin_elo_no_cambia_interfaz():
    # El camino por defecto sigue funcionando y no guarda prior.
    partidos = [
        {"home": "A", "away": "B", "gl": 2, "gv": 1, "fecha": "2024-01-01",
         "neutral": False, "resultado": "HOME"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    model = DixonColesIntl().fit(partidos, ref)
    assert model.elo_z is None
    assert model.prior_scale == 0.0


def test_escala_c_desde_v01_recupera_pendiente():
    # Si los alphas del modelo son exactamente 0.3*z en los equipos elegibles,
    # la regresión devuelve c=0.3.
    z = {"A": 1.0, "B": -1.0, "C": 2.0, "D": 0.5}
    attack = {t: 0.3 * z[t] for t in z}
    defense = {t: -0.3 * z[t] for t in z}
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack=attack, defense=defense)
    conteos = {"A": 50, "B": 40, "C": 35, "D": 5}   # D no elegible (<30)
    c = escala_c_desde_v01(model, z, conteos, min_partidos=30)
    assert abs(c - 0.3) < 1e-9


def test_escala_c_desde_v01_falla_ruidoso_sin_elegibles():
    z = {"A": 1.0, "B": -1.0}
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.3, "B": -0.3},
                                       defense={"A": -0.3, "B": 0.3})
    with pytest.raises(ValueError):
        escala_c_desde_v01(model, z, {"A": 5, "B": 5}, min_partidos=30)
    with pytest.raises(ValueError):   # varianza z = 0
        escala_c_desde_v01(model, {"A": 1.0, "B": 1.0}, {"A": 50, "B": 50}, min_partidos=30)
