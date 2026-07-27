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


def _int(v):
    return None if pd.isna(v) else int(v)


def _real(v):
    return None if pd.isna(v) else float(v)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print("[1/3] DDL: tabla estadisticas_flashscore...")
    run_ddl(DDL, mgmt_token)

    print("[2/3] Resolviendo equipos y construyendo filas...")
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV
    print(f"  CSV: {csv_path}")
    df = pd.read_csv(csv_path)
    teams = sb.table("equipos").select("id, nombre_oficial, aliases").execute().data

    cache = {}
    def resolver(n):
        if n not in cache:
            cache[n] = resolver_equipo_id(str(n), teams)
        return cache[n]

    filas = []
    for _, r in df.iterrows():
        eid, _, _ = resolver(r["equipo_flashscore"])
        rid, _, _ = resolver(r["rival_flashscore"])
        filas.append({
            "event_id": r["event_id"], "fecha": r["fecha"],
            "liga": r["liga"], "season": str(r["season"]),
            "equipo_id": eid, "equipo_flashscore": r["equipo_flashscore"],
            "rival_id": rid, "rival_flashscore": r["rival_flashscore"],
            "es_local": bool(r["es_local"]),
            "corners": _int(r.get("corners")), "crd_y": _int(r.get("crd_y")),
            "crd_r": _int(r.get("crd_r")), "sh": _int(r.get("sh")),
            "sot": _int(r.get("sot")), "fouls": _int(r.get("fouls")),
            "offsides": _int(r.get("offsides")), "possession": _int(r.get("possession")),
            "xg": _real(r.get("xg")),
        })

    for i in range(0, len(filas), 500):
        sb.table("estadisticas_flashscore").upsert(
            filas[i:i+500], on_conflict="event_id,equipo_flashscore"
        ).execute()

    # ── [3/3] Reporte de cobertura ──
    print("[3/3] Reporte de cobertura:")
    nombres = sorted(set(df["equipo_flashscore"]) | set(df["rival_flashscore"]))
    huerfanos = [n for n in nombres if resolver(n)[0] is None]
    vc = df["equipo_flashscore"].value_counts()
    print(f"  filas (partido-equipo): {len(df)}")
    print(f"  por liga              : {df['liga'].value_counts().to_dict()}")
    print(f"  equipos distintos     : {df['equipo_flashscore'].nunique()}")
    print(f"  partidos/equipo       : min={int(vc.min())} med={int(vc.median())} max={int(vc.max())}")
    print(f"  nombres resueltos     : {len(nombres)-len(huerfanos)}/{len(nombres)}"
          f" ({100*(len(nombres)-len(huerfanos))/len(nombres):.0f}%)")
    print(f"  huerfanos ({len(huerfanos)}): {huerfanos[:25]}")
    for col in ["corners", "crd_y", "sh", "sot", "xg"]:
        print(f"  filas con {col:9}: {df[col].notna().mean()*100:.0f}%")
    print("\n✅ Datos cargados. Revisar el reporte para decidir el Sub-proyecto B.")


if __name__ == "__main__":
    main()
