"""
Motor Estadistico Internacional v0.1 — Dixon-Coles para selecciones.
Espejea engine_v02.py pero:
  - Ajusta desde un CSV (martj42/international_results), no Supabase.
  - La ventaja de local (gamma) solo aplica cuando neutral == False.

Train: 2018-2024 | Test: 2025+
Gate: superar al baseline ingenuo (tasas globales neutral-aware) por >= 3% relativo.
"""

import csv
import math
import warnings
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

warnings.filterwarnings("ignore")

MAX_GOALS = 10
XI = 0.004   # mismo decay que Liga 1 v0.2
CSV_PATH = "intl_results.csv"
TRAIN_HASTA = "2024-12-31"
TEST_DESDE = "2025-01-01"


# ── Loader CSV ────────────────────────────────────────────────────────────────

def cargar_csv(path=CSV_PATH):
    """Lee el CSV filtrado y devuelve la lista de partidos normalizados."""
    partidos = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        gl = int(r["home_score"])
        gv = int(r["away_score"])
        if gl > gv:
            res = "HOME"
        elif gl == gv:
            res = "DRAW"
        else:
            res = "AWAY"
        partidos.append({
            "home":      r["home_team"],
            "away":      r["away_team"],
            "gl":        gl,
            "gv":        gv,
            "fecha":     r["date"],
            "neutral":   r["neutral"].strip().upper() == "TRUE",
            "resultado": res,
        })
    return partidos


# ── Time weighting ────────────────────────────────────────────────────────────

def time_weight(fecha_str, ref_date, xi=XI):
    dt = datetime.fromisoformat(fecha_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (ref_date - dt).days)
    return math.exp(-xi * days)


# ── Dixon-Coles correction ────────────────────────────────────────────────────

def tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0:
        return 1 + la * rho
    elif x == 0 and y == 1:
        return 1 + lh * rho
    elif x == 1 and y == 1:
        return max(1e-10, 1 - rho)
    return 1.0


# ── Brier Score (normalizado 0-1) ─────────────────────────────────────────────

def brier_score(predictions):
    total = 0.0
    for ph, pd, pa, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (ph - o_h)**2 + (pd - o_d)**2 + (pa - o_a)**2
    return (total / len(predictions)) / 2


# ── Log-likelihood (gamma condicional a neutral) ──────────────────────────────

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
        i = idx[m["home"]]
        j = idx[m["away"]]
        x = m["gl"]
        y = m["gv"]

        g = 0.0 if m["neutral"] else gamma
        lh = math.exp(mu + alphas[i] + betas[j] + g)
        la = math.exp(mu + alphas[j] + betas[i])

        t = tau(x, y, lh, la, rho)
        if t <= 0:
            return 1e12

        ll += weights[k] * (
            math.log(t)
            + x * math.log(lh) - lh - math.lgamma(x + 1)
            + y * math.log(la) - la - math.lgamma(y + 1)
        )

    penalty = l2 * (np.sum(alphas**2) + np.sum(betas**2))
    return -ll + penalty


# ── Modelo Dixon-Coles internacional ──────────────────────────────────────────

class DixonColesIntl:

    def fit(self, matches, ref_date):
        self.teams = sorted(set(
            [m["home"] for m in matches] + [m["away"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}

        weights = np.array([time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()

        x0 = np.zeros(2 * n + 3)
        x0[2*n]     =  0.20   # mu
        x0[2*n + 1] =  0.30   # gamma
        x0[2*n + 2] = -0.05   # rho

        bounds = (
            [(-2.0, 2.0)] * n +
            [(-2.0, 2.0)] * n +
            [(-1.0, 1.5)] +
            [( 0.0, 1.5)] +
            [(-0.5, 0.5)]
        )

        result = minimize(
            neg_log_likelihood, x0,
            args=(matches, self.teams, weights),
            method="L-BFGS-B", bounds=bounds,
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

    def lambdas(self, home, away, neutral):
        g = 0.0 if neutral else self.gamma
        if home in self.idx and away in self.idx:
            i, j = self.idx[home], self.idx[away]
            lh = math.exp(self.mu + self.alphas[i] + self.betas[j] + g)
            la = math.exp(self.mu + self.alphas[j] + self.betas[i])
        else:
            lh = math.exp(self.mu + g)
            la = math.exp(self.mu)
        return lh, la

    def predict(self, home, away, neutral):
        lh, la = self.lambdas(home, away, neutral)
        p_home = p_draw = p_away = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la) * tau(x, y, lh, la, self.rho)
                if x > y:    p_home += p
                elif x == y: p_draw += p
                else:        p_away += p
        total = p_home + p_draw + p_away
        return p_home / total, p_draw / total, p_away / total


# ── Baseline ingenuo (tasas globales, neutral-aware) ──────────────────────────

def baseline_tasas(train):
    """Devuelve {neutral_bool: (p_home, p_draw, p_away)} con las frecuencias del train."""
    tasas = {}
    for neutral in (False, True):
        subset = [m for m in train if m["neutral"] == neutral]
        if not subset:
            tasas[neutral] = (1/3, 1/3, 1/3)
            continue
        n = len(subset)
        h = sum(1 for m in subset if m["resultado"] == "HOME") / n
        d = sum(1 for m in subset if m["resultado"] == "DRAW") / n
        a = sum(1 for m in subset if m["resultado"] == "AWAY") / n
        tasas[neutral] = (h, d, a)
    return tasas


def predecir_baseline(tasas, neutral):
    return tasas[neutral]


# ── Main: holdout temporal + gate de Brier ────────────────────────────────────

def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("\n" + "=" * 60)
    print("HELPBETOR — MOTOR INTERNACIONAL v0.1 (Dixon-Coles + neutral)")
    print("=" * 60)

    partidos = cargar_csv()
    train = [m for m in partidos if m["fecha"] <= TRAIN_HASTA]
    test  = [m for m in partidos if m["fecha"] >= TEST_DESDE]
    print(f"\nTrain (<= {TRAIN_HASTA}): {len(train)} partidos")
    print(f"Test  (>= {TEST_DESDE}): {len(test)} partidos")

    ref_date = datetime.fromisoformat(TEST_DESDE).replace(tzinfo=timezone.utc)

    print("\nAjustando Dixon-Coles internacional...")
    model = DixonColesIntl().fit(train, ref_date)
    print(f"  Convergio: {model.converged} | iteraciones: {model.n_iter}")
    print(f"  mu={model.mu:.4f}  gamma={model.gamma:.4f}  rho={model.rho:.4f}  xi={XI}")
    print(f"  Equipos en el modelo: {len(model.teams)}")

    # Predicciones del modelo
    preds_modelo = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["home"], m["away"], m["neutral"])
        preds_modelo.append((ph, pd, pa, m["resultado"]))

    # Predicciones del baseline
    tasas = baseline_tasas(train)
    preds_baseline = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = predecir_baseline(tasas, m["neutral"])
        preds_baseline.append((ph, pd, pa, m["resultado"]))

    bs_modelo = brier_score(preds_modelo)
    bs_baseline = brier_score(preds_baseline)
    mejora_rel = (bs_baseline - bs_modelo) / bs_baseline

    print("\n" + "-" * 60)
    print(f"  Brier baseline (tasas neutral-aware): {bs_baseline:.4f}")
    print(f"  Brier modelo Dixon-Coles            : {bs_modelo:.4f}")
    print(f"  Mejora relativa                     : {mejora_rel*100:+.1f}%")
    print(f"  (Referencia Liga 1 v0.2 = 0.2797)")
    print("-" * 60)

    greenlight = (bs_modelo < bs_baseline) and (mejora_rel >= 0.03)
    if greenlight:
        print("  VEREDICTO: ✅ GREENLIGHT — el modelo supera el baseline (>= 3%).")
        print("  Siguiente paso: python load_intl_to_supabase.py")
    else:
        print("  VEREDICTO: ❌ NO PASA — el modelo no aporta señal suficiente.")
        print("  NO cargar a Supabase. Reconsiderar (ponderacion por torneo, ventana).")
    print("=" * 60)

    return bs_modelo, bs_baseline, model


if __name__ == "__main__":
    main()
