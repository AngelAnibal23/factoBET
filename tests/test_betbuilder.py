import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
import betbuilder


def test_scoreline_matrix_sums_to_one():
    M = betbuilder.scoreline_matrix(1.5, 1.2, -0.05)
    assert M.shape == (11, 11)
    assert abs(M.sum() - 1.0) < 1e-9


def test_scoreline_matrix_rho_adjusts_low_score_cells():
    # La corrección Dixon-Coles tau solo toca las 4 celdas de marcador bajo.
    base = betbuilder.scoreline_matrix(1.0, 1.0, 0.0)
    dc   = betbuilder.scoreline_matrix(1.0, 1.0, -0.1)
    assert abs(dc.sum() - 1.0) < 1e-9
    assert dc[0, 0] != base[0, 0]   # rho redistribuye la celda 0-0
    assert dc[3, 2] > 0


def test_parse_exact_score_ok():
    assert betbuilder.parse_exact_score("1-3") == (1, 3)
    assert betbuilder.parse_exact_score(" 10-0 ") == (10, 0)
    assert betbuilder.parse_exact_score("0-0") == (0, 0)


def test_parse_exact_score_malformed():
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("1:3")
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("abc")


def test_parse_exact_score_out_of_range():
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("11-0")


def test_goal_leg_mask_1x2():
    home = betbuilder.goal_leg_mask("1X2", "home", None)
    assert home[3, 1] and not home[1, 3] and not home[2, 2]


def test_goal_leg_mask_over_under():
    over = betbuilder.goal_leg_mask("over_under", "over", 2.5)
    assert over[2, 1] and not over[1, 1]


def test_goal_leg_mask_exact():
    m = betbuilder.goal_leg_mask("resultado_exacto", "1-3", None)
    assert m[1, 3] and m.sum() == 1


def test_marginal_over_under_in_range():
    M = betbuilder.scoreline_matrix(1.4, 1.1, -0.05)
    marg = betbuilder.marginal_prob(M, ("over_under", "over", 1.5))
    assert 0.0 < marg < 1.0


def test_joint_ceiling_le_each_marginal():
    M = betbuilder.scoreline_matrix(1.6, 1.0, -0.05)
    legs = [("1X2", "home", None), ("over_under", "over", 2.5)]
    ceiling = betbuilder.joint_ceiling(M, legs)
    for leg in legs:
        assert ceiling <= betbuilder.marginal_prob(M, leg) + 1e-12


def test_joint_of_identical_legs_equals_marginal():
    M = betbuilder.scoreline_matrix(1.3, 1.3, -0.05)
    leg = ("over_under", "over", 1.5)
    assert abs(betbuilder.joint_ceiling(M, [leg, leg]) - betbuilder.marginal_prob(M, leg)) < 1e-12


def test_verdict_sin_valor():
    # techo <= 1/cuota -> SIN_VALOR
    v, kelly = betbuilder.verdict(ceiling=0.20, cuota_total=4.0, n_modelables=2, n_exoticas=1)
    assert v == "SIN_VALOR" and kelly is None


def test_verdict_no_concluyente():
    # techo > 1/cuota con exóticas -> NO_CONCLUYENTE
    v, kelly = betbuilder.verdict(ceiling=0.40, cuota_total=4.0, n_modelables=2, n_exoticas=3)
    assert v == "NO_CONCLUYENTE" and kelly is None


def test_verdict_valor_with_kelly():
    # techo > 1/cuota sin exóticas -> VALOR + Kelly fraccionario
    v, kelly = betbuilder.verdict(ceiling=0.40, cuota_total=4.0, n_modelables=2, n_exoticas=0)
    assert v == "VALOR" and kelly is not None and kelly > 0


def test_verdict_no_evaluable():
    v, kelly = betbuilder.verdict(ceiling=None, cuota_total=4.0, n_modelables=0, n_exoticas=3)
    assert v == "NO_EVALUABLE" and kelly is None


def test_confidence_sin_valor_is_alta():
    nivel, _ = betbuilder.bb_confidence("SIN_VALOR", n_modelables=2, n_exoticas=2)
    assert nivel == "ALTA"


def test_confidence_no_concluyente_many_exoticas_is_baja():
    nivel, _ = betbuilder.bb_confidence("NO_CONCLUYENTE", n_modelables=1, n_exoticas=4)
    assert nivel == "BAJA"


# ── Familia player (Task 10) ──────────────────────────────────────────────────
from betbuilder import player_leg_prob, PLAYER_MARKET, analyze_bet_builder
from player_model import PlayerModel
from validator import ValidatedParlay, ValidatedSelection, TeamMatch

PM = PlayerModel.from_params({
    "metricas": ["goal", "assist"],
    "jugadores": {"p2": {"nombre": "Bruno Fernandes", "equipo": "Portugal",
                         "cuota_gol": 0.15, "cuota_asist": 0.30}},
})


class _Sel:   # stub mínimo de ValidatedSelection para player_leg_prob
    def __init__(self, **kw):
        self.mercado = PLAYER_MARKET
        self.player = kw.get("player")
        self.metric = kw.get("metric")
        self.umbral = kw.get("umbral", 1)
        self.faltante = kw.get("faltante", False)


def test_player_leg_prob_resuelve_y_calcula():
    import math
    sel = _Sel(player="B. Fernandes", metric="goal_or_assist")
    p = player_leg_prob(PM, sel, lh=1.6, la=0.5, home="Portugal", away="Uzbekistan")
    assert abs(p - (1 - math.exp(-1.6 * (0.15 + 0.30)))) < 1e-9


def test_player_leg_prob_none_si_no_resuelve():
    sel = _Sel(player="Jugador Inexistente", metric="goal")
    assert player_leg_prob(PM, sel, 1.6, 0.5, "Portugal", "Uzbekistan") is None


def test_player_leg_prob_none_si_faltante():
    sel = _Sel(player="B. Fernandes", metric="sot", faltante=True)
    assert player_leg_prob(PM, sel, 1.6, 0.5, "Portugal", "Uzbekistan") is None


def _tm(name):
    return TeamMatch(raw=name, canonical=name, equipo_id=name[:2].upper(),
                     score=1.0, status="MATCHED")


def test_player_baja_exoticas_y_faltante_se_etiqueta():
    sels = [
        ValidatedSelection(
            equipo_local_raw="Portugal", equipo_visitante_raw="Uzbekistan",
            mercado="player", seleccion="yes", cuota=None, linea=None,
            local_match=_tm("Portugal"), visitante_match=_tm("Uzbekistan"),
            prob_implicita=None, mercado_exotico=False,
            player="Bruno Fernandes", metric="goal_or_assist", umbral=1, faltante=False),
        ValidatedSelection(
            equipo_local_raw="Portugal", equipo_visitante_raw="Uzbekistan",
            mercado="player", seleccion="yes", cuota=None, linea=None,
            local_match=_tm("Portugal"), visitante_match=_tm("Uzbekistan"),
            prob_implicita=None, mercado_exotico=False,
            player="Cristiano Ronaldo", metric="sot", umbral=2, faltante=True),
    ]
    parlay = ValidatedParlay(selecciones=sels, cuota_total=3.5, casa_apuestas="Betano")
    res = analyze_bet_builder(parlay, lh=1.6, la=0.5, rho=-0.1,
                              version_modelo="intl_v0.1", margin=0.06,
                              player_model=PM, neutral=True)
    assert res.n_modelables == 1
    assert res.n_exoticas == 1
    assert any("Ronaldo" in d for d in res.faltantes_desc)


def test_player_leg_prob_sot_usa_counts_lambda():
    import math
    from types import SimpleNamespace
    from player_model import PlayerModel
    from counts_model import CountsModel
    from betbuilder import player_leg_prob

    player_sot = PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40},
    }})
    # counts con sot: base_home=4, sin multiplicadores -> lambda_sot local = 4
    counts = CountsModel.from_params({"sot": {
        "base_home": 4.0, "base_away": 3.0, "factor_neutral": 1.0, "disp": 1.0,
        "atk": {}, "def": {},
    }})
    sel = SimpleNamespace(metric="sot", faltante=False, player="Ronaldo",
                          scope="total", seleccion="yes", linea=0.5, umbral=1)
    # Ronaldo (Portugal) es local -> lambda_sot = 4.0 ; lam_jugador = 4.0*0.40 = 1.6
    p = player_leg_prob(player_sot, sel, lh=1.2, la=0.9,
                        home="Portugal", away="Spain",
                        counts_model=counts, c_home="ID_POR", c_away="ID_SPA",
                        neutral=False)
    assert abs(p - (1 - math.exp(-1.6))) < 1e-9


def test_player_leg_prob_sot_sin_counts_devuelve_none():
    from types import SimpleNamespace
    from player_model import PlayerModel
    from betbuilder import player_leg_prob
    player_sot = PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40},
    }})
    sel = SimpleNamespace(metric="sot", faltante=False, player="Ronaldo",
                          scope="total", seleccion="yes", linea=0.5, umbral=1)
    assert player_leg_prob(player_sot, sel, 1.2, 0.9, "Portugal", "Spain",
                           counts_model=None, c_home="A", c_away="B") is None


def _sel_sot(player="Cristiano Ronaldo"):
    return ValidatedSelection(
        equipo_local_raw="Portugal", equipo_visitante_raw="Spain",
        mercado="player", seleccion="yes", cuota=None, linea=None,
        local_match=_tm("Portugal"), visitante_match=_tm("Spain"),
        prob_implicita=None, mercado_exotico=False,
        player=player, metric="sot", umbral=1, faltante=False)


def _counts_sot():
    from counts_model import CountsModel
    return CountsModel.from_params({"sot": {
        "base_home": 4.0, "base_away": 3.0, "factor_neutral": 1.0, "disp": 1.0,
        "atk": {}, "def": {}}})


def _player_sot():
    return PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40}}})


def test_analyze_bb_sot_resuelve_con_modelo():
    parlay = ValidatedParlay(selecciones=[_sel_sot()], cuota_total=2.0,
                             casa_apuestas="Betano")
    res = analyze_bet_builder(parlay, lh=1.2, la=0.9, rho=-0.05,
                              version_modelo="intl_v0.1", margin=0.0,
                              counts_model=_counts_sot(), neutral=False,
                              player_model=None, player_sot_model=_player_sot())
    assert res.selecciones[0].prob_modelo is not None
    assert res.selecciones[0].faltante is False
    assert res.n_modelables == 1


def test_analyze_bb_sot_faltante_si_no_modelo():
    parlay = ValidatedParlay(selecciones=[_sel_sot()], cuota_total=2.0,
                             casa_apuestas="Betano")
    res = analyze_bet_builder(parlay, lh=1.2, la=0.9, rho=-0.05,
                              version_modelo="intl_v0.1", margin=0.0,
                              counts_model=_counts_sot(), neutral=False,
                              player_model=None, player_sot_model=None)
    assert res.selecciones[0].prob_modelo is None
    assert res.selecciones[0].faltante is True
    assert any("Ronaldo" in d for d in res.faltantes_desc)
