import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_events_transform import parse_eventos, parse_titulares

SUI = (
    "IK÷Goal¬IF÷Cristiano Ronaldo¬IM÷p1¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Assistance¬IF÷Bruno Fernandes¬IM÷p2¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Yellow Card¬IF÷Pepe¬IM÷p9¬IA÷1¬IB÷70'¬AC÷2nd Half"
)

LI = (
    "LP÷p1¬LI÷Cristiano Ronaldo¬LH÷FW¬IA÷1¬ST÷1~"
    "LP÷p2¬LI÷Bruno Fernandes¬LH÷MF¬IA÷1¬ST÷1~"
    "LP÷p3¬LI÷Suplente¬LH÷FW¬IA÷1¬ST÷0"
)


def test_parse_eventos_extrae_goles_y_asistencias():
    evs = parse_eventos(SUI)
    goles = [e for e in evs if e["tipo"] == "Goal"]
    asis  = [e for e in evs if e["tipo"] == "Assistance"]
    assert len(goles) == 1 and goles[0]["player_id"] == "p1"
    assert goles[0]["nombre"] == "Cristiano Ronaldo"
    assert goles[0]["lado"] == 1
    assert len(asis) == 1 and asis[0]["player_id"] == "p2"
    assert any(e["tipo"] == "Yellow Card" for e in evs)


def test_parse_titulares_marca_solo_starters():
    tit = parse_titulares(LI)
    assert tit["p1"] is True and tit["p2"] is True
    assert tit["p3"] is False


def test_parse_lineup_trae_lado_y_nombre():
    from player_events_transform import parse_lineup
    filas = parse_lineup(LI)
    by = {f["player_id"]: f for f in filas}
    assert by["p1"]["nombre"] == "Cristiano Ronaldo"
    assert by["p1"]["lado"] == 1 and by["p1"]["fue_titular"] is True
    assert by["p3"]["fue_titular"] is False   # suplente
