# Capa 2 · Sub-proyecto B — Modelo de conteos (córners/tarjetas/tiros) e integración al motor

**Fecha:** 2026-06-23
**Estado:** Diseño aprobado (brainstorming). Siguiente: plan de implementación.
**Depende de:** `estadisticas_flashscore` (Supabase, 1336 filas cargadas — Sub-proyecto Flashscore pipeline cerrado).

## Objetivo

Modelar las métricas de conteo **córners, tarjetas, tiros y tiros al arco** desde
`estadisticas_flashscore` e integrarlas al motor de bet builder como una **segunda
familia de mercados** ("count"), para que dejen de contar como **patas exóticas**.

Resultado buscado (en términos del mecanismo `n_exoticas` ya existente en
`betbuilder.py`): un ticket típico de 7 patas con resultado + goles + córners +
tarjetas debe bajar de "4+ exóticas → BAJA" a "≤2 exóticas → MEDIA/ALTA", quedando
exóticas solo las patas verdaderamente no modelables (goleador, 1ª/2ª mitad).

## Contexto del código existente (no romper)

- **Motor de goles** (`betbuilder.py`): `joint_ceiling` calcula la conjunta EXACTA de
  las patas de goles sobre la matriz de marcadores Dixon-Coles. `GOAL_MARKETS = {1X2,
  over_under, btts, handicap, resultado_exacto}`. Todo lo demás se marca exótico.
- **Veredicto por techo** (`verdict`): el techo es una **cota superior** de la prob real.
  `SIN_VALOR` si techo ≤ 1/cuota (garantizado). `VALOR` (+ Kelly) solo si `n_exoticas==0`
  y el techo es exacto (familia goles sola). `NO_CONCLUYENTE` si hay exóticas.
- **Confianza** (`bb_confidence`): `n_exoticas==0 → ALTA`, `≤2 → MEDIA`, `>2 → BAJA`.
- **Modelo intl** (`engine_intl_v01.py`): patrón a espejar — ataque/defensa por equipo
  (multiplicativo en log), params **congelados** cargados desde Supabase
  (`parametros_modelo`) vía `from_params`, gate por Brier vs baseline ingenuo.
- **OCR** (`ocr.py`): hoy clasifica córners/tarjetas/tiros como `mercado="exotic"`
  (línea ~115). Esta es la razón por la que el motor no los ve.
- **Regla de oro:** la suite actual (172 tests) sigue verde; el runtime de la API no
  cambia su contrato externo.

## Decisiones de diseño (cerradas en brainstorming)

1. **Combinación entre familias = AMBAS.** El motor reporta:
   - **Techo conservador** (cota superior) = `min(joint_goles, marginales_count…)`.
     Preserva la garantía de "cero falsos positivos" y *tightens* la detección de
     SIN_VALOR (más patas modelables → techo más bajo → mejor detección).
   - **Estimado por independencia** = `joint_goles × Π(marginales_count)`. Señal extra
     informativa (asume familias ~independientes), con su aviso de confianza.
2. **Alcance de métricas:** córners + tarjetas (amarillas/total) + tiros + tiros al arco.
   Cada una como over/under **total (partido)** y **por equipo**.
3. **Muestra fina (Mundial) = shrinkage + gate por liga.** Estimación por-equipo con
   regresión a la media (empírico-Bayes por tamaño de muestra). Cada métrica pasa un
   gate (vencer baseline promedio-liga en holdout) **por separado para INT y Liga 1**;
   solo se publica lo que aporta señal.

## Arquitectura

Cinco componentes, cada uno con un propósito y testeable de forma aislada.

### 1. `counts_model.py` — el modelo (funciones puras + clase, sin red)

Esqueleto análogo a `engine_intl_v01.py` pero para conteos y **sin** la corrección
bivariada de marcador bajo (córners/tarjetas no tienen el fenómeno 0-0 de los goles).

- Para cada métrica `m ∈ {corners, cards, shots, sot}`, por equipo:
  - **ataque** `atk_m[equipo]` = cuánto GENERA de esa métrica (córners a favor).
  - **defensa** `def_m[equipo]` = cuánto CONCEDE (córners en contra).
  - Ambos con **shrinkage** hacia 1.0 (media de liga) proporcional al nº de partidos:
    `mult = (n·tasa_equipo + k·media_liga) / (n + k)` normalizado → `k` = fuerza del prior.
- Esperados:
  - `λ_home_m = base_liga_m · atk_m[home] · def_m[away] · factor_local_m`
  - `λ_away_m = base_liga_m · atk_m[away] · def_m[home]`
  - `factor_local_m` = ventaja de local específica de la métrica (córners de local > visitante).
  - Para INT en sede neutral (Mundial fase de grupos+) `factor_local_m = 1`.
- **Distribución Negative Binomial** (closed-form, sin simulación). Decisión basada en
  evidencia: se midió el índice de dispersión (var/media) sobre `estadisticas_flashscore`
  y **tiros (1.55–1.82) y tiros al arco (1.22–1.36) están sobre-dispersos**; Poisson los
  descalibra 4.7–5.1 pp en líneas típicas, NegBin a 0.2–2.6 pp. Córners/tarjetas tienen
  sobredispersión leve (1.0–1.34). Por eso NegBin es el default; **Poisson es el caso
  límite** (dispersión `d→1`, ej. tarjetas Liga 1 con d=0.96).
  - Se estima **un índice de dispersión `d_m` por (métrica, liga)** (var/media de los
    totales por partido). Para una media `λ`: `r = λ/(d−1)`, `p = 1/d`, `X ~ NegBin(r, p)`
    (recupera media `λ`). Si `d ≤ 1` se usa Poisson(`λ`).
  - Over/under **por equipo**: `P(X_team > linea)` con `λ_team_m`.
  - Over/under **total**: `λ_total = λ_home_m + λ_away_m` con la misma `d_m` (aproxima la
    suma como una sola NegBin; validado en el gate sobre totales).
- Params **separados por liga**: `INT` (Mundial + Euro juntos — comparten pool de
  selecciones) y `Liga 1` (clubes peruanos). El loader elige el set según la liga del
  partido (reusa el ruteo Liga1/intl que ya existe en el analyzer).
- `from_params(...)` congelado (patrón intl): carga `{liga: {metric: {base, factor_local,
  atk, def}}}` desde dicts; no reajusta en warm_up.

### 2. `fit_counts_model.py` — ajuste offline + gate (corre fuera del runtime)

- Lee `estadisticas_flashscore` (Supabase o un dump CSV), separa por liga.
- Estima `atk/def/base/factor_local` con shrinkage (método de momentos + prior `k`).
- **Holdout temporal** por liga (train ≤ fecha corte, test después).
- **Gate por (métrica, liga):** baseline = promedio-liga local/visitante (sin
  per-equipo). Métrica del modelo gana si su Brier/log-loss de over/under (en líneas
  típicas: córners 8.5/9.5, tarjetas 3.5/4.5, tiros 22.5, sot 7.5) supera al baseline
  por un margen relativo mínimo (≥3%, igual umbral que intl).
- **Solo las parejas (métrica, liga) que pasan el gate se publican.** Las que no pasan
  quedan registradas como "no modelable para esta liga" → siguen contando exóticas ahí.
- Persiste params en `parametros_modelo` (Supabase) con una clave de modelo
  (`counts_v0.1`), espejando `load_intl_to_supabase.py`.

### 3. `betbuilder.py` — integración (la pieza que des-exotiza)

- Familia genérica **COUNT** parametrizada por métrica (un único code-path para las 4):
  - Mercado `count` con campos `metric` (corners/cards/shots/sot), `scope`
    (total | home | away), `seleccion` (over/under), `linea`.
  - `count_leg_prob(model, metric, scope, sel, linea, home, away, neutral) -> float`
    (marginal desde el Poisson correspondiente).
- **Multi-pata dentro de la familia count:**
  - Patas sobre la **misma métrica+scope** (raro, ej. over 8.5 Y over 9.5): se evalúan
    sobre el mismo Poisson (la más restrictiva domina) → exacto.
  - Patas sobre **distinto scope/métrica**: correlacionadas → se combinan por `min`
    (cota superior).
- **Techo global** = `min(joint_goles_familia, marginal_count_1, …, marginal_count_k)`.
  Cota superior válida (Fréchet). Si no hay patas de goles, el techo es el `min` de las
  marginales count. Drives `SIN_VALOR`.
- **Estimado por independencia** (`prob_estimada`) = `joint_goles · Π(marginales_count)`.
  Campo nuevo, informativo. NO cambia el veredicto; se muestra con su confianza.
- **`n_exoticas`** = patas en NINGUNA familia modelable (goles ni count gateado para esa
  liga). Una métrica que no pasó el gate para la liga del partido → su pata cuenta exótica.
- **Veredicto:** sigue manejado por el techo (cota superior conservadora). `VALOR` exacto
  (+ Kelly) solo cuando hay **una sola familia** presente y su conjunta es exacta (goles
  sola, o count de una sola métrica+scope). Para tickets mezclados totalmente modelables
  (sin exóticas) el techo es cota superior, así que NO se afirma VALOR; se reporta el
  **estimado** con confianza ALTA/MEDIA. Detalle de la tabla de veredictos en el plan.

### 4. `ocr.py` — taxonomía estructurada

- El prompt del OCR aprende a emitir mercados de conteo estructurados en vez de
  `"exotic"`:
  - `mercado="count"`, `metric ∈ {corners, cards, shots, sot}`, `scope ∈ {total, home,
    away}`, `seleccion ∈ {over, under}`, `linea` (float).
  - Reconoce expresiones: "más de 9.5 córners", "córners local +4.5", "tarjetas más de
    3.5", "remates al arco +7.5", etc.
- `"exotic"` queda SOLO para lo verdaderamente no modelable: goleador, asistencias,
  amonestado individual, 1ª/2ª mitad, etc.
- Compatibilidad: las selecciones viejas con `mercado="exotic"` siguen funcionando
  (caen al path exótico). El cambio es aditivo.

### 5. `analyzer.py` — ruteo

- En el path de selección simple (no bet builder) y en el serializer, los mercados
  `count` se rutean a `count_leg_prob` (marginal informativa), igual que hoy se hace con
  over_under de goles. `mercado_exotico` pasa a ser True solo si la métrica no está
  gateada para la liga.

## Flujo de datos

```
estadisticas_flashscore (Supabase)
        │  (offline, una vez)
        ▼
fit_counts_model.py  ──gate por (métrica,liga)──►  parametros_modelo (counts_v0.1)
                                                          │ (warm_up)
                                                          ▼
            ┌──────────────── counts_model.from_params ───────────────┐
            │                                                          │
  ticket OCR (ocr.py: count markets) ──► analyzer ──► betbuilder ──► ParlayAnalysis
                                                       │  techo = min(goles, count…)
                                                       │  estimado = goles · Π count
                                                       │  n_exoticas = no-modelables
                                                       ▼
                                              veredicto + confianza + estimado
```

## Testing

- **TDD de funciones puras** (sin red): shrinkage, λ por métrica, Poisson over/under
  total y por equipo, techo `min` entre familias, estimado por independencia, conteo
  correcto de `n_exoticas`, mapeo OCR de strings → mercado count.
- **Gate offline:** `fit_counts_model.py` imprime el reporte de Brier por (métrica,liga)
  y la decisión publicar/no-publicar. No es test unitario (depende de datos).
- **Regresión:** suite actual (172) sigue verde; tests nuevos en
  `tests/test_counts_model.py` y extensiones a `tests/test_analyzer_betbuilder.py`.

## Fuera de alcance (YAGNI)

- Mercados **por jugador** (goleador, amonestado, asistencias) — Sub-proyecto futuro
  (feed `df_sui_1`, ya investigado y viable).
- Splits **1ª/2ª mitad** — mismo feed, futuro.
- **Mean-variance NB1 vs NB2 / dispersión dependiente de la media**: v0.1 usa un único
  `d` por (métrica, liga). Refinar la relación media-varianza solo si el gate lo pide.
- **Data live / diaria** — el modelo usa la data histórica ya cargada.
- Mejoras al motor de goles (Tweedie / corrección xG×prob del video de referencia) —
  ortogonal, futuro.

## Criterios de éxito

1. Al menos **córners y tarjetas** pasan el gate para **INT** (Mundial) — es la prioridad.
2. Un bet builder de prueba con patas de goles + córners + tarjetas reporta techo,
   estimado y `n_exoticas` reducido respecto al comportamiento actual.
3. Suite 172 verde + tests nuevos verdes.
4. Sin cambios al contrato externo de la API ni al motor de goles.
