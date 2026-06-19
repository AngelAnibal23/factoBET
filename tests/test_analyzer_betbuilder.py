import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analyzer import ParlayAnalysis, SelectionAnalysis


def test_parlay_analysis_has_bet_builder_fields():
    pa = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.0, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[],
    )
    assert pa.es_bet_builder is False
    assert pa.veredicto is None
    assert pa.prob_techo is None
    assert pa.n_modelables == 0
    assert pa.exoticas_desc == []


def test_selection_cuota_can_be_none():
    sa = SelectionAnalysis(
        equipo_local="A", equipo_visitante="B", equipo_local_id="1",
        equipo_visitante_id="2", mercado="over_under", seleccion="over",
        cuota=None, linea=1.5, prob_implicita=None, prob_implicita_adj=None,
        prob_modelo=0.7, lambda_home=1.5, lambda_away=1.2, edge=None,
        kelly_fraccion=None, nivel_cobertura="ALTA", mercado_exotico=False,
        n_partidos_local=0, n_partidos_visitante=0,
    )
    assert sa.cuota is None and sa.prob_implicita is None


from validator import ValidatedParlay, ValidatedSelection, TeamMatch
from engine_intl_v01 import DixonColesIntl
import analyzer
import betbuilder


def _tm(name, eid):
    return TeamMatch(raw=name, canonical=name, equipo_id=eid, score=1.0, status="MATCHED")


def _bb_sel(local, lid, vis, vid, mercado, seleccion, linea=None):
    return ValidatedSelection(
        equipo_local_raw=local, equipo_visitante_raw=vis, mercado=mercado,
        seleccion=seleccion, cuota=None, linea=linea,
        local_match=_tm(local, lid), visitante_match=_tm(vis, vid),
        prob_implicita=None, mercado_exotico=(mercado == "exotic"),
    )


def _intl_model():
    attack = {"Uzbekistan": -0.2, "Colombia": 0.5}
    defense = {"Uzbekistan": 0.2, "Colombia": -0.4}
    return DixonColesIntl.from_params(mu=0.2, gamma=0.35, rho=-0.05, attack=attack, defense=defense)


def test_analyze_bet_builder_no_concluyente():
    parlay = ValidatedParlay(
        selecciones=[
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "resultado_exacto", "1-3"),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "exotic", "Más 7.5 córners"),
        ],
        cuota_total=4.45, casa_apuestas="Betano", es_bet_builder=True,
    )
    m = _intl_model()
    lh, la = m.lambdas("Uzbekistan", "Colombia", neutral=True)
    res = betbuilder.analyze_bet_builder(parlay, lh, la, m.rho, "intl_v0.1", 0.06)
    assert res.es_bet_builder is True
    assert res.veredicto in {"SIN_VALOR", "NO_CONCLUYENTE", "VALOR"}
    assert res.n_modelables == 2 and res.n_exoticas == 1
    assert res.prob_techo is not None
    assert res.exoticas_desc == ["Más 7.5 córners"]


def test_analyze_bet_builder_sin_cuota_raises():
    parlay = ValidatedParlay(
        selecciones=[_bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5)],
        cuota_total=None, casa_apuestas="Betano", es_bet_builder=True,
    )
    import pytest
    with pytest.raises(betbuilder.BetBuilderSinCuotaError):
        analyzer._analyze_bet_builder_route(parlay, "internacional", 0.06)
