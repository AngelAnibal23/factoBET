"""Ajuste offline del modelo de conteos + gate por (métrica, liga).

Lee estadisticas_flashscore de Supabase, separa por liga, estima atk/def con
shrinkage (counts_model.estimar_metrica), valida cada métrica contra un baseline
de promedio-liga en un holdout temporal, e imprime qué (métrica, liga) pasan el
gate. NO escribe a Supabase (eso lo hace load_counts_to_supabase.py).

    python fit_counts_model.py
"""

import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

from counts_model import METRICAS, COL_A_METRICA, estimar_metrica, CountsModel

# Líneas típicas de mercado para evaluar el gate (over/under TOTAL del partido).
LINEAS_GATE = {"corners": [8.5, 9.5, 10.5], "cards": [3.5, 4.5],
               "shots": [21.5, 24.5], "sot": [7.5, 8.5]}
GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
TEST_FRAC = 0.30   # holdout temporal: último 30% de cada liga (por fecha) = test


def cargar_filas():
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    filas, paso = [], 1000
    desde = 0
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,fecha,liga,equipo_flashscore,es_local,corners,crd_y,sh,sot")
                 .range(desde, desde + paso - 1).execute().data)
        filas.extend(chunk)
        if len(chunk) < paso:
            break
        desde += paso
    return filas


def a_partidos(filas, col):
    """Reconstruye partidos {home,away,val_home,val_away,fecha,liga} para una
    columna métrica, uniendo las 2 filas por event_id. Descarta valores nulos."""
    por_evento = defaultdict(dict)
    for f in filas:
        lado = "home" if f["es_local"] else "away"
        por_evento[f["event_id"]][lado] = f
    partidos = []
    for ev in por_evento.values():
        if "home" not in ev or "away" not in ev:
            continue
        vh, va = ev["home"].get(col), ev["away"].get(col)
        if vh is None or va is None:
            continue
        partidos.append({
            "home": ev["home"]["equipo_flashscore"], "away": ev["away"]["equipo_flashscore"],
            "val_home": float(vh), "val_away": float(va),
            "fecha": ev["home"]["fecha"], "liga": ev["home"]["liga"],
        })
    return partidos


def brier_ou(prob_over_list, ocurrio_over_list):
    p = np.asarray(prob_over_list)
    o = np.asarray(ocurrio_over_list, dtype=float)
    return float(np.mean((p - o) ** 2))


def estimar_disp(partidos):
    """Índice de dispersión (var/media) de los totales por partido. >=1 (clamp)."""
    tot = np.array([p["val_home"] + p["val_away"] for p in partidos], float)
    if tot.mean() <= 0:
        return 1.0
    return max(tot.var() / tot.mean(), 1.0)


def evaluar(params_metrica, test, metrica, lineas):
    """Brier promedio sobre las líneas (over/under total). `params_metrica` ya
    trae base/atk/def/disp. El baseline se obtiene pasando atk={}/def={}."""
    m = CountsModel.from_params({metrica: params_metrica})
    briers = []
    for linea in lineas:
        probs, occ = [], []
        for p in test:
            p_over = m.prob_over_under(metrica, "total", "over", linea, p["home"], p["away"], False)
            probs.append(p_over)
            occ.append(1.0 if (p["val_home"] + p["val_away"]) > linea else 0.0)
        briers.append(brier_ou(probs, occ))
    return float(np.mean(briers))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 64)
    print("FIT MODELO DE CONTEOS — gate por (métrica, liga)")
    print("=" * 64)
    filas = cargar_filas()
    ligas = sorted(set(f["liga"] for f in filas))
    # Agrupar las dos ligas internacionales en un solo pool "INT".
    def liga_key(lg):
        return "INT" if lg.startswith("INT-") else lg

    publicables = {}   # liga_key -> {metrica: est_params (fit sobre TODO)}
    for lk in sorted(set(liga_key(l) for l in ligas)):
        print(f"\n── Liga: {lk} ──")
        for col, metrica in COL_A_METRICA.items():
            partidos = [p for p in a_partidos(filas, col) if liga_key(p["liga"]) == lk]
            if len(partidos) < 30:
                print(f"  {metrica:8}: muestra insuficiente ({len(partidos)} partidos) — SKIP")
                continue
            # holdout temporal por liga: ordenar por fecha, último TEST_FRAC = test
            partidos.sort(key=lambda p: p["fecha"])
            corte = int(len(partidos) * (1 - TEST_FRAC))
            train, test = partidos[:corte], partidos[corte:]
            if len(train) < 20 or len(test) < 10:
                print(f"  {metrica:8}: holdout chico (train {len(train)}/test {len(test)}) — SKIP")
                continue
            est = estimar_metrica(train, k=K_SHRINK)
            est["factor_neutral"] = 1.0
            est["disp"] = estimar_disp(train)
            lineas = LINEAS_GATE[metrica]
            base_params = {**est, "atk": {}, "def": {}}   # misma NegBin, sin señal per-equipo
            bs_m = evaluar(est, test, metrica, lineas)
            bs_b = evaluar(base_params, test, metrica, lineas)
            mejora = (bs_b - bs_m) / bs_b if bs_b > 0 else 0.0
            ok = bs_m < bs_b and mejora >= GATE_MIN_MEJORA
            print(f"  {metrica:8}: disp={est['disp']:.2f}  Brier modelo={bs_m:.4f} "
                  f"base={bs_b:.4f} mejora={mejora*100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
            if ok:
                # params de PRODUCCIÓN = re-fit sobre TODOS los partidos de la liga
                prod = estimar_metrica(partidos, k=K_SHRINK)
                prod["factor_neutral"] = 1.0
                prod["disp"] = estimar_disp(partidos)
                publicables.setdefault(lk, {})[metrica] = prod

    print("\n" + "=" * 64)
    for lk, metricas in publicables.items():
        print(f"  {lk}: publicables -> {sorted(metricas)}")
    if not publicables:
        print("  ⚠ NINGUNA métrica pasó el gate. Revisar datos/shrinkage antes de cargar.")
    print("=" * 64)
    return publicables


if __name__ == "__main__":
    main()
