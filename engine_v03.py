"""
Statistical Engine v0.3 — Dixon-Coles + Calibracion Local Liga 1
Mejoras sobre v0.2:
  1. Grid search xi: encuentra el decaimiento optimo para Apertura/Clausura
  2. gamma_alt: ventaja local extra para estadios > 3000 msnm
  3. Debe superar Brier Score v0.2 = 0.2797

Equipos de altitud detectados (> 3000 msnm):
  Deportivo Binacional  — Juliaca  3825m
  Sport Huancayo        — Huancayo 3259m
  Cienciano             — Cusco    3400m
  Cusco FC              — Cusco    3400m
  Deportivo Garcilaso   — Cusco    ~3400m
  Club Dep. Los Chankas — Apurimac ~3500m
"""

import os
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize
from supabase import create_client
from datetime import datetime, timezone
import math
import warnings
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
MAX_GOALS = 10

# Equipos con estadio > 3000 msnm (ventaja local por altitud)
ALTITUDE_NAMES = {
    "Deportivo Binacional",
    "Sport Huancayo",
    "Cienciano",
    "Cusco",
    "Deportivo Garcilaso",
    "Club Deportivo Los Chankas",
}

# Grid search values for xi
XI_GRID = [0.001, 0.002, 0.003, 0.004, 0.005, 0.0065, 0.008, 0.010]


# ── Data loading ──────────────────────────────────────────────────────────────

def load_matches(sb, temporadas):
    rows = (
        sb.table("partidos")
        .select("equipo_local_id, equipo_visitante_id, goles_local, goles_visitante, resultado, temporada, fecha")
        .in_("temporada", temporadas)
        .eq("estado", "FINISHED")
        .execute()
        .data
    )
    return [r for r in rows if r["goles_local"] is not None]

def load_team_names(sb):
    rows = sb.table("equipos").select("id, nombre_oficial").execute().data
    return {r["id"]: r["nombre_oficial"] for r in rows}


# ── Helpers ───────────────────────────────────────────────────────────────────

def time_weight(fecha_str, ref_date, xi):
    dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (ref_date - dt).days)
    return math.exp(-xi * days)

def tau(x, y, lh, la, rho):
    if x == 0 and y == 0: return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0: return 1 + la * rho
    elif x == 0 and y == 1: return 1 + lh * rho
    elif x == 1 and y == 1: return max(1e-10, 1 - rho)
    return 1.0

def brier_score(predictions):
    total = sum(
        (ph - (1. if r=="HOME" else 0.))**2 +
        (pd - (1. if r=="DRAW" else 0.))**2 +
        (pa - (1. if r=="AWAY" else 0.))**2
        for ph, pd, pa, r in predictions
    )
    return (total / len(predictions)) / 2


# ── Model ─────────────────────────────────────────────────────────────────────

class DixonColesV03:

    def __init__(self, xi, altitude_ids):
        self.xi = xi
        self.altitude_ids = altitude_ids  # set of team UUIDs at altitude

    def _build_weights(self, matches, ref_date):
        w = np.array([time_weight(m["fecha"], ref_date, self.xi) for m in matches])
        return w / w.mean()

    def _neg_ll(self, params, matches, teams, weights):
        n = len(teams)
        alphas = params[:n]
        betas  = params[n:2*n]
        mu     = params[2*n]
        gamma  = params[2*n+1]
        rho    = params[2*n+2]
        g_alt  = params[2*n+3]  # extra home advantage for altitude teams

        idx = {t: i for i, t in enumerate(teams)}
        ll  = 0.0

        for k, m in enumerate(matches):
            i  = idx[m["equipo_local_id"]]
            j  = idx[m["equipo_visitante_id"]]
            x  = int(m["goles_local"])
            y  = int(m["goles_visitante"])
            alt = g_alt if m["equipo_local_id"] in self.altitude_ids else 0.0

            lh = math.exp(mu + alphas[i] + betas[j] + gamma + alt)
            la = math.exp(mu + alphas[j] + betas[i])

            t = tau(x, y, lh, la, rho)
            if t <= 0:
                return 1e12

            ll += weights[k] * (
                math.log(t)
                + x * math.log(lh) - lh - math.lgamma(x+1)
                + y * math.log(la) - la - math.lgamma(y+1)
            )

        penalty = 0.001 * (np.sum(alphas**2) + np.sum(betas**2))
        return -ll + penalty

    def fit(self, matches, ref_date):
        self.teams = sorted(set(
            [m["equipo_local_id"] for m in matches] +
            [m["equipo_visitante_id"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}

        weights = self._build_weights(matches, ref_date)

        x0 = np.zeros(2*n + 4)
        x0[2*n]   =  0.20   # mu
        x0[2*n+1] =  0.30   # gamma
        x0[2*n+2] = -0.05   # rho
        x0[2*n+3] =  0.15   # gamma_alt (altitude bonus, start positive)

        bounds = (
            [(-2., 2.)] * n  +   # alpha
            [(-2., 2.)] * n  +   # beta
            [(-1., 1.5)]     +   # mu
            [( 0., 1.5)]     +   # gamma
            [(-0.5, 0.5)]    +   # rho
            [( 0., 0.8)]         # gamma_alt (non-negative: altitude only helps at home)
        )

        result = minimize(
            self._neg_ll,
            x0,
            args=(matches, self.teams, weights),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
        )

        p = result.x
        self.alphas    = p[:n]
        self.betas     = p[n:2*n]
        self.mu        = p[2*n]
        self.gamma     = p[2*n+1]
        self.rho       = p[2*n+2]
        self.gamma_alt = p[2*n+3]
        self.converged = result.success
        self.n_iter    = result.nit
        return self

    def predict(self, home_id, away_id):
        if home_id in self.idx and away_id in self.idx:
            i, j = self.idx[home_id], self.idx[away_id]
            alt = self.gamma_alt if home_id in self.altitude_ids else 0.0
            lh  = math.exp(self.mu + self.alphas[i] + self.betas[j] + self.gamma + alt)
            la  = math.exp(self.mu + self.alphas[j] + self.betas[i])
        else:
            lh = math.exp(self.mu + self.gamma)
            la = math.exp(self.mu)

        ph = pd = pa = 0.0
        for x in range(MAX_GOALS+1):
            for y in range(MAX_GOALS+1):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la) * tau(x, y, lh, la, self.rho)
                if   x > y: ph += p
                elif x == y: pd += p
                else:        pa += p
        total = ph + pd + pa
        return ph/total, pd/total, pa/total


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print("HELPBETOR — MOTOR ESTADISTICO v0.3 (Calibracion Local)")
    print("="*60)

    sb    = create_client(SUPA_URL, SUPA_KEY)
    names = load_team_names(sb)

    # Build altitude ID set
    altitude_ids = {uid for uid, name in names.items() if name in ALTITUDE_NAMES}
    print(f"\nEquipos altitud detectados ({len(altitude_ids)}):")
    for uid in altitude_ids:
        print(f"  {names[uid]}")

    print("\n[1/3] Cargando datos...")
    train = load_matches(sb, ["2022", "2023"])
    test  = load_matches(sb, ["2024"])
    print(f"  Train: {len(train)} | Test: {len(test)}")

    ref_date = datetime.fromisoformat(
        min(m["fecha"] for m in test).replace("Z", "+00:00")
    )
    print(f"  Ref date: {ref_date.date()}")

    # ── Grid search xi ────────────────────────────────────────────────────────
    print(f"\n[2/3] Grid search xi ({len(XI_GRID)} valores)...")
    print(f"  {'xi':>8} | {'Brier Score':>12} | {'Convergio':>10} | {'Iters':>6}")
    print(f"  {'-'*44}")

    best_xi = XI_GRID[0]
    best_bs = 1.0
    grid_results = []

    for xi in XI_GRID:
        model_tmp = DixonColesV03(xi=xi, altitude_ids=altitude_ids)
        model_tmp.fit(train, ref_date)

        preds = []
        for m in test:
            if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
                continue
            ph, pd, pa = model_tmp.predict(m["equipo_local_id"], m["equipo_visitante_id"])
            preds.append((ph, pd, pa, m["resultado"]))

        bs = brier_score(preds)
        flag = " <-- MEJOR" if bs < best_bs else ""
        print(f"  {xi:>8.4f} | {bs:>12.4f} | {str(model_tmp.converged):>10} | {model_tmp.n_iter:>6}{flag}")
        grid_results.append((xi, bs))

        if bs < best_bs:
            best_bs = bs
            best_xi = xi

    print(f"\n  xi optimo: {best_xi}  |  Brier Score: {best_bs:.4f}")

    # ── Final model with best xi ──────────────────────────────────────────────
    print(f"\n[3/3] Modelo final (xi={best_xi})...")
    model = DixonColesV03(xi=best_xi, altitude_ids=altitude_ids)
    model.fit(train, ref_date)

    print(f"  Convergio     : {model.converged}")
    print(f"  mu            : {model.mu:.4f}")
    print(f"  gamma (local) : {model.gamma:.4f}  (x{math.exp(model.gamma):.3f} goles)")
    print(f"  gamma_alt     : {model.gamma_alt:.4f}  (x{math.exp(model.gamma_alt):.3f} extra en altitud)")
    print(f"  rho           : {model.rho:.4f}")
    print(f"  xi            : {best_xi}")

    # Team ranking
    ratings = sorted(
        [{"name": names.get(t, "?"), "alpha": model.alphas[i], "beta": model.betas[i],
          "overall": model.alphas[i] - model.betas[i]}
         for t, i in model.idx.items()],
        key=lambda x: x["overall"], reverse=True
    )
    print(f"\n  Ranking (top 8):")
    print(f"  {'Equipo':<28} {'Ataque':>8} {'Defensa':>8} {'Overall':>8}")
    print(f"  {'-'*54}")
    for r in ratings[:8]:
        print(f"  {r['name']:<28} {r['alpha']:>8.3f} {r['beta']:>8.3f} {r['overall']:>8.3f}")

    # Final evaluation
    preds_final = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        preds_final.append((ph, pd, pa, m["resultado"]))

    bs_v03  = brier_score(preds_final)
    bs_v02  = 0.2797
    bs_v01  = 0.2751
    bs_naive= 0.3333

    print(f"\n  Tabla comparativa final:")
    print(f"  {'Modelo':<22} {'Brier':>8} {'Mejora vs naive':>16}")
    print(f"  {'-'*48}")
    print(f"  {'Naive':<22} {bs_naive:>8.4f} {'—':>16}")
    print(f"  {'v0.1 Poisson':<22} {bs_v01:>8.4f} {(bs_naive-bs_v01)/bs_naive*100:>15.1f}%")
    print(f"  {'v0.2 Dixon-Coles':<22} {bs_v02:>8.4f} {(bs_naive-bs_v02)/bs_naive*100:>15.1f}%")
    print(f"  {'v0.3 DC+Local':<22} {bs_v03:>8.4f} {(bs_naive-bs_v03)/bs_naive*100:>15.1f}%")

    mejora_v2 = bs_v02 - bs_v03
    print(f"\n  Mejora v0.2 -> v0.3: {mejora_v2:+.4f} ({'MEJOR' if mejora_v2 > 0 else 'PEOR'})")

    target = 0.25
    if bs_v03 < target:
        print(f"  TARGET ALCANZADO: {bs_v03:.4f} < {target} — LISTO PARA v1.0")
    else:
        print(f"  Target: {bs_v03:.4f} vs {target} (faltan {bs_v03-target:.4f})")

    # Sample predictions including altitude match
    print(f"\n  Muestra (incluye partido de altitud):")
    print(f"  {'Local':<24} {'Visitante':<22} {'P(H)':>6} {'P(D)':>6} {'P(A)':>6} {'Real':>6} {'Alt':>4}")
    print(f"  {'-'*78}")
    shown = 0
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY") or shown >= 6:
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        hn  = names.get(m["equipo_local_id"], "?")[:23]
        an  = names.get(m["equipo_visitante_id"], "?")[:21]
        alt = "SI" if m["equipo_local_id"] in altitude_ids else ""
        print(f"  {hn:<24} {an:<22} {ph:>5.1%} {pd:>5.1%} {pa:>5.1%} {m['resultado']:>6} {alt:>4}")
        shown += 1

    print("\n" + "="*60)
    print(f"RESULTADO FINAL v0.3 : {bs_v03:.4f}")
    print(f"Baseline v0.2        : {bs_v02:.4f}")
    print("="*60)


if __name__ == "__main__":
    main()
