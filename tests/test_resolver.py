import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from resolver import _calcular_acierto


def test_1x2_home_gana():
    assert _calcular_acierto("1X2", "home", None, 2, 1) is True

def test_1x2_home_pierde():
    assert _calcular_acierto("1X2", "home", None, 1, 1) is False

def test_1x2_draw_gana():
    assert _calcular_acierto("1X2", "draw", None, 1, 1) is True

def test_1x2_away_gana():
    assert _calcular_acierto("1X2", "away", None, 0, 2) is True

def test_over_gana():
    assert _calcular_acierto("over_under", "over", 2.5, 2, 1) is True

def test_over_pierde():
    assert _calcular_acierto("over_under", "over", 2.5, 1, 1) is False

def test_under_gana():
    assert _calcular_acierto("over_under", "under", 2.5, 1, 1) is True

def test_over_sin_linea_devuelve_none():
    assert _calcular_acierto("over_under", "over", None, 3, 0) is None

def test_btts_yes_gana():
    assert _calcular_acierto("btts", "yes", None, 1, 2) is True

def test_btts_yes_pierde():
    assert _calcular_acierto("btts", "yes", None, 1, 0) is False

def test_btts_no_gana():
    assert _calcular_acierto("btts", "no", None, 3, 0) is True

def test_handicap_home_con_linea_negativa_gana():
    assert _calcular_acierto("handicap", "home", -1.5, 3, 1) is True

def test_handicap_home_con_linea_negativa_pierde():
    assert _calcular_acierto("handicap", "home", -1.5, 2, 1) is False

def test_handicap_away_con_linea_positiva_gana():
    # linea=+1.5 es el handicap aplicado al HOME (home +1.5).
    # away gana el handicap si gv - linea > gl. Con 0-2: 2 - 1.5 = 0.5 > 0 -> True
    assert _calcular_acierto("handicap", "away", 1.5, 0, 2) is True

def test_marcador_none_devuelve_none():
    assert _calcular_acierto("1X2", "home", None, None, 1) is None

def test_exotic_devuelve_none():
    assert _calcular_acierto("exotic", "lo que sea", None, 2, 1) is None


# ── Tests para _mapear_status ─────────────────────────────────────────────────

from resolver import _mapear_status


def test_status_full_time_finalizado():
    assert _mapear_status("STATUS_FULL_TIME") == "FINALIZADO"

def test_status_final_finalizado():
    assert _mapear_status("STATUS_FINAL") == "FINALIZADO"

def test_status_scheduled_pendiente():
    assert _mapear_status("STATUS_SCHEDULED") == "PENDIENTE"

def test_status_first_half_pendiente():
    assert _mapear_status("STATUS_FIRST_HALF") == "PENDIENTE"

def test_status_postponed_especial():
    assert _mapear_status("STATUS_POSTPONED") == "ESPECIAL"

def test_status_canceled_especial():
    assert _mapear_status("STATUS_CANCELED") == "ESPECIAL"

def test_status_final_pen_especial():
    # penales -> revisión manual, no liquidar automático
    assert _mapear_status("STATUS_FINAL_PEN") == "ESPECIAL"

def test_status_desconocido_pendiente():
    assert _mapear_status("STATUS_LO_QUE_SEA") == "PENDIENTE"


# ── Tests para _resultado_parlay ──────────────────────────────────────────────

from resolver import _resultado_parlay


def test_parlay_todas_ganadas():
    assert _resultado_parlay(["GANADA", "GANADA"]) == "GANADO"

def test_parlay_una_perdida():
    assert _resultado_parlay(["GANADA", "PERDIDA"]) == "PERDIDO"

def test_parlay_perdida_tiene_precedencia_sobre_pendiente():
    # un leg perdido mata el parlay aunque haya pendientes
    assert _resultado_parlay(["PERDIDA", "PENDIENTE"]) == "PERDIDO"

def test_parlay_pendiente_sin_perdidas():
    assert _resultado_parlay(["GANADA", "PENDIENTE"]) == "PENDIENTE"

def test_parlay_pendiente_precede_a_especial():
    assert _resultado_parlay(["PENDIENTE", "ESPECIAL"]) == "PENDIENTE"

def test_parlay_especial_sin_perdidas_ni_pendientes():
    assert _resultado_parlay(["GANADA", "ESPECIAL"]) == "ANULADO"

def test_parlay_vacio_es_pendiente():
    # parlay con solo exóticas (todas excluidas) -> no concluir
    assert _resultado_parlay([]) == "PENDIENTE"


# ── Tests para _parse_eventos ────────────────────────────────────────────────

from resolver import _parse_eventos


_ESPN_SAMPLE = {
    "events": [
        {
            "date": "2026-05-31T18:15Z",
            "status": {"type": {"name": "STATUS_FULL_TIME", "completed": True}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "score": "1",
                     "team": {"displayName": "FC Cajamarca", "abbreviation": "CAJ"}},
                    {"homeAway": "away", "score": "2",
                     "team": {"displayName": "Alianza Lima", "abbreviation": "ALI"}},
                ]
            }],
        },
        {
            "date": "2026-06-01T20:00Z",
            "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "score": None,
                     "team": {"displayName": "Melgar", "abbreviation": "MEL"}},
                    {"homeAway": "away", "score": None,
                     "team": {"displayName": "Sporting Cristal", "abbreviation": "CRI"}},
                ]
            }],
        },
    ]
}


def test_parse_eventos_cantidad():
    evs = _parse_eventos(_ESPN_SAMPLE)
    assert len(evs) == 2

def test_parse_eventos_marcador_y_nombres():
    ev = _parse_eventos(_ESPN_SAMPLE)[0]
    assert ev["local"] == "FC Cajamarca"
    assert ev["visitante"] == "Alianza Lima"
    assert ev["goles_local"] == 1
    assert ev["goles_visitante"] == 2
    assert ev["status_name"] == "STATUS_FULL_TIME"

def test_parse_eventos_score_none_cuando_no_jugado():
    ev = _parse_eventos(_ESPN_SAMPLE)[1]
    assert ev["goles_local"] is None
    assert ev["goles_visitante"] is None

def test_parse_eventos_vacio():
    assert _parse_eventos({"events": []}) == []

def test_parse_eventos_sin_events_key():
    assert _parse_eventos({}) == []


# ── Tests para _match_evento ────────────────────────────────────────────────

from resolver import _match_evento


_EVENTOS = [
    {"local": "FC Cajamarca", "visitante": "Alianza Lima",
     "goles_local": 1, "goles_visitante": 2, "status_name": "STATUS_FULL_TIME", "fecha": ""},
    {"local": "Melgar", "visitante": "Sporting Cristal",
     "goles_local": 0, "goles_visitante": 0, "status_name": "STATUS_FULL_TIME", "fecha": ""},
]


def test_match_evento_exacto():
    ev = _match_evento("FC Cajamarca", "Alianza Lima", _EVENTOS)
    assert ev is not None
    assert ev["local"] == "FC Cajamarca"

def test_match_evento_nombre_canonico_diferente():
    # equipos.nombre_oficial "FBC Melgar" vs ESPN "Melgar" -> fuzzy debe matchear
    ev = _match_evento("FBC Melgar", "Sporting Cristal", _EVENTOS)
    assert ev is not None
    assert ev["local"] == "Melgar"

def test_match_evento_sin_coincidencia():
    ev = _match_evento("Universitario", "ADT", _EVENTOS)
    assert ev is None

def test_match_evento_local_ok_visitante_no():
    # solo coincide el local -> no es match (exige ambos)
    ev = _match_evento("FC Cajamarca", "Equipo Inexistente", _EVENTOS)
    assert ev is None

def test_match_evento_no_acepta_orientacion_invertida():
    # parlay con local/visitante invertidos respecto a ESPN -> no match
    # (preserva semántica home/away para el cálculo de acierto)
    ev = _match_evento("Alianza Lima", "FC Cajamarca", _EVENTOS)
    assert ev is None


def test_match_evento_no_confunde_clubes_con_prefijo_compartido():
    # BUG real detectado en e2e: "Alianza Lima" hacía falso match con "Alianza Atlético"
    # (club distinto) por el prefijo compartido. token_set_ratio debe rechazarlo.
    eventos = [
        {"local": "Alianza Atletico", "visitante": "Sport Huancayo",
         "goles_local": 4, "goles_visitante": 1, "status_name": "STATUS_FULL_TIME", "fecha": ""},
    ]
    assert _match_evento("Alianza Lima", "Sport Huancayo", eventos) is None
