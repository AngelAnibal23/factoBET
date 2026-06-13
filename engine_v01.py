"""
Statistical Engine v0.1 — Plain Poisson Baseline
Train: 2022 + 2023 (690 matches)
Test : 2024       (306 matches)

Formula:
  lambda_home(i,j) = avg_home * attack_home[i] * defense_away[j]
  lambda_away(i,j) = avg_away * attack_away[j] * defense_home[i]

Where:
  attack_home[i]  = (goals scored by i at home / game)  / avg_home
  defense_away[j] = (goals conceded by j away  / game)  / avg_home
  attack_away[j]  = (goals scored by j away    / game)  / avg_away
  defense_home[i] = (goals conceded by i at home/ game) / avg_away

Output: Brier Score on 2024 holdout (target < 0.25)
"""

import os
import numpy as np
from scipy.stats import poisson
from supabase import create_client
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
MAX_GOALS = 10


# ── Supabase load ─────────────────────────────────────────────────────────────

def load_matches(sb, temporadas):
    rows = (
        sb.table("partidos")
        .select("equipo_local_id, equipo_visitante_id, goles_local, goles_visitante, resultado, temporada")
        .in_("temporada", temporadas)
        .eq("estado", "FINISHED")
        .execute()
        .data
    )
    return [r for r in rows if r["goles_local"] is not None and r["goles_visitante"] is not None]


def load_team_names(sb):
    rows = sb.table("equipos").select("id, nombre_oficial").execute().data
    return {r["id"]: r["nombre_oficial"] for r in rows}


# ── Poisson probability matrix ────────────────────────────────────────────────

def match_probs(lh, la):
    """P(home win), P(draw), P(away win) from Poisson lambdas."""
    home_pmf = [poisson.pmf(g, lh) for g in range(MAX_GOALS + 1)]
    away_pmf = [poisson.pmf(g, la) for g in range(MAX_GOALS + 1)]

    p_home = p_draw = p_away = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = home_pmf[i] * away_pmf[j]
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p

    total = p_home + p_draw + p_away
    return p_home / total, p_draw / total, p_away / total


# ── Model class ───────────────────────────────────────────────────────────────

class PoissonV01:

    def fit(self, matches):
        home_goals = [m["goles_local"] for m in matches]
        away_goals = [m["goles_visitante"] for m in matches]
        self.avg_home = np.mean(home_goals)
        self.avg_away = np.mean(away_goals)

        stats = defaultdict(lambda: {
            "scored_home": [], "conceded_home": [],
            "scored_away": [], "conceded_away": [],
        })

        for m in matches:
            h = m["equipo_local_id"]
            a = m["equipo_visitante_id"]
            gh = m["goles_local"]
            ga = m["goles_visitante"]
            stats[h]["scored_home"].append(gh)
            stats[h]["conceded_home"].append(ga)
            stats[a]["scored_away"].append(ga)
            stats[a]["conceded_away"].append(gh)

        self.params = {}
        for team, s in stats.items():
            def safe_mean(lst, fallback):
                return np.mean(lst) if lst else fallback

            self.params[team] = {
                "attack_home":  safe_mean(s["scored_home"],   self.avg_home) / self.avg_home,
                "defense_home": safe_mean(s["conceded_home"], self.avg_away) / self.avg_away,
                "attack_away":  safe_mean(s["scored_away"],   self.avg_away) / self.avg_away,
                "defense_away": safe_mean(s["conceded_away"], self.avg_home) / self.avg_home,
                "n_home": len(s["scored_home"]),
                "n_away": len(s["scored_away"]),
            }

    def lambdas(self, home_id, away_id):
        ph = self.params.get(home_id, {"attack_home": 1.0, "defense_home": 1.0})
        pa = self.params.get(away_id, {"attack_away": 1.0, "defense_away": 1.0})
        lh = self.avg_home * ph["attack_home"]  * pa["defense_away"]
        la = self.avg_away * pa["attack_away"]  * ph["defense_home"]
        return lh, la

    def predict(self, home_id, away_id):
        lh, la = self.lambdas(home_id, away_id)
        return match_probs(lh, la)


# ── Brier Score ───────────────────────────────────────────────────────────────

def brier_score(predictions):
    """
    Multi-class Brier Score normalizado a [0, 1].
    Formula: sum((p_i - o_i)^2) / 2  para los 3 outcomes.
    Naive baseline (1/3, 1/3, 1/3) = 0.333
    Buen modelo de apuestas europeo: ~0.19-0.23
    Target Helpbetor v0.1: < 0.25
    """
    total = 0.0
    for ph, pd, pa, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (ph - o_h)**2 + (pd - o_d)**2 + (pa - o_a)**2
    return (total / len(predictions)) / 2


def brier_naive(predictions):
    """Baseline: always predict (1/3, 1/3, 1/3). Should be ~0.333."""
    total = 0.0
    for _, _, _, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (1/3 - o_h)**2 + (1/3 - o_d)**2 + (1/3 - o_a)**2
    return (total / len(predictions)) / 2


# ── Calibration check ─────────────────────────────────────────────────────────

def calibration_report(predictions):
    """Groups predictions by probability bucket and checks actual rates."""
    buckets = defaultdict(lambda: {"n": 0, "hits": 0})

    for ph, pd, pa, result in predictions:
        for prob, outcome in [(ph, "HOME"), (pd, "DRAW"), (pa, "AWAY")]:
            bucket = f"{int(prob*10)*10}-{int(prob*10)*10+10}%"
            buckets[bucket]["n"] += 1
            if result == outcome:
                buckets[bucket]["hits"] += 1

    print(f"\n  {'Bucket':<12} {'Predicted':>10} {'Actual':>10} {'N':>6}")
    print(f"  {'-'*42}")
    for bucket in sorted(buckets):
        b = buckets[bucket]
        if b["n"] == 0:
            continue
        predicted_mid = (int(bucket.split("-")[0]) + 5) / 100
        actual = b["hits"] / b["n"]
        flag = "  <-- overestimating" if actual < predicted_mid - 0.08 else ""
        flag = "  <-- underestimating" if actual > predicted_mid + 0.08 else flag
        print(f"  {bucket:<12} {predicted_mid:>9.0%} {actual:>9.1%} {b['n']:>6}{flag}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*55)
    print("HELPBETOR — MOTOR ESTADISTICO v0.1 (Plain Poisson)")
    print("="*55)

    sb = create_client(SUPA_URL, SUPA_KEY)
    names = load_team_names(sb)

    print("\n[1/4] Loading training data (2022+2023)...")
    train = load_matches(sb, ["2022", "2023"])
    print(f"  {len(train)} matches loaded")

    print("\n[2/4] Loading test data (2024)...")
    test = load_matches(sb, ["2024"])
    print(f"  {len(test)} matches loaded")

    print("\n[3/4] Fitting Poisson model...")
    model = PoissonV01()
    model.fit(train)
    print(f"  League avg goals at home : {model.avg_home:.3f}")
    print(f"  League avg goals away    : {model.avg_away:.3f}")
    print(f"  Home advantage ratio     : {model.avg_home / model.avg_away:.3f}x")
    print(f"  Teams with parameters    : {len(model.params)}")

    print("\n  Top 5 teams by attack_home:")
    sorted_att = sorted(model.params.items(), key=lambda x: x[1]["attack_home"], reverse=True)[:5]
    for tid, p in sorted_att:
        print(f"    {names.get(tid,'?'):<28} attack_home={p['attack_home']:.3f}  (n={p['n_home']})")

    print("\n  Top 5 teams by defense_away (lower = better defense):")
    sorted_def = sorted(model.params.items(), key=lambda x: x[1]["defense_away"])[:5]
    for tid, p in sorted_def:
        print(f"    {names.get(tid,'?'):<28} defense_away={p['defense_away']:.3f}  (n={p['n_away']})")

    print("\n[4/4] Evaluating on 2024 holdout...")
    preds = []
    skipped = 0
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            skipped += 1
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        preds.append((ph, pd, pa, m["resultado"]))

    print(f"  Matches evaluated: {len(preds)} (skipped: {skipped})")

    bs = brier_score(preds)
    bs_naive = brier_naive(preds)
    target = 0.25
    status = "PASS" if bs < target else "CERCA — v0.2 deberia cruzar el umbral"
    print(f"\n  Brier Score naive    : {bs_naive:.4f}  (siempre 1/3, 1/3, 1/3)")
    print(f"  Brier Score v0.1     : {bs:.4f}  (target < {target})  [{status}]")
    print(f"  Mejora vs naive      : {(bs_naive - bs):.4f}  ({(bs_naive-bs)/bs_naive*100:.1f}% mejor)")

    print("\n  Calibration (does model confidence match reality?):")
    calibration_report(preds)

    print("\n  Sample predictions (5 matches from 2024):")
    print(f"  {'Home':<24} {'Away':<24} {'P(H)':>6} {'P(D)':>6} {'P(A)':>6} {'Real':>6}")
    print(f"  {'-'*74}")
    for m in test[:5]:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        home_name = names.get(m["equipo_local_id"], "?")[:23]
        away_name = names.get(m["equipo_visitante_id"], "?")[:23]
        print(f"  {home_name:<24} {away_name:<24} {ph:>5.1%} {pd:>5.1%} {pa:>5.1%} {m['resultado']:>6}")

    print("\n" + "="*55)
    print(f"RESULTADO v0.1: Brier Score = {bs:.4f}  |  Naive = {bs_naive:.4f}")
    if bs < target:
        print("PASS: supera el umbral. Listo para v0.2 (Dixon-Coles).")
    else:
        print(f"CERCA: {bs:.4f} vs target {target}. v0.2 Dixon-Coles deberia cruzarlo.")
    print("="*55)

    return bs, bs_naive, model


if __name__ == "__main__":
    main()
