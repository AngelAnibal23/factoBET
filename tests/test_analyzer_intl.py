import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from engine_intl_v01 import DixonColesIntl
from validator import ValidatedParlay, ValidatedSelection, TeamMatch
import analyzer
from analyzer import (
    _liga_de_parlay, _analyze_intl, _prob_for_selection_intl,
    _coverage_intl, HOSTS_2026,
)


# ── Helpers para construir ValidatedParlay sin tocar Supabase ──────────────────

def _tm(name, eid):
    return TeamMatch(raw=name, canonical=name, equipo_id=eid,
                     score=1.0, status="MATCHED")


def _sel(local, lid, mercado, seleccion, cuota, vis=None, vid=None, linea=None):
    return ValidatedSelection(
        equipo_local_raw=local,
        equipo_visitante_raw=vis,
        mercado=mercado,
        seleccion=seleccion,
        cuota=cuota,
        linea=linea,
        local_match=_tm(local, lid),
        visitante_match=_tm(vis, vid) if vis else None,
        prob_implicita=round(1 / cuota, 6),
        mercado_exotico=(mercado == "exotic"),
    )


def _parlay(*sels):
    return ValidatedParlay(selecciones=list(sels), cuota_total=None,
                           casa_apuestas=None)


def _intl_model():
    attack = {"France": 0.6, "Brazil": 0.5, "Mexico": 0.1, "Panama": -0.4}
    defense = {"France": -0.5, "Brazil": -0.4, "Mexico": -0.1, "Panama": 0.3}
    return DixonColesIntl.from_params(mu=0.2, gamma=0.35, rho=-0.05,
                                      attack=attack, defense=defense)


# ── Ruteo ──────────────────────────────────────────────────────────────────────

def test_ruteo_internacional():
    p = _parlay(_sel("France", "I1", "1X2", "home", 2.0, "Brazil", "I2"))
    m = {"I1": "internacional", "I2": "internacional"}
    assert _liga_de_parlay(p, m) == "internacional"


def test_ruteo_liga1():
    p = _parlay(_sel("Universitario", "L1", "1X2", "home", 1.6, "Alianza Lima", "L2"))
    m = {"L1": "liga1", "L2": "liga1"}
    assert _liga_de_parlay(p, m) == "liga1"


def test_ruteo_mixto():
    p = _parlay(_sel("France", "I1", "1X2", "home", 2.0, "Alianza Lima", "L2"))
    m = {"I1": "internacional", "L2": "liga1"}
    assert _liga_de_parlay(p, m) == "mixto"


# ── Predicción de mercado internacional ────────────────────────────────────────

def test_1x2_intl_suma_uno():
    model = _intl_model()
    probs = []
    for s in ("home", "draw", "away"):
        sel = _sel("France", "I1", "1X2", s, 2.0, "Brazil", "I2")
        p, lh, la = _prob_for_selection_intl(model, sel, neutral=True)
        probs.append(p)
    assert abs(sum(probs) - 1.0) < 1e-6
    assert all(0.0 < p < 1.0 for p in probs)


def test_over_intl_en_rango():
    model = _intl_model()
    sel = _sel("France", "I1", "over_under", "over", 1.9, "Brazil", "I2", linea=2.5)
    p, lh, la = _prob_for_selection_intl(model, sel, neutral=True)
    assert 0.0 < p < 1.0


def test_exotico_intl_sin_modelo():
    model = _intl_model()
    sel = _sel("France", "I1", "exotic", "France o empate", 1.5)
    p, lh, la = _prob_for_selection_intl(model, sel, neutral=True)
    assert p is None and lh is None and la is None


# ── Regla anfitrión / neutral ──────────────────────────────────────────────────

def test_anfitrion_local_aplica_ventaja():
    model = _intl_model()
    # México es anfitrión 2026 -> de local recibe gamma (neutral=False)
    p = _parlay(_sel("Mexico", "I3", "1X2", "home", 2.5, "Panama", "I4"))
    res = _analyze_intl(p, model)
    lh_esperado = round(model.lambdas("Mexico", "Panama", neutral=False)[0], 4)
    assert res.selecciones[0].lambda_home == lh_esperado


def test_no_anfitrion_es_neutral():
    model = _intl_model()
    # Francia NO es anfitrión -> cancha neutral aunque figure como "local"
    p = _parlay(_sel("France", "I1", "1X2", "home", 2.0, "Brazil", "I2"))
    res = _analyze_intl(p, model)
    lh_neutral = round(model.lambdas("France", "Brazil", neutral=True)[0], 4)
    assert res.selecciones[0].lambda_home == lh_neutral
    assert "United States" in HOSTS_2026 and "Mexico" in HOSTS_2026 and "Canada" in HOSTS_2026


# ── Cobertura intl ─────────────────────────────────────────────────────────────

def test_coverage_intl_ambos_en_params():
    nivel, _ = _coverage_intl(True, True, exotic=False, no_away=False)
    assert nivel == "ALTA"


def test_coverage_intl_falta_un_equipo():
    nivel, _ = _coverage_intl(True, False, exotic=False, no_away=False)
    assert nivel == "BAJA"


# ── Marcador más probable (solo selecciones) ──────────────────────────────────

def test_analyze_intl_pobla_marcador():
    model = _intl_model()
    p = _parlay(_sel("France", "I1", "1X2", "home", 2.0, "Brazil", "I2"))
    res = _analyze_intl(p, model)
    assert len(res.marcadores_partido) == 1
    m = res.marcadores_partido[0]
    assert m["equipo_local"] == "France"
    assert m["equipo_visitante"] == "Brazil"
    assert "-" in m["marcador"]
    assert 0.0 < m["probabilidad"] < 1.0
    assert len(m["detalle"]["top"]) == 5


def test_analyze_intl_sin_cobertura_no_marcador():
    model = _intl_model()
    # "Narnia" no está en los params congelados -> no se puede formar la matriz.
    p = _parlay(_sel("Narnia", "IX", "1X2", "home", 2.0, "Brazil", "I2"))
    res = _analyze_intl(p, model)
    assert res.marcadores_partido == []


def test_analyze_intl_marcador_dedupe_por_partido():
    model = _intl_model()
    # Dos patas del MISMO partido -> un solo marcador.
    p = _parlay(
        _sel("France", "I1", "1X2", "home", 2.0, "Brazil", "I2"),
        _sel("France", "I1", "over_under", "over", 1.9, "Brazil", "I2", linea=2.5),
    )
    res = _analyze_intl(p, model)
    assert len(res.marcadores_partido) == 1


# ── Rechazo de parlay mixto en el dispatch ─────────────────────────────────────

def test_dispatch_mixto_lanza_error(monkeypatch):
    monkeypatch.setattr(analyzer, "_load_team_liga_map",
                        lambda: {"I1": "internacional", "L2": "liga1"})
    p = _parlay(_sel("France", "I1", "1X2", "home", 2.0, "Alianza Lima", "L2"))
    with pytest.raises(ValueError):
        analyzer.analyze(p)
