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


def _es_entero(s):
    """True si s representa un entero (marcador valido). Excluye '', 'NA', etc."""
    return s.lstrip("-").isdigit()


def descargar_filtrar(url=CSV_URL, desde=DESDE, salida=SALIDA):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    filtrados = []
    for r in rows:
        if r["date"] < desde:
            continue
        # Partidos futuros (sin jugar) traen marcador "NA" o vacio -> excluir.
        if not _es_entero(r["home_score"]) or not _es_entero(r["away_score"]):
            continue
        filtrados.append(r)

    with open(salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(filtrados)

    return len(rows), len(filtrados)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "elo":
        # Histórico profundo para calcular ELO (desde 1990: ratings maduros
        # al llegar a la era del modelo). NO pisa intl_results.csv.
        total, n = descargar_filtrar(desde="1990-01-01", salida="intl_results_elo.csv")
        print(f"Descargados {total} partidos, {n} tras filtrar (>= 1990, con marcador).")
        print("Guardado en intl_results_elo.csv")
    else:
        total, n = descargar_filtrar()
        print(f"Descargados {total} partidos, {n} tras filtrar (>= {DESDE}, con marcador).")
        print(f"Guardado en {SALIDA}")
