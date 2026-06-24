"""Ajuste offline del modelo por-jugador + gate por métrica (goal/assist).

Lee eventos_jugador_flashscore (vía Supabase), arma registros por (jugador, partido
como titular), estima cuotas (player_model.estimar_cuotas) y valida cada métrica
contra un baseline igualitario (1/n_titulares) en un holdout temporal por Brier.
NO escribe a Supabase (eso lo hace load_player_model_to_supabase.py).

    python fit_player_model.py
"""

import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

from player_model import estimar_cuotas, PlayerModel

GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
TEST_FRAC = 0.30
LAMBDA_PROXY = 1.35   # goles esperados por equipo (proxy de liga para el gate)


def registros_desde_eventos(eventos: list[dict], titulares: dict) -> list[dict]:
    """Convierte eventos crudos + titulares en registros por (jugador, partido).

    eventos: [{event_id, equipo, player_id, player_nombre, tipo, fue_titular}].
    titulares: {(event_id, equipo): {player_id: nombre}} (todos los titulares).
    Devuelve un registro POR titular (incluye a los que no anotaron, con 0s).
    """
    goles_eq = defaultdict(int)        # (event_id, equipo) -> goles del equipo
    g = defaultdict(int)               # (event_id, player_id) -> goles
    a = defaultdict(int)               # (event_id, player_id) -> asist
    nombre_de = {}
    for e in eventos:
        key = (e["event_id"], e["player_id"])
        nombre_de[key] = e["player_nombre"]
        if e["tipo"] in ("Goal", "Penalty"):   # penal convertido = el jugador anota
            g[key] += 1
            goles_eq[(e["event_id"], e["equipo"])] += 1
        elif e["tipo"] == "Assistance":
            a[key] += 1
        # "Own goal" se ignora: no acredita al que lo metió ni a su equipo

    regs = []
    for (eid, equipo), starters in titulares.items():
        n_tit = len(starters)
        for pid, nombre in starters.items():
            key = (eid, pid)
            regs.append({
                "event_id": eid, "player_id": pid,
                "nombre": nombre_de.get(key, nombre), "equipo": equipo,
                "goles_jugador": g.get(key, 0), "asist_jugador": a.get(key, 0),
                "goles_equipo": goles_eq.get((eid, equipo), 0), "n_titulares": n_tit,
            })
    return regs


def _brier(probs, occ):
    return float(np.mean((np.asarray(probs) - np.asarray(occ, float)) ** 2))


def _gate(train, test, metrica):
    """Brier del modelo (cuotas) vs baseline (1/n_titulares) en el holdout."""
    cuotas = estimar_cuotas(train, k=K_SHRINK)
    m = PlayerModel.from_params({"metricas": [metrica], "jugadores": cuotas})
    col = "goles_jugador" if metrica == "goal" else "asist_jugador"
    probs_m, probs_b, occ = [], [], []
    for r in test:
        pid = r["player_id"]
        if m.tiene(pid, metrica):
            probs_m.append(m.prob(pid, metrica, LAMBDA_PROXY, umbral=1))
        else:
            probs_m.append(1 - np.exp(-LAMBDA_PROXY / r["n_titulares"]))
        probs_b.append(1 - np.exp(-LAMBDA_PROXY / r["n_titulares"]))
        occ.append(1.0 if r[col] >= 1 else 0.0)
    return _brier(probs_m, occ), _brier(probs_b, occ)


def _cargar(sb):
    """Eventos (con equipo canónico), titulares por (event,equipo), y fecha por event."""
    # equipo_id -> nombre canónico
    eq = {e["id"]: e["nombre"] for e in sb.table("equipos").select("id,nombre").execute().data}
    # fecha por event_id
    fecha_ev = {}
    desde, paso = 0, 1000
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,fecha").range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            fecha_ev[r["event_id"]] = r["fecha"]
        if len(chunk) < paso:
            break
        desde += paso
    # eventos por jugador
    eventos, titulares = [], defaultdict(dict)
    desde = 0
    while True:
        chunk = (sb.table("eventos_jugador_flashscore")
                 .select("event_id,equipo_id,player_id,player_nombre,tipo,fue_titular")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            equipo = eq.get(r["equipo_id"])
            if equipo is None:
                continue
            eventos.append({"event_id": r["event_id"], "equipo": equipo,
                            "player_id": r["player_id"], "player_nombre": r["player_nombre"],
                            "tipo": r["tipo"], "fue_titular": r["fue_titular"]})
            if r["fue_titular"]:
                titulares[(r["event_id"], equipo)][r["player_id"]] = r["player_nombre"]
        if len(chunk) < paso:
            break
        desde += paso
    return eventos, dict(titulares), fecha_ev


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    eventos, titulares, fecha_ev = _cargar(sb)
    regs = registros_desde_eventos(eventos, titulares)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], ""))
    corte = int(len(regs) * (1 - TEST_FRAC))
    train, test = regs[:corte], regs[corte:]

    metricas_ok = []
    print("=" * 60, "\nFIT MODELO POR-JUGADOR — gate (liga INT)\n", "=" * 60)
    for metrica in ("goal", "assist"):
        bm, bb = _gate(train, test, metrica)
        mejora = (bb - bm) / bb if bb > 0 else 0.0
        ok = bm < bb and mejora >= GATE_MIN_MEJORA
        print(f"  {metrica:6}: Brier modelo={bm:.4f} base={bb:.4f} "
              f"mejora={mejora*100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
        if ok:
            metricas_ok.append(metrica)
    cuotas_prod = estimar_cuotas(regs, k=K_SHRINK)   # producción = todos los datos
    return {"metricas": metricas_ok, "jugadores": cuotas_prod}


if __name__ == "__main__":
    main()
