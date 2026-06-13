"""
Analyzer — Phase 1
Receives a ValidatedParlay from validator.py and produces the full statistical analysis:

  1. Loads all finished matches from Supabase (2022-2024) and fits Dixon-Coles v0.2
  2. For each selection computes:
       - prob_modelo   (per market type using fitted lambdas)
       - prob_implicita_adj  (bookmaker-margin-adjusted)
       - edge          (prob_modelo - prob_implicita_adj)
       - kelly_fraccion  (fractional Kelly at 20%, only when edge > 0)
       - nivel_cobertura (ALTA/MEDIA/BAJA/NULA)
  3. Detects same-match correlations
  4. Assigns overall parlay confidence level (ALTA/MEDIA/BAJA)

Returns ParlayAnalysis — ready for the LLM narrative in main.py.
"""

import os
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson
from supabase import create_client
from dotenv import load_dotenv

from validator import ValidatedParlay, ValidatedSelection

warnings.filterwarnings("ignore")
load_dotenv()

MAX_GOALS      = 10
XI             = 0.004   # optimal decay rate found in v0.2
KELLY_FRACTION = 0.20    # always fractional, never full Kelly

# Typical overround by bookmaker (used for margin removal)
BOOKMAKER_MARGINS = {
    "betano":   0.06,
    "inkabet":  0.08,
    "codere":   0.07,
    "betsafe":  0.07,
    "bet365":   0.065,
    "apuesta total": 0.075,
}
DEFAULT_MARGIN = 0.07

# Min matches in DB for coverage level
COVERAGE_ALTA  = 15
COVERAGE_MEDIA = 10

MODEL_TTL_HOURS = 6   # refit model every 6 hours

KNOWN_CORRELATIONS = [
    {"m1": "home",  "m2": "over",  "tipo": "POSITIVA_ALTA",   "nota": "Las victorias locales amplias elevan los goles totales."},
    {"m1": "yes",   "m2": "over",  "tipo": "POSITIVA_MUY_ALTA","nota": "BTTS exige >=2 goles; over 2.5 exige >=3. Alta correlacion."},
    {"m1": "draw",  "m2": "under", "tipo": "POSITIVA_ALTA",   "nota": "Los empates suelen ser de pocos goles."},
    {"m1": "home",  "m2": "yes",   "tipo": "MEDIA",           "nota": "Depende del perfil atacante del equipo."},
    {"m1": "away",  "m2": "under", "tipo": "POSITIVA_MEDIA",  "nota": "Las victorias visitantes son a menudo por la minima."},
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SelectionAnalysis:
    equipo_local:          str
    equipo_visitante:      Optional[str]
    equipo_local_id:       str
    equipo_visitante_id:   Optional[str]
    mercado:               str
    seleccion:             str
    cuota:                 float
    linea:                 Optional[float]
    prob_implicita:        float
    prob_implicita_adj:    float
    prob_modelo:           Optional[float]   # None for exotic/uncovered
    lambda_home:           Optional[float]
    lambda_away:           Optional[float]
    edge:                  Optional[float]
    kelly_fraccion:        Optional[float]   # None if edge <= 0 or no model
    nivel_cobertura:       str               # ALTA/MEDIA/BAJA/NULA
    mercado_exotico:       bool
    n_partidos_local:      int
    n_partidos_visitante:  int
    alertas:               list[str] = field(default_factory=list)


@dataclass
class Correlacion:
    sel_idx_1:   int
    sel_idx_2:   int
    tipo:        str
    nota:        str


@dataclass
class ParlayAnalysis:
    selecciones:          list[SelectionAnalysis]
    prob_parlay_modelo:   Optional[float]   # product of prob_modelo (non-exotic only)
    prob_parlay_impl:     Optional[float]   # product of prob_implicita_adj
    cuota_total:          Optional[float]
    casa_apuestas:        Optional[str]
    nivel_confianza:      str
    razones_confianza:    list[str]
    correlaciones:        list[Correlacion]
    version_modelo:       str = "v0.2"
    margen_aplicado:      float = DEFAULT_MARGIN


# ── Dixon-Coles v0.2 (same as engine_v02.py) ─────────────────────────────────

def _time_weight(fecha_str: str, ref_date: datetime, xi: float = XI) -> float:
    dt = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return math.exp(-xi * max(0, (ref_date - dt).days))


def _tau(x, y, lh, la, rho):
    if   x == 0 and y == 0: return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0: return 1 + la * rho
    elif x == 0 and y == 1: return 1 + lh * rho
    elif x == 1 and y == 1: return max(1e-10, 1 - rho)
    return 1.0


def _neg_ll(params, matches, teams, weights, l2=0.001):
    n      = len(teams)
    alphas = params[:n]
    betas  = params[n:2*n]
    mu     = params[2*n]
    gamma  = params[2*n+1]
    rho    = params[2*n+2]
    idx    = {t: i for i, t in enumerate(teams)}
    ll     = 0.0
    for k, m in enumerate(matches):
        i  = idx[m["equipo_local_id"]]
        j  = idx[m["equipo_visitante_id"]]
        x  = int(m["goles_local"])
        y  = int(m["goles_visitante"])
        lh = math.exp(mu + alphas[i] + betas[j] + gamma)
        la = math.exp(mu + alphas[j] + betas[i])
        t  = _tau(x, y, lh, la, rho)
        if t <= 0:
            return 1e12
        ll += weights[k] * (
            math.log(t)
            + x * math.log(lh) - lh - math.lgamma(x+1)
            + y * math.log(la) - la - math.lgamma(y+1)
        )
    penalty = l2 * (np.sum(alphas**2) + np.sum(betas**2))
    return -ll + penalty


class DixonColesModel:
    """Fitted Dixon-Coles v0.2 model."""

    def fit(self, matches: list[dict], ref_date: datetime) -> "DixonColesModel":
        self.teams = sorted(set(
            [m["equipo_local_id"] for m in matches] +
            [m["equipo_visitante_id"] for m in matches]
        ))
        n        = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}

        weights  = np.array([_time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()

        x0 = np.zeros(2*n + 3)
        x0[2*n] = 0.20; x0[2*n+1] = 0.30; x0[2*n+2] = -0.05

        bounds = (
            [(-2., 2.)] * n + [(-2., 2.)] * n +
            [(-1., 1.5)] + [(0., 1.5)] + [(-0.5, 0.5)]
        )
        result = minimize(
            _neg_ll, x0,
            args=(matches, self.teams, weights),
            method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
        )
        p            = result.x
        self.alphas  = p[:n]
        self.betas   = p[n:2*n]
        self.mu      = p[2*n]
        self.gamma   = p[2*n+1]
        self.rho     = p[2*n+2]
        self.converged = result.success
        return self

    def lambdas(self, home_id: str, away_id: str) -> tuple[float, float]:
        if home_id in self.idx and away_id in self.idx:
            i, j = self.idx[home_id], self.idx[away_id]
            lh = math.exp(self.mu + self.alphas[i] + self.betas[j] + self.gamma)
            la = math.exp(self.mu + self.alphas[j] + self.betas[i])
        else:
            lh = math.exp(self.mu + self.gamma)
            la = math.exp(self.mu)
        return lh, la

    def predict_1x2(self, lh: float, la: float) -> tuple[float, float, float]:
        ph = pd = pa = 0.0
        for x in range(MAX_GOALS+1):
            for y in range(MAX_GOALS+1):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la) * _tau(x, y, lh, la, self.rho)
                if   x > y:  ph += p
                elif x == y: pd += p
                else:        pa += p
        total = ph + pd + pa
        return ph/total, pd/total, pa/total


# ── Market probability calculators ───────────────────────────────────────────

def _prob_over_under(lh: float, la: float, line: float, sel: str) -> float:
    p = 0.0
    for x in range(MAX_GOALS+1):
        for y in range(MAX_GOALS+1):
            total = x + y
            if (sel == "over"  and total > line) or \
               (sel == "under" and total < line):
                p += poisson.pmf(x, lh) * poisson.pmf(y, la)
    return p


def _prob_btts(lh: float, la: float, sel: str) -> float:
    p_yes = (1 - poisson.pmf(0, lh)) * (1 - poisson.pmf(0, la))
    return p_yes if sel == "yes" else 1 - p_yes


def _prob_handicap(lh: float, la: float, line: float, sel: str) -> float:
    """
    line is the Asian handicap applied to the HOME team.
    +1.5 means home starts with +1.5 goals (easy to win).
    -1.5 means home must win by 2+ (hard to win).
    sel='home' → home team wins the handicap market.
    sel='away' → away team wins the handicap market.
    """
    p = 0.0
    for x in range(MAX_GOALS+1):
        for y in range(MAX_GOALS+1):
            adjusted = x + line - y   # home goals + handicap - away goals
            win_home = adjusted > 0
            if (sel == "home" and win_home) or (sel == "away" and not win_home):
                p += poisson.pmf(x, lh) * poisson.pmf(y, la)
    return p


def _prob_for_selection(
    model: DixonColesModel,
    sel: ValidatedSelection,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Returns (prob_modelo, lambda_home, lambda_away).
    All three are None for exotic markets or missing team IDs.
    """
    if sel.mercado_exotico:
        return None, None, None

    home_id = sel.local_match.equipo_id
    away_id = sel.visitante_match.equipo_id if sel.visitante_match else None

    # Without a visitante we cannot compute lambdas
    if not away_id:
        return None, None, None

    lh, la = model.lambdas(home_id, away_id)

    if sel.mercado == "1X2":
        ph, pd, pa = model.predict_1x2(lh, la)
        p = {"home": ph, "draw": pd, "away": pa}.get(sel.seleccion)

    elif sel.mercado == "over_under":
        line = sel.linea if sel.linea is not None else 2.5
        p = _prob_over_under(lh, la, line, sel.seleccion)

    elif sel.mercado == "btts":
        p = _prob_btts(lh, la, sel.seleccion)

    elif sel.mercado == "handicap":
        line = sel.linea if sel.linea is not None else 0.0
        p = _prob_handicap(lh, la, line, sel.seleccion)

    else:
        return None, None, None

    return round(p, 6) if p is not None else None, round(lh, 4), round(la, 4)


# ── Kelly criterion ───────────────────────────────────────────────────────────

def _fractional_kelly(prob_modelo: float, cuota: float) -> Optional[float]:
    b = cuota - 1.0
    q = 1.0 - prob_modelo
    full_kelly = (b * prob_modelo - q) / b
    if full_kelly <= 0:
        return None
    return round(full_kelly * KELLY_FRACTION, 4)


# ── Coverage level ────────────────────────────────────────────────────────────

def _coverage(n_local: int, n_visitante: int, exotic: bool, no_away: bool) -> tuple[str, list[str]]:
    if exotic:
        return "NULA", ["Mercado exotico: sin modelo estadistico disponible."]
    if no_away:
        return "BAJA", ["No se identifico equipo visitante: lambdas no calculables."]
    razones = []
    nivel   = "ALTA"
    if n_local < COVERAGE_MEDIA or n_visitante < COVERAGE_MEDIA:
        nivel = "BAJA"
        razones.append(f"Datos insuficientes: local={n_local} partidos, visitante={n_visitante}.")
    elif n_local < COVERAGE_ALTA or n_visitante < COVERAGE_ALTA:
        nivel = "MEDIA"
        razones.append(f"Datos limitados: local={n_local} partidos, visitante={n_visitante}.")
    return nivel, razones


# ── Correlation detector ──────────────────────────────────────────────────────

def _detect_correlations(sels: list[ValidatedSelection]) -> list[Correlacion]:
    # Group by match (local_id, vis_id) — only selections with both teams
    from collections import defaultdict
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, s in enumerate(sels):
        if s.local_match.equipo_id and s.visitante_match and s.visitante_match.equipo_id:
            key = (s.local_match.equipo_id, s.visitante_match.equipo_id)
            groups[key].append(i)

    found = []
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for a in range(len(idxs)):
            for b in range(a+1, len(idxs)):
                i, j = idxs[a], idxs[b]
                sel_i = sels[i].seleccion
                sel_j = sels[j].seleccion
                for corr in KNOWN_CORRELATIONS:
                    if ({corr["m1"], corr["m2"]} == {sel_i, sel_j}):
                        found.append(Correlacion(
                            sel_idx_1=i, sel_idx_2=j,
                            tipo=corr["tipo"], nota=corr["nota"],
                        ))
    return found


# ── Confidence level ──────────────────────────────────────────────────────────

def _confidence(analyses: list[SelectionAnalysis], correlaciones: list[Correlacion]) -> tuple[str, list[str]]:
    razones = []
    nivel   = "ALTA"

    n_exotic    = sum(1 for s in analyses if s.mercado_exotico)
    n_nula      = sum(1 for s in analyses if s.nivel_cobertura == "NULA")
    n_baja      = sum(1 for s in analyses if s.nivel_cobertura == "BAJA")
    n_media     = sum(1 for s in analyses if s.nivel_cobertura == "MEDIA")
    n_corr      = len(correlaciones)

    if n_nula > 0 or n_exotic > 1:
        nivel = "BAJA"
        if n_exotic:
            razones.append(f"{n_exotic} mercado(s) exotico(s) sin modelo estadistico.")
        if n_nula:
            razones.append(f"{n_nula} seleccion(es) sin visitante identificado.")
    elif n_baja > 0 or n_exotic == 1 or n_corr > 0:
        nivel = "MEDIA"
        if n_baja:
            no_vis   = sum(1 for s in analyses if s.nivel_cobertura == "BAJA" and not s.equipo_visitante_id)
            low_data = n_baja - no_vis
            if no_vis:
                razones.append(f"{no_vis} seleccion(es) sin equipo visitante identificado por el OCR.")
            if low_data:
                razones.append(f"{low_data} seleccion(es) con datos insuficientes (<{COVERAGE_MEDIA} partidos).")
        if n_exotic == 1:
            razones.append("1 mercado exotico presente.")
        if n_corr:
            razones.append(f"{n_corr} correlacion(es) detectada(s) en el mismo partido.")
    elif n_media > 0:
        nivel = "MEDIA"
        razones.append(f"{n_media} seleccion(es) con datos limitados ({COVERAGE_MEDIA}-{COVERAGE_ALTA-1} partidos).")

    if not razones:
        razones.append("Todos los equipos con datos suficientes, sin exoticos ni correlaciones.")

    return nivel, razones


# ── Model + data cache (refit every MODEL_TTL_HOURS) ─────────────────────────

_cached_model:   DixonColesModel | None = None
_cached_matches: list[dict] | None      = None
_cached_counts:  dict[str, int] | None  = None
_cache_ts:       datetime | None        = None


def _load_and_fit() -> tuple[DixonColesModel, list[dict], dict[str, int]]:
    global _cached_model, _cached_matches, _cached_counts, _cache_ts
    now = datetime.now(tz=timezone.utc)
    expired = (
        _cache_ts is None or
        (now - _cache_ts).total_seconds() > MODEL_TTL_HOURS * 3600
    )
    if expired:
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        rows = (
            sb.table("partidos")
            .select("equipo_local_id, equipo_visitante_id, goles_local, goles_visitante, resultado, temporada, fecha")
            .in_("temporada", ["2022", "2023", "2024"])
            .eq("estado", "FINISHED")
            .execute()
            .data
        )
        matches = [r for r in rows if r["goles_local"] is not None]
        counts: dict[str, int] = {}
        for m in matches:
            for tid in (m["equipo_local_id"], m["equipo_visitante_id"]):
                counts[tid] = counts.get(tid, 0) + 1
        model = DixonColesModel().fit(matches, now)
        _cached_model   = model
        _cached_matches = matches
        _cached_counts  = counts
        _cache_ts       = now
    return _cached_model, _cached_matches, _cached_counts   # type: ignore[return-value]


def warm_up() -> None:
    """Pre-load and fit the model. Call at server startup."""
    _load_and_fit()


# ── Main public function ──────────────────────────────────────────────────────

def analyze(parlay: ValidatedParlay) -> ParlayAnalysis:
    """
    Full statistical analysis of a validated parlay.

    Loads matches from Supabase, fits Dixon-Coles, and returns ParlayAnalysis.
    """
    model, _, team_match_count = _load_and_fit()

    # Determine bookmaker margin
    casa = (parlay.casa_apuestas or "").lower().strip()
    margin = BOOKMAKER_MARGINS.get(casa, DEFAULT_MARGIN)

    # Analyze each selection
    analyses: list[SelectionAnalysis] = []
    for sel in parlay.selecciones:
        home_id = sel.local_match.equipo_id
        away_id = sel.visitante_match.equipo_id if sel.visitante_match else None

        n_local = team_match_count.get(home_id, 0)
        n_visit = team_match_count.get(away_id, 0) if away_id else 0

        nivel_cov, alertas_cov = _coverage(
            n_local, n_visit,
            exotic=sel.mercado_exotico,
            no_away=(away_id is None),
        )

        prob_impl_adj = round(sel.prob_implicita / (1 + margin), 6)

        prob_mod, lh, la = _prob_for_selection(model, sel)

        if prob_mod is not None:
            edge          = round(prob_mod - prob_impl_adj, 6)
            kelly_frac    = _fractional_kelly(prob_mod, sel.cuota)
        else:
            edge       = None
            kelly_frac = None

        alertas = list(alertas_cov)
        if edge is not None and edge < -0.05:
            alertas.append("La casa tiene ventaja estadistica clara en esta seleccion.")
        if sel.mercado_exotico:
            alertas.append("Mercado exotico: el modelo no puede validar esta seleccion.")

        analyses.append(SelectionAnalysis(
            equipo_local          = sel.local_match.canonical,
            equipo_visitante      = sel.visitante_match.canonical if sel.visitante_match else None,
            equipo_local_id       = home_id,
            equipo_visitante_id   = away_id,
            mercado               = sel.mercado,
            seleccion             = sel.seleccion,
            cuota                 = sel.cuota,
            linea                 = sel.linea,
            prob_implicita        = sel.prob_implicita,
            prob_implicita_adj    = prob_impl_adj,
            prob_modelo           = prob_mod,
            lambda_home           = lh,
            lambda_away           = la,
            edge                  = edge,
            kelly_fraccion        = kelly_frac,
            nivel_cobertura       = nivel_cov,
            mercado_exotico       = sel.mercado_exotico,
            n_partidos_local      = n_local,
            n_partidos_visitante  = n_visit,
            alertas               = alertas,
        ))

    # Parlay-level probabilities
    modeled = [a.prob_modelo for a in analyses if a.prob_modelo is not None]
    prob_parlay_modelo = round(math.prod(modeled), 6) if modeled else None
    prob_parlay_impl   = round(math.prod(a.prob_implicita_adj for a in analyses), 6)

    correlaciones = _detect_correlations(parlay.selecciones)
    nivel_conf, razones_conf = _confidence(analyses, correlaciones)

    return ParlayAnalysis(
        selecciones         = analyses,
        prob_parlay_modelo  = prob_parlay_modelo,
        prob_parlay_impl    = prob_parlay_impl,
        cuota_total         = parlay.cuota_total,
        casa_apuestas       = parlay.casa_apuestas,
        nivel_confianza     = nivel_conf,
        razones_confianza   = razones_conf,
        correlaciones       = correlaciones,
        margen_aplicado     = margin,
    )


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    from validator import validate, _load_teams

    ocr_data = {
        "selecciones": [
            {"equipo_local": "Universitario de Deportes", "equipo_visitante": None,
             "mercado": "1X2", "seleccion": "home", "cuota": 1.55, "linea": None},
            {"equipo_local": "Alianza Lima", "equipo_visitante": "Sport Huancayo",
             "mercado": "over_under", "seleccion": "over", "cuota": 1.85, "linea": 2.5},
            {"equipo_local": "Sporting Cristal", "equipo_visitante": "FBC Melgar",
             "mercado": "btts", "seleccion": "yes", "cuota": 1.75, "linea": None},
            {"equipo_local": "ADT", "equipo_visitante": None,
             "mercado": "exotic", "seleccion": "ADT o empate", "cuota": 1.5, "linea": None},
            {"equipo_local": "Atletico Grau", "equipo_visitante": None,
             "mercado": "handicap", "seleccion": "home", "cuota": 2.2, "linea": 1.5},
        ],
        "cuota_total": 16.55,
        "casa_apuestas": None,
    }

    print("\nANALYZER — prueba con parlay de parlaytest.png")
    print("=" * 60)
    print("Cargando datos y ajustando modelo Dixon-Coles v0.2...")

    teams   = _load_teams()
    parlay  = validate(ocr_data, teams)
    result  = analyze(parlay)

    print(f"\nModelo: {result.version_modelo} | Margen aplicado: {result.margen_aplicado:.0%}")
    print(f"Confianza parlay: {result.nivel_confianza}")
    for r in result.razones_confianza:
        print(f"  - {r}")

    print(f"\n{'N':>2} {'Equipo local':<22} {'Mercado':<12} {'Sel':<6} "
          f"{'Cuota':>6} {'P.impl.adj':>10} {'P.modelo':>9} {'Edge':>7} {'Kelly%':>7} {'Cob':>5}")
    print("-" * 98)

    for i, s in enumerate(result.selecciones, 1):
        p_mod   = f"{s.prob_modelo:.1%}"   if s.prob_modelo   is not None else "  N/A  "
        edge    = f"{s.edge:+.1%}"         if s.edge          is not None else "  N/A  "
        kelly   = f"{s.kelly_fraccion:.1%}" if s.kelly_fraccion is not None else "  N/A  "
        vis     = s.equipo_visitante or "(sin vis.)"
        label   = f"{s.equipo_local} vs {vis}"[:21]
        print(f"{i:>2} {label:<22} {s.mercado:<12} {s.seleccion:<6} "
              f"{s.cuota:>6.2f} {s.prob_implicita_adj:>10.1%} {p_mod:>9} {edge:>7} {kelly:>7} {s.nivel_cobertura:>5}")
        for a in s.alertas:
            print(f"     ALERTA: {a}")

    if result.correlaciones:
        print(f"\nCORRELACIONES ({len(result.correlaciones)}):")
        for c in result.correlaciones:
            s1 = result.selecciones[c.sel_idx_1]
            s2 = result.selecciones[c.sel_idx_2]
            print(f"  Sel {c.sel_idx_1+1} ({s1.seleccion}) + Sel {c.sel_idx_2+1} ({s2.seleccion}): {c.tipo}")
            print(f"    {c.nota}")

    n_modeladas = sum(1 for a in result.selecciones if a.prob_modelo is not None)
    n_total     = len(result.selecciones)
    if result.prob_parlay_modelo:
        print(f"\nProb. parlay modelo ({n_modeladas}/{n_total} sel.): {result.prob_parlay_modelo:.2%}")
        if n_modeladas < n_total:
            print(f"  (Las {n_total-n_modeladas} sel. sin modelo reducen la probabilidad real aun mas)")
    else:
        print("\nProb. parlay modelo: N/A — ninguna seleccion tiene modelo")
    print(f"Prob. parlay impl. ajustada  ({n_total}/{n_total} sel.): {result.prob_parlay_impl:.2%}")
    if result.cuota_total:
        prob_impl_total = 1 / result.cuota_total
        print(f"Prob. cuota total anunciada  ({n_total}/{n_total} sel.): {prob_impl_total:.2%}  (cuota {result.cuota_total})")
