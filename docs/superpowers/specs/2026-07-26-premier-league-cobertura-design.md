# Premier League — cobertura completa (goles + conteos + jugador) — diseño

**Fecha:** 2026-07-26 · **Fase:** nueva pata de cobertura (post-Mundial)
**Aprobado por:** Angel (brainstorm de esta fecha)

## Problema y contexto

El Mundial 2026 terminó. Angel quiere dirigir el motor a la **Premier League**. La
intuición inicial ("los datos del Mundial igual nos servirían") es solo a medias y
conviene dejarla explícita para no crear expectativas falsas:

- **Lo que transfiere al 100% (lo caro, ya construido):** el motor (Dixon-Coles +
  Poisson para goles, NegBin para conteos, top-down para jugador), el pipeline de
  ingesta, el esquema de Supabase, el ruteo del analyzer y el frontend.
- **Lo que NO transfiere:** los *datos*. El modelo internacional aprende parámetros
  de **selecciones** (`martj42/international_results`). La Premier es **fútbol de
  clubes**: Arsenal/City/Liverpool no están en ese dataset, y las stats de un
  jugador con su selección ≠ con su club. El Mundial no predice la Premier.

**Conclusión de encuadre:** esto NO es empezar de cero. Es **alimentar la máquina
existente con datos de la Premier**. Estructuralmente, la Premier es "el stack de
liga de clubes (como la Liga 1 Peruana) apuntado a Inglaterra", con la ventaja de
que Flashscore y API-Football la cubren mucho mejor que a la Liga 1.

## Decisiones de diseño (Q&A con Angel, 2026-07-26)

1. **Alcance: paridad completa desde el arranque** — goles + conteos por equipo +
   props por jugador (anota/asiste y tiros-al-arco). Se entrega en capas por
   dependencia de datos, pero las cuatro están en el alcance de este proyecto.
2. **Profundidad: 3 temporadas** — 2022/23, 2023/24, 2024/25 (nomenclatura
   API-Football: temporada "2024" = 2024/25). Da volumen para que los props
   por-jugador tengan ≥~10 partidos como titular (umbral conocido para que el gate
   pase; ver [[project-capa2-modelo-por-jugador]]).
3. **Enfoque A: replicar el stack de liga de clubes** — reusar el pipeline
   existente, fuentes mixtas casi todas gratis. Descartados: B (todo API-Football,
   quema el presupuesto de 100/día) y C (solo Flashscore sin SoT por-jugador).

## Fuentes por capa

Todo con `liga_id` de la Premier; **no se crean tablas nuevas**, solo filas nuevas.

| Capa | Fuente | Costo API | Script base a adaptar |
|------|--------|-----------|----------------------|
| Resultados → goles (DC) | API-Football fixtures (liga 39) | ~3 req total | `download_fixtures.py` |
| Conteos equipo (tiros/SoT/córners/tarjetas) | Flashscore scrape | Gratis | `download_flashscore_stats.py` |
| Anota/asiste jugador | Flashscore feeds | Gratis | `download_player_events.py` |
| Tiros-al-arco jugador | API-Football `/fixtures/players` | ~90/día, resumable | `download_sot_jugador.py` |

**Riesgo a validar temprano (probe, no bloquea):** confirmar que el plan Free de
API-Football da acceso a las 3 temporadas de la liga 39 (la Liga 1 nos dio
2022-2024; sondear `/leagues`). Si el Free capa temporadas viejas, se ajusta el
rango a lo disponible.

## Arquitectura de ingesta

Reutiliza el esquema completo (`ligas`, `equipos` con `liga_id`+`aliases`,
`partidos`, `estadisticas_flashscore`, tablas de eventos por jugador y de SoT).
Pasos, en orden de dependencia:

**0. Semilla de liga y equipos.**
- Adaptar `download_fixtures.py`: `LIGA1_ID=281 → 39`, temporadas `[2022,2023,2024]`.
  Inserta la fila `liga` (Premier League), los 20 equipos y ~1140 `partidos` con
  marcador. ~3 requests API.
- **`set_pl_aliases.py`** (nuevo, espejo de `set_intl_aliases.py`): alias de casa de
  apuestas → `nombre_oficial` ("Man City"→"Manchester City", "Tottenham"→"Tottenham
  Hotspur", "Wolves"→"Wolverhampton", "Spurs", "Man Utd", "Newcastle", etc.). Sin
  esto el OCR de boletos no resuelve equipos.

**1. Conteos por equipo (Flashscore, gratis).**
- Adaptar `download_flashscore_stats.py` al slug histórico de la Premier (confirmar
  patrón de URL de archivo por temporada, como pasó con Euro2024). Enumera
  `event_ids` y baja tiros/SoT/córners/tarjetas por partido-equipo →
  `flashscore_stats.csv` → `load_flashscore_stats_to_supabase.py` (resuelve
  `equipo_id`, puebla `estadisticas_flashscore`).

**2. Anota/asiste por jugador (Flashscore, gratis).**
- `download_player_events.py` reusa los `event_ids` del paso 1 (2 feeds livianos por
  partido: eventos + alineaciones) → `player_events.csv` → load a Supabase. Aplicar
  la lección conocida: unir `df_sui_1` + goleadores del `LIT` para no subestimar
  goles (ver [[project-capa2-modelo-por-jugador]]).

**3. Tiros-al-arco por jugador (API-Football, background, ~13 días).**
- `download_sot_jugador.py` ya es un backfill resumable con manifiesto
  `(liga, temporadas)`. Añadir `(39, [2022,2023,2024])`, correr `descubrir` (~1140
  fixtures pendientes) y `hidratar` ~90/día en `/loop`. Publica cuando drena; no
  bloquea las capas 0-2.

**Gate de cobertura de identidad** tras cada carga: reportar % de equipos/jugadores
resueltos antes de modelar. La Premier debería dar identidad casi perfecta (nombres
en inglés estándar).

## Fit, gates y publicación

Cada capa usa su script de fit existente (los de conteos/jugador **ya separan por
liga**), pasa (o no) su gate, y se publica con su `load_*`. **Nada se publica si no
pasa el gate** — misma disciplina honesta de siempre (en Liga 1 córners/tarjetas
por-equipo NO pasaron; el ELO tampoco). Todos los gates exigen **≥3% de mejora
relativa** sobre baseline, en holdout temporal (último 30% por fecha).

| Capa | Script fit | Gate | Publica (versión, con `liga_id` PL) |
|------|-----------|------|------------------------------------|
| Goles (DC) | `engine_v02` | Batir baseline ingenuo (tasas liga) ≥3% | params DC de la Premier |
| Conteos equipo | `fit_counts_model` | Por (métrica, liga) vs promedio-liga, líneas reales | `counts_v0.1` |
| Anota/asiste | `fit_player_model` | Por métrica vs `1/n_titulares` (Brier), `MIN_PARTIDOS=10`, `K=3` | `player_v0.2` |
| Tiros-al-arco jugador | `fit_player_sot` | vs `1/n_titulares` (Brier), λ_sot real, `MIN_PARTIDOS=10` | `player_sot_v0.1` |

**Versionado:** las tablas de parámetros ya están keyed por `(liga_id,
version_modelo)`, así que la Premier convive con Liga 1 e Internacional sin colisión.
Se reutilizan los mismos strings de versión con el `liga_id` de la Premier. Cero
riesgo para producción.

**Expectativa honesta de cada gate (garantizamos el método, no el resultado):**
- **Goles:** casi seguro pasa (señal fuerte, datos limpios y abundantes).
- **Conteos:** tiros y tiros-al-arco probablemente pasan; córners y tarjetas
  por-equipo históricamente NO (situacionales) — si se repite, no se publican esas
  métricas.
- **Anota/asiste y SoT jugador:** riesgo real, pero 3 temporadas + `MIN_PARTIDOS=10`
  dan mejor base que la Liga 1. Gate que no pasa → esa pata queda `faltante`
  (mercado conocido, sin publicar) en vez de dar un número malo.

## Integración en el analyzer: ruteo binario → N-ligas

**El único cambio de código de fondo.** Hoy el ruteo es binario y asume "lo que no
es internacional = liga1" (`analyzer.py:711`). Un equipo de la Premier caería mal
ruteado a la Liga 1. Se generaliza a un registro de N ligas, con TDD y **regresión
blindada** (Liga 1 e Internacional deben quedar idénticos). Cuatro puntos:

1. **`_load_team_liga_map`** → `equipo_id → liga_key` real (liga1 / premier /
   internacional), no binario.
2. **`_load_and_fit`** → ajustar y cachear **un DC por liga de clubes** (dict
   `liga_id → (model, team_match_count)`), cada uno desde los `partidos` de esa liga.
   Hoy ajusta uno solo.
3. **`_liga_de_parlay`** → devolver la liga de clubes específica; **"mixto" rechaza
   cualquier cruce** entre ligas (Liga1+Premier, Premier+intl…), no solo intl+liga1.
   Un boleto es de una sola liga.
4. **Ruta de análisis de clubes** → seleccionar el DC y el `team_match_count` de la
   liga del parlay. Los loads de conteos/jugador ya resuelven params por `liga_id`,
   así que heredan la Premier al resolver la liga desde los equipos del boleto.

**Frontend:** sin trabajo nuevo. Los boletos de Premier fluyen por las cards
genéricas existentes (goles/conteos/jugador). Se añade un caso `?demo=premier` para
verificar visualmente sin red (como en ausencias). La idea de "visuales propios de
Capa 2" queda como pulido opcional aparte, fuera de este proyecto.

## Secuenciación y entrega

Cada capa es un hito publicable e independiente (con su gate + e2e + OK de Angel):

1. **Ruteo N-ligas + goles Premier** — refactor del analyzer, ingesta de fixtures,
   fit DC, gate, e2e de un boleto de goles PL. Es el hito que desbloquea todo.
2. **Conteos por equipo** — scrape Flashscore, fit, gate por métrica, publica lo que
   pasa.
3. **Anota/asiste por jugador** — feeds Flashscore, fit, gate, publica.
4. **Tiros-al-arco por jugador** — backfill resumable en background; publica al
   drenar.

## Validación

- Suite verde incluyendo **tests de regresión** de que Liga 1 e Internacional no
  cambian tras el refactor de ruteo.
- `conftest.py` con fixture autouse para que ningún test dispare scrape/API real.
- e2e real por capa: un bet builder de Premier de verdad (p.ej. Arsenal-Chelsea con
  una pata de goles + una de conteo + una de jugador) recorriendo todo el stack, y
  verificación visual de Angel.
- **Datos frescos (transversal, fuera de alcance):** la ingesta es one-shot; para
  uso en temporada viva habrá que re-scrapear periódicamente. Se anota, no se
  resuelve aquí.

## Fuera de alcance (YAGNI)

- Otras ligas (LaLiga, Serie A…): el ruteo N-ligas las habilita, pero no se ingestan
  ahora.
- Visuales propios de Capa 2 en el frontend (pulido opcional).
- Mecanismo de refresh automático de datos (transversal).
- Google+LLM para eventos/lesiones de la Premier (la capa de ausencias Sofascore ya
  existe y aplica a cualquier liga; ver [[project-ausencias-lesiones]]).

[[project-roadmap]]
[[project-capa2-modelo-por-jugador]]
[[project-capa2-subproyecto-b-conteos]]
[[project-tiros-al-arco-jugador]]
[[project-ausencias-lesiones]]
