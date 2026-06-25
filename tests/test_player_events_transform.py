import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_events_transform import (
    parse_eventos, parse_titulares, parse_lineup, parse_lit_goles, eventos_completos,
)

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


# ---------------------------------------------------------------------------
# Recuperación de goles desde df_li_1.LIT (BUG: df_sui_1 omite el Goal de todo
# gol con asistencia y trae 0 goles en ligas no-top; el goleador SÍ está en LIT).
# Patrón validado contra feeds reales (final Mundial 2018, Escocia-Chequia, etc.):
#   - el goleador es el nombre TRAS EL MINUTO en el texto del LIT, no el dueño de
#     la fila (un jugador con varios eventos guarda solo uno en su LIT);
#   - "MIN' Goleador (Asistente)" o "MIN' Goleador" (sin asistencia);
#   - las TARJETAS comparten formato ("90+2' Vrsaljko S. (Tripping)") y se
#     desambiguan cruzando con Yellow/Red de df_sui_1.
# ---------------------------------------------------------------------------

# El gol de p2 (asistido por p1) NO está como Goal en df_sui_1: solo la Assistance.
# Su LIT aparece en la fila del goleador (p2) Y en la del asistente (p1).
LI_ASIST = (
    "LB÷Starting Lineups¬LC÷1~"
    "LP÷p1¬LI÷Asistente A¬LK÷1¬LIT÷28' Goleador B (Asistente A)~"
    "LP÷p2¬LI÷Goleador B¬LK÷1¬LIT÷28' Goleador B (Asistente A)~"
    "LC÷2~"
    "LP÷p3¬LI÷Rival¬LK÷1"
)


def test_parse_lit_goles_extrae_goleador_del_texto_no_dueno_de_fila():
    goles = parse_lit_goles(LI_ASIST)
    # un solo gol, atribuido al GOLEADOR (p2), no al asistente (p1)
    assert len(goles) == 1
    g = goles[0]
    assert g["player_id"] == "p2" and g["nombre"] == "Goleador B"
    assert g["lado"] == 1 and g["minuto"] == "28'"


# Goleador que además fue sustituido: su PROPIA fila guarda el cambio ("87'"),
# y el LIT del gol vive en la fila del asistente. Debe resolverse igual (por texto).
LI_GOL_EN_FILA_AJENA = (
    "LB÷Starting Lineups¬LC÷2~"
    "LP÷pA¬LI÷Asiste X¬LK÷1¬LIT÷42' Schick P. (Asiste X)~"
    "LP÷pS¬LI÷Schick P.¬LK÷1¬LIT÷87'"
)


def test_parse_lit_goles_resuelve_goleador_aunque_su_fila_muestre_otro_evento():
    goles = parse_lit_goles(LI_GOL_EN_FILA_AJENA)
    assert len(goles) == 1 and goles[0]["player_id"] == "pS"
    assert goles[0]["lado"] == 2


def test_eventos_completos_recupera_gol_asistido_ausente_en_sui():
    sui = "AC÷1st Half~IK÷Assistance¬IF÷Asistente A¬IM÷p1¬IA÷1¬IB÷28'"
    evs = eventos_completos(sui, LI_ASIST)
    goles = [e for e in evs if e["tipo"] == "Goal"]
    assert len(goles) == 1 and goles[0]["player_id"] == "p2"   # goleador recuperado
    assert any(e["tipo"] == "Assistance" and e["player_id"] == "p1" for e in evs)


def test_eventos_completos_excluye_tarjeta_que_parece_gol_en_lit():
    # "90+2' Vrsaljko (Tripping)" es una amarilla; df_sui_1 lo confirma -> NO es gol.
    li = (
        "LB÷Starting Lineups¬LC÷1~"
        "LP÷v1¬LI÷Vrsaljko S.¬LK÷1¬LIT÷90+2' Vrsaljko S. (Tripping)"
    )
    sui = "AC÷2nd Half~IK÷Yellow Card¬IF÷Vrsaljko S.¬IM÷v1¬IA÷1¬IB÷90+2'"
    evs = eventos_completos(sui, li)
    assert not any(e["tipo"] == "Goal" for e in evs)


def test_eventos_completos_no_duplica_gol_ya_presente_en_sui():
    # Gol unassisted SÍ presente en sui (p1 @23') y también en su LIT -> una sola vez.
    sui = "AC÷1st Half~IK÷Goal¬IF÷Cristiano Ronaldo¬IM÷p1¬IA÷1¬IB÷23'"
    li = (
        "LB÷Starting Lineups¬LC÷1~"
        "LP÷p1¬LI÷Cristiano Ronaldo¬LK÷1¬LIT÷23' Cristiano Ronaldo"
    )
    goles = [e for e in eventos_completos(sui, li) if e["tipo"] == "Goal"]
    assert len(goles) == 1


def test_eventos_completos_no_cuenta_own_goal_como_gol_del_jugador():
    sui = "AC÷1st Half~IK÷Own goal¬IF÷Autogol P¬IM÷og1¬IA÷1¬IB÷18'"
    li = (
        "LB÷Starting Lineups¬LC÷1~"
        "LP÷og1¬LI÷Autogol P¬LK÷1¬LIT÷18' Autogol P"
    )
    goles = [e for e in eventos_completos(sui, li) if e["tipo"] == "Goal"]
    assert goles == []


def test_eventos_completos_dobletes_emiten_dos_filas_goal():
    # Schick anota 2: uno asistido (ausente en sui, en LIT) y otro unassisted (en sui).
    sui = (
        "AC÷1st Half~IK÷Assistance¬IF÷Coufal V.¬IM÷pc¬IA÷2¬IB÷42'~"
        "AC÷2nd Half~IK÷Goal¬IF÷Schick P.¬IM÷ps¬IA÷2¬IB÷52'"
    )
    li = (
        "LB÷Starting Lineups¬LC÷2~"
        "LP÷pc¬LI÷Coufal V.¬LK÷1¬LIT÷42' Schick P. (Coufal V.)~"
        "LP÷ps¬LI÷Schick P.¬LK÷1¬LIT÷87'"
    )
    goles = [e for e in eventos_completos(sui, li) if e["tipo"] == "Goal"]
    assert len(goles) == 2 and all(g["player_id"] == "ps" for g in goles)
