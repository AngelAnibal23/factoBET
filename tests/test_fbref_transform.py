import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from fbref_transform import merge_misc_shooting, resolver_equipo_id


def _idx():
    return pd.MultiIndex.from_tuples(
        [("INT-World Cup", "2022", "Argentina", "2022-11-22 Argentina-Saudi Arabia")],
        names=["league", "season", "team", "game"],
    )


def _misc_df():
    cols = pd.MultiIndex.from_tuples([
        ("date", ""), ("venue", ""), ("opponent", ""), ("GF", ""), ("GA", ""),
        ("Performance", "CrdY"), ("Performance", "CrdR"), ("Performance", "2CrdY"),
        ("Performance", "Fls"), ("Performance", "Crs"), ("Performance", "Off"),
    ])
    return pd.DataFrame(
        [["2022-11-22", "Neutral", "Saudi Arabia", 1, 2, 3, 0, 0, 15, 18, 4]],
        index=_idx(), columns=cols,
    )


def _shooting_df():
    cols = pd.MultiIndex.from_tuples([
        ("date", ""), ("venue", ""), ("opponent", ""),
        ("Standard", "Sh"), ("Standard", "SoT"),
    ])
    return pd.DataFrame(
        [["2022-11-22", "Neutral", "Saudi Arabia", 14, 6]],
        index=_idx(), columns=cols,
    )


def test_merge_produces_tidy_row():
    out = merge_misc_shooting(_misc_df(), _shooting_df())
    assert len(out) == 1
    row = out.iloc[0]
    assert row["liga"] == "INT-World Cup"
    assert row["season"] == "2022"
    assert row["equipo_fbref"] == "Argentina"
    assert row["rival_fbref"] == "Saudi Arabia"
    assert row["fecha"] == "2022-11-22"
    assert row["gf"] == 1 and row["ga"] == 2
    assert row["crd_y"] == 3 and row["crd_r"] == 0 and row["crd_2y"] == 0
    assert row["fls"] == 15 and row["crs"] == 18 and row["off"] == 4
    assert row["sh"] == 14 and row["sot"] == 6


def test_merge_keeps_one_row_per_team_match_when_shooting_missing():
    # Si shooting no tiene la fila, la tarjeta se conserva con tiros NaN.
    out = merge_misc_shooting(_misc_df(), _shooting_df().iloc[0:0])
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["sh"])
    assert out.iloc[0]["crd_y"] == 3


def test_merge_deduplicates_source_rows():
    # soccerdata devuelve la misma fila duplicada; el merge no debe multiplicar.
    misc_dup = pd.concat([_misc_df(), _misc_df()])
    shoot_dup = pd.concat([_shooting_df(), _shooting_df()])
    out = merge_misc_shooting(misc_dup, shoot_dup)
    assert len(out) == 1


def test_merge_coerces_numeric_from_string():
    # GF/GA y conteos llegan como string desde FBref → deben quedar numéricos.
    misc = _misc_df().astype({("GF", ""): "string", ("GA", ""): "string"})
    out = merge_misc_shooting(misc, _shooting_df())
    assert out.iloc[0]["gf"] == 1
    assert pd.api.types.is_numeric_dtype(out["gf"])
    assert pd.api.types.is_numeric_dtype(out["crd_y"])


_TEAMS = [
    {"id": "kr", "nombre_oficial": "South Korea", "aliases": ["Corea del Sur", "Korea Republic"]},
    {"id": "ar", "nombre_oficial": "Argentina", "aliases": []},
]


def test_resolver_match_por_alias():
    # FBref dice "Korea Republic"; el alias lo lleva a South Korea.
    eid, canon, score = resolver_equipo_id("Korea Republic", _TEAMS)
    assert eid == "kr"
    assert canon == "South Korea"
    assert score >= 0.85


def test_resolver_huerfano_devuelve_none():
    eid, canon, score = resolver_equipo_id("Atlantis United", _TEAMS)
    assert eid is None
    assert canon == ""


def test_resolver_umbral_estricto_descarta_match_debil():
    # "Argentino" matchea Argentina con score ~0.94 (MATCHED por defecto);
    # forzando umbral 0.99 ese match razonable cae a huérfano.
    eid, _, _ = resolver_equipo_id("Argentino", _TEAMS, umbral=0.99)
    assert eid is None
