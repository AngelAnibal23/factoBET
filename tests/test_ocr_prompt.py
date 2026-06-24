import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import ocr


def test_prompt_lists_exact_score_market():
    assert "resultado_exacto" in ocr.SYSTEM_PROMPT


def test_prompt_routes_corners_to_count_and_props_to_exotic():
    p = ocr.SYSTEM_PROMPT.lower()
    assert "córner" in p or "corner" in p     # mención explícita
    assert "count" in p                        # córners -> familia count (no exótico)
    assert "exotic" in p
    assert "goleador" in p                     # props de jugador -> exótico
    assert "segundo tiempo" in p               # eventos de mitad -> exótico


from ocr import SYSTEM_PROMPT  # el string del prompt del sistema (ocr.py:101)


def test_prompt_documenta_mercado_count():
    # el prompt debe instruir el mercado estructurado de conteos
    assert "count" in SYSTEM_PROMPT
    assert "metric" in SYSTEM_PROMPT and "scope" in SYSTEM_PROMPT
    # las 4 métricas nombradas
    for kw in ("corners", "cards", "shots", "sot"):
        assert kw in SYSTEM_PROMPT


# append to tests/test_ocr_prompt.py
from ocr import SYSTEM_PROMPT


def test_prompt_define_mercado_player_y_faltante():
    p = SYSTEM_PROMPT
    assert "player" in p
    assert "goal_or_assist" in p and "assist" in p
    assert "faltante" in p
