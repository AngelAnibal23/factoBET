"""Carga fbref_stats.csv a Supabase: resuelve equipo_id, crea la tabla
estadisticas_partido e inserta filas crudas por partido-equipo. Imprime un
reporte de cobertura (gate antes de modelar). CORRE EN EL ENTORNO DEL PROYECTO:
    python load_fbref_stats_to_supabase.py
"""

import os
import sys

import pandas as pd
import requests
from dotenv import load_dotenv
from supabase import create_client

from fbref_transform import resolver_equipo_id

CSV = "fbref_stats.csv"
PROJECT_REF = "aahaivisyghpgqarqpak"

DDL = """
CREATE TABLE IF NOT EXISTS estadisticas_partido (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha         DATE,
    liga          TEXT,
    season        TEXT,
    equipo_id     UUID REFERENCES equipos(id),
    equipo_fbref  TEXT NOT NULL,
    rival_id      UUID REFERENCES equipos(id),
    rival_fbref   TEXT NOT NULL,
    venue         TEXT,
    gf            INTEGER,
    ga            INTEGER,
    crd_y         INTEGER,
    crd_r         INTEGER,
    crd_2y        INTEGER,
    fls           INTEGER,
    crs           INTEGER,
    "off"         INTEGER,
    sh            INTEGER,
    sot           INTEGER,
    UNIQUE (fecha, equipo_fbref, rival_fbref)
);
ALTER TABLE estadisticas_partido DISABLE ROW LEVEL SECURITY;
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


def _to_int(v):
    return None if pd.isna(v) else int(v)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print("[1/3] DDL: tabla estadisticas_partido...")
    run_ddl(DDL, mgmt_token)

    print("[2/3] Resolviendo equipos y construyendo filas...")
    df = pd.read_csv(CSV)
    teams = sb.table("equipos").select("id, nombre_oficial, aliases").execute().data

    # cache de resolución por nombre FBref
    cache = {}
    def resolver(n):
        if n not in cache:
            cache[n] = resolver_equipo_id(str(n), teams)
        return cache[n]

    filas = []
    for _, r in df.iterrows():
        eid, _, _ = resolver(r["equipo_fbref"])
        rid, _, _ = resolver(r["rival_fbref"])
        filas.append({
            "fecha": r["fecha"], "liga": r["liga"], "season": str(r["season"]),
            "equipo_id": eid, "equipo_fbref": r["equipo_fbref"],
            "rival_id": rid, "rival_fbref": r["rival_fbref"],
            "venue": r.get("venue"),
            "gf": _to_int(r.get("gf")), "ga": _to_int(r.get("ga")),
            "crd_y": _to_int(r.get("crd_y")), "crd_r": _to_int(r.get("crd_r")),
            "crd_2y": _to_int(r.get("crd_2y")), "fls": _to_int(r.get("fls")),
            "crs": _to_int(r.get("crs")), "off": _to_int(r.get("off")),
            "sh": _to_int(r.get("sh")), "sot": _to_int(r.get("sot")),
        })

    # upsert idempotente por la clave única
    for i in range(0, len(filas), 500):
        sb.table("estadisticas_partido").upsert(
            filas[i:i+500], on_conflict="fecha,equipo_fbref,rival_fbref"
        ).execute()

    # ── [3/3] Reporte de cobertura (gate antes de modelar) ──
    print("[3/3] Reporte de cobertura:")
    nombres = sorted(set(df["equipo_fbref"]) | set(df["rival_fbref"]))
    huerfanos = [n for n in nombres if resolver(n)[0] is None]
    vc = df["equipo_fbref"].value_counts()
    print(f"  filas (partido-equipo): {len(df)}")
    print(f"  selecciones distintas : {df['equipo_fbref'].nunique()}")
    print(f"  partidos/seleccion    : min={int(vc.min())} med={int(vc.median())} max={int(vc.max())}")
    print(f"  nombres resueltos     : {len(nombres)-len(huerfanos)}/{len(nombres)}"
          f" ({100*(len(nombres)-len(huerfanos))/len(nombres):.0f}%)")
    print(f"  huerfanos ({len(huerfanos)}): {huerfanos[:20]}")
    print(f"  filas con tarjetas    : {df['crd_y'].notna().mean()*100:.0f}%")
    print(f"  filas con tiros       : {df['sh'].notna().mean()*100:.0f}%")
    print("\n✅ Datos cargados. Revisar el reporte para decidir el Sub-proyecto B.")


if __name__ == "__main__":
    main()
