"""
Phase 1 — Download 996 Liga 1 Peruana matches into Supabase.
Seasons: 2022, 2023, 2024 (API-Football free plan limit).
Uses 3 API requests total (one per season).
"""

import os
import requests
import time
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY     = os.environ["API_FOOTBALL_KEY"]
API_URL     = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": API_KEY}

SUPA_URL    = os.environ["SUPABASE_URL"]
SUPA_KEY    = os.environ["SUPABASE_KEY"]

LIGA1_ID    = 281
SEASONS     = [2022, 2023, 2024]

supabase    = create_client(SUPA_URL, SUPA_KEY)

# ── Helpers ───────────────────────────────────────────────────────────────────
def api_get(endpoint, params=None):
    r = requests.get(f"{API_URL}/{endpoint}", headers=API_HEADERS,
                     params=params, timeout=20)
    r.raise_for_status()
    remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
    return r.json().get("response", []), remaining


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


# ── Step 1: Insert Liga 1 ─────────────────────────────────────────────────────
print("\n[1/4] Inserting Liga 1 Peruana...")

liga_row = {
    "api_football_id":        281,
    "nombre":                 "Liga 1 Peruana",
    "pais":                   "Peru",
    "nivel_cobertura":        "MEDIA",
    "modelo":                 "dixon_coles_local",
    "temporadas_disponibles": 3,
}

resp = (
    supabase.table("ligas")
    .upsert(liga_row, on_conflict="api_football_id")
    .execute()
)
liga_id = resp.data[0]["id"]
print(f"  Liga 1 ID in Supabase: {liga_id}")


# ── Step 2: Fetch all fixtures (3 API calls) ──────────────────────────────────
print("\n[2/4] Fetching fixtures from API-Football...")

all_fixtures = []
for season in SEASONS:
    fixtures, remaining = api_get("fixtures", {"league": LIGA1_ID, "season": season})
    all_fixtures.extend(fixtures)
    print(f"  {season}: {len(fixtures)} fixtures fetched | API remaining: {remaining}")
    time.sleep(0.3)

print(f"  Total fetched: {len(all_fixtures)}")


# ── Step 3: Build equipos dict and upsert ─────────────────────────────────────
print("\n[3/4] Upserting equipos...")

teams_seen = {}
for f in all_fixtures:
    for side in ("home", "away"):
        t = f["teams"][side]
        tid = t["id"]
        if tid not in teams_seen:
            teams_seen[tid] = {
                "api_football_id": tid,
                "nombre_oficial":  t["name"],
                "liga_id":         liga_id,
                "pais":            "Peru",
            }

team_rows = list(teams_seen.values())

# Upsert in batches of 50
BATCH = 50
for i in range(0, len(team_rows), BATCH):
    batch = team_rows[i:i+BATCH]
    supabase.table("equipos").upsert(batch, on_conflict="api_football_id").execute()
    print(f"  Upserted equipos {i+1}–{min(i+BATCH, len(team_rows))}")

# Fetch all inserted equipos to build api_id → uuid map
all_equipos = supabase.table("equipos").select("id,api_football_id").execute().data
equipo_map = {e["api_football_id"]: e["id"] for e in all_equipos}
print(f"  Total equipos in DB: {len(equipo_map)}")


# ── Step 4: Build partidos and upsert ────────────────────────────────────────
print("\n[4/4] Upserting partidos...")

partido_rows = []
skipped = 0

for f in all_fixtures:
    fix    = f["fixture"]
    goals  = f.get("goals", {})
    score  = f.get("score", {})
    teams  = f["teams"]
    league = f["league"]

    local_id = equipo_map.get(teams["home"]["id"])
    visit_id = equipo_map.get(teams["away"]["id"])

    if not local_id or not visit_id:
        skipped += 1
        continue

    gh = goals.get("home")
    ga = goals.get("away")
    ht = score.get("halftime", {})
    status_short = fix["status"]["short"]
    estado = STATUS_MAP.get(status_short, "SCHEDULED")

    row = {
        "api_football_id":     fix["id"],
        "liga_id":             liga_id,
        "equipo_local_id":     local_id,
        "equipo_visitante_id": visit_id,
        "fecha":               fix["date"],
        "temporada":           str(league.get("season", "")),
        "jornada":             league.get("round", ""),
        "estado":              estado,
        "goles_local":         gh,
        "goles_visitante":     ga,
        "resultado":           result_from_goals(gh, ga) if estado == "FINISHED" else None,
        "goles_ht_local":      ht.get("home"),
        "goles_ht_visitante":  ht.get("away"),
        "estadio_nombre":      fix.get("venue", {}).get("name"),
        "arbitro":             fix.get("referee"),
        "datos_completos":     gh is not None and ga is not None,
        "fuente":              "api_football",
    }
    partido_rows.append(row)

print(f"  Rows to insert: {len(partido_rows)} | Skipped: {skipped}")

inserted = 0
errors   = 0
for i in range(0, len(partido_rows), BATCH):
    batch = partido_rows[i:i+BATCH]
    try:
        supabase.table("partidos").upsert(batch, on_conflict="api_football_id").execute()
        inserted += len(batch)
        print(f"  Upserted partidos {i+1}–{min(i+BATCH, len(partido_rows))}")
    except Exception as e:
        errors += 1
        print(f"  ERROR on batch {i//BATCH + 1}: {e}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "="*55)
print("DOWNLOAD COMPLETE")
print("="*55)
print(f"  Liga inserted    : 1")
print(f"  Equipos upserted : {len(team_rows)}")
print(f"  Partidos inserted: {inserted}")
print(f"  Errors           : {errors}")
print(f"  Skipped          : {skipped}")
print("\nNext: run verify_db.py to confirm counts in Supabase.")
