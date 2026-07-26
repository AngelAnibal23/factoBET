"""
Carga de alias para los equipos de la Premier League.

API-Football los nombra corto ("Manchester United", "Tottenham", "Wolves"),
Flashscore usa otras variantes ("Manchester Utd", "Nottingham", "Wolverhampton")
y las casas de apuestas peruanas mezclan variantes ("Man Utd.", "Tottenham
Hotspur", "Newcastle United"). El validator ya matchea por `aliases`; este script
solo los CARGA en `equipos`.

Updater idempotente: MERGE de los alias nuevos con los existentes (sin duplicar,
sin borrar). Re-ejecutarlo es seguro.

    python set_pl_aliases.py
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

LIGA_NOMBRE = "Premier League"

# Clave = nombre_oficial EXACTO como lo entrega API-Football (verificado con
# /teams?league=39&season=2022|2023|2024 el 2026-07-26).
ALIAS_PL = {
    "Arsenal": ["Arsenal FC"],
    "Aston Villa": ["Villa", "Aston Villa FC"],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": ["Brentford FC"],
    "Brighton": ["Brighton & Hove Albion", "Brighton and Hove Albion", "Brighton Hove"],
    "Burnley": ["Burnley FC"],
    "Chelsea": ["Chelsea FC"],
    "Crystal Palace": ["Palace", "Crystal Palace FC"],
    "Everton": ["Everton FC"],
    "Fulham": ["Fulham FC"],
    "Ipswich": ["Ipswich Town"],
    "Leeds": ["Leeds United", "Leeds Utd"],
    "Leicester": ["Leicester City"],
    "Liverpool": ["Liverpool FC"],
    "Luton": ["Luton Town"],
    "Manchester City": ["Man City", "Manchester City FC", "City"],
    "Manchester United": ["Man United", "Man Utd", "Manchester Utd", "Manchester United FC"],
    "Newcastle": ["Newcastle United", "Newcastle Utd"],
    "Nottingham Forest": ["Nottingham", "Nott'm Forest", "Forest"],
    "Sheffield Utd": ["Sheffield United", "Sheffield"],
    "Southampton": ["Southampton FC", "Saints"],
    "Tottenham": ["Tottenham Hotspur", "Spurs"],
    "West Ham": ["West Ham United", "West Ham Utd"],
    "Wolves": ["Wolverhampton", "Wolverhampton Wanderers"],
}


def merge_alias(existentes: list[str], nuevos: list[str]) -> list[str]:
    """Une preservando los existentes y su orden, sin duplicar (case-insensitive)."""
    vistos = {a.lower() for a in existentes}
    salida = list(existentes)
    for a in nuevos:
        if a.lower() not in vistos:
            salida.append(a)
            vistos.add(a.lower())
    return salida


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    liga = sb.table("ligas").select("id").eq("nombre", LIGA_NOMBRE).execute().data
    if not liga:
        print(f"⚠ la liga '{LIGA_NOMBRE}' no existe en `ligas`. "
              "Corre primero: python download_fixtures.py --liga 39 "
              '--nombre "Premier League" --pais England')
        sys.exit(1)

    equipos = (sb.table("equipos").select("id, nombre_oficial, aliases")
               .eq("liga_id", liga[0]["id"]).execute().data)
    por_nombre = {e["nombre_oficial"]: e for e in equipos}
    print(f"Equipos en {LIGA_NOMBRE}: {len(equipos)}")

    actualizados, sin_cambio, no_encontrados = 0, 0, []
    for nombre, nuevos in ALIAS_PL.items():
        e = por_nombre.get(nombre)
        if e is None:
            no_encontrados.append(nombre)
            continue
        existentes = e.get("aliases") or []
        merged = merge_alias(existentes, nuevos)
        if merged == existentes:
            sin_cambio += 1
            continue
        sb.table("equipos").update({"aliases": merged}).eq("id", e["id"]).execute()
        actualizados += 1

    print(f"  Actualizados   : {actualizados}")
    print(f"  Sin cambio     : {sin_cambio}")
    if no_encontrados:
        print(f"  No encontrados : {no_encontrados}")
    print("✅ Alias de la Premier cargados.")


if __name__ == "__main__":
    main()
