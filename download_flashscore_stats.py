# download_flashscore_stats.py
"""Scrapea stats por partido (córners+tarjetas+tiros+xG) de Flashscore y guarda
flashscore_stats.csv. CORRE EN EL VENV AISLADO .venv-fbref:
    .venv-fbref/Scripts/python download_flashscore_stats.py

Patrón híbrido: seleniumbase UC enumera event ids del DOM de la página de
resultados (1 load por edición); curl_cffi baja el feed df_st de cada partido."""

import sys
import time

import pandas as pd

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
    # ── Premier League: 3 temporadas (paridad con los fixtures de API-Football).
    # Slugs de archivo verificados el 2026-07-26 (HTTP 200); el patrón fechado
    # `premier-league-YYYY-YYYY` sí se archiva (a diferencia de los Euros).
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2022-2023/results/", "2022"),
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2023-2024/results/", "2023"),
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2024-2025/results/", "2024"),
]


# XPath verificado en vivo el 2026-07-26 contra la Premier League: el control ya
# no es `a.event__more`, es un contenedor data-testid="wcl-buttonLink" cuyo span
# interno dice literalmente "Show more matches". Una temporada de Premier (380
# partidos, 109 iniciales) necesitó 3 clicks para agotarse.
XPATH_VER_MAS = '//span[text()="Show more matches"]/ancestor::*[@data-testid="wcl-buttonLink"][1]'
MAX_CLICKS_VER_MAS = 30   # tope defensivo: si el sitio cambia de nuevo, no gira infinito


def _sigue_creciendo(anterior: int, actual: int) -> bool:
    """Pura: si el conteo de bloques de partido no creció tras un click, ya no
    vale la pena seguir pidiendo "ver más" (fin de la lista o botón fantasma)."""
    return actual > anterior


def enumerar_partidos(sb, url):
    sb.uc_open_with_reconnect(url, reconnect_time=6)
    sb.sleep(8)
    try:
        sb.click("button#onetrust-accept-btn-handler")
        sb.sleep(2)
    except Exception:
        pass
    sb.sleep(3)

    anterior = sb.get_page_source().count('id="g_1_')
    for _ in range(MAX_CLICKS_VER_MAS):
        try:
            if not sb.is_element_visible(XPATH_VER_MAS):
                break
            sb.click(XPATH_VER_MAS)
            sb.sleep(2)
        except Exception as e:
            print(f"  ver más: click falló, se detiene ({e})")
            break
        actual = sb.get_page_source().count('id="g_1_')
        print(f"  ver más: {anterior} -> {actual} partidos")
        if not _sigue_creciendo(anterior, actual):
            break
        anterior = actual

    return parse_results(sb.get_page_source())


def bajar_stats(event_id):
    from curl_cffi import requests as cr     # solo existe en .venv-fbref
    r = cr.get(f"{FEED}/df_st_1_{event_id}", headers=HDR, impersonate="chrome", timeout=20)
    return parse_stats_feed(r.content.decode("utf-8", "replace"))


def filtrar_torneos(tournaments, liga=None):
    """Solo los torneos de una liga (o todos si liga es None). Re-scrapear TODO
    son horas de browser; para añadir una liga se corre solo la suya."""
    if liga is None:
        return tournaments
    return [t for t in tournaments if t[0] == liga]


# Una liga o torneo real de UNA temporada completa entrega muchas decenas o
# cientos de partidos (Premier: 380). Si un torneo devuelve menos que esto casi
# seguro NO es que el torneo sea así de chico: es que Flashscore volvió a
# cambiar el marcado (como pasó jul-2026 con el contenedor de fecha y con el
# botón "ver más" — un scrape roto devolvía 0 partidos en silencio).
MIN_PARTIDOS_ESPERADOS = 30


def rendimiento_sospechoso(n_partidos: int, minimo: int = MIN_PARTIDOS_ESPERADOS) -> bool:
    """True si un torneo devolvió tan pocos partidos que huele a marcado roto."""
    return n_partidos < minimo


def descargar(tournaments=None, salida=SALIDA):
    tournaments = TOURNAMENTS if tournaments is None else tournaments
    if not tournaments:
        ligas_disponibles = sorted(set(t[0] for t in TOURNAMENTS))
        raise SystemExit(
            "No hay torneos para scrapear (filtro de liga vacío o inexistente). "
            f"Ligas disponibles: {ligas_disponibles}"
        )
    from seleniumbase import SB              # solo existe en .venv-fbref
    filas = []
    resumen = []   # (liga, season, n_partidos, n_filas)
    with SB(uc=True, headless=True) as sb:
        for liga, url, season in tournaments:
            try:
                partidos = enumerar_partidos(sb, url)
            except Exception as e:
                print(f"  WARN {liga} {season}: no se pudo cargar ({e})")
                resumen.append((liga, season, 0, 0))
                continue
            print(f"  {liga} {season}: {len(partidos)} partidos")
            if rendimiento_sospechoso(len(partidos)):
                print(
                    f"⚠⚠ ATENCION: '{liga}' {season} devolvio solo {len(partidos)} "
                    f"partidos (esperados >={MIN_PARTIDOS_ESPERADOS}).\n"
                    "   Casi seguro Flashscore cambio el marcado otra vez: revisar "
                    "parse_results y el boton \"ver mas\" ANTES de confiar en este CSV."
                )
            antes = len(filas)
            for m in partidos:
                try:
                    stats = bajar_stats(m["event_id"])
                except Exception:
                    stats = {}
                if stats:
                    filas.extend(tidy_match(m, stats, liga, season))
                time.sleep(0.3)   # cortesía con el feed
            resumen.append((liga, season, len(partidos), len(filas) - antes))

    if not filas:
        raise SystemExit(
            "Scrape sin filas: ningún torneo produjo partidos con stats. NO se "
            f"escribe '{salida}' (se protege un CSV bueno existente). Revisar "
            "parse_results / enumerar_partidos antes de reintentar."
        )

    out = pd.DataFrame(filas).drop_duplicates(subset=["event_id", "equipo_flashscore"])
    out.to_csv(salida, index=False, encoding="utf-8")

    print(f"\nResumen: {len(out)} filas totales (partido-equipo)")
    for liga, season, n_partidos, n_filas in resumen:
        print(f"  {liga} {season}: {n_partidos} partidos -> {n_filas} filas")

    return out


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--liga", default=None, help='p.ej. "Premier League"')
    p.add_argument("--salida", default=SALIDA)
    a = p.parse_args()
    tours = filtrar_torneos(TOURNAMENTS, a.liga)
    print(f"Scrapeando Flashscore: {len(tours)} torneos -> {a.salida}")
    out = descargar(tours, a.salida)
    print(f"Guardado {len(out)} filas (partido-equipo) en {a.salida}")
    print(f"Equipos distintos: {out['equipo_flashscore'].nunique()}")
    print("Columnas:", list(out.columns))
