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
#   secciones por header LB (Starting Lineups / Substitutes / Coaches), y dentro de
#   cada sección dos bloques por LC (1=local, 2=visitante). LP=player_id, LI=nombre,
#   LK=1 titular / LK=2 suplente. LQ NO es el equipo (es nacionalidad en clubes).
#   Los técnicos (sección Coaches) traen LP y LK pero NO son jugadores -> excluir.
LI = (
    "LB÷Starting Lineups¬LC÷1~"
    "LP÷p1¬LI÷Cristiano Ronaldo¬LK÷1¬LL÷9~"
    "LP÷p2¬LI÷Bruno Fernandes¬LK÷1¬LL÷8~"
    "LC÷2~"
    "LP÷p3¬LI÷Rival Striker¬LK÷1¬LL÷9~"
    "LB÷Substitutes¬LC÷1~"
    "LP÷p4¬LI÷Suplente¬LK÷2~"
    "LB÷Coaches¬LC÷1~"
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


# La mitad/seccion va en registros-cabecera (AC sin IK). Los penales de la seccion
# "Penalties" son de tanda (sin INX) y NO deben contar como gol del jugador.
SUI_TANDA = (
    "AC÷2nd Half~"
    "IK÷Goal¬IF÷Real Scorer¬IM÷pG¬IA÷1¬IB÷70'~"
    "AC÷Extra Time~"
    "IK÷Penalty¬IF÷ET Penalty¬IM÷pE¬IA÷1¬IB÷109'~"
    "AC÷Penalties~"
    "IK÷Penalty¬IF÷Shootout A¬IM÷pS1¬IA÷1¬IB÷1~"
    "IK÷Penalty¬IF÷Shootout B¬IM÷pS2¬IA÷2¬IB÷1"
)


def test_parse_eventos_excluye_tanda_de_penales():
    evs = parse_eventos(SUI_TANDA)
    ids = {e["player_id"] for e in evs}
    assert "pG" in ids                 # gol en juego cuenta
    assert "pE" in ids                 # penal en Extra Time (con INX) cuenta
    assert "pS1" not in ids and "pS2" not in ids   # penales de tanda excluidos
    assert next(e for e in evs if e["player_id"] == "pG")["mitad"] == "2nd Half"


def test_parse_titulares_marca_solo_starters():
    tit = parse_titulares(LI)
    assert tit["p1"] is True and tit["p2"] is True and tit["p3"] is True
    assert tit["p4"] is False           # suplente (LK=2)
    assert "c1" not in tit              # técnico excluido


def test_parse_lineup_trae_lado_y_titular():
    filas = parse_lineup(LI)
    by = {f["player_id"]: f for f in filas}
    assert by["p1"]["nombre"] == "Cristiano Ronaldo"
    assert by["p1"]["lado"] == 1 and by["p1"]["fue_titular"] is True   # bloque LC=1 (local)
    assert by["p3"]["lado"] == 2                                       # bloque LC=2 (visitante)
    assert by["p4"]["lado"] == 1 and by["p4"]["fue_titular"] is False  # suplente local
    assert "c1" not in by                                              # técnico excluido
