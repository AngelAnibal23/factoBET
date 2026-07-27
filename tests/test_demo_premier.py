"""El demo de Premier corre el motor real sin OCR y sin red de ausencias."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from dotenv import load_dotenv

load_dotenv()


def test_demo_premier_arma_el_parlay_de_la_premier():
    from main import _ocr_demo
    ocr = _ocr_demo("premier")
    equipos = {s["equipo_local"] for s in ocr["selecciones"]}
    assert equipos == {"Man City"}


def test_demo_sin_case_sigue_siendo_el_parlay_internacional():
    """Regresión: `?demo` sin case y `?case=ausencias` no cambian."""
    from main import _ocr_demo
    for case in ("", "ausencias"):
        ocr = _ocr_demo(case)
        assert {s["equipo_local"] for s in ocr["selecciones"]} == {"Argentina"}


def test_demo_premier_no_inyecta_ausentes():
    from main import _payload_ausencias_demo
    assert _payload_ausencias_demo("premier") == {"sin_dato": True}
    assert "equipos" in _payload_ausencias_demo("ausencias")


@pytest.mark.skipif(not os.environ.get("SUPABASE_URL"),
                    reason="necesita Supabase (carga .env)")
def test_demo_premier_es_analizable():
    """El slip del demo tiene que atravesar validator+analyzer de verdad."""
    from main import _ocr_demo, _get_teams
    from validator import validate
    from analyzer import analyze
    parlay = validate(_ocr_demo("premier"), _get_teams())
    result = analyze(parlay)
    leg_1x2 = next(s for s in result.selecciones if s.mercado == "1X2")
    print("local:", leg_1x2.equipo_local, "visitante:", leg_1x2.equipo_visitante,
          "prob_modelo:", leg_1x2.prob_modelo)
    assert leg_1x2.equipo_local == "Manchester City"
    assert leg_1x2.prob_modelo is not None
