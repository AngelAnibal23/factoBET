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
