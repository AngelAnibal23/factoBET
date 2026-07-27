"""Los fits por-jugador deben separar por liga: un solo pool mezclaba 11.140
registros de Liga 1 Peruana dentro de los params publicados como 'Internacional'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


LIGA_DE_EQUIPO = {
    "Argentina": "Internacional",
    "France": "Internacional",
    "Arsenal": "Premier League",
    "Chelsea": "Premier League",
    "Alianza Lima": "Liga 1 Peruana",
}


def _reg(equipo, pid):
    return {"event_id": f"e-{pid}", "player_id": pid, "nombre": pid,
            "equipo": equipo, "goles_jugador": 0, "asist_jugador": 0,
            "goles_equipo": 1, "n_titulares": 11}


def test_agrupa_registros_por_liga():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("Arsenal", "p2"), _reg("Alianza Lima", "p3")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert set(por_liga) == {"Internacional", "Premier League", "Liga 1 Peruana"}
    assert [r["player_id"] for r in por_liga["Premier League"]] == ["p2"]


def test_descarta_equipos_sin_liga_conocida():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("Equipo Fantasma", "p9")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert list(por_liga) == ["Internacional"]


def test_ninguna_liga_se_contamina_con_otra():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("France", "p2"),
            _reg("Arsenal", "p3"), _reg("Chelsea", "p4")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert len(por_liga["Internacional"]) == 2
    assert len(por_liga["Premier League"]) == 2
