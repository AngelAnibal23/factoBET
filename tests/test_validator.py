import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from validator import _best_match, MATCH_AUTO


# Equipos fake (no tocan Supabase): selecciones con y sin alias español.
TEAMS_CON_ALIAS = [
    {"id": "fr", "nombre_oficial": "France", "aliases": ["Francia"]},
    {"id": "de", "nombre_oficial": "Germany", "aliases": ["Alemania"]},
    {"id": "br", "nombre_oficial": "Brazil", "aliases": ["Brasil"]},
]

TEAMS_SIN_ALIAS = [
    {"id": "fr", "nombre_oficial": "France", "aliases": []},
    {"id": "de", "nombre_oficial": "Germany", "aliases": []},
    {"id": "br", "nombre_oficial": "Brazil", "aliases": []},
]


def test_alias_es_matchea_a_canonico_ingles():
    # "Francia" con alias -> MATCHED a France con score alto
    m = _best_match("Francia", TEAMS_CON_ALIAS)
    assert m.status == "MATCHED"
    assert m.canonical == "France"
    assert m.equipo_id == "fr"
    assert m.score >= MATCH_AUTO


def test_alias_es_alemania_a_germany():
    # "Alemania" no se parece NADA a "Germany"; solo el alias lo salva.
    m = _best_match("Alemania", TEAMS_CON_ALIAS)
    assert m.status == "MATCHED"
    assert m.canonical == "Germany"


def test_sin_alias_alemania_no_matchea_germany():
    # Contraste: sin alias, "Alemania" vs "Germany" queda por debajo del auto-match.
    m = _best_match("Alemania", TEAMS_SIN_ALIAS)
    assert m.score < MATCH_AUTO
    assert m.canonical != "Germany" or m.status != "MATCHED"


# ── Bet builder (Fase 1) ──────────────────────────────────────────────────────

import pytest
import validator
from validator import validate, _is_bet_builder

_TEAMS = [
    {"id": "U1", "nombre_oficial": "Uzbekistan", "aliases": ["Uzbekistán"]},
    {"id": "C1", "nombre_oficial": "Colombia", "aliases": []},
]


def test_is_bet_builder_true():
    ocr = {
        "cuota_total": 4.45,
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    assert _is_bet_builder(ocr) is True


def test_is_bet_builder_false_when_per_leg_odds():
    ocr = {"cuota_total": 4.45, "selecciones": [
        {"equipo_local": "Uzbekistan", "mercado": "1X2", "seleccion": "home", "cuota": 1.9}]}
    assert _is_bet_builder(ocr) is False


def test_validate_bet_builder_allows_null_cuota():
    ocr = {
        "cuota_total": 4.45, "casa_apuestas": "Betano",
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    parlay = validate(ocr, _TEAMS)
    assert parlay.es_bet_builder is True
    assert parlay.selecciones[0].cuota is None
    assert parlay.selecciones[0].prob_implicita is None
    assert parlay.selecciones[0].mercado_exotico is False  # resultado_exacto NO es exótico


def test_validate_exact_score_out_of_range_rejected():
    ocr = {"cuota_total": 2.0, "selecciones": [
        {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
         "mercado": "resultado_exacto", "seleccion": "11-0", "cuota": None, "linea": None}]}
    with pytest.raises(validator.RangeError):
        validate(ocr, _TEAMS)


def test_bet_builder_backfill_empty_team_from_consensus():
    # El OCR dejó vacío el equipo en la 2ª pata; al ser bet builder (un solo
    # partido) se rellena con el consenso de las demás y NO debe fallar.
    ocr = {
        "cuota_total": 4.45, "casa_apuestas": "Betano",
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"equipo_local": "", "equipo_visitante": "",
             "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    parlay = validate(ocr, _TEAMS)
    assert parlay.es_bet_builder is True
    assert parlay.selecciones[1].equipo_local_raw == "Uzbekistan"
    assert parlay.selecciones[1].equipo_visitante_raw == "Colombia"
    assert parlay.selecciones[1].local_match.canonical == "Uzbekistan"


def test_bet_builder_backfill_handles_missing_team_key():
    # Caso más duro: el OCR OMITE la clave equipo_local en una pata.
    ocr = {
        "cuota_total": 4.45, "casa_apuestas": "Betano",
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    parlay = validate(ocr, _TEAMS)
    assert parlay.selecciones[1].equipo_local_raw == "Uzbekistan"


# ── Familia "player" (Fase 2 — modelo por jugador) ───────────────────────────

_TEAMS_PLAYER = [
    {"id": "P1", "nombre_oficial": "Portugal", "aliases": []},
    {"id": "U1", "nombre_oficial": "Uzbekistan", "aliases": ["Uzbekistán"]},
]


def test_valida_pata_player():
    ocr = {
        "selecciones": [
            {"equipo_local": "Portugal", "equipo_visitante": "Uzbekistan",
             "mercado": "player", "seleccion": "yes", "cuota": None, "linea": None,
             "player": "Bruno Fernandes", "metric": "goal_or_assist", "umbral": 1},
            {"equipo_local": "Portugal", "equipo_visitante": "Uzbekistan",
             "mercado": "player", "seleccion": "yes", "cuota": None, "linea": None,
             "player": "Cristiano Ronaldo", "metric": "sot", "umbral": 2, "faltante": True},
        ],
        "cuota_total": 3.50, "casa_apuestas": "Betano",
    }
    parlay = validate(ocr, teams=_TEAMS_PLAYER)
    s0, s1 = parlay.selecciones
    assert s0.mercado == "player" and s0.player == "Bruno Fernandes"
    assert s0.metric == "goal_or_assist" and s0.umbral == 1 and s0.faltante is False
    assert s1.faltante is True and s1.metric == "sot"


def test_umbral_no_numerico_lanza_rangeerror():
    from validator import RangeError
    ocr = {
        "selecciones": [
            {"equipo_local": "Portugal", "equipo_visitante": "Uzbekistan",
             "mercado": "player", "seleccion": "yes", "cuota": None, "linea": None,
             "player": "Bruno Fernandes", "metric": "goal", "umbral": "dos"},
        ],
        "cuota_total": 2.0, "casa_apuestas": "Betano",
    }
    with pytest.raises(RangeError):
        validate(ocr, teams=_TEAMS_PLAYER)


_TEAMS_DC = [
    {"id": "nl", "nombre_oficial": "Netherlands", "aliases": []},
    {"id": "ma", "nombre_oficial": "Morocco", "aliases": []},
]


def _ocr_dc(seleccion, cuota):
    return {
        "selecciones": [
            {"equipo_local": "Netherlands", "equipo_visitante": "Morocco",
             "mercado": "double_chance", "seleccion": seleccion,
             "cuota": cuota, "linea": None},
        ],
        "cuota_total": None, "casa_apuestas": "Betano",
    }


def test_double_chance_valida_pasa():
    parlay = validate(_ocr_dc("draw_away", 1.35), teams=_TEAMS_DC)
    s = parlay.selecciones[0]
    assert s.mercado == "double_chance" and s.seleccion == "draw_away"


def test_double_chance_seleccion_invalida_rechazada():
    from validator import RangeError
    with pytest.raises(RangeError):
        validate(_ocr_dc("empate_o_marruecos", 1.35), teams=_TEAMS_DC)


def test_double_chance_cuota_fuera_de_rango():
    from validator import RangeError
    with pytest.raises(RangeError):
        validate(_ocr_dc("home_draw", 12.0), teams=_TEAMS_DC)
