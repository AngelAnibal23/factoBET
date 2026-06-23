"""Funciones puras del pipeline FBref (Capa 2). NO importa soccerdata ni lee
env al importar: corre en el entorno del proyecto y es testeable sin red."""

import pandas as pd

MISC_RENAME = {"CrdY": "crd_y", "CrdR": "crd_r", "2CrdY": "crd_2y",
               "Fls": "fls", "Crs": "crs", "Off": "off"}
SHOOT_RENAME = {"Sh": "sh", "SoT": "sot"}

_KEY = ["league", "season", "team", "game"]
_CTX = ["date", "venue", "opponent", "GF", "GA"]


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """reset_index + aplana columnas MultiIndex: ('Performance','CrdY')->'CrdY',
    ('league','')->'league'."""
    df = df.reset_index()
    nuevas = []
    for c in df.columns:
        if isinstance(c, tuple):
            nuevas.append(c[1] if len(c) > 1 and c[1] else c[0])
        else:
            nuevas.append(c)
    df = df.copy()
    df.columns = nuevas
    return df


def merge_misc_shooting(misc_df: pd.DataFrame, shooting_df: pd.DataFrame) -> pd.DataFrame:
    """Une las stats 'misc' (tarjetas+derivados) y 'shooting' (tiros) de
    soccerdata en una tabla tidy de una fila por partido-equipo."""
    m = _flatten(misc_df).rename(columns=MISC_RENAME)
    s = _flatten(shooting_df).rename(columns=SHOOT_RENAME)

    cols_m = [c for c in (_KEY + _CTX + list(MISC_RENAME.values())) if c in m.columns]
    cols_s = [c for c in (_KEY + list(SHOOT_RENAME.values())) if c in s.columns]
    m = m[cols_m]
    s = s[cols_s]

    out = m.merge(s, on=_KEY, how="left")
    return out.rename(columns={
        "league": "liga", "date": "fecha", "opponent": "rival_fbref",
        "team": "equipo_fbref", "GF": "gf", "GA": "ga",
    })
