# download_intl_extension.py
"""Extensión de densidad internacional para Sub-proyecto B: baja SOLO las
competiciones nuevas (clasificatorios + Nations League + amistosos) y las fusiona
en flashscore_stats.csv (dedup por event_id+equipo). No re-scrapea lo existente.

    .venv-fbref/Scripts/python download_intl_extension.py

Una vez fusionado: python load_flashscore_stats_to_supabase.py ; python fit_counts_model.py
"""

import sys
import time
import pandas as pd
from curl_cffi import requests as cr
from seleniumbase import SB

from flashscore_transform import parse_results, parse_stats_feed, tidy_match

FSIGN = "SW9D1eZo"
FEED = "https://2.flashscore.ninja/2/x/feed"
HDR = {"x-fsign": FSIGN, "Referer": "https://www.flashscore.com/"}
CSV = "flashscore_stats.csv"

NUEVAS = [
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/south-america/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/europe/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/north-central-america/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/africa/world-championship/results/", "2026"),
    ("INT-WC Qualifiers", "https://www.flashscore.com/football/asia/world-championship/results/", "2026"),
    ("INT-Nations League", "https://www.flashscore.com/football/europe/uefa-nations-league-2022-2023/results/", "2022"),
    ("INT-Nations League", "https://www.flashscore.com/football/europe/uefa-nations-league-2024-2025/results/", "2024"),
    ("INT-Friendly", "https://www.flashscore.com/football/world/friendly-international/results/", "2025"),
]


def enumerar(sb, url):
    sb.uc_open_with_reconnect(url, reconnect_time=6)
    sb.sleep(8)
    try:
        sb.click("button#onetrust-accept-btn-handler")
        sb.sleep(2)
    except Exception:
        pass
    sb.sleep(3)
    return parse_results(sb.get_page_source())


def bajar_stats(eid):
    r = cr.get(f"{FEED}/df_st_1_{eid}", headers=HDR, impersonate="chrome", timeout=20)
    return parse_stats_feed(r.content.decode("utf-8", "replace"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    filas = []
    with SB(uc=True, headless=True) as sb:
        for liga, url, season in NUEVAS:
            try:
                partidos = enumerar(sb, url)
            except Exception as e:
                print(f"  WARN {liga} {url}: {e}")
                continue
            print(f"  {liga} ({url.split('/football/')[1].split('/')[0]}): {len(partidos)} partidos")
            for m in partidos:
                try:
                    stats = bajar_stats(m["event_id"])
                except Exception:
                    stats = {}
                if stats:
                    filas.extend(tidy_match(m, stats, liga, season))
                time.sleep(0.3)
    nuevo = pd.DataFrame(filas)
    print(f"\nfilas nuevas con stats: {len(nuevo)} ({nuevo['event_id'].nunique()} partidos)")
    if len(nuevo):
        print("corners %:", round(nuevo['corners'].notna().mean() * 100, 1))

    viejo = pd.read_csv(CSV)
    comb = (pd.concat([viejo, nuevo], ignore_index=True)
            .drop_duplicates(subset=["event_id", "equipo_flashscore"], keep="last"))
    comb.to_csv(CSV, index=False, encoding="utf-8")
    print(f"CSV fusionado: {len(viejo)} -> {len(comb)} filas")
    print("por liga:", comb["liga"].value_counts().to_dict())


if __name__ == "__main__":
    main()
