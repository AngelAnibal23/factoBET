import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_events_transform import parse_eventos, parse_titulares, parse_lineup

# df_sui_1 (incidencias) — esquema real: IK=tipo, IF=nombre, IM=player_id, IA=lado.
SUI = (
    "IK÷Goal¬IF÷Cristiano Ronaldo¬IM÷p1¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Assistance¬IF÷Bruno Fernandes¬IM÷p2¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Yellow Card¬IF÷Pepe¬IM÷p9¬IA÷1¬IB÷70'¬AC÷2nd Half"
)

# df_li_1 (alineaciones) — esquema REAL de Flashscore:
#   secciones por header LB (Starting Lineups / Substitutes / Coaches),
#   LP=player_id, LI=nombre, LQ=equipo (nombre), LK=1 titular / LK=2 suplente.
#   Un registro vacío separa a los dos equipos dentro de cada sección.
#   Los técnicos (sección Coaches) traen LP y LK pero NO son jugadores -> excluir.
LI = (
    "LB÷Starting Lineups~"
    "LP÷p1¬LI÷Cristiano Ronaldo¬LQ÷Portugal¬LK÷1¬LL÷9~"
    "LP÷p2¬LI÷Bruno Fernandes¬LQ÷Portugal¬LK÷1¬LL÷8~"
    "~"
    "LP÷p3¬LI÷Rival Striker¬LQ÷Spain¬LK÷1¬LL÷9~"
    "LB÷Substitutes~"
    "LP÷p4¬LI÷Suplente¬LQ÷Portugal¬LK÷2~"
    "LB÷Coaches~"
    "LP÷c1¬LI÷Roberto Martinez¬LK÷1"
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
    assert tit["p1"] is True and tit["p2"] is True and tit["p3"] is True
    assert tit["p4"] is False           # suplente (LK=2)
    assert "c1" not in tit              # técnico excluido


def test_parse_lineup_trae_equipo_y_titular():
    filas = parse_lineup(LI)
    by = {f["player_id"]: f for f in filas}
    assert by["p1"]["nombre"] == "Cristiano Ronaldo"
    assert by["p1"]["equipo"] == "Portugal" and by["p1"]["fue_titular"] is True
    assert by["p3"]["equipo"] == "Spain"
    assert by["p4"]["fue_titular"] is False       # suplente
    assert "c1" not in by                         # técnico excluido
