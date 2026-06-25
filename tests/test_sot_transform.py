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


def test_jugador_sin_statistics_se_omite():
    resp = [{"team": {"id": 10, "name": "Portugal"},
             "players": [{"player": {"id": 1, "name": "X"}, "statistics": []}]}]
    assert parse_fixtures_players(resp, event_id=1) == []
