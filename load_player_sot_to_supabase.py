# load_player_sot_to_supabase.py
"""Carga los params del modelo SoT por-jugador GATEADOS a parametros_modelo
(player_sot_v0.1). Reusa fit_player_sot.main() (corre el gate). Idempotente.

    python load_player_sot_to_supabase.py
"""
import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_player_sot import main as fit_main

VERSION = "player_sot_v0.1"
LIGA_NOMBRE = "Internacional"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    params = fit_main()
    if not params["metricas"]:
        print("Nada que cargar (sot no pasó el gate).")
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
    print(f"✅ player_sot_v0.1 cargado: {len(params['jugadores'])} jugadores.")


if __name__ == "__main__":
    main()
