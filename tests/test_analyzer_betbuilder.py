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
