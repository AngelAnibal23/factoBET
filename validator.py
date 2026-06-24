"""
Validation layer — Phase 1
Receives raw OCR dict from ocr.py and runs 3 gates in sequence:

  Gate 1 — Syntactic:  all required fields present, correct types
  Gate 2 — Semantic:   team names fuzzy-matched against Supabase equipos
  Gate 3 — Range:      odds within valid bounds per market

Returns a ValidatedParlay with canonical team IDs, or raises a
typed exception explaining exactly what failed and why.

Match confidence:
  >= 0.85  → auto-match (MATCHED)
  0.70–0.84 → needs user confirmation (NEEDS_CONFIRMATION)
  < 0.70   → reject (UNMATCHED)
"""

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from rapidfuzz import fuzz
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ── Thresholds & valid ranges ─────────────────────────────────────────────────

MATCH_AUTO       = 0.85
MATCH_CONFIRM    = 0.70

VALID_ODDS = {
    "1X2":        (1.10, 20.0),
    "over_under": (1.15,  6.0),
    "btts":       (1.25,  4.5),
    "handicap":   (1.10, 10.0),
    "resultado_exacto": (1.5, 500.0),
    "exotic":     (1.05, 200.0),
}
DEFAULT_ODDS_RANGE = (1.05, 200.0)

VALID_MARKETS   = {"1X2", "over_under", "btts", "handicap", "resultado_exacto", "exotic", "count", "player"}
VALID_SEL_1X2   = {"home", "draw", "away"}
VALID_SEL_OU    = {"over", "under"}
VALID_SEL_BTTS  = {"yes", "no"}


# ── Exceptions ────────────────────────────────────────────────────────────────

class ValidationError(Exception):
    """Base for all validation failures."""
    def __init__(self, code: str, message: str, detail: str = ""):
        self.code    = code
        self.message = message
        self.detail  = detail
        super().__init__(f"[{code}] {message}")


class SyntacticError(ValidationError):
    pass

class SemanticError(ValidationError):
    pass

class RangeError(ValidationError):
    pass


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class TeamMatch:
    raw:        str
    canonical:  str
    equipo_id:  str
    score:      float
    status:     str   # MATCHED | NEEDS_CONFIRMATION | UNMATCHED


@dataclass
class ValidatedSelection:
    # Inputs (normalized)
    equipo_local_raw:      str
    equipo_visitante_raw:  Optional[str]
    mercado:               str
    seleccion:             str
    cuota:                 Optional[float]   # None en bet builder
    linea:                 Optional[float]
    # Resolved team matches
    local_match:           TeamMatch
    visitante_match:       Optional[TeamMatch]
    # Derived
    prob_implicita:        Optional[float]   # None en bet builder
    mercado_exotico:       bool
    # `metric` lo comparten dos familias: "count" (corners|cards|shots|sot) y
    # "player" (goal|assist|goal_or_assist|sot). `scope` es solo de la familia count.
    metric:                Optional[str] = None
    scope:                 Optional[str] = None   # total|home|away (familia count)
    # Mercado por-jugador (familia "player"): nombre + métrica + umbral. faltante=True
    # para mercados conocidos pero aún no modelables (p.ej. tiros al arco por jugador).
    player:                Optional[str] = None   # nombre tal cual el boleto
    umbral:                int = 1                 # X+ eventos (default 1)
    faltante:              bool = False


@dataclass
class ValidatedParlay:
    selecciones:   list[ValidatedSelection]
    cuota_total:   Optional[float]
    casa_apuestas: Optional[str]
    # Flags
    needs_confirmation: list[str] = field(default_factory=list)  # human-readable list
    es_bet_builder: bool = False


# ── Supabase team loader ──────────────────────────────────────────────────────

def _load_teams() -> list[dict]:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return sb.table("equipos").select("id, nombre_oficial, aliases").execute().data


# ── Fuzzy matching ────────────────────────────────────────────────────────────

def _best_match(raw: str, teams: list[dict]) -> TeamMatch:
    """Return the best fuzzy match for a raw team name."""
    if not raw:
        return TeamMatch(raw=raw, canonical="", equipo_id="",
                         score=0.0, status="UNMATCHED")

    raw_norm = raw.strip().lower()
    best_score = 0.0
    best_team  = None

    for t in teams:
        candidates = [t["nombre_oficial"]]
        if t.get("aliases"):
            candidates.extend(t["aliases"])

        for candidate in candidates:
            cand_norm = candidate.lower()
            # partial_ratio catches "Universitario de Deportes" → "Universitario"
            # token_sort_ratio handles word-order differences ("Lima Alianza" vs "Alianza Lima")
            score = max(
                fuzz.partial_ratio(raw_norm, cand_norm),
                fuzz.token_sort_ratio(raw_norm, cand_norm),
            ) / 100.0
            if score > best_score:
                best_score = score
                best_team  = t

    if best_team is None or best_score < MATCH_CONFIRM:
        return TeamMatch(raw=raw, canonical="", equipo_id="",
                         score=best_score, status="UNMATCHED")

    status = "MATCHED" if best_score >= MATCH_AUTO else "NEEDS_CONFIRMATION"
    return TeamMatch(
        raw=raw,
        canonical=best_team["nombre_oficial"],
        equipo_id=best_team["id"],
        score=best_score,
        status=status,
    )


# ── Gate 1 — Syntactic ───────────────────────────────────────────────────────

def _is_bet_builder(ocr: dict) -> bool:
    """Bet builder = sin cuotas por pata + cuota combinada presente."""
    sels = ocr.get("selecciones") or []
    if not sels:
        return False
    no_per_leg = all(s.get("cuota") is None for s in sels)
    return no_per_leg and ocr.get("cuota_total") is not None


def _backfill_bet_builder_teams(ocr: dict) -> None:
    """Un bet builder es un solo partido (asunción v1): todas las patas comparten
    local/visitante. El OCR a veces deja vacío el equipo en algunas patas; aquí lo
    rellenamos con el consenso (valor más frecuente) de las que sí lo traen, para no
    depender de que el OCR repita el nombre en cada pata. Muta `ocr` in-place."""
    sels = ocr.get("selecciones") or []

    def _consensus(field: str) -> Optional[str]:
        valores = [(s.get(field) or "").strip() for s in sels]
        valores = [v for v in valores if v]
        if not valores:
            return None
        return Counter(valores).most_common(1)[0][0]

    local_consenso = _consensus("equipo_local")
    vis_consenso   = _consensus("equipo_visitante")

    for s in sels:
        if not (s.get("equipo_local") or "").strip() and local_consenso:
            s["equipo_local"] = local_consenso
        if not (s.get("equipo_visitante") or "").strip() and vis_consenso:
            s["equipo_visitante"] = vis_consenso


def _gate_syntactic(ocr: dict, es_bb: bool = False) -> None:
    if "selecciones" not in ocr:
        raise SyntacticError(
            "VALIDATION_SYNTACTIC",
            "El JSON del OCR no tiene el campo 'selecciones'.",
        )
    if not isinstance(ocr["selecciones"], list) or len(ocr["selecciones"]) == 0:
        raise SyntacticError(
            "VALIDATION_SYNTACTIC",
            "El campo 'selecciones' está vacío o no es una lista.",
        )

    required = {"equipo_local", "mercado", "seleccion"} if es_bb else {"equipo_local", "mercado", "seleccion", "cuota"}
    for i, s in enumerate(ocr["selecciones"], 1):
        missing = required - s.keys()
        if missing:
            raise SyntacticError(
                "VALIDATION_SYNTACTIC",
                f"Selección {i}: faltan campos obligatorios: {missing}",
            )
        if not es_bb:
            if not isinstance(s.get("cuota"), (int, float)) or s["cuota"] is None:
                raise SyntacticError(
                    "VALIDATION_SYNTACTIC",
                    f"Selección {i}: 'cuota' debe ser un número.",
                    detail=f"Valor recibido: {s.get('cuota')!r}",
                )
        if s["mercado"] not in VALID_MARKETS:
            raise SyntacticError(
                "VALIDATION_SYNTACTIC",
                f"Selección {i}: mercado '{s['mercado']}' no reconocido.",
                detail=f"Mercados válidos: {VALID_MARKETS}",
            )


# ── Gate 2 — Semantic ────────────────────────────────────────────────────────

def _gate_semantic(ocr: dict, teams: list[dict]) -> list[dict]:
    """Returns enriched selections with team match results."""
    enriched = []
    for i, s in enumerate(ocr["selecciones"], 1):
        local_raw = (s.get("equipo_local") or "").strip()
        vis_raw   = (s.get("equipo_visitante") or "").strip()

        local_match = _best_match(local_raw, teams)
        if local_match.status == "UNMATCHED":
            raise SemanticError(
                "VALIDATION_SEMANTIC",
                f"Selección {i}: no se reconoce el equipo local '{local_raw}'.",
                detail=f"Similitud máxima: {local_match.score:.0%}. "
                       "Revisa el nombre o sube una imagen más nítida.",
            )

        vis_match = None
        if vis_raw:
            vis_match = _best_match(vis_raw, teams)
            if vis_match.status == "UNMATCHED":
                raise SemanticError(
                    "VALIDATION_SEMANTIC",
                    f"Selección {i}: no se reconoce el equipo visitante '{vis_raw}'.",
                    detail=f"Similitud máxima: {vis_match.score:.0%}.",
                )

        enriched.append({**s, "_local_match": local_match, "_vis_match": vis_match})

    return enriched


# ── Gate 3 — Range ───────────────────────────────────────────────────────────

def _gate_range(enriched: list[dict], es_bb: bool = False) -> None:
    for i, s in enumerate(enriched, 1):
        mercado = s["mercado"]
        if not es_bb:
            cuota  = float(s["cuota"])
            lo, hi = VALID_ODDS.get(mercado, DEFAULT_ODDS_RANGE)
            if not (lo <= cuota <= hi):
                raise RangeError(
                    "VALIDATION_RANGE",
                    f"Selección {i}: cuota {cuota} fuera de rango para mercado '{mercado}'.",
                    detail=f"Rango válido: [{lo}, {hi}]. Posible error del OCR.",
                )

        # Selección values — only validate non-exotic markets
        sel = s.get("seleccion", "")
        if mercado == "1X2" and sel not in VALID_SEL_1X2:
            raise RangeError(
                "VALIDATION_RANGE",
                f"Selección {i}: valor '{sel}' no válido para mercado 1X2.",
                detail=f"Válidos: {VALID_SEL_1X2}",
            )
        if mercado == "over_under":
            if sel not in VALID_SEL_OU:
                raise RangeError(
                    "VALIDATION_RANGE",
                    f"Selección {i}: valor '{sel}' no válido para over_under.",
                    detail=f"Válidos: {VALID_SEL_OU}",
                )
            if s.get("linea") is None:
                raise RangeError(
                    "VALIDATION_RANGE",
                    f"Selección {i}: mercado over_under requiere campo 'linea' (ej: 2.5).",
                )
        if mercado == "btts" and sel not in VALID_SEL_BTTS:
            raise RangeError(
                "VALIDATION_RANGE",
                f"Selección {i}: valor '{sel}' no válido para btts.",
                detail=f"Válidos: {VALID_SEL_BTTS}",
            )
        if mercado == "resultado_exacto":
            from betbuilder import parse_exact_score
            try:
                parse_exact_score(sel)
            except ValueError as e:
                raise RangeError(
                    "VALIDATION_RANGE",
                    f"Selección {i}: resultado exacto inválido.",
                    detail=str(e),
                )
        if mercado == "player" and s.get("umbral") is not None:
            try:
                int(s["umbral"])
            except (TypeError, ValueError):
                raise RangeError(
                    "VALIDATION_RANGE",
                    f"Selección {i}: 'umbral' debe ser un número (recibido {s['umbral']!r}).",
                )


# ── Public API ────────────────────────────────────────────────────────────────

def validate(ocr: dict, teams: list[dict] | None = None) -> ValidatedParlay:
    """
    Run all 3 validation gates and return a ValidatedParlay.

    Args:
        ocr:   dict from ocr.extract_parlay()
        teams: pre-loaded team list (optional — loads from Supabase if None)

    Raises:
        SyntacticError, SemanticError, RangeError
    """
    if teams is None:
        teams = _load_teams()

    es_bb = _is_bet_builder(ocr)
    if es_bb:
        _backfill_bet_builder_teams(ocr)
    _gate_syntactic(ocr, es_bb)
    enriched = _gate_semantic(ocr, teams)
    _gate_range(enriched, es_bb)

    # Build ValidatedParlay
    selections   = []
    needs_confirm = []

    for s in enriched:
        local_m = s["_local_match"]
        vis_m   = s["_vis_match"]

        if local_m.status == "NEEDS_CONFIRMATION":
            needs_confirm.append(
                f"Equipo local '{local_m.raw}' → '{local_m.canonical}' "
                f"({local_m.score:.0%} similitud). ¿Es correcto?"
            )
        if vis_m and vis_m.status == "NEEDS_CONFIRMATION":
            needs_confirm.append(
                f"Equipo visitante '{vis_m.raw}' → '{vis_m.canonical}' "
                f"({vis_m.score:.0%} similitud). ¿Es correcto?"
            )

        cuota = float(s["cuota"]) if s.get("cuota") is not None else None
        prob_impl = round(1 / cuota, 6) if cuota else None
        selections.append(ValidatedSelection(
            equipo_local_raw     = s.get("equipo_local", ""),
            equipo_visitante_raw = s.get("equipo_visitante") or "",
            mercado              = s["mercado"],
            seleccion            = s["seleccion"],
            cuota                = cuota,
            linea                = s.get("linea"),
            local_match          = local_m,
            visitante_match      = vis_m,
            prob_implicita       = prob_impl,
            mercado_exotico      = s["mercado"] == "exotic",
            metric               = s.get("metric"),
            scope                = s.get("scope"),
            player               = s.get("player"),
            umbral               = int(s.get("umbral") or 1),
            faltante             = bool(s.get("faltante", False)),
        ))

    return ValidatedParlay(
        selecciones         = selections,
        cuota_total         = ocr.get("cuota_total"),
        casa_apuestas       = ocr.get("casa_apuestas"),
        needs_confirmation  = needs_confirm,
        es_bet_builder      = es_bb,
    )


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")

    # Load test data from ocr.py output or a JSON file
    if len(sys.argv) >= 2:
        with open(sys.argv[1], encoding="utf-8") as f:
            ocr_data = json.load(f)
    else:
        # Inline test — parlay from parlaytest.png
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

    print("\nVALIDATOR — probando con parlay de parlaytest.png")
    print("=" * 60)

    try:
        result = validate(ocr_data)

        for i, s in enumerate(result.selecciones, 1):
            lm = s.local_match
            vm = s.visitante_match
            vis_str = f" vs {vm.canonical} [{vm.score:.0%}]" if vm else ""
            print(f"\nSeleccion {i}: {s.mercado.upper()} | {s.seleccion} @ {s.cuota}")
            print(f"  Local   : {lm.raw!r} -> {lm.canonical!r} [{lm.score:.0%}] {lm.status}")
            if vm:
                print(f"  Visit.  : {vm.raw!r} -> {vm.canonical!r} [{vm.score:.0%}] {vm.status}")
            print(f"  Prob. impl.: {s.prob_implicita:.2%}")

        print(f"\nCuota total : {result.cuota_total}")
        print(f"Casa        : {result.casa_apuestas or 'No detectada'}")

        if result.needs_confirmation:
            print("\nREQUIERE CONFIRMACION:")
            for msg in result.needs_confirmation:
                print(f"  - {msg}")
        else:
            print("\nOK: todas las selecciones validadas sin ambiguedad")

    except (SyntacticError, SemanticError, RangeError) as e:
        print(f"\nERROR [{e.code}]: {e.message}")
        if e.detail:
            print(f"  Detalle: {e.detail}")
        sys.exit(1)
