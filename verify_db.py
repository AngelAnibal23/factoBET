"""Verifica que los datos en Supabase son correctos."""
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]

sb = create_client(SUPA_URL, SUPA_KEY)

print("=" * 50)
print("HELPBETOR — VERIFICACION DB")
print("=" * 50)

# Ligas
ligas = sb.table("ligas").select("*").execute().data
print(f"\nLigas      : {len(ligas)}")
for l in ligas:
    print(f"  {l['nombre']} | ID: {l['api_football_id']} | Cobertura: {l['nivel_cobertura']}")

# Equipos
equipos = sb.table("equipos").select("id").execute().data
print(f"\nEquipos    : {len(equipos)}")

# Partidos totales
partidos = sb.table("partidos").select("id, temporada, resultado").execute().data
print(f"\nPartidos   : {len(partidos)}")

# Por temporada
from collections import Counter
por_temporada = Counter(p["temporada"] for p in partidos)
for season, count in sorted(por_temporada.items()):
    print(f"  {season}: {count} partidos")

# Resultados
resultados = Counter(p["resultado"] for p in partidos)
total = len(partidos)
print(f"\nResultados:")
print(f"  HOME : {resultados.get('HOME', 0)}  ({resultados.get('HOME',0)/total*100:.1f}%)")
print(f"  DRAW : {resultados.get('DRAW', 0)}  ({resultados.get('DRAW',0)/total*100:.1f}%)")
print(f"  AWAY : {resultados.get('AWAY', 0)}  ({resultados.get('AWAY',0)/total*100:.1f}%)")

# Muestra 3 partidos
print(f"\nMuestra (3 partidos recientes de 2024):")
sample = sb.table("partidos").select(
    "fecha, temporada, jornada, goles_local, goles_visitante, resultado, estadio_nombre, "
    "equipo_local_id, equipo_visitante_id"
).eq("temporada", "2024").order("fecha", desc=True).limit(3).execute().data

equipo_map = {e["id"]: e["nombre_oficial"]
              for e in sb.table("equipos").select("id, nombre_oficial").execute().data}

for p in sample:
    local   = equipo_map.get(p["equipo_local_id"], "?")
    visita  = equipo_map.get(p["equipo_visitante_id"], "?")
    fecha   = p["fecha"][:10]
    print(f"  {fecha} | {local} {p['goles_local']}-{p['goles_visitante']} {visita} | {p['jornada']}")

print("\nDB verificada correctamente.")
