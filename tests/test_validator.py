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
