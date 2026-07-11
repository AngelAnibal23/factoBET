# download_sot_jugador.py
"""Backfill resumable de SoT por-jugador desde API-Football /fixtures/players.

Dos fases idempotentes:
  descubrir  -> lista fixtures por (liga, temporada) y los marca 'pendiente'.
  hidratar   -> toma N pendientes (presupuesto del día), baja /fixtures/players,
                escribe eventos_sot_jugador, marca 'hecho'/'sin_datos'.

    python download_sot_jugador.py descubrir
    python download_sot_jugador.py hidratar [N]

Plan Free: ~100 req/día, 10/min. Corre 'hidratar' una vez al día hasta agotar
pendientes (o déjalo en /loop). La resolución equipo_nombre->equipo_id es fuzzy
contra equipos.nombre_oficial (nombres en inglés, como martj42); ver alias abajo.
"""
import os
import sys
import time

import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz
from supabase import create_client

from sot_transform import parse_fixtures_players

API_URL = "https://v3.football.api-sports.io"
PRESUPUESTO_DEFAULT = 90        # margen bajo el límite de 100/día
RESOLVER_UMBRAL = 85

# MANIFIESTO: (liga_api_id, [temporadas]). Confirmar IDs con un sondeo a /leagues.
# Selecciones donde se repiten los jugadores bettables (profundidad para el gate).
MANIFIESTO = [
    (1,  [2022]),            # World Cup
    (4,  [2024]),            # Euro
    (5,  [2022, 2024]),      # Nations League
    (9,  [2024]),            # Copa America
    (34, [2022]),            # WC Qualification CONMEBOL (ciclo 2020-2022; plan Free solo 2022-2024)
    # añadir clasificatorias/amistosos según presupuesto disponible
]

# Alias ES/EN o variantes API-Football -> nombre_oficial en `equipos` (crece a demanda)
ALIAS = {}


def elegir_pendientes(progreso: list[dict], presupuesto: int) -> list[int]:
    """event_ids en estado 'pendiente', hasta `presupuesto`."""
    return [p["event_id"] for p in progreso if p["estado"] == "pendiente"][:presupuesto]


def filas_descubrir(fixtures: list[dict], liga_id: int, season: int) -> list[dict]:
    """Filas para sot_backfill_progreso desde /fixtures. Incluye fecha del partido
    (fixture.date) — /fixtures/players no la trae y sin ella el gate no puede
    hacer split temporal."""
    return [{"event_id": f["fixture"]["id"], "liga_api_id": liga_id,
             "temporada": season, "estado": "pendiente",
             "fecha": f["fixture"]["date"]} for f in fixtures]


class ApiFootballError(RuntimeError):
    """La API respondió 200 pero con `errors` poblado (cuota diaria, rate-limit)."""


def chequear_errores_api(payload: dict):
    """API-Football señala fallas con HTTP 200 + `errors` no vacío y `response`
    vacío. Hay que abortar: si se sigue, hidratar confunde "no pude consultar"
    con "fixture sin datos" (2026-07-10: 90 falsos sin_datos con cuota agotada)."""
    err = payload.get("errors")
    if err:
        raise ApiFootballError(str(err))


def _api_get(endpoint, params, key):
    r = requests.get(f"{API_URL}/{endpoint}", headers={"x-apisports-key": key},
                     params=params, timeout=25)
    r.raise_for_status()
    j = r.json()
    chequear_errores_api(j)
    remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
    return j.get("response", []), remaining


def _resolver_equipo(nombre, mapa_nombre_id):
    n = ALIAS.get(nombre, nombre).lower()
    mejor_id, mejor = None, 0.0
    for nom, _id in mapa_nombre_id.items():
        sc = fuzz.token_set_ratio(n, nom.lower())
        if sc > mejor:
            mejor_id, mejor = _id, sc
    return mejor_id if mejor >= RESOLVER_UMBRAL else None


def descubrir(sb, key):
    total = 0
    for liga_id, temporadas in MANIFIESTO:
        for season in temporadas:
            fixtures, rem = _api_get("fixtures", {"league": liga_id, "season": season}, key)
            rows = filas_descubrir(fixtures, liga_id, season)
            for i in range(0, len(rows), 100):
                # ignore_duplicates: NO pisar estado de fixtures ya 'hecho'/'sin_datos'
                sb.table("sot_backfill_progreso").upsert(
                    rows[i:i+100], on_conflict="event_id",
                    ignore_duplicates=True).execute()
                # 2º pase solo-fecha: backfill de fecha en filas ya existentes
                # (el upsert de arriba las saltó) sin tocar su estado.
                solo_fecha = [{"event_id": r["event_id"], "fecha": r["fecha"]}
                              for r in rows[i:i+100]]
                sb.table("sot_backfill_progreso").upsert(
                    solo_fecha, on_conflict="event_id").execute()
            total += len(rows)
            print(f"  liga {liga_id} {season}: {len(rows)} fixtures | API rem {rem}")
            time.sleep(0.3)
    print(f"✅ descubrimiento: {total} fixtures marcados pendiente.")


def hidratar(sb, key, presupuesto):
    # liga_api_id desc => primero 34 (quals CONMEBOL) y 9 (Copa América):
    # densifica sudamericanos (Messi & co.) para el umbral >=10 del gate.
    prog = (sb.table("sot_backfill_progreso").select("event_id,estado,fecha")
            .eq("estado", "pendiente").order("liga_api_id", desc=True)
            .limit(presupuesto).execute().data)
    pendientes = elegir_pendientes(prog, presupuesto)
    fecha_de = {p["event_id"]: p.get("fecha") for p in prog}
    mapa = {e["nombre_oficial"]: e["id"]
            for e in sb.table("equipos").select("id,nombre_oficial").execute().data}
    print(f"  {len(pendientes)} pendientes a hidratar (presupuesto {presupuesto}).")
    hechos = 0
    for eid in pendientes:
        try:
            resp, rem = _api_get("fixtures/players", {"fixture": eid}, key)
        except ApiFootballError as e:
            print(f"  ⛔ API-Football: {e} — paro; los fixtures quedan pendientes.")
            break
        filas = parse_fixtures_players(resp, eid)
        if not filas:
            sb.table("sot_backfill_progreso").update(
                {"estado": "sin_datos", "fecha_proceso": "now()"}).eq("event_id", eid).execute()
            continue
        rows = []
        for f in filas:
            rows.append({"event_id": f["event_id"], "player_id": f["player_id"],
                         "player_nombre": f["player_nombre"],
                         "equipo_id": _resolver_equipo(f["equipo_nombre"], mapa),
                         "sot": f["sot"], "fue_titular": f["fue_titular"],
                         "minutos": f["minutos"], "fecha": fecha_de.get(eid)})
        sb.table("eventos_sot_jugador").upsert(rows, on_conflict="event_id,player_id").execute()
        sb.table("sot_backfill_progreso").update(
            {"estado": "hecho", "fecha_proceso": "now()"}).eq("event_id", eid).execute()
        hechos += 1
        if str(rem).isdigit() and int(rem) <= 5:
            print(f"  ⚠ rate-limit casi agotado (rem {rem}); paro.")
            break
        time.sleep(6.5)   # ~9/min, bajo el límite de 10/min
    print(f"✅ hidratados {hechos} fixtures.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    key = os.environ["API_FOOTBALL_KEY"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hidratar"
    if cmd == "descubrir":
        descubrir(sb, key)
    elif cmd == "hidratar":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else PRESUPUESTO_DEFAULT
        hidratar(sb, key, n)
    else:
        print("uso: python download_sot_jugador.py [descubrir|hidratar [N]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
