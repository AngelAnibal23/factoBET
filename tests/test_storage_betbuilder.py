import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import MagicMock
import storage
from analyzer import ParlayAnalysis
from validator import ValidatedParlay


def test_save_includes_bet_builder_columns(monkeypatch):
    captured = {}
    fake = MagicMock()

    def insert(row):
        if "veredicto" in (row if isinstance(row, dict) else {}):
            captured.update(row)
        m = MagicMock()
        m.execute.return_value.data = [{"id": "uuid-1"}]
        return m

    fake.table.return_value.insert.side_effect = insert
    monkeypatch.setattr(storage, "_client", lambda: fake)

    result = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.45, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[], es_bet_builder=True,
        veredicto="SIN_VALOR", prob_techo=0.18,
    )
    parlay = ValidatedParlay(selecciones=[], cuota_total=4.45, casa_apuestas="Betano")
    storage.save_analysis(result, parlay, "hash123")
    assert captured["es_bet_builder"] is True
    assert captured["veredicto"] == "SIN_VALOR"
    assert captured["prob_techo"] == 0.18
