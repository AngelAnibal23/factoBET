# Doble Oportunidad (double_chance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir el mercado "doble oportunidad" (`double_chance`) a la familia goles del bet builder, servible desde la matriz Dixon-Coles ya calculada.

**Architecture:** Mercado nativo de la familia goles: una rama nueva en `goal_leg_mask` (betbuilder.py) devuelve la máscara booleana 11×11 de cada selección (`home_draw`=I≥J, `draw_away`=I≤J, `home_away`=I≠J). La pata entra a marginal/conjunta/techo/veredicto sin ningún cambio al motor. Validator y prompt del OCR se extienden con el mismo patrón de los mercados existentes.

**Tech Stack:** Python 3.12, numpy, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-07-09-doble-oportunidad-design.md`
**Rama:** `feat/doble-oportunidad` (desde master `e37e67c`)

**Convenciones del repo:** tests en `tests/test_*.py` con `sys.path.insert` al root (ya está en los archivos, no repetir). Correr tests con `python -m pytest` desde el root. Commits estilo `feat(scope): descripción en español`.

---

### Task 1: Máscaras double_chance en betbuilder

**Files:**
- Modify: `betbuilder.py:17` (GOAL_MARKETS) y `betbuilder.py:100-120` (goal_leg_mask)
- Test: `tests/test_betbuilder.py` (añadir al final de los tests de máscaras, tras `test_goal_leg_mask_exact`, ~línea 55)

- [ ] **Step 1: Write the failing tests**

Añadir a `tests/test_betbuilder.py` (el archivo ya importa `numpy as np`, `pytest` y `betbuilder`):

```python
def test_double_chance_en_goal_markets():
    assert "double_chance" in betbuilder.GOAL_MARKETS


def test_goal_leg_mask_double_chance():
    hd = betbuilder.goal_leg_mask("double_chance", "home_draw", None)
    da = betbuilder.goal_leg_mask("double_chance", "draw_away", None)
    ha = betbuilder.goal_leg_mask("double_chance", "home_away", None)
    # celda (goles_local, goles_visita): (2,1)=gana local, (1,1)=empate, (0,2)=gana visita
    assert hd[2, 1] and hd[1, 1] and not hd[0, 2]
    assert da[0, 2] and da[1, 1] and not da[2, 1]
    assert ha[2, 1] and ha[0, 2] and not ha[1, 1]


def test_double_chance_es_suma_de_1x2():
    m = betbuilder.scoreline_matrix(1.4, 1.1, -0.1)
    p_home = betbuilder.marginal_prob(m, ("1X2", "home", None))
    p_draw = betbuilder.marginal_prob(m, ("1X2", "draw", None))
    p_away = betbuilder.marginal_prob(m, ("1X2", "away", None))
    assert betbuilder.marginal_prob(m, ("double_chance", "home_draw", None)) == pytest.approx(p_home + p_draw)
    assert betbuilder.marginal_prob(m, ("double_chance", "draw_away", None)) == pytest.approx(p_draw + p_away)
    assert betbuilder.marginal_prob(m, ("double_chance", "home_away", None)) == pytest.approx(p_home + p_away)
    # complementariedad: cubrir 2 resultados = 1 - el tercero
    assert betbuilder.marginal_prob(m, ("double_chance", "home_draw", None)) == pytest.approx(1.0 - p_away)


def test_goal_leg_mask_double_chance_seleccion_invalida():
    with pytest.raises(ValueError):
        betbuilder.goal_leg_mask("double_chance", "1X", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_betbuilder.py -k double_chance -v`
Expected: 4 FAIL — `test_double_chance_en_goal_markets` con AssertionError; los otros con `ValueError: Pata no modelable en familia goles: double_chance/...`

- [ ] **Step 3: Write minimal implementation**

En `betbuilder.py` línea 17, añadir el mercado:

```python
GOAL_MARKETS = {"1X2", "over_under", "btts", "handicap", "resultado_exacto", "double_chance"}
```

En `goal_leg_mask`, tras la rama de `"1X2"` (después de la línea `if seleccion == "away": return I < J`):

```python
    elif mercado == "double_chance":
        if seleccion == "home_draw": return I >= J
        if seleccion == "draw_away": return I <= J
        if seleccion == "home_away": return I != J
```

(La selección desconocida cae al `raise ValueError` final ya existente — no añadir nada.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_betbuilder.py -v`
Expected: TODOS PASS (los 4 nuevos + los existentes del archivo intactos)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat(betbuilder): mercado double_chance en familia goles (mascaras DC)"
```

---

### Task 2: Validación del mercado double_chance

**Files:**
- Modify: `validator.py:34-47` (VALID_ODDS, VALID_MARKETS, VALID_SEL_*) y `validator.py:~306` (chequeo de selección, tras el bloque de btts)
- Test: `tests/test_validator.py` (añadir al final)

- [ ] **Step 1: Write the failing tests**

Añadir a `tests/test_validator.py` (importa lo necesario localmente, como hace `test_umbral_no_numerico_lanza_rangeerror`):

```python
_TEAMS_DC = [
    {"id": "nl", "nombre_oficial": "Netherlands", "aliases": []},
    {"id": "ma", "nombre_oficial": "Morocco", "aliases": []},
]


def _ocr_dc(seleccion, cuota):
    return {
        "selecciones": [
            {"equipo_local": "Netherlands", "equipo_visitante": "Morocco",
             "mercado": "double_chance", "seleccion": seleccion,
             "cuota": cuota, "linea": None},
        ],
        "cuota_total": None, "casa_apuestas": "Betano",
    }


def test_double_chance_valida_pasa():
    import validator
    from validator import validate
    parlay = validate(_ocr_dc("draw_away", 1.35), _TEAMS_DC)
    s = parlay.selecciones[0]
    assert s.mercado == "double_chance" and s.seleccion == "draw_away"


def test_double_chance_seleccion_invalida_rechazada():
    import pytest, validator
    from validator import validate
    with pytest.raises(validator.RangeError):
        validate(_ocr_dc("empate_o_marruecos", 1.35), _TEAMS_DC)


def test_double_chance_cuota_fuera_de_rango():
    import pytest, validator
    from validator import validate
    with pytest.raises(validator.RangeError):
        validate(_ocr_dc("home_draw", 12.0), _TEAMS_DC)
```

Nota: si `validate(...)` con una sola pata y `cuota_total: None` fallara por otra validación previa (p.ej. mínimo de patas), añadir una segunda pata `over_under` válida (`"seleccion": "over", "cuota": 1.5, "linea": 2.5`) a `_ocr_dc` y ajustar el índice — el objetivo del test es el chequeo de double_chance, no el formato del boleto.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_validator.py -k double_chance -v`
Expected: FAIL — `test_double_chance_valida_pasa` y los otros deben fallar porque `double_chance` no está en `VALID_MARKETS` (SyntacticError/RangeError distinto al esperado). Leer el error real: si el mercado desconocido lanza otra excepción, el test de "pasa" es el que guía.

- [ ] **Step 3: Write minimal implementation**

En `validator.py`, dentro de `VALID_ODDS` (línea 34-41), añadir la entrada:

```python
    "double_chance": (1.01, 8.0),
```

En la línea 44-47, añadir el mercado y el set de selecciones:

```python
VALID_MARKETS   = {"1X2", "over_under", "btts", "handicap", "resultado_exacto", "exotic", "count", "player", "double_chance"}
...
VALID_SEL_DC    = {"home_draw", "draw_away", "home_away"}
```

Tras el bloque del chequeo de btts (línea ~306-310), añadir con el mismo patrón:

```python
        if mercado == "double_chance" and sel not in VALID_SEL_DC:
            raise RangeError(
                "VALIDATION_RANGE",
                f"Selección {i}: valor '{sel}' no válido para double_chance.",
                detail=f"Válidos: {VALID_SEL_DC}",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_validator.py -v`
Expected: TODOS PASS

- [ ] **Step 5: Commit**

```bash
git add validator.py tests/test_validator.py
git commit -m "feat(validator): valida mercado double_chance (selecciones + rango de cuota)"
```

---

### Task 3: Prompt del OCR reconoce doble oportunidad

**Files:**
- Modify: `ocr.py:107` (lista de mercados) y `ocr.py:108-115` (reglas de selección)
- Test: `tests/test_ocr_prompt.py` (añadir al final)

- [ ] **Step 1: Write the failing test**

Añadir a `tests/test_ocr_prompt.py`:

```python
def test_prompt_documenta_double_chance():
    from ocr import SYSTEM_PROMPT
    assert "double_chance" in SYSTEM_PROMPT
    for kw in ("home_draw", "draw_away", "home_away"):
        assert kw in SYSTEM_PROMPT
    # ancla en español para que Gemini reconozca el mercado en boletos peruanos
    assert "oble oportunidad" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ocr_prompt.py -v`
Expected: el nuevo FAIL (`"double_chance" not in SYSTEM_PROMPT`); los existentes PASS

- [ ] **Step 3: Write minimal implementation**

En `ocr.py` línea 107, añadir `double_chance` a la lista:

```
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, resultado_exacto, double_chance, count, player, exotic
```

En la lista de la regla 4 (tras la línea de `- 1X2: home, draw, away`), añadir:

```
   - double_chance (Doble oportunidad): home_draw, draw_away, home_away.
     "Empate o <equipo local>" -> home_draw ; "Empate o <equipo visitante>" -> draw_away ;
     "<local> o <visitante>" (gana cualquiera) -> home_away. "linea": null.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ocr_prompt.py -v`
Expected: TODOS PASS

- [ ] **Step 5: Commit**

```bash
git add ocr.py tests/test_ocr_prompt.py
git commit -m "feat(ocr): prompt reconoce doble oportunidad -> mercado double_chance"
```

---

### Task 4: Conjunta, suite completa y COBERTURA

**Files:**
- Test: `tests/test_betbuilder.py` (test de conjunta, al final)
- Modify: `docs/COBERTURA.md:7` (fecha) y `docs/COBERTURA.md:13` (fila Goles)

- [ ] **Step 1: Write the failing test** (falla solo si Task 1 no está; con Task 1 hecha debe pasar — es el candado de integración)

Añadir a `tests/test_betbuilder.py`:

```python
def test_joint_double_chance_con_over_misma_familia():
    m = betbuilder.scoreline_matrix(1.4, 1.1, -0.1)
    legs = [("double_chance", "home_draw", None), ("over_under", "over", 1.5)]
    joint = betbuilder.joint_ceiling(m, legs)
    marg = [betbuilder.marginal_prob(m, l) for l in legs]
    assert 0 < joint <= min(marg) + 1e-12
```

- [ ] **Step 2: Run the FULL suite**

Run: `python -m pytest tests/ -q`
Expected: todo verde (era ~230 en la rama SoT; en esta rama base master el número será el de master + los nuevos; CERO fails)

- [ ] **Step 3: Update COBERTURA.md**

En `docs/COBERTURA.md` línea 7: `Última actualización: 2026-07-09` (o fecha del día de ejecución).
En la línea 13 (fila **Goles** de la tabla), añadir doble oportunidad a las patas:

```
| **Goles** | 1X2 (gana/empata), más/menos goles (over/under), ambos anotan (BTTS), hándicap, resultado exacto, **doble oportunidad** (1X/X2/12) | Liga 1 + Internacional | Dixon-Coles (matriz de marcadores) | ✅ Fase 1 + quick win 2026-07-09 |
```

(NOTA: en esta rama la tabla "Pendiente" NO tiene la fila de doble oportunidad — esa fila vive en la rama `feat/tiros-al-arco-por-jugador`. Al mergear ambas ramas habrá un conflicto trivial en este archivo: resolver dejando la fila Goles nueva y QUITANDO la fila "Doble oportunidad" de la tabla Pendiente.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_betbuilder.py docs/COBERTURA.md
git commit -m "feat(betbuilder): conjunta con double_chance + COBERTURA actualizada"
```

- [ ] **Step 5: Push de la rama**

```bash
git push -u origin feat/doble-oportunidad
```

---

## Verificación final (tras las 4 tasks)

1. `python -m pytest tests/ -q` → todo verde.
2. Smoke e2e sin servidor (opcional, ~30s de warm-up de modelos):

```bash
python -c "
from validator import validate, _load_teams
from analyzer import analyze
ocr = {'selecciones': [
  {'equipo_local':'Netherlands','equipo_visitante':'Morocco','mercado':'double_chance','seleccion':'draw_away','cuota':None,'linea':None},
  {'equipo_local':'Netherlands','equipo_visitante':'Morocco','mercado':'over_under','seleccion':'over','cuota':None,'linea':2.5},
 ], 'cuota_total': 3.1, 'casa_apuestas':'DoradoBet'}
r = analyze(validate(ocr, _load_teams()))
for s in r.selecciones: print(s.mercado, s.seleccion, s.prob_modelo)
"
```

Expected: la pata `double_chance/draw_away` sale con `prob_modelo` numérica (no None, no exotic) — es el boleto BET6 real, modelado.
