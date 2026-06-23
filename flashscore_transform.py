"""Funciones puras del pipeline Flashscore (Capa 2). NO importa seleniumbase ni
lee red al importar: corre en el entorno del proyecto y es testeable sin red."""

import re

SEP_F = "¬"   # ¬  separador de campo del feed packed
SEP_KV = "÷"  # ÷  separador clave-valor


def parse_stats_feed(text: str) -> dict:
    """Feed df_st packed -> {métrica: (local, visitante)}. Toma la 1ª ocurrencia
    de cada métrica (período full-match; Flashscore lista el total primero)."""
    out = {}
    metric = None
    home = None
    for chunk in text.split(SEP_F):
        if SEP_KV not in chunk:
            continue
        k, v = chunk.split(SEP_KV, 1)
        if k == "SG":
            metric, home = v, None
        elif k == "SH" and metric is not None:
            home = v
        elif k == "SI" and metric is not None and metric not in out:
            out[metric] = (home, v)
            metric = None
    return out


_DATE_RE = re.compile(r'event__time">(\d{2})\.(\d{2})\.(\d{4})')
_ALT_RE = re.compile(r'data-testid="wcl-participantLogo"[^>]*?alt="([^"]+)"')


def parse_results(html: str) -> list:
    """Del HTML de la página de resultados, una entrada por partido:
    {event_id, fecha (ISO), home, away}."""
    out = []
    bloques = html.split('id="g_1_')[1:]
    for b in bloques:
        eid = b[:8]
        if not eid.isalnum():
            continue
        dm = _DATE_RE.search(b[:1200])
        alts = _ALT_RE.findall(b[:2500])
        if dm and len(alts) >= 2:
            d, mth, y = dm.groups()
            out.append({
                "event_id": eid,
                "fecha": f"{y}-{mth}-{d}",
                "home": alts[0],
                "away": alts[1],
            })
    return out


# nombre de métrica Flashscore -> columna canónica
METRIC_MAP = {
    "Corner kicks": "corners",
    "Yellow cards": "crd_y",
    "Red cards": "crd_r",
    "Total shots": "sh",
    "Shots on target": "sot",
    "Fouls": "fouls",
    "Offsides": "offsides",
    "Ball possession": "possession",
    "Expected goals (xG)": "xg",
}


def _num(raw):
    """'54%' -> 54, '2.3' -> 2.3, '4' -> 4, None/'' -> None."""
    if raw is None:
        return None
    s = str(raw).replace("%", "").strip()
    if s == "":
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def tidy_match(meta: dict, stats: dict, liga: str, season: str) -> list:
    """meta {event_id,fecha,home,away} + stats {métrica:(local,visit)} ->
    2 filas por-equipo con columnas canónicas."""
    rows = []
    perspectivas = [
        (meta["home"], meta["away"], True, 0),
        (meta["away"], meta["home"], False, 1),
    ]
    for equipo, rival, es_local, idx in perspectivas:
        row = {
            "event_id": meta["event_id"], "fecha": meta["fecha"],
            "liga": liga, "season": season,
            "equipo_flashscore": equipo, "rival_flashscore": rival,
            "es_local": es_local,
        }
        for fs_name, col in METRIC_MAP.items():
            par = stats.get(fs_name)
            row[col] = _num(par[idx]) if par else None
        rows.append(row)
    return rows
