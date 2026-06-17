# Mundial Sub-proyecto B (Integración en vivo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Conectar el modelo internacional (ya cargado a Supabase en Sub-proyecto A) al pipeline OCR → validación → análisis → narrativa, ruteando automáticamente Liga 1 vs Internacional y leyendo los **parámetros congelados** de `parametros_modelo` (sin reajustar).

**Architecture:** El analyzer detecta a qué liga pertenece un parlay (vía `liga_id` de los equipos matcheados) y despacha al motor correspondiente. Para Internacional reconstruye un predictor name-keyed desde `parametros_modelo` (is_production=true) y **reusa los calculadores de mercado existentes** alimentándolos con `(lh, la, rho)`. La ruta de Liga 1 no se toca salvo el punto de dispatch.

**Principio:** cambios aditivos; no romper Liga 1.

**Tech Stack:** Python 3.12, numpy, scipy, supabase, rapidfuzz, FastAPI, pytest, google-genai. Todo ya instalado.

---

## Decisiones cerradas (locked)

- **Flag `neutral`:** `neutral = (nombre_oficial_local ∉ {"United States", "Mexico", "Canada"})`. Si el equipo marcado como local en el boleto es anfitrión 2026 → aplica ventaja de local (gamma); en cualquier otro caso → cancha neutral (sin gamma).
- **Alias español:** solo las 48 selecciones clasificadas al Mundial 2026 + un puñado de potencias habituales (~50 entradas curadas).
- **Cobertura intl:** `ALTA` si el equipo está en los params congelados; `BAJA` si falta (sin query extra de conteos).
- **Parlay mixto** (un equipo Liga 1 + uno Internacional): se **rechaza** con error claro (422). No tiene sentido estadístico y además atrapa cross-matches accidentales del fuzzy.
- **Persistencia:** el analyzer intl LEE params de `parametros_modelo`; NO reajusta (a diferencia de Liga 1, que reajusta en cada warm_up). Patrón nuevo introducido a propósito.

---

## Estructura de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `set_intl_aliases.py` | Dict curado ES→EN + updater idempotente de `equipos.aliases` (liga Internacional) |
| Modificar | `engine_intl_v01.py` | `DixonColesIntl.from_params(...)` — construir predictor sin `fit()` |
| Modificar | `analyzer.py` | Loader de params congelados, mapa de ruteo, `_analyze_intl`, dispatch, regla neutral/anfitrión |
| Modificar | `main.py` | `version_modelo` por-parlay en `meta`; `modelo/estado` con 2 ligas |
| Modificar | `narrator.py` | Polish de wording (ya es agnóstico de liga) |
| Modificar | `frontend/` | Verificar render de parlay intl; etiqueta de liga si aporta |
| Crear | `tests/test_analyzer_intl.py` | Ruteo, regla anfitrión, probs de mercado intl, rechazo de mixto |
| Modificar | `tests/test_engine_intl.py` | Tests de `from_params` |
| Modificar/Crear | `tests/test_validator.py` | Test de alias ES→EN |

**Sin tocar:** `engine_v02.py`, `ocr.py`, `storage.py`, `resolver.py`, la lógica de fit de Liga 1.

**Referencias de integración (verificadas 2026-06-17):**
- `validator._best_match` ya usa `nombre_oficial` + `aliases`; umbral auto-match 0.85.
- `analyzer._prob_over_under/_prob_btts/_prob_handicap` operan sobre `(lh, la)`; `predict_1x2` y `_tau` usan `rho`.
- `engine_intl_v01.DixonColesIntl.lambdas(home, away, neutral)` y `.predict(...)` ya existen y toman nombres + flag neutral.
- `parametros_modelo` (liga Internacional, is_production=true): `mu, gamma, rho, xi, attack_params{nombre:alpha}, defense_params{nombre:beta}`. `liga_id = cc1ffe11-7ba1-4a86-9d35-e6eedbe2ec38`.
- Los params usan **nombre** como clave; el validator entrega `local_match.canonical` (= `nombre_oficial`) → ése es el puente equipo_id ↔ nombre.

---

## Task B1: Alias español para selecciones

**Files:** Create `set_intl_aliases.py`; Modify/Create `tests/test_validator.py`.

- [ ] **Step 1: Test del alias (TDD)**

En `tests/test_validator.py`, con una lista de equipos fake que incluya `{"nombre_oficial": "France", "aliases": ["Francia"]}`, verificar que `_best_match("Francia", teams).status == "MATCHED"` y `.canonical == "France"` (score ≥ 0.85). Verificar también un caso sin alias para confirmar el contraste ("Francia" vs "France" sin alias < 0.85).

- [ ] **Step 2: Crear `set_intl_aliases.py`**

Dict `ALIAS_ES = {"France": ["Francia"], "Brazil": ["Brasil"], "Germany": ["Alemania"], "England": ["Inglaterra"], "Spain": ["España"], "Italy": ["Italia"], "Netherlands": ["Países Bajos", "Holanda"], "United States": ["Estados Unidos", "EEUU"], "Mexico": ["México"], ...}` cubriendo las 48 del Mundial 2026 + potencias. Updater idempotente: para cada equipo de la liga Internacional, hace **merge** de los aliases nuevos con los existentes (sin duplicar, sin borrar). Usa SDK Supabase (`.update().eq("id", ...)`), credenciales de `.env`.

- [ ] **Step 3: Ejecutar y verificar**

Run: `python set_intl_aliases.py` → imprime cuántos equipos actualizó. Spot-check: `python -c "from validator import _load_teams, _best_match; t=_load_teams(); print(_best_match('Francia', t))"` → MATCHED a France.

- [ ] **Step 4: Commit** (`feat: add Spanish aliases for World Cup national teams`)

---

## Task B2: Predictor internacional desde params congelados

**Files:** Modify `engine_intl_v01.py`, `tests/test_engine_intl.py`.

- [ ] **Step 1: Tests de `from_params` (TDD)**

`DixonColesIntl.from_params(mu, gamma, rho, attack, defense)` con dicts de 2 equipos → `predict("A","B",neutral=False)` suma 1; `lambdas("A","B",neutral=True)` no incluye gamma; equipo desconocido cae al fallback de `mu`.

- [ ] **Step 2: Implementar `from_params` (classmethod)**

Construye una instancia sin `fit()`: `teams=sorted(attack)`, `alphas/betas` como np.array en ese orden, `idx`, y setea `mu/gamma/rho`. Marca `converged=True` (cargado, no ajustado).

- [ ] **Step 3: Correr tests** → todos verdes. **Commit** (`feat: build intl predictor from frozen params (no refit)`)

---

## Task B3: Loader de params + ruteo en el analyzer

**Files:** Modify `analyzer.py`; Create `tests/test_analyzer_intl.py`.

- [ ] **Step 1: Tests de ruteo y predicción intl (TDD)**

Con un predictor intl fake (vía `from_params`) y un `ValidatedParlay` de selecciones intl: probs de 1X2 suman 1 y están en (0,1); `over` está en (0,1); anfitrión (México) como local → `lambda_home` mayor que con neutral; parlay con un equipo Liga 1 + uno intl → el dispatch lanza error.

- [ ] **Step 2: Loader cacheado de params congelados**

`_load_intl_predictor()`: lee `parametros_modelo` (liga Internacional, is_production=true) → `DixonColesIntl.from_params(...)`. Cache con TTL 6h (espejo del de Liga 1). Si no hay fila → error explícito (fail loud).

- [ ] **Step 3: Mapa de ruteo**

Extender el cache de equipos para incluir `liga_id`; cargar `ligas` (`id→nombre`). Helper `_liga_de_parlay(parlay) -> "liga1"|"internacional"|"mixto"` según las ligas de los equipos matcheados.

- [ ] **Step 4: `_analyze_intl(parlay)` + dispatch**

Por selección: `equipo_id→canonical`, `neutral` por la regla anfitrión, `lh,la = intl.lambdas(...)`, reusar `_prob_over_under/_prob_btts/_prob_handicap` y un 1X2 con `rho` intl; cobertura por la regla acordada; `version_modelo="intl_v0.1"`. En `analyze()`: despachar; `"mixto"` → `ValueError`. Extender `warm_up()` para precargar el predictor intl.

- [ ] **Step 5: Correr tests** (incl. los de Liga 1 para no regresionar). **Commit** (`feat: route Liga 1 vs Internacional in analyzer`)

---

## Task B4: main, narrator, frontend (polish)

**Files:** Modify `main.py`, `narrator.py`, `frontend/`.

- [ ] **Step 1: `main.py`** — usar `result.version_modelo` en `meta` (no la constante hardcodeada); `modelo/estado` reporta 2 ligas cubiertas y Brier intl 0.2470. Mapear `ValueError` de parlay mixto a 422 con mensaje claro.
- [ ] **Step 2: `narrator.py`** — revisar wording para selecciones nacionales; opcional contexto de competición. Verificar que los 30 tests siguen pasando.
- [ ] **Step 3: Frontend** — levantar ambos servidores, subir/forzar un parlay intl, verificar render; etiqueta de liga/competición si aporta.
- [ ] **Step 4: Commit** (`feat: surface model version per parlay + intl polish`)

---

## Task B5: Verificación e2e

- [ ] **Step 1:** Parlay sintético del Mundial: (a) Francia vs Brasil 1X2 + over 2.5 (neutral); (b) México vs Panamá 1X2 (anfitrión local). Correr `validate → analyze → narrate`. Confirmar probabilidades sensatas, suma 1 en 1X2, y que `lambda_home` de México refleja la ventaja de anfitrión mientras que Francia-Brasil es neutral.
- [ ] **Step 2 (opcional):** Confirmar que el `resolver` resuelve un partido intl por nombre vía ESPN (slug `fifa.world`). Ya soportado; solo verificar.

---

## Checklist de cobertura

| Requisito | Task |
|---|---|
| Validator reconoce selecciones por alias ES→EN | B1 |
| Predictor intl desde params congelados (sin refit) | B2 |
| Loader de `parametros_modelo` cacheado | B3 |
| Ruteo Liga 1 vs Internacional + rechazo de mixto | B3 |
| Regla neutral/anfitrión (USA/MEX/CAN) | B3 |
| Reuso de calculadores de mercado existentes | B3 |
| `version_modelo` por-parlay en la API | B4 |
| Narrativa para parlays internacionales | B4 |
| Frontend renderiza parlay intl | B4 |
| e2e Mundial (neutral + anfitrión) | B5 |
| No tocar el fit de Liga 1 | (ningún task lo modifica) |
