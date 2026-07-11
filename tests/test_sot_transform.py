# tests/test_sot_transform.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sot_transform import parse_fixtures_players

# Forma real (abreviada) de /fixtures/players: "response" es una lista con una
# entrada por equipo; cada equipo trae team{id,name} y players[] con statistics[0].
RESPONSE = [
    {"team": {"id": 10, "name": "Portugal"},
     "players": [
        {"player": {"id": 100, "name": "Cristiano Ronaldo"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 5, "on": 3}}]},
        {"player": {"id": 101, "name": "Bruno Fernandes"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 2, "on": 1}}]},
        {"player": {"id": 102, "name": "Suplente"},
         "statistics": [{"games": {"minutes": 12, "substitute": True},
                         "shots": {"total": 0, "on": None}}]},
     ]},
    {"team": {"id": 20, "name": "Spain"},
     "players": [
        {"player": {"id": 200, "name": "Alvaro Morata"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 4, "on": 2}}]},
     ]},
]


def test_parse_estructura_y_sot():
    filas = parse_fixtures_players(RESPONSE, event_id=999)
    by_pid = {f["player_id"]: f for f in filas}
    assert len(filas) == 4
    # sot leído de shots.on; null -> 0
    assert by_pid["100"]["sot"] == 3
    assert by_pid["102"]["sot"] == 0
    # substitute:false -> fue_titular True ; substitute:true -> False
    assert by_pid["100"]["fue_titular"] is True
    assert by_pid["102"]["fue_titular"] is False
    # nombre de equipo crudo (la resolución a equipo_id se hace en el loader)
    assert by_pid["100"]["equipo_nombre"] == "Portugal"
    assert by_pid["200"]["equipo_nombre"] == "Spain"
    # event_id e ids como str (espacio de IDs de API-Football)
    assert by_pid["100"]["event_id"] == 999
    assert by_pid["100"]["player_nombre"] == "Cristiano Ronaldo"
    assert by_pid["100"]["minutos"] == 90


def test_jugador_duplicado_en_feed_se_deduplica():
    # Quirk real de API-Football: el mismo player_id puede venir dos veces en un
    # fixture (visto en quals CONMEBOL 2026-07-10; rompía el upsert con error 21000).
    # Se queda la entrada con más minutos.
    resp = [{"team": {"id": 10, "name": "Portugal"},
             "players": [
                {"player": {"id": 7, "name": "CR7"},
                 "statistics": [{"games": {"minutes": None, "substitute": True},
                                 "shots": {"total": 0, "on": None}}]},
                {"player": {"id": 7, "name": "CR7"},
                 "statistics": [{"games": {"minutes": 90, "substitute": False},
                                 "shots": {"total": 5, "on": 3}}]},
             ]}]
    filas = parse_fixtures_players(resp, event_id=1)
    assert len(filas) == 1
    assert filas[0]["sot"] == 3
    assert filas[0]["minutos"] == 90
    assert filas[0]["fue_titular"] is True


def test_jugador_sin_statistics_se_omite():
    resp = [{"team": {"id": 10, "name": "Portugal"},
             "players": [{"player": {"id": 1, "name": "X"}, "statistics": []}]}]
    assert parse_fixtures_players(resp, event_id=1) == []


import pytest

from download_sot_jugador import (ApiFootballError, chequear_errores_api,
                                  elegir_pendientes, filas_descubrir)


def test_chequear_errores_api_lanza_con_cuota_agotada():
    # API-Football devuelve HTTP 200 con `errors` poblado cuando falla (cuota
    # diaria, rate-limit). Sin este chequeo, hidratar marcaba 'sin_datos' los
    # fixtures que en realidad no pudo consultar (2026-07-10: 90 falsos
    # sin_datos con la cuota agotada; hubo que revertirlos a mano).
    with pytest.raises(ApiFootballError, match="request limit"):
        chequear_errores_api({"errors": {"requests": "You have reached the "
                                         "request limit for the day"},
                              "response": []})


def test_chequear_errores_api_no_lanza_sin_errores():
    chequear_errores_api({"errors": [], "response": [{"x": 1}]})   # lista vacía OK
    chequear_errores_api({"response": []})                          # sin clave OK


def test_filas_descubrir_incluye_fecha():
    # La fecha del partido viene de /fixtures (descubrir), NO de /fixtures/players:
    # sin ella el gate no puede hacer split temporal (bug 2026-07-10: fecha 100% null).
    fixtures = [
        {"fixture": {"id": 555, "date": "2022-11-20T16:00:00+00:00"}},
        {"fixture": {"id": 556, "date": "2022-11-21T13:00:00+00:00"}},
    ]
    rows = filas_descubrir(fixtures, liga_id=1, season=2022)
    assert rows == [
        {"event_id": 555, "liga_api_id": 1, "temporada": 2022,
         "estado": "pendiente", "fecha": "2022-11-20T16:00:00+00:00"},
        {"event_id": 556, "liga_api_id": 1, "temporada": 2022,
         "estado": "pendiente", "fecha": "2022-11-21T13:00:00+00:00"},
    ]


def test_elegir_pendientes_respeta_presupuesto():
    prog = [{"event_id": i, "estado": "pendiente"} for i in range(10)]
    prog += [{"event_id": 100, "estado": "hecho"}]
    elegidos = elegir_pendientes(prog, presupuesto=3)
    assert elegidos == [0, 1, 2]            # solo pendientes, hasta el presupuesto
    assert elegir_pendientes(prog, presupuesto=0) == []
