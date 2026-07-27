# fit_player_sot.py
"""Ajuste offline del modelo SoT por-jugador + gate de la métrica `sot`, por liga.

Lee eventos_sot_jugador (vía Supabase), arma registros por (jugador, partido como
titular), los separa por liga (equipo -> liga; equipos sin liga conocida se
descartan) y dentro de cada liga estima cuota_sot y valida contra un baseline
igualitario (1/n_titulares) en un holdout temporal por Brier. El lambda_sot del
equipo en el gate es la TASA REAL OBSERVADA del dataset (no un proxy), para no
repetir la miscalibración de goal/assist. Una liga con muestra insuficiente
(< MIN_REGISTROS_LIGA) se salta. NO escribe a Supabase (eso lo hace
load_player_sot_to_supabase.py).

    python fit_player_sot.py
"""
import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

from player_model import estimar_cuotas_sot, PlayerModel

GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
TEST_FRAC = 0.30
MIN_PARTIDOS = 10     # historial mínimo (titular) para publicar/evaluar un jugador
MIN_REGISTROS_LIGA = 500   # por debajo de esto el gate de una liga no dice nada


def agrupar_por_liga(regs: list[dict], liga_de_equipo: dict[str, str]) -> dict[str, list[dict]]:
    """{liga: [registros]} usando la liga del equipo. Los equipos sin liga conocida
    se descartan (mismo criterio que fit_player_model)."""
    por_liga = defaultdict(list)
    for r in regs:
        liga = liga_de_equipo.get(r["equipo"])
        if liga:
            por_liga[liga].append(r)
    return dict(por_liga)


def registros_desde_filas(filas: list[dict]) -> list[dict]:
    """filas: [{event_id, equipo, player_id, player_nombre, sot, fue_titular}].

    Devuelve un registro POR titular: {event_id, player_id, nombre, equipo,
    sot_jugador, sot_equipo, n_titulares}. sot_equipo = suma de SoT de TODO el
    equipo en ese partido (titulares + suplentes)."""
    sot_eq = defaultdict(int)            # (event_id, equipo) -> sot del equipo
    titulares = defaultdict(dict)        # (event_id, equipo) -> {pid: nombre}
    for f in filas:
        sot_eq[(f["event_id"], f["equipo"])] += f["sot"]
        if f["fue_titular"]:
            titulares[(f["event_id"], f["equipo"])][f["player_id"]] = f["player_nombre"]
    sot_jug = {(f["event_id"], f["player_id"]): f["sot"] for f in filas}

    regs = []
    for (eid, equipo), starters in titulares.items():
        n_tit = len(starters)
        for pid, nombre in starters.items():
            regs.append({
                "event_id": eid, "player_id": pid, "nombre": nombre, "equipo": equipo,
                "sot_jugador": sot_jug.get((eid, pid), 0),
                "sot_equipo": sot_eq[(eid, equipo)], "n_titulares": n_tit,
            })
    return regs


def _brier(probs, occ):
    return float(np.mean((np.asarray(probs) - np.asarray(occ, float)) ** 2))


def _lambda_sot_real(registros: list[dict]) -> float:
    """Tasa real observada de SoT por equipo-partido (media de sot_equipo sobre
    equipos-partido únicos). Es el techo del baseline y del modelo en el gate."""
    por_eq = {(r["event_id"], r["equipo"]): r["sot_equipo"] for r in registros}
    vals = list(por_eq.values())
    return float(np.mean(vals)) if vals else 0.0


def _gate(train, test, min_partidos=MIN_PARTIDOS):
    """Brier del modelo (cuota_sot) vs baseline (1/n_titulares) en el holdout.
    Solo evalúa jugadores elegibles (>= min_partidos en train)."""
    cuotas = estimar_cuotas_sot(train, k=K_SHRINK, min_partidos=min_partidos)
    m = PlayerModel.from_params({"metricas": ["sot"], "jugadores": cuotas})
    lam_sot = _lambda_sot_real(train)
    probs_m, probs_b, occ = [], [], []
    for r in test:
        pid = r["player_id"]
        if not m.tiene(pid, "sot"):
            continue
        probs_m.append(m.prob(pid, "sot", lam_sot, umbral=1))
        probs_b.append(1 - np.exp(-lam_sot / max(r["n_titulares"], 1)))
        occ.append(1.0 if r["sot_jugador"] >= 1 else 0.0)
    return _brier(probs_m, occ), _brier(probs_b, occ)


def _cargar(sb):
    """Filas de eventos_sot_jugador con equipo canónico + fecha, y el mapa
    nombre_de_equipo -> liga (para el split por liga). Pagina de a 1000."""
    ligas = {l["id"]: l["nombre"]
             for l in sb.table("ligas").select("id,nombre").execute().data}
    eq, liga_de_equipo = {}, {}
    for e in sb.table("equipos").select("id,nombre_oficial,liga_id").execute().data:
        eq[e["id"]] = e["nombre_oficial"]
        liga_de_equipo[e["nombre_oficial"]] = ligas.get(e["liga_id"])
    filas, desde, paso = [], 0, 1000
    while True:
        chunk = (sb.table("eventos_sot_jugador")
                 .select("event_id,equipo_id,player_id,player_nombre,sot,fue_titular,fecha")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            equipo = eq.get(r["equipo_id"])
            if equipo is None:
                continue
            filas.append({"event_id": r["event_id"], "equipo": equipo,
                          "player_id": r["player_id"], "player_nombre": r["player_nombre"],
                          "sot": r["sot"] or 0, "fue_titular": r["fue_titular"],
                          "fecha": r["fecha"]})
        if len(chunk) < paso:
            break
        desde += paso
    return filas, liga_de_equipo


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    filas, liga_de_equipo = _cargar(sb)
    fecha_ev = {f["event_id"]: f["fecha"] for f in filas}
    regs = registros_desde_filas(filas)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], "") or "")

    print("=" * 60, "\nFIT MODELO SoT POR-JUGADOR — gate por liga\n", "=" * 60)
    salida = {}
    for liga, regs_liga in sorted(agrupar_por_liga(regs, liga_de_equipo).items()):
        print(f"\n── Liga: {liga} ({len(regs_liga)} registros) ──")
        if len(regs_liga) < MIN_REGISTROS_LIGA:
            print(f"  muestra insuficiente (< {MIN_REGISTROS_LIGA}) — SKIP")
            continue
        corte = int(len(regs_liga) * (1 - TEST_FRAC))
        train, test = regs_liga[:corte], regs_liga[corte:]
        bm, bb = _gate(train, test)
        mejora = (bb - bm) / bb if bb > 0 else 0.0
        ok = bm < bb and mejora >= GATE_MIN_MEJORA
        print(f"  sot: Brier modelo={bm:.4f} base={bb:.4f} "
              f"mejora={mejora * 100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
        print(f"  (lambda_sot real train = {_lambda_sot_real(train):.2f}/equipo)")
        cuotas_prod = estimar_cuotas_sot(regs_liga, k=K_SHRINK, min_partidos=MIN_PARTIDOS)
        print(f"  jugadores publicables: {len(cuotas_prod)}")
        salida[liga] = {"metricas": ["sot"] if ok else [], "jugadores": cuotas_prod}
    return salida


if __name__ == "__main__":
    main()
