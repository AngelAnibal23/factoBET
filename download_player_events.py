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
  - tipo=evento (Goal/Assistance/Yellow Card/...): UNIÓN de df_sui_1 y los goleadores
    recuperados del campo LIT de df_li_1. df_sui_1 OMITE el `Goal` de todo gol con
    asistencia (deja solo la `Assistance`) y trae 0 goles en ligas no-top; sin el LIT
    la tasa caía a ~0.84 goles/partido (real ~2.7). Ver eventos_completos().

Esquema verificado contra el feed real (2026-06-24): en df_li_1 el titular es LK==1
(suplente LK==2), el LADO se deriva del bloque LC (1=local, 2=visitante) y los técnicos
van en la sección LB÷Coaches (excluidos). OJO: LQ NO es el equipo (es nacionalidad del
jugador en partidos de club). El lado se resuelve a equipo_id contra es_local en el load.
Ver player_events_transform.py.
"""

import argparse
import csv
import sys
import time

from player_events_transform import eventos_completos, parse_lineup

FEED = "https://2.flashscore.ninja/2/x/feed"
HDR = {"x-fsign": "SW9D1eZo", "Referer": "https://www.flashscore.com/"}
ENTRADA = "flashscore_stats.csv"
SALIDA = "player_events.csv"


def parsear_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", default=ENTRADA, help="CSV con los event_id ya scrapeados")
    p.add_argument("--salida", default=SALIDA)
    return p.parse_args(argv)


def _feed(nombre: str) -> str:
    from curl_cffi import requests as cr   # solo existe en .venv-fbref
    r = cr.get(f"{FEED}/{nombre}", headers=HDR, impersonate="chrome", timeout=20)
    return r.content.decode("utf-8", "replace")


def _event_ids(entrada):
    """event_ids distintos de flashscore_stats.csv (ya scrapeados)."""
    ids = []
    visto = set()
    with open(entrada, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            eid = r.get("event_id")
            if eid and eid not in visto:
                visto.add(eid)
                ids.append(eid)
    return ids


def bajar_partido(eid: str) -> list[dict]:
    sui_blob = _feed(f"df_sui_1_{eid}")
    li_blob = _feed(f"df_li_1_{eid}")
    # UNIÓN sui_1 ∪ LIT: recupera los goles que df_sui_1 omite (asistidos / ligas no-top).
    eventos = eventos_completos(sui_blob, li_blob)
    lineup = parse_lineup(li_blob)
    titular = {f["player_id"]: f["fue_titular"] for f in lineup}
    lado_lin = {f["player_id"]: f["lado"] for f in lineup}   # player_id -> lado (LC)
    filas = []
    for f in lineup:   # filas de alineación (todos los titulares/suplentes listados)
        filas.append({
            "event_id": eid, "player_id": f["player_id"], "nombre": f["nombre"],
            "tipo": "Lineup", "lado": f["lado"], "fue_titular": f["fue_titular"],
        })
    for e in eventos:  # filas de incidencias (goles/asistencias/tarjetas/...)
        lado = lado_lin.get(e["player_id"], e["lado"])   # lado del lineup; IA del evento como respaldo
        filas.append({
            "event_id": eid, "player_id": e["player_id"], "nombre": e["nombre"],
            "tipo": e["tipo"],
            "lado": lado if lado is not None else "",
            "fue_titular": titular.get(e["player_id"], False),
        })
    return filas


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    args = parsear_args(sys.argv[1:] if argv is None else argv)
    ids = _event_ids(args.entrada)
    print(f"{len(ids)} partidos a procesar (desde {args.entrada})")
    todos = []
    for i, eid in enumerate(ids, 1):
        try:
            todos.extend(bajar_partido(eid))
        except Exception as ex:   # noqa: BLE001 — scraper offline, log y sigue
            print(f"  WARN {eid}: {ex}")
        if i % 50 == 0:
            print(f"  {i}/{len(ids)}…")
        time.sleep(0.2)   # cortesía con el feed
    with open(args.salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "player_id", "nombre",
                                          "tipo", "lado", "fue_titular"])
        w.writeheader()
        w.writerows(todos)
    print(f"✅ {len(todos)} filas -> {args.salida}")


if __name__ == "__main__":
    main()
