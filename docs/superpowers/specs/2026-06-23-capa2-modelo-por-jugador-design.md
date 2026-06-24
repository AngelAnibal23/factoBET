# Capa 2 · Modelo por-jugador — anota / asiste / anota-o-asiste (top-down desde Capa 1)

**Fecha:** 2026-06-23
**Estado:** Diseño aprobado (brainstorming). Siguiente: plan de implementación.
**Decisión que lo origina:** [[ADR-0001]] (los mercados de conteo apostables son
por-jugador y situacionales; pivote a por-jugador).
**Depende de:** Capa 1 (motor de goles Dixon-Coles, `engine_intl_v01.py`, produce
`λ_equipo` por partido) + feed Flashscore `df_sui_1`/`df_li_1` (sondeado viable,
ver [[reference-capa2-datasources]]).
**Liga objetivo:** INT/Mundial primero (Liga 1 es fase posterior).

## Objetivo

Modelar las patas **por-jugador** de un bet builder —**jugador anota**, **jugador
asiste**, **jugador anota o asiste**— desde el feed de eventos de Flashscore, e
integrarlas al motor como una **tercera familia de mercados** (`player`), para que
dejen de contar como patas exóticas.

Resultado buscado (mecanismo `n_exoticas` ya existente en `betbuilder.py`): un ticket
con resultado + goles + "Fulano anota o asiste" baja de contar esa pata como exótica a
contarla como **modelable**, mejorando la detección de SIN_VALOR y la confianza.

Evidencia que lo motiva: boletos reales Betano del Mundial 2026 (`BET5.jpeg`) incluyen
"Bruno Fernandes — Jugador que anota o da una asistencia". Ese mercado hoy es exótico.

## Contexto del código existente (no romper)

- **Capa 1 / motor de goles** (`betbuilder.py` + `engine_intl_v01.py`): el Dixon-Coles
  ya calcula `lh`/`la` (goles esperados local/visitante) del partido. La familia `goal`
  valora desde la matriz de marcadores; `joint_ceiling` da la conjunta exacta.
- **Familia `count`** (Sub-proyecto B, ya en producción): patrón a espejar —
  `counts_model.py` (puro) ← `fit_counts_model.py` (gate) → `load_counts_to_supabase.py`
  (params `counts_v0.1` en `parametros_modelo`) → `analyzer._load_counts_model`
  (congelado en warm-up) → ruteo en `betbuilder.analyze_bet_builder`. Cada marginal
  count entra al techo como `min` conservador y al `prob_estimada` como factor producto.
- **Veredicto por techo** (`verdict`): el techo es **cota superior**. `SIN_VALOR` si
  techo ≤ 1/cuota. `VALOR` (+ Kelly) solo si `n_exoticas==0` y techo exacto (una sola
  familia). `NO_CONCLUYENTE` si hay no-modelables.
- **Confianza** (`bb_confidence`): `n_exoticas==0 → ALTA`, `≤2 → MEDIA`, `>2 → BAJA`.
- **OCR** (`ocr.py`): clasifica `mercado` ∈ {1X2, over_under, btts, handicap,
  resultado_exacto, count, exotic}; para `count` rellena `metric`/`scope`. Hoy una pata
  de jugador cae en `exotic`.
- **Regla de oro:** la suite actual (183 tests) sigue verde; el contrato externo de la
  API no cambia; la firma de `verdict`/`bb_confidence` no cambia.

## Decisiones de diseño (cerradas en brainstorming con Angel)

1. **Alcance = anota / asiste / anota-o-asiste.** Familia nueva `player`.
   **Jugador amonestado** queda FUERA (situacional como tarjetas, alto riesgo de no
   pasar gate). **Jugador tiros-al-arco** se reconoce pero se marca **`faltante`** (ver
   decisión 5).
2. **Estimando = `P(participa | el jugador es titular)`.** Se condiciona a titular
   porque la casa **anula** la apuesta si el jugador no inicia (texto explícito en
   BET5: "si un jugador no inicia, se anularán sus selecciones"). No se modela la
   distribución de minutos de suplentes.
3. **Enfoque = TOP-DOWN.** Se reparte el `λ_equipo` que ya da Capa 1 (Dixon-Coles)
   entre los jugadores según su **cuota histórica** de goles/asistencias, con shrinkage
   empírico-Bayes (mismo método de momentos que `counts_model`). No se re-estima la
   fuerza del equipo (Capa 1 ya la sabe); el por-jugador solo aporta el reparto.
4. **Distribución = Poisson** (NO NegBin). Los eventos de UN jugador en un partido son
   conteos muy chicos (0, 1, rara vez 2); no hay la sobre-dispersión que justificó
   NegBin en conteos por-equipo.
5. **Patas `faltante` cuentan como no-modelables** para techo y confianza (no se pueden
   valorar) pero se **etiquetan distinto** en la UI ("datos pendientes", no "exótico").
   **Deuda obligatoria de roadmap:** conseguir una fuente de tiros-al-arco por jugador
   (Opta u otra) en una fase futura. No es opcional, es pendiente declarado.
6. **UI mínima incluida** en este proyecto: la pantalla de análisis muestra la pata
   `player` con su % y lista las `faltante` aparte.

## Matemática

Para un jugador titular de un equipo con goles esperados `λ_equipo` (de Capa 1,
neutral para Mundial):

```
λ_gol_jugador   = λ_equipo × cuota_gol(jugador)
λ_asist_jugador = λ_equipo × cuota_asist(jugador)

P(anota ≥1)         = 1 − e^(−λ_gol_jugador)
P(asiste ≥1)        = 1 − e^(−λ_asist_jugador)
P(anota o asiste ≥1) = 1 − e^(−(λ_gol_jugador + λ_asist_jugador))
P(anota ≥ n)        = 1 − Poisson.cdf(n−1, λ_gol_jugador)   # umbral del boleto (default n=1)
```

- `anota o asiste` trata gol y asistencia como eventos aditivos (un jugador no se asiste
  su propio gol → aproximación estándar, error pequeño).
- Las cuotas se estiman por método de momentos con shrinkage hacia un prior:
  `cuota = (Σ ratios + k·prior) / (n + k)`, prior = `1/n_titulares` (cuota igualitaria),
  k = fuerza del prior (arranca en 5, igual que counts; se puede tunear).
- `cuota_gol(jugador)` = fracción de goles del equipo que metió el jugador, en partidos
  donde fue titular, encogida hacia el prior. Análogo `cuota_asist`.

## Arquitectura (espejo del patrón `count`)

Datos (offline) → modelo puro → fit con gate → load params → ruteo en analyzer → OCR →
motor → UI.

### 1. Capa de datos (offline, en `.venv-fbref`)
- **`download_player_events.py`**: para los ~561 event_ids ya enumerados, baja con
  `curl_cffi` + header `x-fsign` (sin browser):
  - `df_sui_1_{eid}` → eventos: `tipo` (Goal/Assistance/…), jugador (`IF` nombre,
    `IM` playerId, `IU` URL canónica), lado (`IA`), minuto (`IB`), mitad (`AC`).
  - `df_li_1_{eid}` → alineaciones: quién fue **titular** (denominador de "partidos como
    titular").
- **Tabla Supabase `eventos_jugador_flashscore`**: `event_id, equipo_id, player_id,
  player_nombre, player_url, tipo, minuto, mitad, fue_titular`. Identidad de equipo reusa
  el sistema `equipo_id`; identidad de jugador por `player_id` nativo de Flashscore (id
  estable, NO fuzzy).
- Idempotente (upsert por `event_id`+`player_id`+`tipo`+`minuto`), con reporte de
  cobertura (igual que el loader de flashscore actual).

### 2. `player_model.py` (puro, sin red — espejo de `counts_model.py`)
- `estimar_cuotas(partidos_jugador: list[dict], k: float = 5.0) -> dict`: por jugador,
  `cuota_gol` y `cuota_asist` con shrinkage hacia `1/n_titulares`.
- `class PlayerModel`:
  - `from_params(params)` (params congelados desde Supabase).
  - `tiene(player_id, metric)` → bool (solo métricas gateadas).
  - `prob(player_id, metric, lambda_equipo, umbral=1) -> float` → la prob Poisson de la
    sección Matemática. `metric ∈ {goal, assist, goal_or_assist}`.

### 3. `fit_player_model.py` (gate offline — espejo de `fit_counts_model.py`)
- Estima cuotas sobre el train, valida cada métrica (`goal`, `assist`) contra baseline
  (todos los titulares con cuota igualitaria `1/n_titulares`) por **Brier en holdout**.
- Split fraccional por fecha (igual fix que counts). Publica SOLO lo que vence al
  baseline. Si solo `goal` pasa, se publica solo `goal` (y `goal_or_assist` se deriva si
  ambos componentes existen; si `assist` no pasa, `goal_or_assist` no se publica).

### 4. `load_player_model_to_supabase.py`
- Params congelados versión **`player_v0.1`** en `parametros_modelo` (JSON en `notas`,
  consistente con counts). Contiene cuotas por `player_id` + metadatos (k, prior, qué
  métricas pasaron).

### 5. Integración al motor
- **`analyzer._load_player_model`**: carga congelada en warm-up (junto a counts).
  El `PlayerModel` se pasa a `analyze_bet_builder` igual que `counts_model`.
- **`betbuilder.py`**: nueva rama `is_player` en el loop de selecciones.
  - La pata `player` necesita `λ_equipo` del lado del jugador → se toma de `lh`/`la` ya
    calculados por Dixon-Coles (lado resuelto del nombre del equipo del jugador).
  - Su prob entra al techo como **una marginal más** (`min` conservador) y al
    `prob_estimada` como factor producto (misma mecánica que `count`).
  - Patas `faltante` → cuentan en `n_exoticas` (no-modelables) pero se acumulan en una
    lista separada `faltantes_desc` (distinta de `exoticas_desc`) para etiquetado.
- `verdict`/`bb_confidence` no cambian de firma. Las patas `player` modelables bajan
  `n_exoticas`; las `faltante` lo suben (correctamente: no se pueden valorar).

### 6. OCR (`ocr.py`)
- Reconoce `mercado="player"` con campos nuevos: `player` (nombre tal cual el boleto),
  `metric` (`goal`/`assist`/`goal_or_assist`/`sot`), `umbral` (default 1).
- "Tiros al Arco" de un jugador → `mercado="player"`, `metric="sot"`, `faltante=True`.
- **Resolución de nombre** OCR→`player_id`: fuzzy `token_set_ratio` contra el catálogo de
  jugadores (`eventos_jugador_flashscore`), igual patrón que el alias de equipos. Si no
  resuelve con confianza, la pata cae a no-modelable etiquetada "jugador no reconocido".

### 7. UI mínima (React)
- `SelectionCard` muestra la pata `player` con su % calculado (como las demás
  modelables).
- Las patas `faltante` se listan en una sección propia "datos pendientes" (visualmente
  distinta de "PATAS NO MODELADAS"/exóticas).

## Manejo de errores / casos límite
- **Partido con 0 goles del equipo**: la cuota por-partido `player_goles/team_goles` es
  0/0 (indefinida). Se excluye ese partido del denominador de cuota (no aporta
  información de reparto); sí cuenta como partido-titular para el prior.
- Jugador sin historial suficiente → cuota = prior (shrinkage total), pata sigue
  modelable pero con cuota igualitaria (señal débil, honesta).
- Nombre OCR no resuelto → no-modelable etiquetada (no se inventa un player_id).
- Equipo del jugador sin cobertura en Capa 1 (`lh`/`la` None) → la pata player no se
  puede valorar (cae a no-modelable, igual que las patas goal sin cobertura).
- `metric` gateada ausente para la liga → `tiene()` devuelve False → pata exótica
  (mismo contrato que counts).

## Testing (TDD)
- `player_model.py`: `estimar_cuotas` (shrinkage hacia prior, cuotas ~suman 1 entre
  titulares); probs Poisson (anota/asiste/anota-o-asiste; umbral ≥2).
- `fit_player_model.py`: gate vence/no-vence baseline.
- `betbuilder.py`: ruteo (player baja `n_exoticas`; `faltante` cuenta como no-modelable
  y va a `faltantes_desc`; techo `min` incluye marginal player; `prob_estimada` la
  multiplica).
- `ocr.py`: clasificación player (nombre+metric+umbral); "tiros al arco" → faltante.
- Resolución de nombre: fuzzy match (caso exacto, abreviado, no-resuelto).
- Suite actual (183) sigue verde.

## Criterio de éxito
- `goal` y/o `assist` **pasan el gate** (vencen baseline Brier en holdout INT). Si solo
  pasa `goal`, se publica solo eso (igual que counts publicó solo shots/sot).
- E2e: re-analizar BET5 → "Bruno Fernandes anota o asiste" deja de ser exótica y aparece
  con su %; "Ronaldo tiros al arco" aparece como **faltante**. Verificación visual humana.

## Fuera de alcance (YAGNI)
- Jugador amonestado (situacional como tarjetas).
- Tiros-al-arco por jugador (deuda de datos obligatoria, fase futura — fuente Opta u
  otra).
- Liga 1 (fase posterior; el feed la cubre, pero se prioriza Mundial).
- Modelar minutos de suplentes / distribución de minutos.
- Refactors no relacionados.

## Riesgos abiertos
1. **El gate puede fallar** (como tarjetas). Mitigación: anytime-goalscorer tiene skill
   conocido (goleador ES rasgo del jugador); optimismo mayor que con tarjetas.
2. **Resolución de nombre OCR→player_id** (abreviaturas, homónimos). Fuzzy + umbral de
   confianza; sin resolver → no-modelable etiquetada.
3. **Cuota histórica vs cambio de rol/equipo** del jugador. Shrinkage mitiga, no elimina.
4. **Asistencias más ruidosas** que goles; `assist` puede no pasar el gate (solo `goal`).
5. **`x-fsign` estático** y slugs genéricos — riesgos heredados del scraper Flashscore
   (ver [[project-capa2-dudas-abiertas]]).

[[ADR-0001]]
[[project-capa2-subproyecto-b]]
[[reference-capa2-datasources]]
[[project-capa2-flashscore]]
