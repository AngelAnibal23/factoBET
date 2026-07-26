"""Merge idempotente de alias (misma lógica que set_intl_aliases, sin tocar red)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_merge_agrega_sin_duplicar():
    from set_pl_aliases import merge_alias
    assert merge_alias(["Man City"], ["Manchester City", "Man City"]) == \
        ["Man City", "Manchester City"]


def test_merge_es_case_insensitive():
    from set_pl_aliases import merge_alias
    assert merge_alias(["man city"], ["Man City"]) == ["man city"]


def test_merge_preserva_los_existentes_y_su_orden():
    from set_pl_aliases import merge_alias
    assert merge_alias(["Z", "A"], ["B"]) == ["Z", "A", "B"]


def test_alias_cubren_los_24_equipos_de_2022_2024():
    """Los 24 nombres son los que devolvió /teams?league=39 para 2022, 2023 y 2024."""
    from set_pl_aliases import ALIAS_PL
    esperados = {
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Burnley",
        "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich", "Leeds",
        "Leicester", "Liverpool", "Luton", "Manchester City", "Manchester United",
        "Newcastle", "Nottingham Forest", "Sheffield Utd", "Southampton",
        "Tottenham", "West Ham", "Wolves",
    }
    assert set(ALIAS_PL) == esperados


def test_cada_equipo_tiene_al_menos_un_alias():
    from set_pl_aliases import ALIAS_PL
    assert all(len(v) >= 1 for v in ALIAS_PL.values())


def test_merge_es_idempotente():
    from set_pl_aliases import merge_alias
    nuevos = ["Man City", "City"]
    una_vez = merge_alias([], nuevos)
    dos_veces = merge_alias(una_vez, nuevos)
    assert dos_veces == una_vez


def test_ningun_alias_colisiona_con_otro_equipo():
    """
    Invariante: un alias de un equipo NO puede apuntar a otro equipo.

    Caso real que motiva este test (2026-07-26): el alias "City" en
    "Manchester City" es substring de "Leicester City" — la forma en que
    casas de apuestas y Flashscore escriben a Leicester (cuyo nombre_oficial
    en esta BD es solo "Leicester", sin "City"). El validator toma el score
    máximo por partial_ratio sobre nombre_oficial + aliases de TODOS los
    equipos, así que un OCR "Leicester City" empataba 100/100 entre
    "Leicester" (match directo) y "Manchester City" (vía el alias "City"),
    resuelto arbitrariamente por orden de fila — resolución silenciosa al
    equipo equivocado. Por eso "City" se quitó y se agregó "Leicester City"
    como alias de Leicester. Este test evita que alguien vuelva a agregar
    "City" (o cualquier alias igual de genérico) más adelante.
    """
    from set_pl_aliases import ALIAS_PL

    for equipo_a, aliases_a in ALIAS_PL.items():
        for alias in aliases_a:
            alias_norm = alias.lower()
            for equipo_b, aliases_b in ALIAS_PL.items():
                if equipo_a == equipo_b:
                    continue
                assert alias_norm not in equipo_b.lower(), (
                    f'Colisión: el alias "{alias}" de "{equipo_a}" es '
                    f'substring del nombre oficial de "{equipo_b}".'
                )
                for otro_alias in aliases_b:
                    assert alias_norm not in otro_alias.lower(), (
                        f'Colisión: el alias "{alias}" de "{equipo_a}" es '
                        f'substring (o igual) del alias "{otro_alias}" de '
                        f'"{equipo_b}".'
                    )
