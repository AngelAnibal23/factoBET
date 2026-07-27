# load_player_model_to_supabase.py
"""Carga los params del modelo por-jugador GATEADOS a parametros_modelo (player_v0.2).

Reusa fit_player_model.main() (corre el gate por liga). Persiste UNA fila por
liga cuyo gate pasó al menos una métrica, con jugadores+metricas en `notas`
(JSON). Una liga que NO pasó el gate deliberadamente NO se publica: esa pata
queda `faltante` en el producto en vez de servir un número malo. Idempotente.

    python load_player_model_to_supabase.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_player_model import main as fit_main

VERSION = "player_v0.2"   # v0.2: k=3 (calibración cola elite) + gate con λ por-equipo


def ligas_publicables(params_por_liga: dict) -> dict:
    """Solo las ligas cuyo gate pasó al menos una métrica."""
    return {liga: p for liga, p in params_por_liga.items() if p["metricas"]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    publicables = ligas_publicables(fit_main())
    if not publicables:
        print("Nada que cargar (ninguna liga pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ligas = {l["nombre"]: l["id"]
             for l in sb.table("ligas").select("id,nombre").execute().data}

    for liga_nombre, params in publicables.items():
        liga_id = ligas.get(liga_nombre)
        if liga_id is None:
            print(f"  ⚠ liga '{liga_nombre}' no existe en `ligas` — SKIP")
            continue
        (sb.table("parametros_modelo").delete()
         .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
        sb.table("parametros_modelo").insert({
            "liga_id": liga_id, "version_modelo": VERSION,
            "attack_params": {}, "defense_params": {}, "is_production": True,
            "notas": json.dumps(params),
        }).execute()
        print(f"  ✅ {liga_nombre}: métricas {params['metricas']}, "
              f"{len(params['jugadores'])} jugadores.")


if __name__ == "__main__":
    main()
