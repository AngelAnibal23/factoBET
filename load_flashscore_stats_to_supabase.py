# load_flashscore_stats_to_supabase.py
"""Carga flashscore_stats.csv a Supabase: resuelve equipo_id, crea la tabla
estadisticas_flashscore e inserta filas crudas por partido-equipo. Imprime un
reporte de cobertura (gate antes de modelar). CORRE EN EL ENTORNO DEL PROYECTO:
    python load_flashscore_stats_to_supabase.py
"""

import os
import sys

import pandas as pd
import requests
from dotenv import load_dotenv
from supabase import create_client

from fbref_transform import resolver_equipo_id

CSV = "flashscore_stats.csv"
PROJECT_REF = "aahaivisyghpgqarqpak"

DDL = """
CREATE TABLE IF NOT EXISTS estadisticas_flashscore (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id           TEXT NOT NULL,
    fecha              DATE,
    liga               TEXT,
    season             TEXT,
    equipo_id          UUID REFERENCES equipos(id),
    equipo_flashscore  TEXT NOT NULL,
    rival_id           UUID REFERENCES equipos(id),
    rival_flashscore   TEXT NOT NULL,
    es_local           BOOLEAN,
    corners            INTEGER,
    crd_y              INTEGER,
    crd_r              INTEGER,
    sh                 INTEGER,
    sot                INTEGER,
    fouls              INTEGER,
    offsides           INTEGER,
    possession         INTEGER,
    xg                 REAL,
    UNIQUE (event_id, equipo_flashscore)
);
ALTER TABLE estadisticas_flashscore DISABLE ROW LEVEL SECURITY;
"""


def run_ddl(sql, mgmt_token):
    resp = requests.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={"Authorization": f"Bearer {mgmt_token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    print("[1/3] DDL: tabla estadisticas_flashscore...")
    run_ddl(DDL, mgmt_token)
    print("  tabla lista")


if __name__ == "__main__":
    main()
