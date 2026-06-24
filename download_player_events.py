# download_player_events.py
"""Baja eventos por-jugador (df_sui_1) + alineaciones (df_li_1) de Flashscore para
los event_ids YA enumerados en flashscore_stats.csv, y escribe player_events.csv.
CORRE EN EL VENV AISLADO .venv-fbref (tiene curl_cffi):

    .venv-fbref/Scripts/python download_player_events.py

No usa browser: los event_ids ya están en flashscore_stats.csv (los enumeró
download_flashscore_stats.py). Aquí solo se bajan 2 feeds livianos por partido.

Emite DOS tipos de fila por partido:
  - tipo="Lineup": una por jugador del df_li_1 (con lado y fue_titular) — necesarias
    para incluir a los titulares que NO anotaron (denominador del reparto).
  - tipo=evento (Goal/Assistance/Yellow Card/...): una por incidencia del df_sui_1.

OJO (verificar al correr): el marcador de titular se asume en la clave `ST` del
df_li_1 (ST==1 => titular). Si el feed real usa otra clave, ajustar parse_lineup/
parse_titulares en player_events_transform.py (y su test) en el mismo commit.
"""

import csv
import sys
import time

from curl_cffi import requests as cr

from player_events_transform import parse_eventos, parse_lineup

FEED = "https://2.flashscore.ninja/2/x/feed"
HDR = {"x-fsign": "SW9D1eZo", "Referer": "https://www.flashscore.com/"}
ENTRADA = "flashscore_stats.csv"
SALIDA = "player_events.csv"


def _feed(nombre: str) -> str:
    r = cr.get(f"{FEED}/{nombre}", headers=HDR, impersonate="chrome", timeout=20)
    return r.content.decode("utf-8", "replace")


def _event_ids():
    """event_ids distintos de flashscore_stats.csv (ya scrapeados)."""
    ids = []
    visto = set()
    with open(ENTRADA, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            eid = r.get("event_id")
            if eid and eid not in visto:
                visto.add(eid)
                ids.append(eid)
    return ids


def bajar_partido(eid: str) -> list[dict]:
    eventos = parse_eventos(_feed(f"df_sui_1_{eid}"))
    lineup = parse_lineup(_feed(f"df_li_1_{eid}"))
    titular = {f["player_id"]: f["fue_titular"] for f in lineup}
    lado_lin = {f["player_id"]: f["lado"] for f in lineup}
    filas = []
    for f in lineup:   # filas de alineación (todos los titulares/suplentes listados)
        filas.append({
            "event_id": eid, "player_id": f["player_id"], "nombre": f["nombre"],
            "tipo": "Lineup", "lado": f["lado"], "fue_titular": f["fue_titular"],
        })
    for e in eventos:  # filas de incidencias (goles/asistencias/tarjetas/...)
        filas.append({
            "event_id": eid, "player_id": e["player_id"], "nombre": e["nombre"],
            "tipo": e["tipo"],
            "lado": e["lado"] if e["lado"] is not None else lado_lin.get(e["player_id"]),
            "fue_titular": titular.get(e["player_id"], False),
        })
    return filas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ids = _event_ids()
    print(f"{len(ids)} partidos a procesar (desde {ENTRADA})")
    todos = []
    for i, eid in enumerate(ids, 1):
        try:
            todos.extend(bajar_partido(eid))
        except Exception as ex:   # noqa: BLE001 — scraper offline, log y sigue
            print(f"  WARN {eid}: {ex}")
        if i % 50 == 0:
            print(f"  {i}/{len(ids)}…")
        time.sleep(0.2)   # cortesía con el feed
    with open(SALIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "player_id", "nombre",
                                          "tipo", "lado", "fue_titular"])
        w.writeheader()
        w.writerows(todos)
    print(f"✅ {len(todos)} filas -> {SALIDA}")


if __name__ == "__main__":
    main()
