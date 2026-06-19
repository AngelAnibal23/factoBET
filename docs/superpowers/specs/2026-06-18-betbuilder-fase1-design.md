# Diseño: Bet Builder — Fase 1 (motor de probabilidad conjunta + veredicto por techo)

**Fecha:** 2026-06-18
**Estado:** En revisión por Angel

---

## Contexto

Helpbetor fue construido para **acumuladores multi-partido**: cada pata es un partido distinto, con su propia cuota, y la probabilidad del parlay = producto de las marginales (las patas son independientes). Esto está en `analyzer.py` (`prob_parlay_modelo = math.prod(modeled)`).

El caso de uso real del proyecto, sin embargo, son los **bet builders** (same-game multis): un solo partido, varias patas combinadas bajo **una única cuota total**, sin cuotas por pata. Las apps de apuestas empujan justo este formato.

Esto rompe dos supuestos del sistema actual:

1. **No hay cuota por pata.** El validador exige `cuota` en cada selección y rechaza el boleto con `422 VALIDATION_SYNTACTIC` (verificado con `ejemploBET.png`, un bet builder de Betano).
2. **Las patas NO son independientes.** Todas son el mismo partido y están correlacionadas. Multiplicar marginales sería estadísticamente incorrecto (sobreestima o subestima según el signo de la correlación).

Este spec cubre **solo la Fase 1**: el motor de bet builder y la familia de mercados de **goles** (incluido resultado exacto). Las familias de Capa 2 (córners, tarjetas) y los goles de primer tiempo son fases posteriores, cada una con su propio spec y su propia validación de calibración. Los props de jugador individual quedan fuera de alcance (data gratuita no confiable).

---

## Principio rector

**Honestidad sobre cobertura.** Un bet builder mezcla patas que el modelo de goles puede valorar (1X2, over/under, BTTS, hándicap, resultado exacto) con patas que no (córners, tarjetas, props). El sistema no inventa una probabilidad para lo que no puede modelar: calcula un **techo** sobre el subconjunto modelable y emite un veredicto riguroso, declarando explícitamente cuántas patas quedaron sin modelar.

---

## Decisiones cerradas (sesión 2026-06-18)

1. **Salida = veredicto por techo.** La conjunta de las patas modelables es un límite superior de la probabilidad real (las patas no modelables solo la bajan).
2. **Alcance de mercados Fase 1:** la familia `goles` — 1X2, over/under (partido completo), BTTS, hándicap y **resultado exacto** (nuevo, sale gratis de la matriz). Todo lo demás → exótico.
3. **Método de la conjunta:** exacta sobre la matriz de marcadores (no Monte Carlo, no multiplicar marginales con parche).
4. **Arquitectura por familias:** cada familia es un proceso aleatorio independiente. Conjunta dentro de la familia (exacta), producto entre familias. Fase 1 entrega una familia (`goles`); Capa 2 enchufa nuevas familias sin re-diseñar el núcleo.
5. **Este spec = Fase 1 con extensibilidad.** Cada fase posterior tendrá su propio spec.
6. **Fuente de datos para Capa 2 (futura):** ESPN summary endpoint (ya probado, ya usado por el resolver) trae córners/tarjetas/tiros a nivel de equipo. No se requiere scraping de Sofascore para mercados de equipo. Props de jugador = fuera de alcance.

---

## Detección y ruteo

Un parlay es **bet builder** cuando:
- ninguna pata tiene `cuota` (todas null/ausentes), **y**
- hay una `cuota_total` combinada presente, **y**
- todas las patas pertenecen a un **único partido**.

Si hay cuotas por pata → es un acumulador multi-partido (camino actual, **intacto**).

```
analyze(parlay)
  ├─ liga mixta (Liga1 + intl)?  ──► 422 PARLAY_MIXTO   [igual que hoy]
  ├─ es_bet_builder?  ──no──► camino acumulador actual (Liga1 / intl)   [SIN CAMBIOS]
  └─ sí ──► obtener (lh, la, rho) del engine que toque
            │     · Liga 1  → DixonColesModel reajustado (warm_up)
            │     · Internacional → DixonColesIntl congelado (parametros_modelo)
            └─ betbuilder.analyze_bet_builder(parlay, lh, la, rho)
```

El motor de bet builder es **agnóstico del engine**: recibe `(lh, la, rho)` y funciona igual para Liga 1 y para el Mundial. La detección de liga y el rechazo de parlay mixto se reutilizan tal cual (`_liga_de_parlay`).

El partido del boleto lo fijan las patas que nombran ambos equipos; las patas sin equipo (props) heredan ese contexto para mostrarse, pero son exóticas y no entran en el techo.

---

## El motor "techo" + veredicto

### Matriz de marcadores
Desde `(lh, la, rho)` se construye `M[i,j] = P(local=i, visitante=j)` para `i,j ∈ {0..10}` (MAX_GOALS=10), usando la misma matemática Dixon-Coles ya presente (`poisson.pmf(i,lh) * poisson.pmf(j,la) * _tau(i,j,lh,la,rho)`), normalizada a suma 1.

### Predicado por pata (familia goles)
Cada pata modelable es un predicado booleano sobre `(i,j)`:

| Mercado | Predicado |
|---|---|
| `1X2` home / draw / away | `i>j` / `i==j` / `i<j` |
| `over_under` over/under, línea L | `i+j > L` / `i+j < L` |
| `btts` yes / no | `(i>0 ∧ j>0)` / `¬(i>0 ∧ j>0)` |
| `handicap` home/away, línea L | `i+L-j > 0` / `i+L-j ≤ 0` |
| `resultado_exacto` "a-b" | `i==a ∧ j==b` |

### Conjunta (techo) y marginal
- **Techo** `C = Σ M[i,j]` sobre las celdas donde **todas** las patas modelables se cumplen a la vez.
- **Marginal** de una pata = `Σ M[i,j]` sobre las celdas donde se cumple esa sola pata (contexto informativo por pata).

Propiedad que se testea: `C ≤ min(marginales)`.

### Veredicto
`p = 1 / cuota_total` (implícita combinada de la casa).

| Condición | Veredicto | Justificación |
|---|---|---|
| `C ≤ p` | **SIN_VALOR** | Garantía matemática: prob_real ≤ C ≤ p ⟹ EV ≤ 0. No depende del margen ni de las patas no modelables. |
| `C > p` y `n_exoticas > 0` | **NO_CONCLUYENTE** | El subconjunto de goles deja margen, pero las K patas no modelables bajan la prob real un factor desconocido. Se reporta el hueco y K. |
| `C > p` y `n_exoticas == 0` | **VALOR** | Todas modelables ⟹ C *es* la prob real (no solo techo). Se calcula Kelly fraccionario 20% sobre `(C, cuota_total)`. |
| `n_modelables == 0` | **NO_EVALUABLE** | No se puede ni formar un techo. |

**Margen:** el veredicto se compara contra `1/cuota_total` crudo. El margen de la casa solo empeora el boleto, reforzando `SIN_VALOR`; se reporta como contexto pero no altera la desigualdad.

**Sin edge/Kelly por pata.** Un bet builder no tiene cuotas por pata, así que no hay edge individual. Solo el caso `VALOR` (cero exóticas) produce Kelly, a nivel de boleto. Se muestra la prob marginal de cada pata modelable como contexto.

**Correlación.** El techo captura la correlación de forma **exacta** y numérica. Las notas cualitativas de `KNOWN_CORRELATIONS` dejan de ser necesarias para bet builders (quedan como narrativa explicativa opcional).

---

## Familias de mercado (extensibilidad para Capa 2)

El motor se organiza por **familias** = procesos aleatorios independientes.

- **Fase 1 entrega una familia: `goles`** — provee la matriz de marcadores + los predicados de la tabla anterior.
- Interfaz mínima de una familia:
  - `construir_distribucion(contexto_partido) -> distribución` (en goles: la matriz 11×11).
  - `predicado(pata) -> callable` (en goles: la tabla de predicados).
  - `conjunta(distribución, patas_de_la_familia) -> float`.
- **Conjunta total** = producto de las conjuntas por familia: `C = C_goles × C_córners × C_tarjetas × …`. Dentro de cada familia: exacta y correlacionada. Entre familias: independiente.
- **Capa 2 (futura)** = un módulo nuevo que implementa la interfaz para córners (modelo Poisson con tasas por equipo, datos ESPN) + registro. **Cero cambios** en el núcleo `joint_ceiling`/`verdict`.

En Fase 1 hay una sola familia, así que `C = C_goles`. La estructura de "lista de familias cuyas conjuntas se multiplican" se deja montada para no re-diseñar.

---

## Cambios por componente

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `betbuilder.py` | Núcleo aislado: matriz, predicados, techo, marginal, veredicto, `analyze_bet_builder` |
| Crear | `tests/test_betbuilder.py` | Unitarias del núcleo |
| Modificar | `ocr.py` | Reconocer resultado exacto; mapear córners/tarjetas/tiros/1er-tiempo/props a exótico |
| Modificar | `validator.py` | `es_bet_builder`, relajar cuota por pata, mercado `resultado_exacto`, partido único |
| Modificar | `analyzer.py` | Ruteo a `betbuilder` cuando `es_bet_builder`; `_confidence` para bet builders |
| Modificar | `main.py` | Bloque `bet_builder` en el response; manejo del 422 nuevo |
| Modificar | `storage.py` + DDL (Management API) | Columnas `es_bet_builder`, `prob_techo`, `veredicto` en `analisis_parlays` |
| Modificar | `narrator.py` | Rama de narrativa para bet builders |
| Modificar | `frontend/` | Chip de veredicto + techo vs implícita + lista de patas no modeladas |
| Modificar | `tests/test_validator.py`, `tests/test_analyzer*.py` | Detección, cuota relajada, parseo exacto, integración |

**Sin tocar:** el camino acumulador en `analyze()`, los engines (`engine_v02.py`, `engine_intl_v01.py`), el resolver.

### `ocr.py` (prompt Gemini)
- Reconocer resultado exacto ("Marcador 1-3") → `mercado="resultado_exacto"`, `seleccion="1-3"`.
- Mapear córners / tarjetas / tiros / "primer tiempo" / cualquier prop de jugador → `mercado="exotic"` (hoy mapea córners y 1er-tiempo a `over_under` — bug que produce números falsos).
- Seguir extrayendo `cuota_total` y `cuota` por pata (null en bet builders). El tipo se infiere en el validador, sin campo nuevo.

### `validator.py`
- Nuevo campo `es_bet_builder: bool` en `ValidatedParlay`.
- Detección: todas las `cuota` null + `cuota_total` presente + un solo partido → `es_bet_builder=True`.
- Cuando es bet builder: saltar el gate sintáctico que exige `cuota` por pata. Equipos, mercado, línea siguen validándose.
- Añadir `resultado_exacto` a `VALID_MARKETS`; parsear `"a-b"` → dos enteros, rango 0–10.

### `analyzer.py`
- En `analyze()`, tras resolver liga y rechazar mixto: si `es_bet_builder`, obtener `(lh,la,rho)` del engine que toque y delegar en `betbuilder.analyze_bet_builder`. Camino acumulador intacto.
- `_confidence` para bet builders: `NO_EVALUABLE`→BAJA; muchas exóticas → techo flojo → MEDIA/BAJA; cero exóticas → ALTA.

### `main.py` (serializer)
Bloque nuevo en `data`:
```json
"bet_builder": {
  "es_bet_builder": true,
  "prob_techo": 0.41,
  "prob_impl_combinada": 0.2247,
  "veredicto": "NO_CONCLUYENTE",
  "n_modelables": 2,
  "n_exoticas": 4,
  "exoticas": ["Más 7.5 córners", "Andrés Gómez 2+ tiros", "Luis Díaz anota/asiste", "Más 0.5 goles 1er tiempo"],
  "kelly_fraccion": null
}
```
Para acumuladores el bloque va `null`. No rompe el contrato actual.

### `storage.py`
Persistir `es_bet_builder`, `prob_techo`, `veredicto` en `analisis_parlays`. Las patas exóticas se guardan como hoy (prob_modelo null). DDL vía Management API.

### `narrator.py`
Rama nueva: explica el veredicto en español honesto ("modelamos K de N patas; el techo es X%, la casa pide Y%; …"). Recibe números pre-computados, nunca datos crudos, como el resto.

### `frontend/`
Chip de veredicto como titular (SIN_VALOR / NO_CONCLUYENTE / VALOR / NO_EVALUABLE) + techo vs implícita + lista de patas no modeladas. Es el toque más ligero; puede ser la sub-tarea final de la fase.

---

## Manejo de errores (fail loudly)

- `cuota_total` ausente en un bet builder → `422 BET_BUILDER_SIN_CUOTA` (no se puede formar el veredicto).
- Resultado exacto mal formado (`"x-y"` no parseable o fuera de rango) → `RangeError` claro.
- Cero patas modelables → **no es error**: veredicto `NO_EVALUABLE` con mensaje honesto.
- Engine internacional sin params → se mantiene el `RuntimeError` actual de `_load_intl_predictor`.

---

## Pruebas

**Unitarias `betbuilder`:**
- La matriz suma 1.
- Cada predicado correcto por mercado (incl. resultado exacto).
- Propiedad de techo: `joint_ceiling ≤ min(marginales)`.
- Conjunta de dos patas idénticas = la marginal.
- Umbrales de veredicto: `C≤p`→SIN_VALOR; `C>p`+exóticas→NO_CONCLUYENTE; `C>p`+0 exóticas→VALOR (+Kelly); 0 modelables→NO_EVALUABLE.

**Validador:** detección de bet builder; relajación de cuota por pata; parseo/rango de resultado exacto; partido único.

**Integración:** boleto equivalente a `ejemploBET.png` (Uzbekistán-Colombia) → rutea a bet builder + engine intl; modela resultado exacto + over 1.5; marca córners/props/1er-tiempo como exóticos; calcula techo y veredicto.

**e2e:** la imagen real `ejemploBET.png` por el endpoint → ya no devuelve 422; sale veredicto.

**Regresión:** la suite actual (102 tests) sigue verde; el camino acumulador no cambia.

---

## Fuera de alcance (Fase 1)

- Goles de primer/segundo tiempo (λ/2) → Fase 2.
- Córners y tarjetas (familias Capa 2, datos ESPN) → Fase 3.
- Props de jugador individual → diferido (data gratuita no confiable).
- Bet builders multi-partido (same-game multi de varios partidos) → v1 asume un solo partido.

---

## Fases posteriores (resumen, specs aparte)

| Fase | Cubre |
|---|---|
| 2 | Familia goles de medio tiempo (λ/2, validada con su propio Brier) |
| 3 | Capa 2: familias `corners` y `cards` (datos ESPN + Poisson por familia) |
| 4 | Props de jugador (solo si aparece fuente confiable; quizá nunca) |
