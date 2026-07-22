# Capa de ausencias (lesiones/suspensiones) — diseño

**Fecha:** 2026-07-16 · **Fase:** 3 punto 4 del roadmap ("eventos recientes")
**Aprobado por:** Angel (brainstorm de esta fecha)

## Problema

El motor "vive en un mundo ideal": los α/β del Dixon-Coles internacional salen del
histórico y no saben que hoy Messi está lesionado. Dos consecuencias en boletos
reales: (a) las patas de goles sobreestiman al equipo mutilado, (b) una pata de
jugador ("Messi anota") se analiza como si fuera a jugar cuando está descartado.

## Fuente (confirmada con spike 2026-06-25)

Sofascore renderiza en el DOM: XI confirmado, formación, y **ausentes con motivo y
estado** (ej. `Cristian Roldán — Injured — Muscle`). La API está murada pero el DOM
no: **Scrapling render+DOM** lo lee (~2 min/partido). Probado e2e en Türkiye–USA
(Mundial 2026). La cardinalidad es la correcta: solo los partidos del boleto.
Google+LLM queda como complemento FUTURO (noticias que Sofascore no marque) — fuera
de este spec.

## Decisiones de diseño (Q&A con Angel, 2026-07-16)

1. **Alcance del efecto: equipo Y jugador.** Un ausente ajusta los λ del equipo
   (familia goles) Y se cruza contra las patas de jugador del boleto.
2. **Magnitud: peso real del jugador.** La importancia ofensiva sale de la cuota del
   `player_v0.2` (fracción de los goles del equipo que produce), no de constantes
   inventadas. Defensivos/arqueros (sin cuota ofensiva): constante por posición.
3. **Frescura: on-demand + caché.** Se scrapea al analizar el boleto, caché local
   JSON con TTL 6h. Sin dato → se sirve SIN ajuste y se dice.
4. **Latencia: esperar con etapa visible.** El análisis espera el scrape (~2 min sin
   caché); el loader por etapas del frontend muestra "Consultando ausencias…".

## Arquitectura

Tres unidades nuevas + integración en serving. **Nada toca el fit ni Supabase**: los
ajustes son efímeros, por-predicción, en memoria.

```
boleto → analyzer (_analyze_intl / bet builder route)
              │
              ├─ ausencias_sofascore.obtener_ausencias(home, away)   [scrape + caché]
              │        └→ AusenciasPartido | None
              │
              ├─ ajuste_ausencias.deltas_equipo(ausencias, cuotas_player, posiciones)
              │        └→ multiplicadores (mult_ataque, mult_defensa) por equipo
              │
              ├─ familia goles: lh, la = model.lambdas(...) × multiplicadores
              └─ familia jugador: cruce nombre-pata vs ausentes → ausente:true
```

### 1. `ausencias_sofascore.py` — fuente + caché

- `obtener_ausencias(home: str, away: str) -> AusenciasPartido | None`
  - Busca el partido en Sofascore (equipos internacionales, próximos días), lee el
    DOM renderizado con Scrapling.
  - `AusenciasPartido`: por equipo, lista de `Ausente {nombre, estado, motivo}` con
    `estado ∈ {"out", "doubtful"}`, más `xi_confirmado: list[str] | None` y
    `scrapeado_en` (timestamp).
  - **Caché**: un JSON por partido en `cache_ausencias/` (local, gitignored), clave
    `home_away_fecha`, TTL 6 horas. Con caché vigente NO se scrapea.
  - **Degradación**: partido no encontrado, DOM sin sección de ausencias, timeout o
    challenge → devuelve `None` (nunca lanza hacia el analyzer). El motivo del
    `None` se loguea.
- Resolución de nombres: los nombres de Sofascore se resuelven contra el roster del
  modelo por-jugador (Supabase `player_v0.2` + `player_sot_v0.1`, que ya están
  cargados en serving): match exacto → fuzzy (rapidfuzz ≥ 80, el mismo
  `PlayerModel.RESOLVER_UMBRAL` que ya usa el resolver de jugadores en prod). Un ausente que
  no resuelve contra el roster **se ignora para el ajuste de equipo** (no sabemos su
  peso) pero **sí participa del cruce con patas de jugador** (ahí el nombre del
  boleto es la referencia y se compara directo contra el texto de Sofascore).

### 2. `ajuste_ausencias.py` — lógica pura (sin I/O)

- `deltas_equipo(ausentes_out, cuotas, posiciones) -> (mult_ataque, mult_defensa)`
  - Solo `estado == "out"` ajusta. Los `doubtful` NO ajustan (conservador); solo
    generan aviso.
  - **Ofensivo** (jugador con cuota `q` en player_v0.2):
    `mult_ataque *= (1 − K_AUSENCIA · q)` con **`K_AUSENCIA = 0.6`** — si Messi
    produce el 30% de los goles, su ausencia resta ~18%, no 30%, porque alguien
    ocupa su lugar. Constante de diseño, visible y discutible.
  - **Defensivo/arquero**: `mult_defensa *= (1 + PENAL_DEF)` con
    **`PENAL_DEF = 0.05`** (+5% goles concedidos por titular defensivo ausente).
    **Enmienda (plan 2026-07-17):** el repo NO persiste posiciones (verificado) —
    la posición sale del DOM de Sofascore SI la trae; si no viene, el ausente sin
    cuota ofensiva simplemente no ajusta (fila de la tabla de errores). Enriquecer
    posiciones vía API-Football queda como mejora futura, no bloquea.
  - **Tope global de seguridad**: los multiplicadores acumulados se recortan a
    **[0.70, 1.30]** (±30%) — freno contra scrapes raros o equipos diezmados que
    romperían la matriz de marcadores.
- `cruzar_patas_jugador(patas, ausentes) -> lista de (pata, estado)` — matching por
  nombre (exacto/fuzzy) entre el jugador de la pata y los ausentes.

### 3. Integración en serving (`analyzer.py`)

- En `_analyze_intl` y en la ruta internacional de `_analyze_bet_builder_route`:
  tras identificar home/away, llamar `obtener_ausencias`; si hay dato, aplicar
  multiplicadores a los λ de la familia goles **de ese partido únicamente**.
- **Patas de jugador**:
  - Jugador **out** confirmado → la pata se marca `ausente: true`, su
    `prob_modelo ≈ 0`, y el veredicto del boleto es **SIN_VALOR** con razón visible
    ("Messi no juega: lesión muscular"). Decisión deliberadamente agresiva,
    aprobada por Angel: si el dato dice que no juega, la pata está muerta.
  - Jugador **doubtful** → la pata conserva su prob pero gana warning fuerte y el
    veredicto se degrada a **NO_CONCLUYENTE** ("en duda por lesión").
- **Bloque `ausencias` en la respuesta** (transparencia total): por equipo, los
  ausentes detectados (nombre, estado, motivo), los λ antes/después del ajuste, y
  `"sin_dato": true` cuando el scrape devolvió `None`. El frontend muestra la nueva
  etapa del loader ("Consultando ausencias en Sofascore…") y el detalle del bloque.

## Qué NO hace (YAGNI)

- NO toca el fit, ni los parámetros publicados, ni Supabase (cero escrituras).
- NO ajusta familias conteos ni Liga1 (Liga1 descartada; conteos quedan para después
  si el uso lo pide).
- NO usa Google+LLM (complemento futuro, capítulo aparte).
- NO modela suspensiones por acumulación de tarjetas que Sofascore no liste.
- NO re-scrapea dentro del TTL aunque el partido esté cerca (simplicidad primero;
  si duele, se acorta el TTL).

## Manejo de errores

| Situación | Comportamiento |
|---|---|
| Sofascore sin el partido / sin sección de ausentes | `None` → servir sin ajuste + `sin_dato: true` |
| Scrapling timeout / challenge | igual que arriba (logueado) |
| Ausente no resuelve contra roster | se ignora para α/β, se lista en el bloque `ausencias` |
| Ausente resuelto pero sin cuota NI posición conocida | igual que arriba: sin peso conocido no se inventa ajuste |
| Ajuste acumulado extremo | clamp a ±30% |
| Caché corrupto | se borra y se re-scrapea |

## Validación (sin gate estadístico — asumido)

No existe histórico de lesiones para backtest, así que NO hay gate de Brier. La
validación es:

1. **TDD** de las funciones puras: deltas (cuota alta/baja, defensivo, acumulación,
   clamp), doubtful vs out, resolución de nombres, TTL del caché, cruce de patas.
2. **E2E manual** en 2-3 partidos reales de la fecha (uno con lesionado conocido,
   uno sin dato publicado) — verificación humana de Angel del bloque `ausencias` y
   del veredicto SIN_VALOR con jugador out.
3. El clamp ±30% y el "sin dato → sin ajuste" son las redes de seguridad
   permanentes.

## Constantes del spec

| Constante | Valor | Sentido |
|---|---|---|
| `K_AUSENCIA` | 0.6 | fracción de la cuota del ausente que realmente se pierde |
| `PENAL_DEF` | 0.05 | +5% λ concedido por titular defensivo/arquero out |
| `CLAMP` | [0.70, 1.30] | tope del ajuste acumulado por equipo |
| `TTL_CACHE` | 6 h | vigencia del scrape por partido |
| Fuzzy nombres | ≥ 80 | `PlayerModel.RESOLVER_UMBRAL` (mismo umbral que el resolver de jugadores en prod). El cruce de patas (`cruzar_pata`) usa `WRatio ≥ 80`, no `partial_token_set_ratio`, para no colisionar por apellido compartido |
