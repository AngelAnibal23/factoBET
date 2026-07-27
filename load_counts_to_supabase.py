# load_counts_to_supabase.py
"""Carga los params de conteos GATEADOS a parametros_modelo (counts_v0.1).

Reusa fit_counts_model.main() (que ya corre el gate) y persiste una fila por
(liga, métrica) con los multiplicadores atk/def en attack_params/defense_params
y las bases/dispersión en notas (JSON). Idempotente: borra las filas counts_v0.1
de cada liga antes de reinsertar.

    python load_counts_to_supabase.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_counts_model import main as fit_main

VERSION = "counts_v0.1"
# etiqueta de liga del scrape (columna `liga`) -> nombre en la tabla `ligas`
LIGA_NOMBRE = {"INT": "Internacional", "Liga 1 Peru": "Liga 1 Peruana",
               "Premier League": "Premier League"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    publicables = fit_main()
    if not publicables:
        print("Nada que cargar (ninguna métrica pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ligas = {l["nombre"]: l["id"] for l in sb.table("ligas").select("id,nombre").execute().data}

    for lk, metricas in publicables.items():
        nombre = LIGA_NOMBRE.get(lk)
        liga_id = ligas.get(nombre)
        if liga_id is None:
            print(f"  ⚠ liga '{nombre}' no existe en `ligas` — SKIP {lk}")
            continue
        # idempotencia: borrar counts previos de esta liga
        (sb.table("parametros_modelo").delete()
         .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
        for metrica, est in metricas.items():
            sb.table("parametros_modelo").insert({
                "liga_id": liga_id,
                "version_modelo": VERSION,
                "attack_params": est["atk"],
                "defense_params": est["def"],
                "is_production": True,
                "notas": json.dumps({
                    "metrica": metrica,
                    "base_home": est["base_home"], "base_away": est["base_away"],
                    "factor_neutral": est["factor_neutral"], "disp": est["disp"],
                }),
            }).execute()
        print(f"  {lk} ({nombre}): cargadas {sorted(metricas)}")
    print("✅ Params de conteos cargados.")


if __name__ == "__main__":
    main()
