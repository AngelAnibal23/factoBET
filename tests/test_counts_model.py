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


from counts_model import CountsModel

PARAMS = {
    "corners": {
        "base_home": 6.0, "base_away": 4.0, "factor_neutral": 1.0, "disp": 1.0,
        "atk": {"A": 1.5, "B": 1.0}, "def": {"A": 1.0, "B": 1.2},
    },
    # métrica sobre-dispersa para probar el camino NegBin
    "shots": {
        "base_home": 13.0, "base_away": 11.0, "factor_neutral": 1.0, "disp": 1.6,
        "atk": {}, "def": {},
    },
}


def test_lambdas_local_visitante():
    m = CountsModel.from_params(PARAMS)
    lh, la = m.lambdas("corners", "A", "B", neutral=False)
    # lh = base_home * atk[A] * def[B] = 6 * 1.5 * 1.2 = 10.8
    assert round(lh, 4) == 10.8
    # la = base_away * atk[B] * def[A] = 4 * 1.0 * 1.0 = 4.0
    assert round(la, 4) == 4.0


def test_lambdas_neutral_usa_base_promedio():
    m = CountsModel.from_params(PARAMS)
    lh_n, la_n = m.lambdas("corners", "A", "B", neutral=True)
    # en neutral, ambas usan la base neutra (promedio de home/away = 5.0)
    assert round(lh_n, 4) == round(5.0 * 1.5 * 1.2, 4)   # 9.0
    assert round(la_n, 4) == round(5.0 * 1.0 * 1.0, 4)   # 5.0


def test_prob_over_under_poisson_cuando_disp_uno():
    # corners tiene disp=1.0 -> camino Poisson exacto
    m = CountsModel.from_params(PARAMS)
    from scipy.stats import poisson
    # equipo local over 9.5: P(X>9.5) con X~Poisson(10.8)
    p_home_over = m.prob_over_under("corners", "home", "over", 9.5, "A", "B", False)
    assert abs(p_home_over - (1 - poisson.cdf(9, 10.8))) < 1e-9
    # total over 13.5: X~Poisson(10.8+4.0=14.8)
    p_total_over = m.prob_over_under("corners", "total", "over", 13.5, "A", "B", False)
    assert abs(p_total_over - (1 - poisson.cdf(13, 14.8))) < 1e-9
    # under es complemento
    p_total_under = m.prob_over_under("corners", "total", "under", 13.5, "A", "B", False)
    assert abs(p_total_under - poisson.cdf(13, 14.8)) < 1e-9


def test_prob_over_under_negbin_cuando_sobredisperso():
    # shots tiene disp=1.6 -> camino NegBin con r=lam/(d-1), p=1/d
    m = CountsModel.from_params(PARAMS)
    from scipy.stats import nbinom
    lam = 13.0 + 11.0   # total, atk/def vacíos -> mult 1.0
    d = 1.6
    r, p = lam / (d - 1.0), 1.0 / d
    p_over = m.prob_over_under("shots", "total", "over", 22.5, "A", "B", False)
    assert abs(p_over - (1 - nbinom.cdf(22, r, p))) < 1e-9
    # la media de la NegBin recupera lam (sanity): media = r*(1-p)/p
    assert abs(r * (1 - p) / p - lam) < 1e-9


def test_equipo_desconocido_cae_a_multiplicador_neutro():
    m = CountsModel.from_params(PARAMS)
    lh, la = m.lambdas("corners", "DESCONOCIDO", "B", neutral=False)
    # atk/def de un equipo no visto = 1.0
    assert round(lh, 4) == round(6.0 * 1.0 * 1.2, 4)   # 7.2


def test_tiene_metrica():
    m = CountsModel.from_params(PARAMS)
    assert m.tiene("corners") is True
    assert m.tiene("cards") is False
