import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from narrator import _prob_to_text, _edge_to_text, _framing_n


def test_prob_to_text_muy_bajo():
    assert "Poco probable" in _prob_to_text(0.20)

def test_prob_to_text_bajo():
    assert "Bajo" in _prob_to_text(0.40)

def test_prob_to_text_ligero():
    assert "Ligeramente favorable" in _prob_to_text(0.55)

def test_prob_to_text_moderado():
    assert "Moderado" in _prob_to_text(0.65)

def test_prob_to_text_alto():
    assert "Alto" in _prob_to_text(0.75)

def test_prob_to_text_muy_alto():
    assert "Muy alto" in _prob_to_text(0.85)

def test_prob_to_text_boundary_35():
    # 0.35 cae en "Bajo"
    assert "Bajo" in _prob_to_text(0.35)

def test_prob_to_text_boundary_50():
    # 0.50 cae en "Ligeramente favorable"
    assert "Ligeramente favorable" in _prob_to_text(0.50)


def test_edge_to_text_valor_real():
    assert "Valor estadístico real" in _edge_to_text(0.06)

def test_edge_to_text_marginal():
    assert "marginal" in _edge_to_text(0.03)

def test_edge_to_text_sin_valor_neutro():
    assert "Sin valor" in _edge_to_text(0.0)

def test_edge_to_text_sin_valor_negativo_leve():
    assert "Sin valor" in _edge_to_text(-0.03)

def test_edge_to_text_ventaja_clara():
    assert "ventaja clara" in _edge_to_text(-0.08)

def test_edge_to_text_none():
    result = _edge_to_text(None)
    assert "Sin valor estadístico" in result


def test_framing_n_20_pct():
    result = _framing_n(0.20)
    assert result == "1 de cada 5 veces"

def test_framing_n_50_pct():
    result = _framing_n(0.50)
    assert result == "1 de cada 2 veces"

def test_framing_n_10_pct():
    result = _framing_n(0.10)
    assert result == "1 de cada 10 veces"

def test_framing_n_none():
    assert _framing_n(None) is None

def test_framing_n_zero():
    assert _framing_n(0.0) is None
