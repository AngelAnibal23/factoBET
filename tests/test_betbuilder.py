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
