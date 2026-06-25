# sot_ddl.py
"""Crea las tablas del pipeline de SoT por-jugador vía Supabase Management API.

Idempotente (CREATE TABLE IF NOT EXISTS). Corre con el python del sistema.

    python sot_ddl.py
"""
import os
import sys

from curl_cffi import requests as cr
from dotenv import load_dotenv

PROJECT_REF = "aahaivisyghpgqarqpak"
URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"

DDL = """
create table if not exists eventos_sot_jugador (
  event_id      bigint not null,
  player_id     text   not null,
  player_nombre text,
  equipo_id     uuid,
  sot           int    not null default 0,
  fue_titular   boolean,
  minutos       int,
  liga_api_id   int,
  fecha         timestamptz,
  primary key (event_id, player_id)
);
create table if not exists sot_backfill_progreso (
  event_id      bigint primary key,
  liga_api_id   int,
  temporada     int,
  estado        text not null default 'pendiente',
  fecha_proceso timestamptz
);
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    r = cr.post(URL, headers={"Authorization": f"Bearer {token}"},
                json={"query": DDL}, impersonate="chrome", timeout=30)
    print(f"status {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    print("✅ tablas eventos_sot_jugador + sot_backfill_progreso listas.")


if __name__ == "__main__":
    main()
