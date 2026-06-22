import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
import betbuilder
import marcador


def test_most_likely_scoreline_is_argmax():
    M = betbuilder.scoreline_matrix(1.6, 0.9, -0.05)
    gl, ga, prob = marcador.most_likely_scoreline(M)
    # Coincide con el argmax bruto de la matriz.
    i, j = np.unravel_index(np.argmax(M), M.shape)
    assert (gl, ga) == (int(i), int(j))
    assert abs(prob - float(M[i, j])) < 1e-12
    assert 0.0 < prob < 1.0


def test_most_likely_scoreline_returns_python_ints():
    M = betbuilder.scoreline_matrix(1.2, 1.2, -0.05)
    gl, ga, prob = marcador.most_likely_scoreline(M)
    assert isinstance(gl, int) and isinstance(ga, int) and isinstance(prob, float)


def test_top_scorelines_sorted_desc_and_sized():
    M = betbuilder.scoreline_matrix(1.5, 1.1, -0.05)
    top = marcador.top_scorelines(M, n=5)
    assert len(top) == 5
    probs = [p for _, _, p in top]
    assert probs == sorted(probs, reverse=True)
    # El primero del top es el marcador más probable.
    gl, ga, prob = marcador.most_likely_scoreline(M)
    assert top[0] == (gl, ga, prob)


def test_outcome_probs_sum_to_one():
    M = betbuilder.scoreline_matrix(1.4, 1.0, -0.05)
    ph, pd, pa = marcador.outcome_probs(M)
    assert abs((ph + pd + pa) - 1.0) < 1e-9
    # Local más fuerte (lh>la) -> gana local con más probabilidad que visitante.
    assert ph > pa


def test_marcador_partido_dict_shape():
    d = marcador.marcador_partido(1.6, 0.9, -0.05, "Argentina", "Austria")
    assert d["equipo_local"] == "Argentina"
    assert d["equipo_visitante"] == "Austria"
    assert d["marcador"] == f"{d['goles_local']}-{d['goles_visitante']}"
    assert 0.0 < d["probabilidad"] < 1.0
    # Detalle opcional para la vista "ver detalle".
    assert len(d["detalle"]["top"]) == 5
    res = d["detalle"]["resultado"]
    # Valores redondeados a 4 decimales: suma ~1 dentro del error de redondeo.
    assert abs(res["local"] + res["empate"] + res["visitante"] - 1.0) < 1e-3
