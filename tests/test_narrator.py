import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import math
from narrator import _prob_to_text, _edge_to_text, _framing_n, _weakest_selection, _build_prompt, generate_narrative
from analyzer import ParlayAnalysis, SelectionAnalysis, Correlacion


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


def _make_selection(
    prob_modelo=0.55,
    edge=0.03,
    kelly_fraccion=None,
    mercado="1X2",
    seleccion="home",
    cuota=1.80,
    nivel_cobertura="ALTA",
    mercado_exotico=False,
    equipo_local="Alianza Lima",
    equipo_visitante="Sport Huancayo",
    equipo_local_id="alianza",
    equipo_visitante_id="sport_huancayo",
    linea=None,
    lambda_home=1.5,
    lambda_away=1.1,
    prob_implicita=0.55,
    prob_implicita_adj=0.51,
    n_partidos_local=20,
    n_partidos_visitante=18,
    alertas=None,
):
    return SelectionAnalysis(
        equipo_local=equipo_local,
        equipo_visitante=equipo_visitante,
        equipo_local_id=equipo_local_id,
        equipo_visitante_id=equipo_visitante_id,
        mercado=mercado,
        seleccion=seleccion,
        cuota=cuota,
        linea=linea,
        prob_implicita=prob_implicita,
        prob_implicita_adj=prob_implicita_adj,
        prob_modelo=prob_modelo,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        edge=edge,
        kelly_fraccion=kelly_fraccion,
        nivel_cobertura=nivel_cobertura,
        mercado_exotico=mercado_exotico,
        n_partidos_local=n_partidos_local,
        n_partidos_visitante=n_partidos_visitante,
        alertas=alertas or [],
    )


def _make_analysis(sels=None, correlaciones=None, nivel_confianza="ALTA"):
    sels = sels or [_make_selection()]
    modeladas = [s for s in sels if s.prob_modelo is not None]
    prob_parlay = None
    if modeladas:
        prob_parlay = round(math.prod(s.prob_modelo for s in modeladas), 6)
    return ParlayAnalysis(
        selecciones=sels,
        prob_parlay_modelo=prob_parlay,
        prob_parlay_impl=0.45,
        cuota_total=2.20,
        casa_apuestas="Betano",
        nivel_confianza=nivel_confianza,
        razones_confianza=["Todos los equipos con datos suficientes."],
        correlaciones=correlaciones or [],
        version_modelo="v0.2",
        margen_aplicado=0.06,
    )


# ── _weakest_selection ────────────────────────────────────────────────────────

def test_weakest_selection_picks_lowest_prob():
    strong = _make_selection(prob_modelo=0.75, edge=0.05, equipo_local="Universitario")
    weak   = _make_selection(prob_modelo=0.35, edge=-0.03, equipo_local="Alianza Lima")
    result = _weakest_selection([strong, weak])
    assert result.equipo_local == "Alianza Lima"

def test_weakest_selection_all_exotic():
    s = _make_selection(prob_modelo=None, edge=None, mercado_exotico=True)
    assert _weakest_selection([s]) is None

def test_weakest_selection_single():
    s = _make_selection(prob_modelo=0.55)
    assert _weakest_selection([s]) is s


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_contains_confidence():
    analysis = _make_analysis(nivel_confianza="MEDIA")
    prompt = _build_prompt(analysis)
    assert "MEDIA" in prompt

def test_build_prompt_contains_framing():
    sels = [_make_selection(prob_modelo=0.50)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "1 de cada" in prompt

def test_build_prompt_contains_disclaimer_instruction():
    analysis = _make_analysis()
    prompt = _build_prompt(analysis)
    assert "estadístico, no predictivo" in prompt

def test_build_prompt_contains_selection_name():
    sels = [_make_selection(equipo_local="Sporting Cristal")]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "Sporting Cristal" in prompt

def test_build_prompt_shows_correlacion():
    sels = [
        _make_selection(equipo_local="Alianza Lima", seleccion="home"),
        _make_selection(equipo_local="Alianza Lima", seleccion="over", mercado="over_under", linea=2.5),
    ]
    corr = Correlacion(sel_idx_1=0, sel_idx_2=1, tipo="POSITIVA_ALTA", nota="Las victorias locales amplias elevan los goles totales.")
    analysis = _make_analysis(sels=sels, correlaciones=[corr])
    prompt = _build_prompt(analysis)
    assert "CORRELACIONES" in prompt
    assert "POSITIVA_ALTA" in prompt

def test_build_prompt_no_kelly_when_no_edge():
    sels = [_make_selection(kelly_fraccion=None)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "KELLY" not in prompt

def test_build_prompt_shows_kelly_when_present():
    sels = [_make_selection(kelly_fraccion=0.024)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "KELLY" in prompt
    assert "2.4%" in prompt


# ── generate_narrative sin API key ────────────────────────────────────────────

def test_generate_narrative_no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    analysis = _make_analysis()
    result = generate_narrative(analysis)
    assert result is None
