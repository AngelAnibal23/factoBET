"""ELO internacional (fórmula World Football Elo, la de eloratings.net) calculado
sobre el histórico martj42. Produce z-scores por selección para usarse como PRIOR
del Dixon-Coles internacional (ver spec 2026-07-13-elo-prior-design.md).

Puro y sin red: lee CSVs locales. `intl_results_elo.csv` se genera con
`python download_intl_results.py elo` (histórico desde 1990, misma fuente).
"""
import csv
import math
import os

CSV_ELO = "intl_results_elo.csv"
FIFA_CSV = "fifa_ranking.csv"
ELO_INICIAL = 1500.0
VENTAJA_LOCAL = 100.0
K_DEFAULT = 30.0

# (patrón, K) — se matchea por substring en minúsculas; el orden importa:
# 'fifa world cup qualification' contiene 'fifa world cup', va primero.
K_TORNEOS = [
    ("fifa world cup qualification", 40.0),
    ("fifa world cup", 60.0),
    ("uefa euro qualification", 40.0),
    ("uefa euro", 50.0),
    ("copa américa", 50.0),
    ("copa america", 50.0),
    ("african cup of nations", 50.0),
    ("afc asian cup", 50.0),
    ("gold cup", 50.0),
    ("uefa nations league", 40.0),
    ("friendly", 20.0),
]


def k_torneo(tournament: str) -> float:
    t = tournament.strip().lower()
    for patron, k in K_TORNEOS:
        if patron in t:
            return k
    return K_DEFAULT


def multiplicador_goles(diff: int) -> float:
    """Estándar World Football Elo: 1 gol ->x1, 2 ->x1.5, 3 ->x1.75, +1/8 por gol extra."""
    d = abs(diff)
    if d <= 1:
        return 1.0
    if d == 2:
        return 1.5
    return 1.75 + (d - 3) / 8.0


def calcular_elo(partidos: list[dict], hasta: str | None = None) -> dict[str, float]:
    """Recorre partidos ORDENADOS por fecha y devuelve {selección: elo}.

    `hasta` (ISO, exclusivo) corta el recorrido: para el gate, el ELO del train
    se calcula con hasta=TEST_DESDE para no fugar resultados del test.
    El intercambio es suma-cero: delta = K * G * (W - We).
    """
    elos: dict[str, float] = {}
    for m in partidos:
        if hasta is not None and m["fecha"] >= hasta:
            break
        eh = elos.setdefault(m["home"], ELO_INICIAL)
        ea = elos.setdefault(m["away"], ELO_INICIAL)
        dr = eh - ea + (0.0 if m["neutral"] else VENTAJA_LOCAL)
        we = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        if m["gl"] > m["gv"]:
            w = 1.0
        elif m["gl"] == m["gv"]:
            w = 0.5
        else:
            w = 0.0
        delta = k_torneo(m["tournament"]) * multiplicador_goles(m["gl"] - m["gv"]) * (w - we)
        elos[m["home"]] = eh + delta
        elos[m["away"]] = ea - delta
    return elos


def estandarizar(valores: dict[str, float]) -> dict[str, float]:
    """z-scores sobre el conjunto dado. Es lo que consume el prior del DC."""
    if not valores:
        return {}
    vals = list(valores.values())
    media = sum(vals) / len(vals)
    var = sum((v - media) ** 2 for v in vals) / len(vals)
    sd = math.sqrt(var) or 1.0
    return {t: (v - media) / sd for t, v in valores.items()}


def blend_z(z_propio: dict, z_fifa: dict, w: float = 0.7) -> dict[str, float]:
    """Mezcla con el nuestro predominante; equipos sin señal FIFA usan solo la nuestra."""
    return {t: (w * z + (1.0 - w) * z_fifa[t]) if t in z_fifa else z
            for t, z in z_propio.items()}


def cargar_partidos_elo(path: str = CSV_ELO) -> list[dict]:
    """Lee el CSV histórico (mismas columnas martj42) incluyendo `tournament`,
    ordenado por fecha ascendente."""
    partidos = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        partidos.append({
            "home": r["home_team"], "away": r["away_team"],
            "gl": int(r["home_score"]), "gv": int(r["away_score"]),
            "fecha": r["date"],
            "neutral": r["neutral"].strip().upper() == "TRUE",
            "tournament": r["tournament"],
        })
    partidos.sort(key=lambda m: m["fecha"])
    return partidos


def cargar_z_fifa(path: str = FIFA_CSV) -> dict[str, float] | None:
    """z-scores del ranking FIFA, o None si no hay archivo (el blend es opcional).
    Espera columnas `team,points` (snapshot más reciente, nombres ya en el
    espacio martj42 — el casado se hace al generar el archivo, Task 6)."""
    if not os.path.exists(path):
        return None
    puntos = {r["team"]: float(r["points"])
              for r in csv.DictReader(open(path, encoding="utf-8"))}
    return estandarizar(puntos)
