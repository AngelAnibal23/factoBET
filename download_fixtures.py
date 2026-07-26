"""
Descarga fixtures de una liga de clubes a Supabase (ligas + equipos + partidos).

Por defecto, la Liga 1 Peruana (comportamiento histórico). Para la Premier:

    python download_fixtures.py --liga 39 --nombre "Premier League" --pais England

Usa 1 request de API-Football por temporada (3 en total). El plan Free solo da
2022, 2023 y 2024 (verificado 2026-07-26: season=2025 responde "Free plans do not
have access to this season").
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from supabase import create_client

API_URL = "https://v3.football.api-sports.io"
BATCH = 50
PAGINA_SUPABASE = 1000  # tope real de PostgREST por .select(); paginar con .range()


@dataclass
class Config:
    liga_api_id: int
    temporadas: list[int]
    nombre: str
    pais: str
    cobertura: str


def parsear_args(argv: list[str]) -> Config:
    p = argparse.ArgumentParser(description="Ingesta de fixtures por liga.")
    p.add_argument("--liga", type=int, default=281, help="league id de API-Football")
    p.add_argument("--temporadas", default="2022,2023,2024")
    p.add_argument("--nombre", default="Liga 1 Peruana", help="nombre en la tabla `ligas`")
    p.add_argument("--pais", default="Peru")
    p.add_argument("--cobertura", default="MEDIA", choices=["ALTA", "MEDIA", "BAJA", "NULA"])
    a = p.parse_args(argv)
    return Config(
        liga_api_id=a.liga,
        temporadas=[int(t) for t in a.temporadas.split(",") if t.strip()],
        nombre=a.nombre, pais=a.pais, cobertura=a.cobertura,
    )


def api_get(endpoint, params, api_key):
    r = requests.get(f"{API_URL}/{endpoint}",
                     headers={"x-apisports-key": api_key}, params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    # API-Football señala cuota agotada con HTTP 200 + `errors` poblado.
    if payload.get("errors"):
        raise RuntimeError(f"API-Football: {payload['errors']}")
    return payload.get("response", []), r.headers.get("x-ratelimit-requests-remaining", "?")


def result_from_goals(gh, ga):
    if gh is None or ga is None:
        return None
    if gh > ga:
        return "HOME"
    if gh < ga:
        return "AWAY"
    return "DRAW"


STATUS_MAP = {
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "NS": "SCHEDULED", "TBD": "SCHEDULED",
    "1H": "LIVE", "HT": "LIVE", "2H": "LIVE", "ET": "LIVE", "P": "LIVE",
    "SUSP": "SUSPENDED", "PST": "POSTPONED",
    "CANC": "CANCELLED", "ABD": "CANCELLED",
}


def filas_equipos(fixtures, liga_id, pais):
    vistos = {}
    for f in fixtures:
        for side in ("home", "away"):
            t = f["teams"][side]
            if t["id"] not in vistos:
                vistos[t["id"]] = {"api_football_id": t["id"],
                                   "nombre_oficial": t["name"],
                                   "liga_id": liga_id, "pais": pais}
    return list(vistos.values())


def filas_partidos(fixtures, liga_id, equipo_map):
    filas, saltados = [], 0
    for f in fixtures:
        fix, goals, score = f["fixture"], f.get("goals", {}), f.get("score", {})
        local_id = equipo_map.get(f["teams"]["home"]["id"])
        visit_id = equipo_map.get(f["teams"]["away"]["id"])
        if not local_id or not visit_id:
            saltados += 1
            continue
        gh, ga = goals.get("home"), goals.get("away")
        ht = score.get("halftime", {})
        estado = STATUS_MAP.get(fix["status"]["short"], "SCHEDULED")
        filas.append({
            "api_football_id": fix["id"], "liga_id": liga_id,
            "equipo_local_id": local_id, "equipo_visitante_id": visit_id,
            "fecha": fix["date"], "temporada": str(f["league"].get("season", "")),
            "jornada": f["league"].get("round", ""), "estado": estado,
            "goles_local": gh, "goles_visitante": ga,
            "resultado": result_from_goals(gh, ga) if estado == "FINISHED" else None,
            "goles_ht_local": ht.get("home"), "goles_ht_visitante": ht.get("away"),
            "estadio_nombre": fix.get("venue", {}).get("name"),
            "arbitro": fix.get("referee"),
            "datos_completos": gh is not None and ga is not None,
            "fuente": "api_football",
        })
    return filas, saltados


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = parsear_args(sys.argv[1:] if argv is None else argv)
    load_dotenv()
    api_key = os.environ["API_FOOTBALL_KEY"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print(f"\n[1/4] Upsert de la liga {cfg.nombre} (api id {cfg.liga_api_id})...")
    resp = sb.table("ligas").upsert({
        "api_football_id": cfg.liga_api_id, "nombre": cfg.nombre, "pais": cfg.pais,
        "nivel_cobertura": cfg.cobertura, "modelo": "dixon_coles_local",
        "temporadas_disponibles": len(cfg.temporadas),
    }, on_conflict="api_football_id").execute()
    liga_id = resp.data[0]["id"]
    print(f"  liga_id: {liga_id}")

    print("\n[2/4] Bajando fixtures...")
    fixtures = []
    for season in cfg.temporadas:
        fx, rem = api_get("fixtures", {"league": cfg.liga_api_id, "season": season}, api_key)
        fixtures.extend(fx)
        print(f"  {season}: {len(fx)} fixtures | API remaining: {rem}")
        time.sleep(0.3)
    print(f"  total: {len(fixtures)}")

    print("\n[3/4] Upsert de equipos...")
    equipos = filas_equipos(fixtures, liga_id, cfg.pais)
    for i in range(0, len(equipos), BATCH):
        lote = equipos[i:i + BATCH]
        sb.table("equipos").upsert(lote, on_conflict="api_football_id").execute()
        print(f"  upsert equipos {i + 1}-{i + len(lote)}")

    equipo_map = {}
    desde = 0
    while True:
        pagina = (sb.table("equipos").select("id,api_football_id")
                  .range(desde, desde + PAGINA_SUPABASE - 1).execute().data)
        equipo_map.update({e["api_football_id"]: e["id"] for e in pagina})
        if len(pagina) < PAGINA_SUPABASE:
            break
        desde += PAGINA_SUPABASE
    print(f"  equipos de esta liga: {len(equipos)}")

    print("\n[4/4] Upsert de partidos...")
    filas, saltados = filas_partidos(fixtures, liga_id, equipo_map)
    print(f"  filas a insertar: {len(filas)} | saltados: {saltados}")
    insertados, errores = 0, 0
    try:
        for i in range(0, len(filas), BATCH):
            lote = filas[i:i + BATCH]
            try:
                sb.table("partidos").upsert(lote, on_conflict="api_football_id").execute()
                insertados += len(lote)
                print(f"  upsert partidos {i + 1}-{i + len(lote)}")
            except Exception as e:   # noqa: BLE001 — un lote malo no debe tirar la corrida
                errores += 1
                print(f"  ERROR en el lote {i // BATCH + 1}: {e}")
    finally:
        print("\n" + "=" * 55)
        print(f"  Liga            : {cfg.nombre} ({liga_id})")
        print(f"  Equipos         : {len(equipos)}")
        print(f"  Partidos        : {insertados}")
        print(f"  Lotes con error : {errores}")
        print(f"  Saltados        : {saltados}")
        print("=" * 55)


if __name__ == "__main__":
    main()
