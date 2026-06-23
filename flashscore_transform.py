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
