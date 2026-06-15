"""
Descarga el dataset abierto martj42/international_results y lo filtra a los
partidos relevantes para el modelo de selecciones (2018+ con marcador no nulo).
Guarda una copia local en intl_results.csv.
"""

import csv
import io
import sys

import requests

CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DESDE = "2018-01-01"
SALIDA = "intl_results.csv"


def descargar_filtrar(url=CSV_URL, desde=DESDE, salida=SALIDA):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    filtrados = []
    for r in rows:
        if r["date"] < desde:
            continue
        if r["home_score"] == "" or r["away_score"] == "":
            continue
        filtrados.append(r)

    with open(salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(filtrados)

    return len(rows), len(filtrados)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    total, n = descargar_filtrar()
    print(f"Descargados {total} partidos, {n} tras filtrar (>= {DESDE}, con marcador).")
    print(f"Guardado en {SALIDA}")
