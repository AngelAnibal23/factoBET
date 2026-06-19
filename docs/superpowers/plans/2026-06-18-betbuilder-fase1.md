# Bet Builder — Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Habilitar el análisis de bet builders (same-game multis) calculando la probabilidad conjunta exacta de las patas de goles y emitiendo un veredicto por techo, sin romper el camino de acumuladores multi-partido.

**Architecture:** Un módulo nuevo `betbuilder.py` construye la matriz de marcadores Dixon-Coles 11×11, evalúa cada pata de goles como una máscara booleana sobre `(i,j)`, calcula la conjunta (techo) y emite el veredicto. `analyzer.analyze()` detecta el bet builder y delega, obteniendo `(lh, la, rho)` del engine que toque (Liga 1 reajustado o Internacional congelado). El motor es agnóstico del engine. Las familias futuras (córners/tarjetas) enchufan multiplicando su conjunta.

**Tech Stack:** Python 3.12, numpy, scipy.stats.poisson, FastAPI, Supabase, pytest. Gemini 2.5 Flash para OCR/narrativa.

---

## Estructura de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `betbuilder.py` | Núcleo: matriz de marcadores, máscaras por mercado, techo, marginal, veredicto, `analyze_bet_builder`, excepciones |
| Crear | `tests/test_betbuilder.py` | Unitarias del núcleo |
| Modificar | `analyzer.py` | Campos bet builder en dataclasses; ruteo en `analyze()`; helper de partido |
| Modificar | `validator.py` | `es_bet_builder`, cuota opcional, mercado `resultado_exacto`, gates relajados |
| Modificar | `ocr.py` | Prompt: reconocer resultado exacto; mapear córners/tarjetas/1er-tiempo/props a exótico |
| Modificar | `main.py` | Bloque `bet_builder` en el response; 422 `BET_BUILDER_SIN_CUOTA` |
| Modificar | `storage.py` + DDL | Columnas `es_bet_builder`, `prob_techo`, `veredicto` |
| Modificar | `narrator.py` | Rama de narrativa para bet builders |
| Modificar | `frontend/` | Chip de veredicto + techo vs implícita + patas no modeladas |
| Modificar | `tests/test_validator.py`, `tests/test_analyzer_betbuilder.py` (nuevo) | Validación e integración |

**Sin tocar:** el camino acumulador en `analyze()`, `engine_v02.py`, `engine_intl_v01.py`, `resolver.py`.

**Convención de commits:** cada commit termina con
```
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
```

---

### Task 1: Matriz de marcadores

**Files:**
- Create: `betbuilder.py`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_betbuilder.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
import betbuilder


def test_scoreline_matrix_sums_to_one():
    M = betbuilder.scoreline_matrix(1.5, 1.2, -0.05)
    assert M.shape == (11, 11)
    assert abs(M.sum() - 1.0) < 1e-9


def test_scoreline_matrix_rho_adjusts_low_score_cells():
    # La corrección Dixon-Coles tau solo toca las 4 celdas de marcador bajo.
    base = betbuilder.scoreline_matrix(1.0, 1.0, 0.0)
    dc   = betbuilder.scoreline_matrix(1.0, 1.0, -0.1)
    assert abs(dc.sum() - 1.0) < 1e-9
    assert dc[0, 0] != base[0, 0]   # rho redistribuye la celda 0-0
    assert dc[3, 2] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_betbuilder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'betbuilder'`

- [ ] **Step 3: Write minimal implementation**

```python
# betbuilder.py
"""
Bet Builder — Fase 1
Motor de probabilidad conjunta para same-game multis.

Calcula la conjunta EXACTA de las patas de goles sobre la matriz de marcadores
Dixon-Coles (no multiplica marginales: respeta la correlación del mismo partido),
y emite un veredicto por techo. Agnóstico del engine: recibe (lh, la, rho).
"""

import numpy as np
from scipy.stats import poisson

MAX_GOALS = 10
KELLY_FRACTION = 0.20

# Mercados que la familia "goles" puede valorar desde la matriz de marcadores.
GOAL_MARKETS = {"1X2", "over_under", "btts", "handicap", "resultado_exacto"}


def scoreline_matrix(lh: float, la: float, rho: float) -> np.ndarray:
    """P(local=i, visitante=j) para i,j en {0..MAX_GOALS}, normalizada a suma 1.

    Aplica la corrección Dixon-Coles tau a las cuatro celdas de marcador bajo.
    """
    i = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(i, lh)
    pa = poisson.pmf(i, la)
    M = np.outer(ph, pa)
    M[0, 0] *= max(1e-10, 1 - lh * la * rho)
    M[1, 0] *= 1 + la * rho
    M[0, 1] *= 1 + lh * rho
    M[1, 1] *= max(1e-10, 1 - rho)
    return M / M.sum()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_betbuilder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat: scoreline matrix for bet builder engine

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Parseo de resultado exacto

**Files:**
- Modify: `betbuilder.py`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_betbuilder.py  (append)
def test_parse_exact_score_ok():
    assert betbuilder.parse_exact_score("1-3") == (1, 3)
    assert betbuilder.parse_exact_score(" 10-0 ") == (10, 0)
    assert betbuilder.parse_exact_score("0-0") == (0, 0)


def test_parse_exact_score_malformed():
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("1:3")
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("abc")


def test_parse_exact_score_out_of_range():
    with pytest.raises(ValueError):
        betbuilder.parse_exact_score("11-0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_betbuilder.py::test_parse_exact_score_ok -v`
Expected: FAIL with `AttributeError: module 'betbuilder' has no attribute 'parse_exact_score'`

- [ ] **Step 3: Write minimal implementation**

```python
# betbuilder.py  (append)
def parse_exact_score(seleccion) -> tuple[int, int]:
    """'1-3' -> (1, 3). ValueError si está mal formado o fuera de rango."""
    parts = str(seleccion).replace(" ", "").split("-")
    if len(parts) != 2:
        raise ValueError(f"Resultado exacto mal formado: {seleccion!r}")
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"Resultado exacto no numérico: {seleccion!r}")
    if not (0 <= a <= MAX_GOALS and 0 <= b <= MAX_GOALS):
        raise ValueError(f"Resultado exacto fuera de rango [0,{MAX_GOALS}]: {seleccion!r}")
    return a, b
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_betbuilder.py -v -k parse_exact`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat: parse exact-score market string

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Máscaras por mercado, marginal y conjunta (techo)

**Files:**
- Modify: `betbuilder.py`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_betbuilder.py  (append)
def test_goal_leg_mask_1x2():
    home = betbuilder.goal_leg_mask("1X2", "home", None)
    assert home[3, 1] and not home[1, 3] and not home[2, 2]


def test_goal_leg_mask_over_under():
    over = betbuilder.goal_leg_mask("over_under", "over", 2.5)
    assert over[2, 1] and not over[1, 1]


def test_goal_leg_mask_exact():
    m = betbuilder.goal_leg_mask("resultado_exacto", "1-3", None)
    assert m[1, 3] and m.sum() == 1


def test_marginal_over_under_in_range():
    M = betbuilder.scoreline_matrix(1.4, 1.1, -0.05)
    marg = betbuilder.marginal_prob(M, ("over_under", "over", 1.5))
    assert 0.0 < marg < 1.0


def test_joint_ceiling_le_each_marginal():
    M = betbuilder.scoreline_matrix(1.6, 1.0, -0.05)
    legs = [("1X2", "home", None), ("over_under", "over", 2.5)]
    ceiling = betbuilder.joint_ceiling(M, legs)
    for leg in legs:
        assert ceiling <= betbuilder.marginal_prob(M, leg) + 1e-12


def test_joint_of_identical_legs_equals_marginal():
    M = betbuilder.scoreline_matrix(1.3, 1.3, -0.05)
    leg = ("over_under", "over", 1.5)
    assert abs(betbuilder.joint_ceiling(M, [leg, leg]) - betbuilder.marginal_prob(M, leg)) < 1e-12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_betbuilder.py -v -k "mask or marginal or ceiling or identical"`
Expected: FAIL with `AttributeError: module 'betbuilder' has no attribute 'goal_leg_mask'`

- [ ] **Step 3: Write minimal implementation**

```python
# betbuilder.py  (append)
def goal_leg_mask(mercado: str, seleccion: str, linea) -> np.ndarray:
    """Máscara booleana 11x11 de las celdas (i,j) donde esta pata es VERDADERA."""
    I, J = np.indices((MAX_GOALS + 1, MAX_GOALS + 1))
    if mercado == "1X2":
        if seleccion == "home": return I > J
        if seleccion == "draw": return I == J
        if seleccion == "away": return I < J
    elif mercado == "over_under":
        total = I + J
        if seleccion == "over":  return total > linea
        if seleccion == "under": return total < linea
    elif mercado == "btts":
        yes = (I > 0) & (J > 0)
        return yes if seleccion == "yes" else ~yes
    elif mercado == "handicap":
        win_home = (I + linea - J) > 0
        return win_home if seleccion == "home" else ~win_home
    elif mercado == "resultado_exacto":
        a, b = parse_exact_score(seleccion)
        return (I == a) & (J == b)
    raise ValueError(f"Pata no modelable en familia goles: {mercado}/{seleccion}")


def marginal_prob(matrix: np.ndarray, leg: tuple) -> float:
    """Probabilidad marginal de una sola pata (contexto informativo)."""
    return float(matrix[goal_leg_mask(*leg)].sum())


def joint_ceiling(matrix: np.ndarray, legs: list[tuple]) -> float:
    """Conjunta de varias patas del mismo partido = techo de la prob real."""
    mask = np.ones(matrix.shape, dtype=bool)
    for leg in legs:
        mask &= goal_leg_mask(*leg)
    return float(matrix[mask].sum())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_betbuilder.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat: goal-market masks, marginal and joint ceiling

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Veredicto, Kelly y nivel de confianza

**Files:**
- Modify: `betbuilder.py`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_betbuilder.py  (append)
def test_verdict_sin_valor():
    # techo <= 1/cuota -> SIN_VALOR
    v, kelly = betbuilder.verdict(ceiling=0.20, cuota_total=4.0, n_modelables=2, n_exoticas=1)
    assert v == "SIN_VALOR" and kelly is None


def test_verdict_no_concluyente():
    # techo > 1/cuota con exóticas -> NO_CONCLUYENTE
    v, kelly = betbuilder.verdict(ceiling=0.40, cuota_total=4.0, n_modelables=2, n_exoticas=3)
    assert v == "NO_CONCLUYENTE" and kelly is None


def test_verdict_valor_with_kelly():
    # techo > 1/cuota sin exóticas -> VALOR + Kelly fraccionario
    v, kelly = betbuilder.verdict(ceiling=0.40, cuota_total=4.0, n_modelables=2, n_exoticas=0)
    assert v == "VALOR" and kelly is not None and kelly > 0


def test_verdict_no_evaluable():
    v, kelly = betbuilder.verdict(ceiling=None, cuota_total=4.0, n_modelables=0, n_exoticas=3)
    assert v == "NO_EVALUABLE" and kelly is None


def test_confidence_sin_valor_is_alta():
    nivel, _ = betbuilder.bb_confidence("SIN_VALOR", n_modelables=2, n_exoticas=2)
    assert nivel == "ALTA"


def test_confidence_no_concluyente_many_exoticas_is_baja():
    nivel, _ = betbuilder.bb_confidence("NO_CONCLUYENTE", n_modelables=1, n_exoticas=4)
    assert nivel == "BAJA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_betbuilder.py -v -k "verdict or confidence"`
Expected: FAIL with `AttributeError: module 'betbuilder' has no attribute 'verdict'`

- [ ] **Step 3: Write minimal implementation**

```python
# betbuilder.py  (append)
def _fractional_kelly(prob: float, cuota: float):
    b = cuota - 1.0
    q = 1.0 - prob
    full = (b * prob - q) / b
    if full <= 0:
        return None
    return round(full * KELLY_FRACTION, 4)


def verdict(ceiling, cuota_total, n_modelables: int, n_exoticas: int):
    """Devuelve (veredicto, kelly_fraccion).

    SIN_VALOR     : ceiling <= 1/cuota -> EV<=0 garantizado (prob_real <= ceiling).
    NO_CONCLUYENTE: ceiling > 1/cuota con patas exóticas (techo = cota superior).
    VALOR         : ceiling > 1/cuota sin exóticas (ceiling = prob real) + Kelly.
    NO_EVALUABLE  : ninguna pata modelable.
    """
    if n_modelables == 0:
        return "NO_EVALUABLE", None
    p = 1.0 / cuota_total
    if ceiling <= p:
        return "SIN_VALOR", None
    if n_exoticas == 0:
        return "VALOR", _fractional_kelly(ceiling, cuota_total)
    return "NO_CONCLUYENTE", None


def bb_confidence(veredicto: str, n_modelables: int, n_exoticas: int):
    """Confianza = cuánto confiar en el VEREDICTO."""
    if veredicto == "SIN_VALOR":
        return "ALTA", ["Sin valor garantizado: incluso el mejor caso (techo) no supera la cuota."]
    if veredicto == "VALOR":
        return "ALTA", ["Todas las patas modelables: el techo es la probabilidad real."]
    if veredicto == "NO_EVALUABLE":
        return "BAJA", ["Ninguna pata es modelable: no se puede formar un techo."]
    # NO_CONCLUYENTE
    total = n_modelables + n_exoticas
    if n_exoticas <= 2:
        return "MEDIA", [f"{n_exoticas} pata(s) no modelable(s): el techo es una cota superior; el resultado depende de ellas."]
    return "BAJA", [f"{n_exoticas} de {total} patas no modelables: el techo es muy flojo."]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_betbuilder.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat: bet builder verdict, kelly and confidence

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Campos bet builder en las dataclasses del analyzer

**Files:**
- Modify: `analyzer.py:74-117` (dataclasses `SelectionAnalysis` y `ParlayAnalysis`)
- Test: `tests/test_analyzer_betbuilder.py` (nuevo)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyzer_betbuilder.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analyzer import ParlayAnalysis, SelectionAnalysis


def test_parlay_analysis_has_bet_builder_fields():
    pa = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.0, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[],
    )
    assert pa.es_bet_builder is False
    assert pa.veredicto is None
    assert pa.prob_techo is None
    assert pa.n_modelables == 0
    assert pa.exoticas_desc == []


def test_selection_cuota_can_be_none():
    sa = SelectionAnalysis(
        equipo_local="A", equipo_visitante="B", equipo_local_id="1",
        equipo_visitante_id="2", mercado="over_under", seleccion="over",
        cuota=None, linea=1.5, prob_implicita=None, prob_implicita_adj=None,
        prob_modelo=0.7, lambda_home=1.5, lambda_away=1.2, edge=None,
        kelly_fraccion=None, nivel_cobertura="ALTA", mercado_exotico=False,
        n_partidos_local=0, n_partidos_visitante=0,
    )
    assert sa.cuota is None and sa.prob_implicita is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyzer_betbuilder.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument` o assertion error sobre `es_bet_builder`

- [ ] **Step 3: Write minimal implementation**

In `analyzer.py`, change `SelectionAnalysis` fields `cuota` and `prob_implicita` to Optional (lines 82-84 and 84):

```python
    cuota:                 Optional[float]   # None en bet builder (cuota combinada)
    linea:                 Optional[float]
    prob_implicita:        Optional[float]   # None en bet builder
```

In `analyzer.py`, extend `ParlayAnalysis` (after line 117 `margen_aplicado`):

```python
    # Bet builder (Fase 1) — None/0 para acumuladores
    es_bet_builder:       bool = False
    veredicto:            Optional[str] = None    # SIN_VALOR|NO_CONCLUYENTE|VALOR|NO_EVALUABLE
    prob_techo:           Optional[float] = None
    prob_impl_combinada:  Optional[float] = None
    n_modelables:         int = 0
    n_exoticas:           int = 0
    bet_builder_kelly:    Optional[float] = None
    exoticas_desc:        list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analyzer_betbuilder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite (regression)**

Run: `pytest -q`
Expected: PASS — la suite previa (102 tests) sigue verde.

- [ ] **Step 6: Commit**

```bash
git add analyzer.py tests/test_analyzer_betbuilder.py
git commit -m "feat: add bet builder fields to analysis dataclasses

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Validador — detección de bet builder, cuota opcional, resultado exacto

**Files:**
- Modify: `validator.py` (varios puntos, ver pasos)
- Test: `tests/test_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validator.py  (append; usa el patrón de mocks de teams del archivo)
import validator
from validator import validate, _is_bet_builder, ValidatedParlay

# teams mock mínimo: ajusta a los helpers ya presentes en el archivo
_TEAMS = [
    {"id": "U1", "nombre_oficial": "Uzbekistan", "aliases": ["Uzbekistán"]},
    {"id": "C1", "nombre_oficial": "Colombia", "aliases": []},
]


def test_is_bet_builder_true():
    ocr = {
        "cuota_total": 4.45,
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    assert _is_bet_builder(ocr) is True


def test_is_bet_builder_false_when_per_leg_odds():
    ocr = {"cuota_total": 4.45, "selecciones": [
        {"equipo_local": "Uzbekistan", "mercado": "1X2", "seleccion": "home", "cuota": 1.9}]}
    assert _is_bet_builder(ocr) is False


def test_validate_bet_builder_allows_null_cuota():
    ocr = {
        "cuota_total": 4.45, "casa_apuestas": "Betano",
        "selecciones": [
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "resultado_exacto", "seleccion": "1-3", "cuota": None, "linea": None},
            {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
             "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        ],
    }
    parlay = validate(ocr, _TEAMS)
    assert parlay.es_bet_builder is True
    assert parlay.selecciones[0].cuota is None
    assert parlay.selecciones[0].prob_implicita is None
    assert parlay.selecciones[0].mercado_exotico is False  # resultado_exacto NO es exótico


def test_validate_exact_score_out_of_range_rejected():
    ocr = {"cuota_total": 2.0, "selecciones": [
        {"equipo_local": "Uzbekistan", "equipo_visitante": "Colombia",
         "mercado": "resultado_exacto", "seleccion": "11-0", "cuota": None, "linea": None}]}
    with pytest.raises(validator.RangeError):
        validate(ocr, _TEAMS)
```

(Si el archivo aún no importa `pytest`, añade `import pytest` arriba.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py -v -k "bet_builder or exact"`
Expected: FAIL (`_is_bet_builder` no existe / `es_bet_builder` no existe).

- [ ] **Step 3: Write minimal implementation**

3a. `validator.py` — añadir `resultado_exacto` a mercados/odds (líneas 33-42):

```python
VALID_ODDS = {
    "1X2":        (1.10, 20.0),
    "over_under": (1.15,  6.0),
    "btts":       (1.25,  4.5),
    "handicap":   (1.10, 10.0),
    "resultado_exacto": (1.5, 500.0),
    "exotic":     (1.05, 200.0),
}
DEFAULT_ODDS_RANGE = (1.05, 200.0)

VALID_MARKETS   = {"1X2", "over_under", "btts", "handicap", "resultado_exacto", "exotic"}
```

3b. `validator.py` — `ValidatedSelection`: hacer `cuota` y `prob_implicita` opcionales (líneas 87, 93):

```python
    cuota:                 Optional[float]   # None en bet builder
    ...
    prob_implicita:        Optional[float]   # None en bet builder
```

3c. `validator.py` — `ValidatedParlay`: añadir flag (después de línea 101):

```python
    es_bet_builder: bool = False
```

3d. `validator.py` — detección (añadir antes de `_gate_syntactic`, ~línea 156):

```python
def _is_bet_builder(ocr: dict) -> bool:
    """Bet builder = sin cuotas por pata + cuota combinada presente."""
    sels = ocr.get("selecciones") or []
    if not sels:
        return False
    no_per_leg = all(s.get("cuota") is None for s in sels)
    return no_per_leg and ocr.get("cuota_total") is not None
```

3e. `validator.py` — `_gate_syntactic(ocr, es_bb)` relaja cuota (reemplazar la firma y el bloque de `required`/cuota, líneas 158-189):

```python
def _gate_syntactic(ocr: dict, es_bb: bool = False) -> None:
    if "selecciones" not in ocr:
        raise SyntacticError("VALIDATION_SYNTACTIC", "El JSON del OCR no tiene el campo 'selecciones'.")
    if not isinstance(ocr["selecciones"], list) or len(ocr["selecciones"]) == 0:
        raise SyntacticError("VALIDATION_SYNTACTIC", "El campo 'selecciones' está vacío o no es una lista.")

    required = {"equipo_local", "mercado", "seleccion"} if es_bb else {"equipo_local", "mercado", "seleccion", "cuota"}
    for i, s in enumerate(ocr["selecciones"], 1):
        missing = required - s.keys()
        if missing:
            raise SyntacticError("VALIDATION_SYNTACTIC", f"Selección {i}: faltan campos obligatorios: {missing}")
        if not es_bb:
            if not isinstance(s.get("cuota"), (int, float)) or s["cuota"] is None:
                raise SyntacticError("VALIDATION_SYNTACTIC", f"Selección {i}: 'cuota' debe ser un número.",
                                     detail=f"Valor recibido: {s.get('cuota')!r}")
        if s["mercado"] not in VALID_MARKETS:
            raise SyntacticError("VALIDATION_SYNTACTIC", f"Selección {i}: mercado '{s['mercado']}' no reconocido.",
                                 detail=f"Mercados válidos: {VALID_MARKETS}")
```

3f. `validator.py` — `_gate_range(enriched, es_bb)`: saltar rango de cuota en bet builder y validar resultado exacto (reemplazar líneas 227-265):

```python
def _gate_range(enriched: list[dict], es_bb: bool = False) -> None:
    for i, s in enumerate(enriched, 1):
        mercado = s["mercado"]
        if not es_bb:
            cuota  = float(s["cuota"])
            lo, hi = VALID_ODDS.get(mercado, DEFAULT_ODDS_RANGE)
            if not (lo <= cuota <= hi):
                raise RangeError("VALIDATION_RANGE",
                                 f"Selección {i}: cuota {cuota} fuera de rango para mercado '{mercado}'.",
                                 detail=f"Rango válido: [{lo}, {hi}]. Posible error del OCR.")

        sel = s.get("seleccion", "")
        if mercado == "1X2" and sel not in VALID_SEL_1X2:
            raise RangeError("VALIDATION_RANGE", f"Selección {i}: valor '{sel}' no válido para mercado 1X2.",
                             detail=f"Válidos: {VALID_SEL_1X2}")
        if mercado == "over_under":
            if sel not in VALID_SEL_OU:
                raise RangeError("VALIDATION_RANGE", f"Selección {i}: valor '{sel}' no válido para over_under.",
                                 detail=f"Válidos: {VALID_SEL_OU}")
            if s.get("linea") is None:
                raise RangeError("VALIDATION_RANGE", f"Selección {i}: mercado over_under requiere campo 'linea' (ej: 2.5).")
        if mercado == "btts" and sel not in VALID_SEL_BTTS:
            raise RangeError("VALIDATION_RANGE", f"Selección {i}: valor '{sel}' no válido para btts.",
                             detail=f"Válidos: {VALID_SEL_BTTS}")
        if mercado == "resultado_exacto":
            from betbuilder import parse_exact_score
            try:
                parse_exact_score(sel)
            except ValueError as e:
                raise RangeError("VALIDATION_RANGE", f"Selección {i}: resultado exacto inválido.", detail=str(e))
```

3g. `validator.py` — `validate()`: detectar, pasar flag a los gates, construir cuota/prob opcionales y setear flag (reemplazar líneas 281-326):

```python
    if teams is None:
        teams = _load_teams()

    es_bb = _is_bet_builder(ocr)
    _gate_syntactic(ocr, es_bb)
    enriched = _gate_semantic(ocr, teams)
    _gate_range(enriched, es_bb)

    selections    = []
    needs_confirm = []

    for s in enriched:
        local_m = s["_local_match"]
        vis_m   = s["_vis_match"]

        if local_m.status == "NEEDS_CONFIRMATION":
            needs_confirm.append(f"Equipo local '{local_m.raw}' → '{local_m.canonical}' "
                                 f"({local_m.score:.0%} similitud). ¿Es correcto?")
        if vis_m and vis_m.status == "NEEDS_CONFIRMATION":
            needs_confirm.append(f"Equipo visitante '{vis_m.raw}' → '{vis_m.canonical}' "
                                 f"({vis_m.score:.0%} similitud). ¿Es correcto?")

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
        ))

    return ValidatedParlay(
        selecciones         = selections,
        cuota_total         = ocr.get("cuota_total"),
        casa_apuestas       = ocr.get("casa_apuestas"),
        needs_confirmation  = needs_confirm,
        es_bet_builder      = es_bb,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py -v`
Expected: PASS (incluidos los nuevos y los previos).

- [ ] **Step 5: Run the full suite (regression)**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add validator.py tests/test_validator.py
git commit -m "feat: validator support for bet builders and exact score

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `analyze_bet_builder` + ruteo en `analyze()`

**Files:**
- Modify: `betbuilder.py` (función de ensamblado + excepción)
- Modify: `analyzer.py` (ruteo + helper de partido)
- Test: `tests/test_analyzer_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyzer_betbuilder.py  (append)
from validator import ValidatedParlay, ValidatedSelection, TeamMatch
from engine_intl_v01 import DixonColesIntl
import analyzer
import betbuilder


def _tm(name, eid):
    return TeamMatch(raw=name, canonical=name, equipo_id=eid, score=1.0, status="MATCHED")


def _bb_sel(local, lid, vis, vid, mercado, seleccion, linea=None):
    return ValidatedSelection(
        equipo_local_raw=local, equipo_visitante_raw=vis, mercado=mercado,
        seleccion=seleccion, cuota=None, linea=linea,
        local_match=_tm(local, lid), visitante_match=_tm(vis, vid),
        prob_implicita=None, mercado_exotico=(mercado == "exotic"),
    )


def _intl_model():
    attack = {"Uzbekistan": -0.2, "Colombia": 0.5}
    defense = {"Uzbekistan": 0.2, "Colombia": -0.4}
    return DixonColesIntl.from_params(mu=0.2, gamma=0.35, rho=-0.05, attack=attack, defense=defense)


def test_analyze_bet_builder_no_concluyente():
    parlay = ValidatedParlay(
        selecciones=[
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "resultado_exacto", "1-3"),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "exotic", "Más 7.5 córners"),
        ],
        cuota_total=4.45, casa_apuestas="Betano", es_bet_builder=True,
    )
    m = _intl_model()
    lh, la = m.lambdas("Uzbekistan", "Colombia", neutral=True)
    res = betbuilder.analyze_bet_builder(parlay, lh, la, m.rho, "intl_v0.1", 0.06)
    assert res.es_bet_builder is True
    assert res.veredicto in {"SIN_VALOR", "NO_CONCLUYENTE", "VALOR"}
    assert res.n_modelables == 2 and res.n_exoticas == 1
    assert res.prob_techo is not None
    assert res.exoticas_desc == ["Más 7.5 córners"]


def test_analyze_bet_builder_sin_cuota_raises():
    parlay = ValidatedParlay(
        selecciones=[_bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5)],
        cuota_total=None, casa_apuestas="Betano", es_bet_builder=True,
    )
    import pytest
    with pytest.raises(betbuilder.BetBuilderSinCuotaError):
        analyzer._analyze_bet_builder_route(parlay, "internacional", 0.06)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyzer_betbuilder.py -v -k "analyze_bet_builder"`
Expected: FAIL (`analyze_bet_builder` / `BetBuilderSinCuotaError` no existen).

- [ ] **Step 3: Write minimal implementation**

3a. `betbuilder.py` — excepción + ensamblado (append):

```python
# betbuilder.py  (append)
class BetBuilderSinCuotaError(ValueError):
    """Bet builder sin cuota_total: no se puede formar el veredicto."""


def analyze_bet_builder(parlay, lh, la, rho, version_modelo: str, margin: float):
    """Ensambla el análisis de un bet builder en un ParlayAnalysis.

    lh/la/rho: del partido (lh None si los equipos no están en el modelo).
    Import local de analyzer para evitar ciclo de import a nivel de módulo.
    """
    from analyzer import SelectionAnalysis, ParlayAnalysis

    if not parlay.cuota_total:
        raise BetBuilderSinCuotaError("Bet builder sin cuota_total: no se puede formar el veredicto.")

    covered = lh is not None
    matrix = scoreline_matrix(lh, la, rho) if covered else None

    analyses = []
    goal_legs = []
    exoticas_desc = []
    for sel in parlay.selecciones:
        is_goal = sel.mercado in GOAL_MARKETS
        modelable = covered and is_goal
        if modelable:
            leg = (sel.mercado, sel.seleccion, sel.linea)
            prob_mod = round(marginal_prob(matrix, leg), 6)
            goal_legs.append(leg)
            nivel_cov, alertas = "ALTA", []
        elif not is_goal:
            prob_mod = None
            exoticas_desc.append(sel.seleccion)
            nivel_cov, alertas = "NULA", ["Mercado exótico: el modelo no puede validar esta selección."]
        else:  # goles pero sin cobertura de equipos
            prob_mod = None
            nivel_cov, alertas = "BAJA", ["Equipos sin datos en el modelo: no se puede calcular probabilidad."]

        analyses.append(SelectionAnalysis(
            equipo_local=sel.local_match.canonical,
            equipo_visitante=sel.visitante_match.canonical if sel.visitante_match else None,
            equipo_local_id=sel.local_match.equipo_id,
            equipo_visitante_id=sel.visitante_match.equipo_id if sel.visitante_match else None,
            mercado=sel.mercado, seleccion=sel.seleccion,
            cuota=None, linea=sel.linea,
            prob_implicita=None, prob_implicita_adj=None,
            prob_modelo=prob_mod,
            lambda_home=round(lh, 4) if covered else None,
            lambda_away=round(la, 4) if covered else None,
            edge=None, kelly_fraccion=None,
            nivel_cobertura=nivel_cov, mercado_exotico=sel.mercado_exotico,
            n_partidos_local=0, n_partidos_visitante=0, alertas=alertas,
        ))

    n_modelables = len(goal_legs)
    n_exoticas = len(parlay.selecciones) - n_modelables
    ceiling = joint_ceiling(matrix, goal_legs) if (covered and n_modelables > 0) else None

    vered, kelly = verdict(ceiling, parlay.cuota_total, n_modelables, n_exoticas)
    nivel_conf, razones = bb_confidence(vered, n_modelables, n_exoticas)
    p_impl = round(1.0 / parlay.cuota_total, 6)

    return ParlayAnalysis(
        selecciones=analyses, prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=parlay.cuota_total, casa_apuestas=parlay.casa_apuestas,
        nivel_confianza=nivel_conf, razones_confianza=razones, correlaciones=[],
        version_modelo=version_modelo, margen_aplicado=margin,
        es_bet_builder=True, veredicto=vered,
        prob_techo=round(ceiling, 6) if ceiling is not None else None,
        prob_impl_combinada=p_impl, n_modelables=n_modelables, n_exoticas=n_exoticas,
        bet_builder_kelly=kelly, exoticas_desc=exoticas_desc,
    )
```

3b. `analyzer.py` — helper de ruteo (añadir antes de `def analyze(` en línea 685):

```python
def _analyze_bet_builder_route(parlay: ValidatedParlay, liga: str, margin: float) -> ParlayAnalysis:
    """Obtiene (lh,la,rho) del engine que toque y delega en betbuilder."""
    from betbuilder import analyze_bet_builder, BetBuilderSinCuotaError
    if not parlay.cuota_total:
        raise BetBuilderSinCuotaError("Bet builder sin cuota_total: no se puede formar el veredicto.")

    match_sel = next((s for s in parlay.selecciones if s.visitante_match), None)

    if liga == "internacional":
        model = _load_intl_predictor()
        rho, version = model.rho, "intl_v0.1"
        if match_sel:
            home = match_sel.local_match.canonical
            away = match_sel.visitante_match.canonical
            if home in model.idx and away in model.idx:
                neutral = home not in HOSTS_2026
                lh, la = model.lambdas(home, away, neutral)
            else:
                lh, la = None, None
        else:
            lh, la = None, None
    else:
        model, _, _ = _load_and_fit()
        rho, version = model.rho, "v0.2"
        if match_sel:
            hid = match_sel.local_match.equipo_id
            aid = match_sel.visitante_match.equipo_id
            if hid in model.idx and aid in model.idx:
                lh, la = model.lambdas(hid, aid)
            else:
                lh, la = None, None
        else:
            lh, la = None, None

    return analyze_bet_builder(parlay, lh, la, rho, version, margin)
```

3c. `analyzer.py` — ruteo en `analyze()` (insertar tras calcular `margin`, después de la línea 708 `margin = BOOKMAKER_MARGINS.get(...)`; mover el cálculo de `casa`/`margin` arriba del bloque internacional si hace falta). Reemplaza el bloque 694-708 por:

```python
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
```

Este bloque reemplaza COMPLETO el original 694-708 (incluido el `model, _, team_match_count = _load_and_fit()` de la línea 704 y el `casa`/`margin` de 707-708, ahora movidos arriba). El resto de `analyze()` (el bucle acumulador, 709+) queda intacto y sigue usando `margin` y `team_match_count`, ya definidos.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analyzer_betbuilder.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite (regression)**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add analyzer.py betbuilder.py tests/test_analyzer_betbuilder.py
git commit -m "feat: route bet builders through joint ceiling engine

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: OCR — reconocer resultado exacto, mapear no-goles a exótico

**Files:**
- Modify: `ocr.py:40-71` (SYSTEM_PROMPT)
- Test: `tests/test_ocr_prompt.py` (nuevo, estructural — sin llamar a Gemini)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ocr_prompt.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import ocr


def test_prompt_lists_exact_score_market():
    assert "resultado_exacto" in ocr.SYSTEM_PROMPT


def test_prompt_routes_corners_and_player_props_to_exotic():
    p = ocr.SYSTEM_PROMPT.lower()
    assert "córner" in p or "corner" in p     # mención explícita
    assert "exotic" in p
    assert "primer tiempo" in p               # goles de 1er tiempo -> exótico
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ocr_prompt.py -v`
Expected: FAIL (el prompt aún no menciona `resultado_exacto`).

- [ ] **Step 3: Write minimal implementation**

En `ocr.py`, reemplazar las reglas 3-4 y añadir reglas nuevas dentro de `SYSTEM_PROMPT` (líneas ~45-52). Texto a insertar/ajustar:

```
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, resultado_exacto, exotic
4. Para "seleccion":
   - 1X2: home, draw, away
   - over_under: over, under  (SOLO goles de partido completo)
   - btts: yes, no
   - handicap: home, away (el equipo con handicap)
   - resultado_exacto: el marcador como "local-visitante", ej "1-3" (Marcador exacto)
   - exotic: el texto exacto visible
4b. CLASIFICA COMO "exotic" (no inventes over_under): córners, tarjetas, tiros/remates,
    saques de esquina, goles de PRIMER TIEMPO o SEGUNDO TIEMPO, y cualquier prop de jugador
    individual (anota, asiste, tiros del jugador). El modelo solo valora goles de partido completo.
```

(Mantén el resto del prompt — reglas 5-8 y el bloque FORMATO — sin cambios.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ocr_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ocr.py tests/test_ocr_prompt.py
git commit -m "feat: OCR recognizes exact score, routes non-goal markets to exotic

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: API — bloque `bet_builder` y manejo de error sin cuota

**Files:**
- Modify: `main.py` (serializer + import + except)
- Test: `tests/test_main_serializer.py` (nuevo)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main_serializer.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import main
from analyzer import ParlayAnalysis


def test_bet_builder_block_present():
    res = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.45, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[], version_modelo="intl_v0.1",
        es_bet_builder=True, veredicto="NO_CONCLUYENTE", prob_techo=0.41,
        prob_impl_combinada=0.2247, n_modelables=2, n_exoticas=4,
        exoticas_desc=["Más 7.5 córners"], bet_builder_kelly=None,
    )
    block = main._bet_builder_block(res)
    assert block["veredicto"] == "NO_CONCLUYENTE"
    assert block["prob_techo"] == 0.41
    assert block["n_exoticas"] == 4


def test_bet_builder_block_none_for_accumulator():
    res = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=0.3, prob_parlay_impl=0.36,
        cuota_total=5.0, casa_apuestas=None, nivel_confianza="ALTA",
        razones_confianza=[], correlaciones=[],
    )
    assert main._bet_builder_block(res) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main_serializer.py -v`
Expected: FAIL (`_bet_builder_block` no existe).

- [ ] **Step 3: Write minimal implementation**

3a. `main.py` — import de la excepción (junto a los imports de analyzer, línea ~32):

```python
from betbuilder import BetBuilderSinCuotaError
```

3b. `main.py` — helper serializer (añadir antes de `_serialize_analysis`, ~línea 106):

```python
def _bet_builder_block(result: ParlayAnalysis) -> dict | None:
    if not getattr(result, "es_bet_builder", False):
        return None
    return {
        "veredicto":            result.veredicto,
        "prob_techo":           result.prob_techo,
        "prob_impl_combinada":  result.prob_impl_combinada,
        "n_modelables":         result.n_modelables,
        "n_exoticas":           result.n_exoticas,
        "exoticas":             result.exoticas_desc,
        "kelly_fraccion":       result.bet_builder_kelly,
    }
```

3c. `main.py` — incluir el bloque en `_serialize_analysis` (dentro del dict retornado, junto a `"narrativa"`):

```python
        "bet_builder":         _bet_builder_block(result),
```

3d. `main.py` — manejo del error sin cuota (en `analizar_parlay`, dentro del `try` del paso 4, ANTES del `except ValueError`):

```python
    try:
        result = analyze(parlay)
    except BetBuilderSinCuotaError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(status_code=422,
            content=_err("BET_BUILDER_SIN_CUOTA",
                         "El bet builder no trae cuota combinada; no se puede emitir veredicto.",
                         str(e), ms))
    except ValueError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(status_code=422,
            content=_err("PARLAY_MIXTO",
                         "El parlay mezcla equipos de Liga 1 y selecciones internacionales.",
                         str(e), ms))
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(status_code=500,
            content=_err("ANALYSIS_ERROR", "Error interno en el motor estadístico.", str(e), ms))
```

(Como `BetBuilderSinCuotaError` es subclase de `ValueError`, su `except` debe ir PRIMERO.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main_serializer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main_serializer.py
git commit -m "feat: expose bet builder verdict in API, handle missing combined odd

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: Persistencia — columnas nuevas en `analisis_parlays`

**Files:**
- Modify: `storage.py:64-76`
- Crear/usar: script DDL vía Management API

- [ ] **Step 1: Aplicar DDL en Supabase (Management API)**

Run (Bash):
```bash
curl -s -X POST "https://api.supabase.com/v1/projects/aahaivisyghpgqarqpak/database/query" \
  -H "Authorization: Bearer $SUPABASE_MANAGEMENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"ALTER TABLE analisis_parlays ADD COLUMN IF NOT EXISTS es_bet_builder boolean DEFAULT false, ADD COLUMN IF NOT EXISTS prob_techo numeric, ADD COLUMN IF NOT EXISTS veredicto text;"}'
```
Expected: respuesta JSON sin error (`[]` o `{}`). Cargar `SUPABASE_MANAGEMENT_TOKEN` desde `.env` primero (`export $(grep SUPABASE_MANAGEMENT_TOKEN .env)`).

- [ ] **Step 2: Modificar `storage.py` — mapear los campos nuevos**

En `parlay_row` (líneas 64-76) añadir:
```python
        "es_bet_builder":          getattr(result, "es_bet_builder", False),
        "prob_techo":              getattr(result, "prob_techo", None),
        "veredicto":               getattr(result, "veredicto", None),
```

- [ ] **Step 3: Smoke test de inserción (con mock de Supabase)**

```python
# tests/test_storage_betbuilder.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from unittest.mock import MagicMock
import storage
from analyzer import ParlayAnalysis
from validator import ValidatedParlay


def test_save_includes_bet_builder_columns(monkeypatch):
    captured = {}
    fake = MagicMock()
    def insert(row):
        if "veredicto" in (row if isinstance(row, dict) else {}):
            captured.update(row)
        m = MagicMock()
        m.execute.return_value.data = [{"id": "uuid-1"}]
        return m
    fake.table.return_value.insert.side_effect = insert
    monkeypatch.setattr(storage, "_client", lambda: fake)

    result = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.45, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[], es_bet_builder=True,
        veredicto="SIN_VALOR", prob_techo=0.18,
    )
    parlay = ValidatedParlay(selecciones=[], cuota_total=4.45, casa_apuestas="Betano")
    storage.save_analysis(result, parlay, "hash123")
    assert captured["es_bet_builder"] is True
    assert captured["veredicto"] == "SIN_VALOR"
    assert captured["prob_techo"] == 0.18
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage_betbuilder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_betbuilder.py
git commit -m "feat: persist bet builder verdict to analisis_parlays

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Narrativa — rama de bet builder

**Files:**
- Modify: `narrator.py` (branch en `generate_narrative` + builder dedicado)
- Test: `tests/test_narrator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_narrator.py  (append)
from analyzer import ParlayAnalysis
import narrator


def test_bet_builder_prompt_mentions_verdict_and_ceiling():
    res = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.45, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[], version_modelo="intl_v0.1",
        es_bet_builder=True, veredicto="SIN_VALOR", prob_techo=0.18,
        prob_impl_combinada=0.2247, n_modelables=2, n_exoticas=4,
        exoticas_desc=["Más 7.5 córners", "Luis Díaz anota"],
    )
    prompt = narrator._build_prompt_bet_builder(res)
    assert "SIN_VALOR" in prompt
    assert "18" in prompt        # techo 18%
    assert "córners" in prompt.lower() or "corners" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_narrator.py -v -k bet_builder`
Expected: FAIL (`_build_prompt_bet_builder` no existe).

- [ ] **Step 3: Write minimal implementation**

3a. `narrator.py` — builder dedicado (añadir antes de `_build_prompt`):

```python
def _build_prompt_bet_builder(analysis: ParlayAnalysis) -> str:
    techo = analysis.prob_techo
    impl  = analysis.prob_impl_combinada
    techo_txt = f"{techo:.1%}" if techo is not None else "N/A"
    impl_txt  = f"{impl:.1%}" if impl is not None else "N/A"
    exoticas = "; ".join(analysis.exoticas_desc) or "ninguna"
    veredictos = {
        "SIN_VALOR": "SIN VALOR: incluso en el mejor caso (techo) la probabilidad no supera lo que paga la cuota.",
        "NO_CONCLUYENTE": "NO CONCLUYENTE: el subconjunto modelable deja margen, pero las patas no modelables bajan la probabilidad real un factor desconocido.",
        "VALOR": "VALOR: todas las patas son modelables y el techo (= probabilidad real) supera lo que paga la cuota.",
        "NO_EVALUABLE": "NO EVALUABLE: ninguna pata es modelable; no se puede formar un techo.",
    }
    return (
        "Eres un auditor estadístico de apuestas. Explica en español claro y honesto, en 2-3 párrafos, "
        "el veredicto de este BET BUILDER (varias apuestas del mismo partido bajo una sola cuota combinada). "
        "No prometas resultados. No inventes números.\n\n"
        f"Veredicto: {analysis.veredicto} — {veredictos.get(analysis.veredicto, '')}\n"
        f"Patas modelables (goles/resultado): {analysis.n_modelables}. Patas no modelables: {analysis.n_exoticas} ({exoticas}).\n"
        f"Techo del subconjunto modelable: {techo_txt}. La casa paga como si la probabilidad fuera: {impl_txt} (1/cuota).\n"
        f"Cuota combinada: {analysis.cuota_total}.\n\n"
        "Explica qué significa el 'techo' (cota superior porque las patas no modelables solo bajan la probabilidad) "
        "y por qué el veredicto se sostiene. Cierra con una recomendación prudente de gestión de bankroll."
    )
```

3b. `narrator.py` — branch en `generate_narrative` (al inicio de la función, antes de construir el prompt normal):

```python
    if getattr(analysis, "es_bet_builder", False):
        prompt = _build_prompt_bet_builder(analysis)
    else:
        prompt = _build_prompt(analysis)
```

(Reemplaza la línea existente que hacía `prompt = _build_prompt(analysis)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_narrator.py -v -k bet_builder`
Expected: PASS.

- [ ] **Step 5: Run the full suite (regression)**

Run: `pytest -q`
Expected: PASS (los 30 tests previos de narrator siguen verdes).

- [ ] **Step 6: Commit**

```bash
git add narrator.py tests/test_narrator.py
git commit -m "feat: narrative branch for bet builder verdict

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Frontend — mostrar el veredicto

**Files:**
- Modify: `frontend/` (componente de resultados; seguir el patrón de componentes existente)

- [ ] **Step 1: Localizar el componente que renderiza el análisis**

Run: `grep -rl "narrativa\|prob_parlay\|selecciones" frontend/src`
Identifica el componente de resultados (probablemente `ResultCard`/`Analysis*`).

- [ ] **Step 2: Renderizar el bloque `bet_builder` cuando viene en `data`**

Añadir, cuando `data.bet_builder` no es null:
- Un chip de veredicto con color por estado: `SIN_VALOR` (rojo), `NO_CONCLUYENTE` (ámbar), `VALOR` (verde), `NO_EVALUABLE` (gris).
- Línea "Techo {prob_techo} vs la casa pide {prob_impl_combinada}".
- Lista "Patas no modeladas ({n_exoticas})" con `bet_builder.exoticas`.
- Reusar las CSS vars y tipografía del sistema (ver `project_frontend_design`): no introducir estilos genéricos.

Mantener el render de acumulador intacto (cuando `data.bet_builder` es null).

- [ ] **Step 3: Verificación manual (ambos servidores)**

Run (Bash, dos terminales):
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
# en otra terminal:
cd frontend && npm run dev   # http://localhost:5173
```
Subir `ejemploBET.png` en el navegador. Confirmar: aparece el chip de veredicto, el techo vs implícita, y la lista de patas no modeladas. El layout de acumulador no se rompe con un parlay tradicional.

- [ ] **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: render bet builder verdict in frontend

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: e2e con la imagen real + regresión final

**Files:** (sin cambios de código; verificación)

- [ ] **Step 1: Suite completa**

Run: `pytest -q`
Expected: PASS — toda la suite (102 previos + nuevos) en verde.

- [ ] **Step 2: Arrancar el servidor**

Run (Bash, background): `uvicorn main:app --host 0.0.0.0 --port 8000`
Esperar a que `GET http://localhost:8000/api/v1/modelo/estado` responda (warm_up ~30s).

- [ ] **Step 3: Enviar `ejemploBET.png` por el endpoint**

Run:
```bash
curl -s -X POST http://localhost:8000/api/v1/parlay/analizar \
  -F "imagen=@ejemploBET.png;type=image/png" \
  -o bb_result.json -w "HTTP %{http_code}\n"
python -c "import json;d=json.load(open('bb_result.json',encoding='utf-8'));print(json.dumps(d['data']['bet_builder'],indent=2,ensure_ascii=False))"
```
Expected:
- HTTP 200 (ya NO 422).
- `bet_builder.veredicto` ∈ {SIN_VALOR, NO_CONCLUYENTE, VALOR, NO_EVALUABLE}.
- `bet_builder.n_modelables` ≥ 1 (resultado exacto 1-3 + over 1.5 modelados).
- `bet_builder.exoticas` incluye córners y los props de jugador.

- [ ] **Step 4: Limpiar el artefacto**

Run: `rm -f bb_result.json`

- [ ] **Step 5: Commit (si la verificación dejó algún ajuste menor)**

```bash
git add -A
git commit -m "test: verify bet builder e2e with real Betano image

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notas de implementación

- **Import circular:** `analyzer` importa `betbuilder` a nivel de módulo; `betbuilder.analyze_bet_builder` importa `analyzer` de forma LOCAL (dentro de la función) para romper el ciclo. No mover ese import al tope del archivo.
- **`_tau` duplicado:** `betbuilder.scoreline_matrix` aplica la corrección Dixon-Coles inline (no importa `analyzer._tau`) para mantener el módulo autocontenido y testeable en aislamiento. Es la misma fórmula congelada de `engine_v02.py`.
- **Margen y veredicto:** el veredicto compara contra `1/cuota_total` crudo. El margen de la casa solo empeora el boleto; se reporta como contexto pero no altera la desigualdad de `SIN_VALOR`.
- **Asunción v1:** bet builder = un solo partido. Si las patas referencian varios partidos, se usa el primero con ambos equipos; multi-partido SGP queda fuera de alcance.
```
