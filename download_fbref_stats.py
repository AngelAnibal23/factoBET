"""Descarga stats por partido-equipo (tarjetas+tiros) de FBref via soccerdata
y las guarda en fbref_stats.csv. CORRE EN EL VENV AISLADO .venv-fbref:
    .venv-fbref/Scripts/python download_fbref_stats.py

Cobertura: INT-World Cup + INT-European Championship, ediciones disponibles.
Cada edición devuelve el match-log del año de sus participantes."""

import sys
import pandas as pd
import soccerdata as sd

from fbref_transform import merge_misc_shooting

# Seasons POR LIGA: cada competición solo tiene sus ediciones. Pedir una season
# inexistente (ej. World Cup 2020) hace que soccerdata reviente con KeyError.
LEAGUE_SEASONS = {
    "INT-World Cup": [2018, 2022, 2026],
    "INT-European Championship": [2020, 2024],
}
SALIDA = "fbref_stats.csv"


def descargar():
    # Fetch POR LIGA: soccerdata deja el nivel 'league' del índice en <NA> cuando
    # se piden varias ligas juntas, así que la columna 'liga' queda vacía. Pedimos
    # cada liga por separado (con sus seasons) y la taggeamos explícitamente.
    frames = []
    for liga, seasons in LEAGUE_SEASONS.items():
        fb = sd.FBref(leagues=[liga], seasons=seasons)
        misc = fb.read_team_match_stats(stat_type="misc")
        shooting = fb.read_team_match_stats(stat_type="shooting")
        tidy = merge_misc_shooting(misc, shooting)
        tidy["liga"] = liga
        frames.append(tidy)
    out = pd.concat(frames, ignore_index=True)
    # dedup final por si un equipo aparece en ambas competiciones
    out = out.drop_duplicates(subset=["fecha", "equipo_fbref", "rival_fbref"])
    out.to_csv(SALIDA, index=False, encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Descargando misc + shooting de FBref (puede tardar varios minutos)...")
    tidy = descargar()
    print(f"Guardado {len(tidy)} filas (partido-equipo) en {SALIDA}")
    print(f"Selecciones distintas: {tidy['equipo_fbref'].nunique()}")
    print("Columnas:", list(tidy.columns))
