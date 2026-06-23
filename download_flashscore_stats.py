# download_flashscore_stats.py
"""Scrapea stats por partido (córners+tarjetas+tiros+xG) de Flashscore y guarda
flashscore_stats.csv. CORRE EN EL VENV AISLADO .venv-fbref:
    .venv-fbref/Scripts/python download_flashscore_stats.py

Patrón híbrido: seleniumbase UC enumera event ids del DOM de la página de
resultados (1 load por edición); curl_cffi baja el feed df_st de cada partido."""

import sys
import time
import pandas as pd
from curl_cffi import requests as cr
from seleniumbase import SB

from flashscore_transform import parse_results, parse_stats_feed, tidy_match

FSIGN = "SW9D1eZo"
FEED = "https://2.flashscore.ninja/2/x/feed"
HDR = {"x-fsign": FSIGN, "Referer": "https://www.flashscore.com/"}
SALIDA = "flashscore_stats.csv"

# (liga, url de resultados, season)
TOURNAMENTS = [
    ("INT-World Cup", "https://www.flashscore.com/football/world/world-championship-2018/results/", "2018"),
    ("INT-World Cup", "https://www.flashscore.com/football/world/world-championship-2022/results/", "2022"),
    ("INT-European Championship", "https://www.flashscore.com/football/europe/euro-2020/results/", "2020"),
    # Euro 2024 vive bajo el slug GENERICO `euro` (la edicion mas reciente no se
    # archiva con slug fechado: el archivo salta de euro-2020 a nada). OJO: cuando
    # arranque el ciclo Euro 2028, `euro` apuntara a 2028; re-confirmar el slug.
    ("INT-European Championship", "https://www.flashscore.com/football/europe/euro/results/", "2024"),
    # ── Extensión de densidad para el Mundial (Sub-proyecto B): clasificatorios +
    # Nations League + amistosos. Todo agrupa al pool "INT" (liga_key startswith INT-).
    # Sube partidos/selección de ~6 a decenas → saca la señal de conteos del ruido.
    # Clasificatorios Mundial 2026 por confederación: slug `/{region}/world-championship/`
    # (genérico = ciclo actual; el World Cup en sí usa `world-championship-{año}`).
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/south-america/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/europe/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/north-central-america/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/africa/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/asia/world-championship/results/", "2026"),
    # Nations League (ediciones con sufijo fechado, como los Euros viejos).
    ("INT-Nations League", "https://www.flashscore.com/football/europe/uefa-nations-league-2022-2023/results/", "2022"),
    ("INT-Nations League", "https://www.flashscore.com/football/europe/uefa-nations-league-2024-2025/results/", "2024"),
    # Amistosos internacionales (slug genérico, ~recientes).
    ("INT-Friendly", "https://www.flashscore.com/football/world/friendly-international/results/", "2025"),
    ("Liga 1 Peru", "https://www.flashscore.com/football/peru/liga-1-2024/results/", "2024"),
    ("Liga 1 Peru", "https://www.flashscore.com/football/peru/liga-1-2025/results/", "2025"),
]


def enumerar_partidos(sb, url):
    sb.uc_open_with_reconnect(url, reconnect_time=6)
    sb.sleep(8)
    try:
        sb.click("button#onetrust-accept-btn-handler")
        sb.sleep(2)
    except Exception:
        pass
    sb.sleep(3)
    return parse_results(sb.get_page_source())


def bajar_stats(event_id):
    r = cr.get(f"{FEED}/df_st_1_{event_id}", headers=HDR, impersonate="chrome", timeout=20)
    return parse_stats_feed(r.content.decode("utf-8", "replace"))


def descargar():
    filas = []
    with SB(uc=True, headless=True) as sb:
        for liga, url, season in TOURNAMENTS:
            try:
                partidos = enumerar_partidos(sb, url)
            except Exception as e:
                print(f"  WARN {liga} {season}: no se pudo cargar ({e})")
                continue
            print(f"  {liga} {season}: {len(partidos)} partidos")
            for m in partidos:
                try:
                    stats = bajar_stats(m["event_id"])
                except Exception:
                    stats = {}
                if stats:
                    filas.extend(tidy_match(m, stats, liga, season))
                time.sleep(0.3)   # cortesía con el feed
    out = pd.DataFrame(filas).drop_duplicates(subset=["event_id", "equipo_flashscore"])
    out.to_csv(SALIDA, index=False, encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Scrapeando Flashscore (browser por edición + feed por partido)...")
    out = descargar()
    print(f"Guardado {len(out)} filas (partido-equipo) en {SALIDA}")
    print(f"Equipos distintos: {out['equipo_flashscore'].nunique()}")
    print("Columnas:", list(out.columns))
