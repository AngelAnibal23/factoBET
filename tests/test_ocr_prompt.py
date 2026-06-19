import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import ocr


def test_prompt_lists_exact_score_market():
    assert "resultado_exacto" in ocr.SYSTEM_PROMPT


def test_prompt_routes_corners_and_player_props_to_exotic():
    p = ocr.SYSTEM_PROMPT.lower()
    assert "córner" in p or "corner" in p     # mención explícita
    assert "exotic" in p
    assert "primer tiempo" in p               # goles de 1er tiempo -> exótico
