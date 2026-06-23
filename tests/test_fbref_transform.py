import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from fbref_transform import merge_misc_shooting


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
