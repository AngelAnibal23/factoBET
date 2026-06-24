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

Esquema verificado contra el feed real (2026-06-24): en df_li_1 el titular es LK==1
(suplente LK==2), el equipo es el nombre en LQ (= estadisticas_flashscore.equipo_flashscore)
y los técnicos van en la sección LB÷Coaches (excluidos). Ver player_events_transform.py.
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
    equipo_lin = {f["player_id"]: f["equipo"] for f in lineup}   # player_id -> nombre equipo
    filas = []
    for f in lineup:   # filas de alineación (todos los titulares/suplentes listados)
        filas.append({
            "event_id": eid, "player_id": f["player_id"], "nombre": f["nombre"],
            "tipo": "Lineup", "equipo": f["equipo"], "fue_titular": f["fue_titular"],
        })
    for e in eventos:  # filas de incidencias (goles/asistencias/tarjetas/...)
        filas.append({
            "event_id": eid, "player_id": e["player_id"], "nombre": e["nombre"],
            "tipo": e["tipo"],
            "equipo": equipo_lin.get(e["player_id"], ""),   # equipo por nombre desde el lineup
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
                                          "tipo", "equipo", "fue_titular"])
        w.writeheader()
        w.writerows(todos)
    print(f"✅ {len(todos)} filas -> {SALIDA}")


if __name__ == "__main__":
    main()
