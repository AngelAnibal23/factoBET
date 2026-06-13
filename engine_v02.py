"""
Statistical Engine v0.2 — Dixon-Coles + Time-Weighting
Mejoras sobre v0.1:
  1. MLE joint optimization (no simple averages)
  2. Correccion rho para bajos marcadores (0-0, 1-0, 0-1, 1-1)
  3. Time-weighting: w(t) = exp(-xi * dias_desde_partido)

Parametros globales: mu, gamma, rho, xi
Parametros por equipo: alpha_i (ataque), beta_i (defensa)
log(lambda_home) = mu + alpha_i + beta_j + gamma
log(lambda_away) = mu + alpha_j + beta_i

Train: 2022 + 2023 | Test: 2024
Baseline a superar: Brier Score v0.1 = 0.2751
Target: < 0.25
"""

import os
import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize
from supabase import create_client
from datetime import datetime, timezone
from collections import defaultdict
import math
import warnings
from dotenv import load_dotenv

warnings.filterwarnings("ignore")
load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
MAX_GOALS = 10
XI = 0.004  # decay rate — longer half-life than European default (0.0065) for Apertura/Clausura


# ── Supabase ──────────────────────────────────────────────────────────────────

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


# ── Time weighting ────────────────────────────────────────────────────────────

def time_weight(fecha_str, ref_date, xi=XI):
    dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (ref_date - dt).days)
    return math.exp(-xi * days)


# ── Dixon-Coles correction ────────────────────────────────────────────────────

def tau(x, y, lh, la, rho):
    """Correction factor for low-scoring outcomes."""
    if x == 0 and y == 0:
        return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0:
        return 1 + la * rho
    elif x == 0 and y == 1:
        return 1 + lh * rho
    elif x == 1 and y == 1:
        return max(1e-10, 1 - rho)
    return 1.0


# ── Log-likelihood ────────────────────────────────────────────────────────────

def neg_log_likelihood(params, matches, teams, weights, l2=0.001):
    n = len(teams)
    alphas = params[:n]
    betas  = params[n:2*n]
    mu     = params[2*n]
    gamma  = params[2*n + 1]
    rho    = params[2*n + 2]

    idx = {t: i for i, t in enumerate(teams)}
    ll  = 0.0

    for k, m in enumerate(matches):
        i = idx[m["equipo_local_id"]]
        j = idx[m["equipo_visitante_id"]]
        x = int(m["goles_local"])
        y = int(m["goles_visitante"])

        lh = math.exp(mu + alphas[i] + betas[j] + gamma)
        la = math.exp(mu + alphas[j] + betas[i])

        t  = tau(x, y, lh, la, rho)
        if t <= 0:
            return 1e12

        ll += weights[k] * (
            math.log(t)
            + x * math.log(lh) - lh - math.lgamma(x + 1)
            + y * math.log(la) - la - math.lgamma(y + 1)
        )

    # L2 regularization to handle identifiability
    penalty = l2 * (np.sum(alphas**2) + np.sum(betas**2))
    return -ll + penalty


# ── Dixon-Coles model ─────────────────────────────────────────────────────────

class DixonColesV02:

    def fit(self, matches, ref_date):
        self.teams = sorted(set(
            [m["equipo_local_id"] for m in matches] +
            [m["equipo_visitante_id"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}

        weights = np.array([time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()  # normalize so scale doesn't affect rho

        x0 = np.zeros(2 * n + 3)
        x0[2*n]     =  0.20   # mu
        x0[2*n + 1] =  0.30   # gamma (home advantage)
        x0[2*n + 2] = -0.05   # rho (low-score correction, usually small negative)

        bounds = (
            [(-2.0,  2.0)] * n   +   # alpha
            [(-2.0,  2.0)] * n   +   # beta
            [(-1.0,  1.5)]       +   # mu
            [( 0.0,  1.5)]       +   # gamma >= 0
            [(-0.5,  0.5)]           # rho
        )

        result = minimize(
            neg_log_likelihood,
            x0,
            args=(matches, self.teams, weights),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
        )

        p = result.x
        self.alphas = p[:n]
        self.betas  = p[n:2*n]
        self.mu     = p[2*n]
        self.gamma  = p[2*n + 1]
        self.rho    = p[2*n + 2]
        self.converged = result.success
        self.n_iter = result.nit
        return self

    def lambdas(self, home_id, away_id):
        if home_id in self.idx and away_id in self.idx:
            i, j = self.idx[home_id], self.idx[away_id]
            lh = math.exp(self.mu + self.alphas[i] + self.betas[j] + self.gamma)
            la = math.exp(self.mu + self.alphas[j] + self.betas[i])
        else:
            lh = math.exp(self.mu + self.gamma)
            la = math.exp(self.mu)
        return lh, la

    def predict(self, home_id, away_id):
        lh, la = self.lambdas(home_id, away_id)
        p_home = p_draw = p_away = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la) * tau(x, y, lh, la, self.rho)
                if x > y:   p_home += p
                elif x == y: p_draw += p
                else:        p_away += p
        total = p_home + p_draw + p_away
        return p_home / total, p_draw / total, p_away / total


# ── Brier Score (normalized 0-1) ──────────────────────────────────────────────

def brier_score(predictions):
    total = 0.0
    for ph, pd, pa, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (ph - o_h)**2 + (pd - o_d)**2 + (pa - o_a)**2
    return (total / len(predictions)) / 2


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*58)
    print("HELPBETOR — MOTOR ESTADISTICO v0.2 (Dixon-Coles)")
    print("="*58)

    sb       = create_client(SUPA_URL, SUPA_KEY)
    names    = load_team_names(sb)

    print("\n[1/4] Cargando datos...")
    train = load_matches(sb, ["2022", "2023"])
    test  = load_matches(sb, ["2024"])
    print(f"  Train (2022+2023): {len(train)} partidos")
    print(f"  Test  (2024)     : {len(test)} partidos")

    # ref_date = primer partido de 2024 (limite del entrenamiento)
    fechas_test = [m["fecha"] for m in test]
    ref_date = datetime.fromisoformat(
        min(fechas_test).replace("Z", "+00:00")
    )
    print(f"  Ref date (inicio 2024): {ref_date.date()}")

    print(f"\n[2/4] Ajustando Dixon-Coles (xi={XI}, MLE + L-BFGS-B)...")
    model = DixonColesV02()
    model.fit(train, ref_date)

    print(f"  Convergio: {model.converged}")
    print(f"  Iteraciones: {model.n_iter}")
    print(f"\n  Parametros globales:")
    print(f"    mu    = {model.mu:.4f}  (tasa base de goles)")
    print(f"    gamma = {model.gamma:.4f}  (ventaja local — exp={math.exp(model.gamma):.3f}x goles extra)")
    print(f"    rho   = {model.rho:.4f}  (correccion marcadores bajos)")
    print(f"    xi    = {XI}    (decaimiento temporal)")

    # Team rankings
    team_ratings = []
    for tid in model.teams:
        i = model.idx[tid]
        team_ratings.append({
            "name":    names.get(tid, tid[:8]),
            "alpha":   model.alphas[i],
            "beta":    model.betas[i],
            "overall": model.alphas[i] - model.betas[i],
        })
    team_ratings.sort(key=lambda x: x["overall"], reverse=True)

    print(f"\n  Ranking equipos (ataque - defensa, mayor = mejor):")
    print(f"  {'Equipo':<28} {'Ataque':>8} {'Defensa':>8} {'Overall':>8}")
    print(f"  {'-'*54}")
    for t in team_ratings[:8]:
        print(f"  {t['name']:<28} {t['alpha']:>8.3f} {t['beta']:>8.3f} {t['overall']:>8.3f}")

    print(f"\n[3/4] Evaluando en holdout 2024...")
    preds_v02 = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        preds_v02.append((ph, pd, pa, m["resultado"]))

    bs_v02 = brier_score(preds_v02)
    bs_v01 = 0.2751  # resultado previo
    bs_naive = 0.3333

    print(f"\n  {'Modelo':<20} {'Brier Score':>12} {'vs naive':>10}")
    print(f"  {'-'*44}")
    print(f"  {'Naive (1/3,1/3,1/3)':<20} {bs_naive:>12.4f} {'—':>10}")
    print(f"  {'v0.1 Poisson':<20} {bs_v01:>12.4f} {(bs_naive-bs_v01)/bs_naive*100:>9.1f}%")
    print(f"  {'v0.2 Dixon-Coles':<20} {bs_v02:>12.4f} {(bs_naive-bs_v02)/bs_naive*100:>9.1f}%")
    mejora = bs_v01 - bs_v02
    print(f"\n  Mejora v0.1 -> v0.2: {mejora:+.4f} ({'MEJOR' if mejora > 0 else 'PEOR'})")

    target = 0.25
    if bs_v02 < target:
        print(f"  TARGET ALCANZADO: {bs_v02:.4f} < {target}")
    else:
        print(f"  Target no alcanzado aun: {bs_v02:.4f} (faltan {bs_v02-target:.4f})")

    print(f"\n[4/4] Muestra de predicciones (5 partidos 2024):")
    print(f"  {'Local':<24} {'Visitante':<24} {'P(H)':>6} {'P(D)':>6} {'P(A)':>6} {'Real':>6}")
    print(f"  {'-'*76}")
    for m in test[:5]:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        hn = names.get(m["equipo_local_id"], "?")[:23]
        an = names.get(m["equipo_visitante_id"], "?")[:23]
        print(f"  {hn:<24} {an:<24} {ph:>5.1%} {pd:>5.1%} {pa:>5.1%} {m['resultado']:>6}")

    print("\n" + "="*58)
    print(f"RESULTADO v0.2: Brier Score = {bs_v02:.4f}")
    print(f"Baseline v0.1            = {bs_v01:.4f}")
    print("="*58)

    return bs_v02, model


if __name__ == "__main__":
    main()
