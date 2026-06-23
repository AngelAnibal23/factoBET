"""Funciones puras del pipeline FBref (Capa 2). NO importa soccerdata ni lee
env al importar: corre en el entorno del proyecto y es testeable sin red."""

import pandas as pd

# NOTA: validator (rapidfuzz/supabase/dotenv) se importa LAZY dentro de
# resolver_equipo_id, no a nivel de módulo. Así merge_misc_shooting queda
# importable con solo pandas en el venv aislado .venv-fbref (que no tiene
# las deps del proyecto), donde corre el scrape.

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
    # soccerdata devuelve filas duplicadas por clave (misc viene 2x); deduplicar
    # antes del merge para que sea 1:1 y no multiplique las filas.
    m = m[cols_m].drop_duplicates(subset=_KEY)
    s = s[cols_s].drop_duplicates(subset=_KEY)

    out = m.merge(s, on=_KEY, how="left")
    out = out.rename(columns={
        "league": "liga", "date": "fecha", "opponent": "rival_fbref",
        "team": "equipo_fbref", "GF": "gf", "GA": "ga",
    })
    # GF/GA y los conteos llegan como string desde FBref → coercer a numérico.
    for col in ["gf", "ga", *MISC_RENAME.values(), *SHOOT_RENAME.values()]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def resolver_equipo_id(nombre: str, teams: list[dict], umbral: float | None = None):
    """(equipo_id | None, canonical, score). Solo acepta match >= umbral
    (bulk, sin confirmación humana). Por debajo -> huérfano (None).
    Import lazy de validator: solo corre en el entorno del proyecto."""
    from validator import _best_match, MATCH_AUTO  # no lee env relevante al importar
    if umbral is None:
        umbral = MATCH_AUTO
    m = _best_match(nombre, teams)
    if m.score >= umbral and m.equipo_id:
        return m.equipo_id, m.canonical, m.score
    return None, "", m.score
