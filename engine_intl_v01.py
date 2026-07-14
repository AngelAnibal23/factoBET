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
from scipy.special import gammaln
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

def precompute_matches(matches, teams, weights, a0=None, b0=None):
    """Convierte la lista de partidos a arrays numpy una sola vez.

    Los indices de equipo, goles, flag neutral y pesos son CONSTANTES durante
    toda la optimizacion (solo cambian los params), asi que se calculan aqui y
    se reutilizan en cada evaluacion de la verosimilitud.

    a0/b0: anclas del prior ELO (alpha0/beta0), una por equipo en el mismo
    orden que `teams`. None (default) = anclas en 0, comportamiento clasico.
    """
    idx = {t: i for i, t in enumerate(teams)}
    M = len(matches)
    hi = np.empty(M, dtype=np.intp)
    aj = np.empty(M, dtype=np.intp)
    x = np.empty(M, dtype=np.float64)
    y = np.empty(M, dtype=np.float64)
    not_neutral = np.empty(M, dtype=np.float64)
    for k, m in enumerate(matches):
        hi[k] = idx[m["home"]]
        aj[k] = idx[m["away"]]
        x[k] = m["gl"]
        y[k] = m["gv"]
        not_neutral[k] = 0.0 if m["neutral"] else 1.0
    n_teams = len(teams)
    if a0 is None:
        a0 = np.zeros(n_teams)
    if b0 is None:
        b0 = np.zeros(n_teams)
    return {
        "hi": hi, "aj": aj, "x": x, "y": y,
        "w": np.asarray(weights, dtype=np.float64),
        "not_neutral": not_neutral,
        "lgx": gammaln(x + 1.0),
        "lgy": gammaln(y + 1.0),
        # mascaras de los 4 casos de la correccion Dixon-Coles (resto -> tau=1)
        "m00": (x == 0) & (y == 0),
        "m10": (x == 1) & (y == 0),
        "m01": (x == 0) & (y == 1),
        "m11": (x == 1) & (y == 1),
        "a0": np.asarray(a0, dtype=np.float64),
        "b0": np.asarray(b0, dtype=np.float64),
    }


def nll_and_grad(params, pre, n, l2=0.001):
    """Verosimilitud negativa vectorizada + gradiente analitico (jac=True).

    Devuelve (nll, grad). La ventaja de local (gamma) solo se suma cuando
    not_neutral == 1.0. El gradiente exacto evita el coste del gradiente
    numerico (~2n+3 evals por paso), permitiendo que L-BFGS-B converja de
    verdad en lugar de cortarse por maxfun.

    `l2` penaliza la distancia a las anclas `pre['a0']/pre['b0']` (cero por
    defecto = comportamiento clasico).

    Layout de params/grad: [alphas(n), betas(n), mu, gamma, rho].
    """
    alphas = params[:n]
    betas  = params[n:2*n]
    mu     = params[2*n]
    gamma  = params[2*n + 1]
    rho    = params[2*n + 2]

    hi, aj = pre["hi"], pre["aj"]
    x, y, w = pre["x"], pre["y"], pre["w"]
    nn = pre["not_neutral"]

    log_lh = mu + alphas[hi] + betas[aj] + nn * gamma
    log_la = mu + alphas[aj] + betas[hi]
    lh = np.exp(log_lh)
    la = np.exp(log_la)

    m00, m10, m01, m11 = pre["m00"], pre["m10"], pre["m01"], pre["m11"]
    raw00 = 1.0 - lh * la * rho   # solo significativo donde m00
    tau_arr = np.ones_like(lh)
    tau_arr[m00] = np.maximum(1e-10, raw00[m00])
    tau_arr[m10] = 1.0 + la[m10] * rho
    tau_arr[m01] = 1.0 + lh[m01] * rho
    tau_arr[m11] = max(1e-10, 1.0 - rho)
    if np.any(tau_arr <= 0.0):
        # region infeasible (m10/m01 con tau<=0): el valor enorme hace que el
        # line search la rechace; el gradiente cero no guia mal porque domina f.
        return 1e12, np.zeros_like(params)

    # ── Valor ──
    ll = np.sum(w * (
        np.log(tau_arr)
        + x * log_lh - lh - pre["lgx"]
        + y * log_la - la - pre["lgy"]
    ))
    da = alphas - pre["a0"]
    db = betas  - pre["b0"]
    penalty = l2 * (np.dot(da, da) + np.dot(db, db))
    nll = -ll + penalty

    # ── Gradiente de log tau respecto a log_lh, log_la y rho ──
    # (d tau/d lh)*lh = d tau/d log_lh, etc. Solo los 4 casos corregidos aportan.
    inv = 1.0 / tau_arr
    dT_dloglh = np.zeros_like(lh)
    dT_dlogla = np.zeros_like(lh)
    dT_drho   = np.zeros_like(lh)

    # m00: tau = 1 - lh*la*rho (donde no esta clampeado a 1e-10)
    act00 = m00 & (raw00 > 1e-10)
    coef00 = (-lh[act00] * la[act00] * rho) * inv[act00]
    dT_dloglh[act00] = coef00
    dT_dlogla[act00] = coef00
    dT_drho[act00]   = (-lh[act00] * la[act00]) * inv[act00]

    # m10: tau = 1 + la*rho  (sin dependencia de lh)
    dT_dlogla[m10] = (la[m10] * rho) * inv[m10]
    dT_drho[m10]   = la[m10] * inv[m10]

    # m01: tau = 1 + lh*rho  (sin dependencia de la)
    dT_dloglh[m01] = (lh[m01] * rho) * inv[m01]
    dT_drho[m01]   = lh[m01] * inv[m01]

    # m11: tau = 1 - rho  (sin dependencia de lh/la)
    dT_drho[m11] = -1.0 * inv[m11]

    # ── Gradiente de la log-verosimilitud por partido ──
    # d ll/d log_lh = (x - lh) + dT/d log_lh ; idem para log_la con y, la.
    wG_lh = w * ((x - lh) + dT_dloglh)
    wG_la = w * ((y - la) + dT_dlogla)

    grad = np.empty_like(params)
    # alpha_i aparece en log_lh del local (hi) y en log_la del visitante (aj)
    grad_alpha = np.bincount(hi, wG_lh, minlength=n) + np.bincount(aj, wG_la, minlength=n)
    # beta_j aparece en log_lh (beta_aj) y en log_la (beta_hi)
    grad_beta  = np.bincount(aj, wG_lh, minlength=n) + np.bincount(hi, wG_la, minlength=n)

    # NLL = -ll + penalty  ->  signo negativo, mas derivada de la penalizacion L2
    grad[:n]      = -grad_alpha + 2.0 * l2 * da
    grad[n:2*n]   = -grad_beta  + 2.0 * l2 * db
    grad[2*n]     = -np.sum(wG_lh + wG_la)            # mu
    grad[2*n + 1] = -np.sum(wG_lh * nn)               # gamma (solo log_lh, condicional a neutral)
    grad[2*n + 2] = -np.sum(w * dT_drho)              # rho (solo via tau)
    return nll, grad


def neg_log_likelihood(params, pre, n, l2=0.001):
    """Solo el valor de la verosimilitud negativa. Delega en nll_and_grad para
    mantener una unica fuente de verdad del calculo."""
    return nll_and_grad(params, pre, n, l2)[0]


# ── Modelo Dixon-Coles internacional ──────────────────────────────────────────

class DixonColesIntl:

    @classmethod
    def from_params(cls, mu, gamma, rho, attack, defense):
        """Construye un predictor desde parametros congelados, SIN ajustar.

        Patron del Mundial (Sub-proyecto B): los params de produccion viven en
        `parametros_modelo` (Supabase) y se cargan tal cual; no se reajusta en
        cada warm_up como hace Liga 1. `attack`/`defense` son dicts
        {nombre_seleccion: valor}. Deben compartir el mismo conjunto de claves.
        """
        model = cls()
        model.teams = sorted(attack)
        model.idx = {t: i for i, t in enumerate(model.teams)}
        model.alphas = np.array([attack[t] for t in model.teams], dtype=np.float64)
        model.betas = np.array([defense[t] for t in model.teams], dtype=np.float64)
        model.mu = float(mu)
        model.gamma = float(gamma)
        model.rho = float(rho)
        model.converged = True   # cargado, no ajustado
        model.n_iter = 0
        return model

    def fit(self, matches, ref_date, elo_z=None, prior_scale=0.0, l2_prior=None):
        """Ajusta el Dixon-Coles internacional.

        elo_z: {equipo: z-score ELO} para anclar el prior (None = clasico).
        prior_scale (c): ancla alpha0=c*z, beta0=-c*z.
        l2_prior: fuerza del prior (pseudo-partidos); solo aplica si hay elo_z.
        """
        self.teams = sorted(set(
            [m["home"] for m in matches] + [m["away"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.elo_z = dict(elo_z) if elo_z else None
        self.prior_scale = float(prior_scale) if elo_z else 0.0

        weights = np.array([time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()
        if elo_z:
            z = np.array([elo_z.get(t, 0.0) for t in self.teams])
            a0, b0 = prior_scale * z, -prior_scale * z
            l2 = float(l2_prior) if l2_prior is not None else 0.001
        else:
            a0 = b0 = None
            l2 = 0.001
        pre = precompute_matches(matches, self.teams, weights, a0=a0, b0=b0)

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

        # Gradiente analitico (jac=True): cada paso cuesta 1 eval en vez de ~(2n+3),
        # asi cada iteracion es barata y L-BFGS-B converge por ftol (~3.4k iter, ~5s).
        # maxiter holgado: el corte real es la reduccion relativa de f, no el numero
        # de pasos. gtol no aplica: muchas selecciones raras quedan en sus bounds
        # (gradiente proyectado ~0, pero ||grad|| completo se mantiene > 0).
        result = minimize(
            nll_and_grad, x0,
            args=(pre, n, l2), jac=True,
            method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 20000, "ftol": 1e-12, "gtol": 1e-8},
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


def escala_c_desde_v01(model, elo_z, conteos, min_partidos=30):
    """Escala c del ancla: pendiente de la regresion alpha_hat ~ z sobre los
    equipos BIEN muestreados del fit clasico. El dato fija c; el grid solo
    decide la FUERZA del prior (l2_prior)."""
    zs, als = [], []
    for t in model.teams:
        if conteos.get(t, 0) >= min_partidos and t in elo_z:
            zs.append(elo_z[t])
            als.append(float(model.alphas[model.idx[t]]))
    zs, als = np.array(zs), np.array(als)
    dz = zs - zs.mean()
    return float(np.dot(dz, als - als.mean()) / np.dot(dz, dz))


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
