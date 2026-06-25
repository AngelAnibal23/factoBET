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
