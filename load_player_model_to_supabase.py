# load_player_model_to_supabase.py
"""Carga los params del modelo por-jugador GATEADOS a parametros_modelo (player_v0.1).

Reusa fit_player_model.main() (corre el gate). Persiste UNA fila para la liga
Internacional con jugadores+metricas en `notas` (JSON). Idempotente.

    python load_player_model_to_supabase.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_player_model import main as fit_main

VERSION = "player_v0.2"   # v0.2: k=3 (calibración cola elite) + gate con λ por-equipo
LIGA_NOMBRE = "Internacional"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    params = fit_main()
    if not params["metricas"]:
        print("Nada que cargar (ninguna métrica pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", LIGA_NOMBRE).execute().data
    if not liga:
        print(f"⚠ liga '{LIGA_NOMBRE}' no existe en `ligas`.")
        sys.exit(1)
    liga_id = liga[0]["id"]

    (sb.table("parametros_modelo").delete()
     .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
    sb.table("parametros_modelo").insert({
        "liga_id": liga_id, "version_modelo": VERSION,
        "attack_params": {}, "defense_params": {}, "is_production": True,
        "notas": json.dumps(params),
    }).execute()
    print(f"✅ {VERSION} cargado: métricas {params['metricas']}, "
          f"{len(params['jugadores'])} jugadores.")


if __name__ == "__main__":
    main()
