# Diseño — Tiros al arco POR-JUGADOR (SoT por jugador)

**Fecha:** 2026-06-25
**Fase:** Roadmap Fase 2, paso 1 (completar cobertura — añadir una pata que las casas ofrecen).
**Origen:** boletos reales (BET5: "Ronaldo X+ tiros al arco") muestran que las casas ofrecen SoT por-jugador; hoy esa pata cae a `faltante` en `betbuilder`.

## Objetivo

Convertir la pata "tiros al arco por jugador" (`metric="sot"`, familia `player`) de mercado
`faltante` a mercado **servible**, para selecciones internacionales / Mundial, con valor
predictivo real (gate ≥3% sobre baseline).

## Decisiones tomadas (brainstorming)

1. **Competición: Internacional/Mundial primero** (no Liga1). Razones: coherente con el modelo
   por-jugador anota/asiste que ya existe (permite combinar "anota" + "tiros al arco" del mismo
   jugador en un bet builder), y es donde aparecieron los boletos reales. Liga1 queda para después.
2. **Backfill profundo (gate-first)**: varios torneos + clasificatorias + Nations League hasta tener
   jugadores con ≥10 apariciones. Necesario para que el gate pase (lección de anota/asiste: con
   pocos partidos la cuota es ruido). Plan Free de API-Football (~100 req/día) → backfill goteado y
   resumable.
3. **Arquitectura A — top-down desde el λ_sot de `counts_model`** (ver comparación abajo).

### Por qué A y no B/C (decisión por criterios, no por gusto)

| Criterio | A (top-down counts) | B (bottom-up absoluto) | C (fold Flashscore) |
|---|---|---|---|
| Valor predictivo (ajuste rival/sede/neutral) | ✅ vía `def` de counts_model | ❌ lo pierde | ✅ |
| Reuso de código existente | ✅ player_model + counts_model | 🟡 parcial | 🟡 |
| Linaje de datos limpio | ✅ API-Football aislado | ✅ | ❌ reconciliar IDs |
| Coherencia con anota/asiste | ✅ misma mecánica | ❌ | ✅ |
| Factibilidad de datos | ✅ feed trae SoT | ✅ | ❌ Flashscore NO trae SoT |

- **C eliminado por factibilidad**: el feed de Flashscore no trae SoT por jugador (ya marcado
  `faltante` en el proyecto). Reusar sus IDs no aporta porque igual hay que ir a API-Football.
- **B eliminado por valor**: pierde el ajuste de enfrentamiento, que es justo donde está el *edge*
  (Haaland 2+ SoT vs defensa cerrada ≠ vs defensa abierta). El top-down lo captura gratis vía los
  multiplicadores `def` del counts_model.
- **A gana en todo criterio que no empata.**

## Arquitectura y flujo de datos

```
        API-Football /fixtures (por liga+temporada)  ── descubre fixtures intl
                              │
                              ▼
   download_sot_jugador.py  ──(1 req/fixture, resumable, ~100/día)──►
                              │  /fixtures/players → shots.on por jugador
                              ▼
              tabla nueva: eventos_sot_jugador
        {event_id, equipo_id(canónico), player_id, player_nombre,
         sot, fue_titular, minutos, liga_api_id, fecha}
                              │
                              ▼
              fit_player_sot.py  (gate Brier vs baseline)
        cuota_sot = sot_jugador / sot_equipo  (shrinkage → 1/n_titulares)
                              │  si pasa gate
                              ▼
              player_sot_v0.1  (params en Supabase)
                              │
   SERVING: betbuilder, pata sot por-jugador
   λ_jugador_sot = counts_model.lambdas("sot", home, away, neutral)[lado] × cuota_sot
   P(jugador ≥ umbral SoT) = Poisson(λ_jugador_sot)
```

**Piezas nuevas:** `download_sot_jugador.py`, tablas `eventos_sot_jugador` + `sot_backfill_progreso`,
`fit_player_sot.py`, `load_player_sot_to_supabase.py`.

**Reutilizado sin cambios:** `player_model.estimar_cuotas` (cuota+shrinkage), `PlayerModel`
(resolver fuzzy, equipo_de), `counts_model` (λ_sot por-equipo del Mundial, ya modelado y publicado
en counts_v0.1).

**Cambios quirúrgicos:** `player_model.METRICAS_PLAYER` (+`"sot"`), `PlayerModel.prob` (rama sot),
`betbuilder.player_leg_prob` (λ del counts_model para sot; quitar `faltante`), `analyzer` (cargar
segundo PlayerModel y enrutar por métrica).

## Modelo de datos

### Tabla `eventos_sot_jugador` (una fila por jugador-fixture)

| columna | tipo | nota |
|---|---|---|
| `event_id` | int | `fixture.id` de API-Football (PK junto a player_id) |
| `player_id` | text | `player.id` de API-Football (espacio de IDs propio) |
| `player_nombre` | text | para el resolver fuzzy del serving |
| `equipo_id` | uuid | FK a `equipos`, resuelto por alias/fuzzy como el resto del pipeline |
| `sot` | int | `statistics[0].shots.on` (null → 0) |
| `fue_titular` | bool | `statistics[0].games.substitute == false` |
| `minutos` | int | `games.minutes` (para excluir cameos si hace falta) |
| `liga_api_id` | int | competición de origen |
| `fecha` | timestamptz | `fixture.date`, para el split temporal del gate |

PK compuesta `(event_id, player_id)` → upsert idempotente. DDL vía Supabase Management API
(curl_cffi impersonate chrome).

### Tabla de control `sot_backfill_progreso` (una fila por fixture)

| columna | tipo |
|---|---|
| `event_id` | int (PK) |
| `liga_api_id` | int |
| `temporada` | int |
| `estado` | `pendiente` / `hecho` / `sin_datos` |
| `fecha_proceso` | timestamptz |

## Backfill resumable (dos fases)

**Fase descubrimiento** (barato, ~1 req/liga+temporada): por cada `(liga_api_id, temporada)` del
manifiesto, `GET /fixtures` → upsert de `event_id` en `sot_backfill_progreso` como `pendiente`.
Idempotente.

**Fase hidratación** (cara, 1 req/fixture): toma los primeros N `pendiente` (N = presupuesto diario,
default ~90 para dejar margen), llama `/fixtures/players`, escribe a `eventos_sot_jugador`, marca
`hecho` (o `sin_datos` si el fixture no trae stats). Respeta rate-limit (10/min → sleep) y lee
`x-ratelimit-requests-remaining` para auto-frenar antes del límite diario. Se detiene solo al agotar
presupuesto o pendientes. Sin estado en memoria: re-correr retoma donde quedó (apto para `/loop` o
corrida diaria manual).

### Manifiesto de ligas (constante editable arriba del script)

Lista configurable de `(liga_api_id, temporadas)` de competiciones de selecciones donde se repiten
los jugadores bettables: Mundial + clasificatorias por confederación, Euro + clasificatorias, Nations
League, Copa América, amistosos de selección, AFCON. Los IDs exactos se confirman contra API-Football
en implementación (un par de requests de sondeo; feasibility ya verde). El manifiesto define el
alcance del backfill (= cuántos días) sin tocar lógica.

## Fit y gate

### Estimación de cuotas (`fit_player_sot.py`)

Reutiliza `player_model.estimar_cuotas`. Registro por (jugador, partido-como-titular):

```
{player_id, nombre, equipo, sot_jugador, sot_equipo, n_titulares}
cuota_sot = sot_jugador / sot_equipo
```

Partidos con `sot_equipo == 0` se excluyen del promedio (share indefinido) pero su prior
`1/n_titulares` sí informa el shrinkage. Idéntico a goal/assist salvo numerador/denominador.

### Gate (la decisión crítica de modelado)

El baseline debe usar el **λ_sot del equipo**, no el de goles:

```
baseline:  1 - exp( -λ_sot_equipo / n_titulares )      # "todos tiran igual"
modelo:    1 - exp( -λ_sot_equipo · cuota_sot )         # "el delantero tira más"
```

- **λ_sot del equipo en el gate offline = tasa real observada** de SoT/equipo en el propio dataset
  de backfill (media empírica), NO un proxy inventado. Evita el bug que tuvimos con goal/assist
  (`LAMBDA_PROXY=1.35` sobre-predecía hasta bajarlo a 1.0). La tasa real sale gratis de los datos.
- **Elegibilidad ≥10 partidos** (lección aprendida): el gate solo evalúa jugadores con historial
  (a quienes las casas ofrecen props). Sin esto se diluye con ruido y no pasa.
- **Umbral del gate**: mejora Brier ≥3% sobre baseline. Split temporal 70/30.
- **Distribución**: Poisson para "≥1 SoT" (consistente con player_model); `umbral` ya soporta
  líneas 2+/3+. SoT por-jugador es conteo bajo (0-5). Si en validación aparece sobre-dispersión
  fuerte se evalúa NegBin, pero se arranca con Poisson — lo decide la evidencia, no a priori.

**Riesgo / expectativa:** el SoT está más concentrado en delanteros que los goles (un 9 hace ~60%
de los SoT del equipo), lo que *favorece* que el gate pase (señal de cuota más fuerte). Escenario
optimista, pero no se da por hecho hasta correr el gate con datos reales.

## Integración en serving (cambios quirúrgicos)

1. `player_model.METRICAS_PLAYER`: añadir `"sot"`. `PlayerModel.prob` gana rama `metric=="sot"`
   → `lam = lambda_equipo * cuota_sot`.
2. `betbuilder.player_leg_prob`: si `sel.metric=="sot"`, el λ del equipo viene de
   `counts_model.lambdas("sot", home, away, neutral)` (lado del jugador), NO de `lh/la` (goles).
   goal/assist sigue igual. Requiere pasar `counts_model` a la función (ya disponible en el scope
   de `analyze_bet_builder`).
3. Quitar el `faltante` forzado de la pata `sot` por-jugador. Ahora resuelve de verdad si el
   jugador está en `player_sot_v0.1` y hay `counts_model` con `sot` para esos equipos. Si falta
   cualquiera (jugador desconocido o liga sin λ_sot) → cae a `faltante` con gracia (mecanismo ya
   existe).
4. `analyzer`: cargar `player_sot_v0.1` como segundo `PlayerModel` y enrutar por métrica
   (goal/assist → modelo Flashscore; sot → modelo API-Football). Dos instancias, misma clase.

### `load_player_sot_to_supabase.py`

Clónico de `load_player_model_to_supabase.py`. Publica `player_sot_v0.1` =
`{metricas: ["sot"], jugadores: {pid: {nombre, equipo, cuota_sot}}}` solo si el gate pasó.

## Testing (TDD)

- `test_player_events_sot_transform`: API-Football JSON → filas (sot null→0, suplente→fue_titular
  False, equipo resuelto por alias).
- `test_fit_player_sot`: cuota_sot correcta, exclusión `sot_equipo==0`, gate con datos sintéticos
  donde un "delantero" domina la cuota.
- `test_betbuilder` (extender): pata `sot` por-jugador resuelve vía counts λ_sot; jugador
  desconocido → faltante; sin counts_model → faltante.

## Fuera de alcance (YAGNI)

- Liga1 per-jugador SoT (Fase 2 paso 2, después).
- NegBin para SoT por-jugador (solo si la evidencia muestra sobre-dispersión).
- Frontend específico para la pata SoT (la card de jugador y el veredicto ya manejan la familia
  `player`; reusa lo existente).
- Recuperar SoT histórico vía scraping (API-Football lo da limpio; no hace falta).
