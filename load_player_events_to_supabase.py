# load_player_events_to_supabase.py
"""Crea/puebla eventos_jugador_flashscore desde player_events.csv.

Resuelve equipo_id por (event_id, lado) contra estadisticas_flashscore (que ya tiene
event_id, es_local y equipo_id resueltos; lado 1=local, 2=visitante, derivado del bloque
LC del lineup). Idempotente por (event_id, player_id, tipo).

    python load_player_events_to_supabase.py

NOTA: crear la tabla con el DDL de abajo en el SQL editor de Supabase si no existe.
"""

import csv
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

DDL = """
create table if not exists eventos_jugador_flashscore (
  id bigint generated always as identity primary key,
  event_id text not null,
  equipo_id uuid,
  player_id text not null,
  player_nombre text,
  tipo text not null,
  fue_titular boolean,
  cantidad int not null default 1,
  unique (event_id, player_id, tipo)
);
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    print("Si la tabla no existe, ejecuta este DDL en el SQL editor de Supabase:\n", DDL)

    # mapa (event_id, lado) -> equipo_id desde estadisticas_flashscore (1=local, 2=visitante)
    lado_equipo, desde, paso = {}, 0, 1000
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,es_local,equipo_id")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            lado_equipo[(r["event_id"], 1 if r["es_local"] else 2)] = r["equipo_id"]
        if len(chunk) < paso:
            break
        desde += paso

    # agrega por (event_id, player_id, tipo): un jugador puede anotar/asistir 2+ veces
    # en un partido -> cantidad>1 (necesario para "anota 2+" y para el reparto de goles).
    agg = {}
    with open("player_events.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["event_id"], r["player_id"], r["tipo"])
            if k not in agg:
                lado = int(r["lado"]) if r["lado"] not in ("", "None") else None
                agg[k] = {"nombre": r["nombre"], "lado": lado,
                          "fue_titular": r["fue_titular"] == "True", "cantidad": 0}
            agg[k]["cantidad"] += 1
    filas = [{
        "event_id": e,
        "equipo_id": lado_equipo.get((e, v["lado"])),
        "player_id": p, "player_nombre": v["nombre"],
        "tipo": t, "fue_titular": v["fue_titular"], "cantidad": v["cantidad"],
    } for (e, p, t), v in agg.items()]
    for i in range(0, len(filas), 500):
        sb.table("eventos_jugador_flashscore").upsert(
            filas[i:i + 500], on_conflict="event_id,player_id,tipo").execute()
    con_equipo = sum(1 for f in filas if f["equipo_id"])
    print(f"✅ {len(filas)} filas; identidad equipo {con_equipo}/{len(filas)} "
          f"({con_equipo / max(len(filas), 1) * 100:.0f}%)")


if __name__ == "__main__":
    main()
