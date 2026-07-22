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
from supabase import create_client, PostgrestAPIError
from dotenv import load_dotenv

from validator import ValidatedParlay, ValidatedSelection
from engine_intl_v01 import DixonColesIntl
from ausencias_sofascore import obtener_ausencias
from ajuste_ausencias import deltas_equipo, aplicar_ajuste

warnings.filterwarnings("ignore")
load_dotenv()

MAX_GOALS      = 10
XI             = 0.004   # optimal decay rate found in v0.2
KELLY_FRACTION = 0.20    # always fractional, never full Kelly

# Liga "Internacional" (Mundial 2026) — params congelados en parametros_modelo.
LIGA_INTERNACIONAL_ID = "cc1ffe11-7ba1-4a86-9d35-e6eedbe2ec38"
# Anfitriones 2026: de local reciben ventaja (gamma); el resto juega neutral.
HOSTS_2026 = {"United States", "Mexico", "Canada"}

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
    cuota:                 Optional[float]   # None en bet builder (cuota combinada)
    linea:                 Optional[float]
    prob_implicita:        Optional[float]   # None en bet builder
    prob_implicita_adj:    Optional[float]
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
    # Familia "player": nombre del jugador y si es una pata conocida pero no
    # modelable aún (faltante, p.ej. tiros al arco por jugador).
    player:                Optional[str] = None
    faltante:              bool = False


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
    # Bet builder (Fase 1) — None/0 para acumuladores
    es_bet_builder:       bool = False
    veredicto:            Optional[str] = None    # SIN_VALOR|NO_CONCLUYENTE|VALOR|NO_EVALUABLE
    prob_techo:           Optional[float] = None
    prob_estimada:        Optional[float] = None   # estimado por independencia (familias mezcladas)
    prob_impl_combinada:  Optional[float] = None
    n_modelables:         int = 0
    n_exoticas:           int = 0
    bet_builder_kelly:    Optional[float] = None
    exoticas_desc:        list[str] = field(default_factory=list)
    faltantes_desc:       list[str] = field(default_factory=list)
    # Marcador más probable por partido (solo selecciones por ahora; ver marcador.py)
    marcadores_partido:   list[dict] = field(default_factory=list)
    # Ausencias/lesiones (Fase 3.4, solo Internacional) — None = liga sin esta capa
    ausencias:            Optional[dict] = None


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


# ── Internacional (Mundial): predicción con params congelados ─────────────────

def _prob_1x2(lh: float, la: float, rho: float) -> tuple[float, float, float]:
    """1X2 a partir de lambdas + rho (libre de modelo, reusable por Liga 1 e intl)."""
    ph = pd = pa = 0.0
    for x in range(MAX_GOALS + 1):
        for y in range(MAX_GOALS + 1):
            p = poisson.pmf(x, lh) * poisson.pmf(y, la) * _tau(x, y, lh, la, rho)
            if   x > y:  ph += p
            elif x == y: pd += p
            else:        pa += p
    total = ph + pd + pa
    return ph / total, pd / total, pa / total


def _prob_for_selection_intl(
    model: DixonColesIntl,
    sel: ValidatedSelection,
    neutral: bool,
    mults: Optional[tuple] = None,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Espejo de _prob_for_selection para el motor internacional.

    Reusa TAL CUAL los calculadores de mercado (_prob_over_under/_prob_btts/
    _prob_handicap) alimentándolos con (lh, la); el 1X2 usa el rho intl. La
    única diferencia con Liga 1 es la fuente de lambdas: el predictor name-keyed
    cargado de parametros_modelo, con la ventaja de local condicional a neutral.

    mults: (deltas_home, deltas_away) de la capa de ausencias (Fase 3.4), o
    None si no hay ajuste (sin dato de ausentes para este partido).
    """
    if sel.mercado_exotico:
        return None, None, None

    home = sel.local_match.canonical
    away = sel.visitante_match.canonical if sel.visitante_match else None
    if not away:
        return None, None, None

    lh, la = model.lambdas(home, away, neutral)
    if mults is not None:
        lh, la = aplicar_ajuste(lh, la, mults[0], mults[1])

    if sel.mercado == "1X2":
        ph, pd, pa = _prob_1x2(lh, la, model.rho)
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


def _coverage_intl(home_in: bool, away_in: bool, exotic: bool, no_away: bool) -> tuple[str, list[str]]:
    """Cobertura para selecciones nacionales: ALTA si ambos equipos están en los
    parámetros congelados, BAJA si falta alguno (sin query de conteos)."""
    if exotic:
        return "NULA", ["Mercado exotico: sin modelo estadistico disponible."]
    if no_away:
        return "BAJA", ["No se identifico equipo visitante: lambdas no calculables."]
    if home_in and away_in:
        return "ALTA", []
    faltan = []
    if not home_in:
        faltan.append("local")
    if not away_in:
        faltan.append("visitante")
    return "BAJA", [f"Seleccion(es) sin parametros en el modelo internacional: {', '.join(faltan)}."]


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


# ── Internacional: predictor congelado + mapa de ruteo (cache 6h) ─────────────

_cached_intl_model: DixonColesIntl | None = None
_intl_cache_ts:     datetime | None       = None

_cached_team_liga:  dict[str, str] | None  = None
_team_liga_ts:      datetime | None        = None


def _es_error_columna_faltante(exc: PostgrestAPIError) -> bool:
    """True si PostgREST reporta que las columnas elo no existen (42703).

    Esquema v0.1 (el loader v0.2 puede no haber corrido nunca): el select con
    `elo_params, prior_scale` da 400/42703. Cualquier otro APIError no es de
    esquema y debe propagarse tal cual.
    """
    if exc.code == "42703":
        return True
    msg = (exc.message or "").lower()
    return "column" in msg and ("elo_params" in msg or "prior_scale" in msg)


def _select_intl_params(sb, columnas: str) -> list[dict]:
    return (
        sb.table("parametros_modelo")
        .select(columnas)
        .eq("liga_id", LIGA_INTERNACIONAL_ID)
        .eq("is_production", True)
        .execute()
        .data
    )


def _load_intl_predictor() -> DixonColesIntl:
    """Carga el predictor internacional desde parametros_modelo (is_production).

    A diferencia de Liga 1 (que reajusta en cada warm_up), aqui solo se LEEN los
    parametros congelados de Sub-proyecto A. Sin fila de produccion -> fail loud.
    """
    global _cached_intl_model, _intl_cache_ts
    now = datetime.now(tz=timezone.utc)
    expired = (
        _intl_cache_ts is None or
        (now - _intl_cache_ts).total_seconds() > MODEL_TTL_HOURS * 3600
    )
    if expired:
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        try:
            rows = _select_intl_params(
                sb, "mu, gamma, rho, attack_params, defense_params, elo_params, prior_scale"
            )
        except PostgrestAPIError as exc:
            if not _es_error_columna_faltante(exc):
                raise
            # Esquema v0.1 sin columnas elo -> select viejo; r.get() abajo
            # devuelve None y el modelo carga sin prior (cero regresion).
            rows = _select_intl_params(sb, "mu, gamma, rho, attack_params, defense_params")
        if not rows:
            raise RuntimeError(
                "No hay parametros_modelo de produccion para la liga Internacional. "
                "Ejecuta load_intl_to_supabase.py (Sub-proyecto A) antes de analizar parlays del Mundial."
            )
        r = rows[0]
        _cached_intl_model = DixonColesIntl.from_params(
            mu=float(r["mu"]), gamma=float(r["gamma"]), rho=float(r["rho"]),
            attack=r["attack_params"], defense=r["defense_params"],
            elo_z=r.get("elo_params") or None,
            prior_scale=float(r.get("prior_scale") or 0.0),
        )
        _intl_cache_ts = now
    return _cached_intl_model   # type: ignore[return-value]


_cached_counts_model: dict = {}


def _load_counts_model(liga_nombre: str):
    """Carga el CountsModel de una liga desde parametros_modelo (counts_v0.1).
    liga_nombre: 'Internacional' | 'Liga 1 Peruana'. None si no hay params."""
    import json
    from counts_model import CountsModel
    if liga_nombre in _cached_counts_model:
        return _cached_counts_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_counts_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo")
            .select("attack_params,defense_params,notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", "counts_v0.1")
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_counts_model[liga_nombre] = None
        return None
    params = {}
    for r in rows:
        meta = json.loads(r["notas"])
        params[meta["metrica"]] = {
            "base_home": meta["base_home"], "base_away": meta["base_away"],
            "factor_neutral": meta["factor_neutral"], "disp": meta.get("disp", 1.0),
            "atk": r["attack_params"], "def": r["defense_params"],
        }
    model = CountsModel.from_params(params)
    _cached_counts_model[liga_nombre] = model
    return model


_cached_player_model: dict = {}

PLAYER_MODEL_VERSION = "player_v0.2"   # v0.2: k=3 (calibración cola elite)


def _load_player_model(liga_nombre: str):
    """Carga el PlayerModel de una liga desde parametros_modelo (PLAYER_MODEL_VERSION).
    None si no hay params (mismo contrato que _load_counts_model)."""
    import json
    from player_model import PlayerModel
    if liga_nombre in _cached_player_model:
        return _cached_player_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_player_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo")
            .select("notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", PLAYER_MODEL_VERSION)
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_player_model[liga_nombre] = None
        return None
    model = PlayerModel.from_params(json.loads(rows[0]["notas"]))
    _cached_player_model[liga_nombre] = model
    return model


_cached_player_sot_model: dict = {}


def _load_player_sot_model(liga_nombre: str):
    """Carga el PlayerModel de tiros al arco (player_sot_v0.1) de una liga.
    None si no hay params (mismo contrato que _load_player_model)."""
    import json
    from player_model import PlayerModel
    if liga_nombre in _cached_player_sot_model:
        return _cached_player_sot_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_player_sot_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo")
            .select("notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", "player_sot_v0.1")
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_player_sot_model[liga_nombre] = None
        return None
    model = PlayerModel.from_params(json.loads(rows[0]["notas"]))
    _cached_player_sot_model[liga_nombre] = model
    return model


def _load_team_liga_map() -> dict[str, str]:
    """Mapa equipo_id -> "liga1" | "internacional" para rutear cada parlay."""
    global _cached_team_liga, _team_liga_ts
    now = datetime.now(tz=timezone.utc)
    expired = (
        _team_liga_ts is None or
        (now - _team_liga_ts).total_seconds() > MODEL_TTL_HOURS * 3600
    )
    if expired:
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        rows = sb.table("equipos").select("id, liga_id").execute().data
        _cached_team_liga = {
            r["id"]: ("internacional" if r["liga_id"] == LIGA_INTERNACIONAL_ID else "liga1")
            for r in rows
        }
        _team_liga_ts = now
    return _cached_team_liga   # type: ignore[return-value]


def _liga_de_parlay(parlay: ValidatedParlay, team_liga_map: dict[str, str]) -> str:
    """Devuelve "liga1" | "internacional" | "mixto" según las ligas de los
    equipos matcheados. Mixto (Liga 1 + Internacional) se rechaza aguas arriba."""
    ligas: set[str] = set()
    for sel in parlay.selecciones:
        ids = [sel.local_match.equipo_id]
        if sel.visitante_match:
            ids.append(sel.visitante_match.equipo_id)
        for tid in ids:
            if tid and tid in team_liga_map:
                ligas.add(team_liga_map[tid])

    if "internacional" in ligas and "liga1" in ligas:
        return "mixto"
    if ligas == {"internacional"}:
        return "internacional"
    return "liga1"   # solo liga1, o sin equipos reconocidos -> comportamiento original


def warm_up() -> None:
    """Pre-load and fit the models. Call at server startup."""
    _load_and_fit()             # Liga 1: ajusta Dixon-Coles
    _load_team_liga_map()       # ruteo
    _load_intl_predictor()      # Internacional: params congelados


# ── Main public function ──────────────────────────────────────────────────────

def _analyze_intl(parlay: ValidatedParlay, model: DixonColesIntl) -> ParlayAnalysis:
    """Analisis de un parlay de selecciones nacionales (Mundial 2026).

    Espejea analyze() pero usa el predictor congelado (name-keyed), aplica la
    regla anfitrion/neutral, y deriva la cobertura de la presencia en params
    (no de conteos de partidos). Reusa correlaciones y nivel de confianza.
    """
    casa = (parlay.casa_apuestas or "").lower().strip()
    margin = BOOKMAKER_MARGINS.get(casa, DEFAULT_MARGIN)

    mults_map, bloque_ausencias = _ausencias_del_parlay(parlay)

    analyses: list[SelectionAnalysis] = []
    for sel in parlay.selecciones:
        home = sel.local_match.canonical
        away = sel.visitante_match.canonical if sel.visitante_match else None
        away_id = sel.visitante_match.equipo_id if sel.visitante_match else None

        # Regla anfitrion: solo USA/MEX/CAN reciben ventaja de local; resto neutral.
        neutral = home not in HOSTS_2026

        home_in = bool(home) and (home in model.idx)
        away_in = bool(away) and (away in model.idx)
        nivel_cov, alertas_cov = _coverage_intl(
            home_in, away_in, exotic=sel.mercado_exotico, no_away=(away is None),
        )

        prob_impl_adj = round(sel.prob_implicita / (1 + margin), 6)

        entry = mults_map.get((home, away)) if away else None
        mults = (entry[0], entry[1]) if entry else None
        prob_mod, lh, la = _prob_for_selection_intl(model, sel, neutral, mults=mults)

        clave_partido = f"{home} - {away}" if away else None
        if entry and home_in and away_in and clave_partido not in bloque_ausencias["lambdas"]:
            lh0, la0 = model.lambdas(home, away, neutral)
            lh2, la2 = aplicar_ajuste(lh0, la0, entry[0], entry[1])
            bloque_ausencias["lambdas"][clave_partido] = {
                "antes":   [round(lh0, 4), round(la0, 4)],
                "despues": [round(lh2, 4), round(la2, 4)],
            }

        if prob_mod is not None:
            edge       = round(prob_mod - prob_impl_adj, 6)
            kelly_frac = _fractional_kelly(prob_mod, sel.cuota)
        else:
            edge       = None
            kelly_frac = None

        alertas = list(alertas_cov)
        if edge is not None and edge < -0.05:
            alertas.append("La casa tiene ventaja estadistica clara en esta seleccion.")
        if sel.mercado_exotico:
            alertas.append("Mercado exotico: el modelo no puede validar esta seleccion.")

        analyses.append(SelectionAnalysis(
            equipo_local          = home,
            equipo_visitante      = away,
            equipo_local_id       = sel.local_match.equipo_id,
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
            n_partidos_local      = 0,   # intl: cobertura por params, no por conteos
            n_partidos_visitante  = 0,
            alertas               = alertas,
        ))

    modeled = [a.prob_modelo for a in analyses if a.prob_modelo is not None]
    prob_parlay_modelo = round(math.prod(modeled), 6) if modeled else None
    prob_parlay_impl   = round(math.prod(a.prob_implicita_adj for a in analyses), 6)

    correlaciones = _detect_correlations(parlay.selecciones)
    nivel_conf, razones_conf = _confidence(analyses, correlaciones)
    marcadores = _marcadores_intl(parlay, model)

    return ParlayAnalysis(
        selecciones         = analyses,
        prob_parlay_modelo  = prob_parlay_modelo,
        prob_parlay_impl    = prob_parlay_impl,
        cuota_total         = parlay.cuota_total,
        casa_apuestas       = parlay.casa_apuestas,
        nivel_confianza     = nivel_conf,
        razones_confianza   = razones_conf,
        correlaciones       = correlaciones,
        version_modelo      = "intl_v0.1",
        margen_aplicado     = margin,
        marcadores_partido  = marcadores,
        ausencias           = bloque_ausencias,
    )


def _marcadores_intl(parlay: ValidatedParlay, model: DixonColesIntl) -> list[dict]:
    """Marcador más probable de cada partido distinto cubierto por el modelo.

    Un boleto del Mundial suele ser un solo partido -> lista de uno. Soporta
    acumuladores (un marcador por partido). Dedupe por (local, visitante); omite
    partidos sin visitante o con alguna selección fuera de los params congelados.
    """
    from marcador import marcador_partido

    marcadores: list[dict] = []
    vistos: set[tuple[str, str]] = set()
    for sel in parlay.selecciones:
        home = sel.local_match.canonical
        away = sel.visitante_match.canonical if sel.visitante_match else None
        if not away or (home, away) in vistos:
            continue
        if home not in model.idx or away not in model.idx:
            continue
        vistos.add((home, away))
        neutral = home not in HOSTS_2026
        lh, la = model.lambdas(home, away, neutral)
        marcadores.append(marcador_partido(lh, la, model.rho, home, away))
    return marcadores


def _ausencias_del_parlay(parlay: ValidatedParlay) -> tuple[dict, dict]:
    """Consulta ausencias por partido distinto del parlay (normalmente 1).

    Devuelve (mults_por_partido, bloque_respuesta). mults_por_partido mapea
    (home, away) -> (deltas_home, deltas_away, aus_dict_crudo). Falla suave:
    sin dato de ningun partido -> ({}, {"sin_dato": True}).
    """
    from dataclasses import asdict

    player = _load_player_model("Internacional")
    mults: dict = {}
    bloque_eq: dict = {}
    bloque_lam: dict = {}
    urls = []
    vistos: set[tuple[str, str]] = set()
    for sel in parlay.selecciones:
        home = sel.local_match.canonical
        away = sel.visitante_match.canonical if sel.visitante_match else None
        if not away or (home, away) in vistos:
            continue
        vistos.add((home, away))
        aus = obtener_ausencias(home, away)
        if aus is None:
            continue
        d_home = deltas_equipo(aus["equipos"].get(home, []), home, player)
        d_away = deltas_equipo(aus["equipos"].get(away, []), away, player)
        mults[(home, away)] = (d_home, d_away, aus)
        for eq, lst in aus["equipos"].items():
            bloque_eq[eq] = [asdict(a) for a in lst]
        urls.append(aus.get("url"))
    if not mults:
        return {}, {"sin_dato": True}
    return mults, {"equipos": bloque_eq, "urls": urls, "lambdas": bloque_lam}


def _analyze_bet_builder_route(parlay: ValidatedParlay, liga: str, margin: float) -> ParlayAnalysis:
    """Obtiene (lh,la,rho) del engine que toque y delega en betbuilder."""
    from betbuilder import analyze_bet_builder, BetBuilderSinCuotaError
    if not parlay.cuota_total:
        raise BetBuilderSinCuotaError("Bet builder sin cuota_total: no se puede formar el veredicto.")

    match_sel = next((s for s in parlay.selecciones if s.visitante_match), None)

    neutral_flag = False
    ausencias_match = None
    if liga == "internacional":
        model = _load_intl_predictor()
        rho, version = model.rho, "intl_v0.1"
        counts = _load_counts_model("Internacional")
        player = _load_player_model("Internacional")
        player_sot = _load_player_sot_model("Internacional")
        if match_sel:
            home = match_sel.local_match.canonical
            away = match_sel.visitante_match.canonical
            neutral_flag = home not in HOSTS_2026
            if home in model.idx and away in model.idx:
                lh, la = model.lambdas(home, away, neutral_flag)
            else:
                lh, la = None, None

            if lh is not None:
                mults_map, _ = _ausencias_del_parlay(parlay)
                entry = mults_map.get((home, away))
                if entry:
                    d_home, d_away, ausencias_match = entry
                    lh0, la0 = lh, la
                    lh, la = aplicar_ajuste(lh, la, d_home, d_away)
                    ausencias_match = dict(ausencias_match)
                    ausencias_match["lambdas"] = {
                        "antes":   [round(lh0, 4), round(la0, 4)],
                        "despues": [round(lh, 4),  round(la, 4)],
                    }
        else:
            lh, la = None, None
    else:
        model, _, _ = _load_and_fit()
        rho, version = model.rho, "v0.2"
        counts = _load_counts_model("Liga 1 Peruana")
        player = _load_player_model("Liga 1 Peruana")
        player_sot = _load_player_sot_model("Liga 1 Peruana")
        if match_sel:
            hid = match_sel.local_match.equipo_id
            aid = match_sel.visitante_match.equipo_id
            if hid in model.idx and aid in model.idx:
                lh, la = model.lambdas(hid, aid)
            else:
                lh, la = None, None
        else:
            lh, la = None, None

    return analyze_bet_builder(parlay, lh, la, rho, version, margin,
                               counts_model=counts, neutral=neutral_flag,
                               player_model=player, player_sot_model=player_sot,
                               ausencias=ausencias_match)


def analyze(parlay: ValidatedParlay) -> ParlayAnalysis:
    """
    Full statistical analysis of a validated parlay.

    Routes to Liga 1 (refit Dixon-Coles) or Internacional (frozen params) based
    on the leagues of the matched teams. A mixed parlay (Liga 1 + Internacional)
    is rejected — it has no statistical meaning and usually signals a fuzzy
    cross-match.
    """
    team_liga_map = _load_team_liga_map()
    liga = _liga_de_parlay(parlay, team_liga_map)
    if liga == "mixto":
        raise ValueError(
            "Parlay mixto: combina equipos de Liga 1 Peruana y selecciones "
            "internacionales. No es analizable como un solo parlay; sube boletos separados."
        )

    casa = (parlay.casa_apuestas or "").lower().strip()
    margin = BOOKMAKER_MARGINS.get(casa, DEFAULT_MARGIN)

    if parlay.es_bet_builder:
        return _analyze_bet_builder_route(parlay, liga, margin)

    if liga == "internacional":
        return _analyze_intl(parlay, _load_intl_predictor())

    model, _, team_match_count = _load_and_fit()

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
