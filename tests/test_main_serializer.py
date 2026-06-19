import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import main
from analyzer import ParlayAnalysis


def test_bet_builder_block_present():
    res = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.45, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[], version_modelo="intl_v0.1",
        es_bet_builder=True, veredicto="NO_CONCLUYENTE", prob_techo=0.41,
        prob_impl_combinada=0.2247, n_modelables=2, n_exoticas=4,
        exoticas_desc=["Más 7.5 córners"], bet_builder_kelly=None,
    )
    block = main._bet_builder_block(res)
    assert block["veredicto"] == "NO_CONCLUYENTE"
    assert block["prob_techo"] == 0.41
    assert block["n_exoticas"] == 4


def test_bet_builder_block_none_for_accumulator():
    res = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=0.3, prob_parlay_impl=0.36,
        cuota_total=5.0, casa_apuestas=None, nivel_confianza="ALTA",
        razones_confianza=[], correlaciones=[],
    )
    assert main._bet_builder_block(res) is None
