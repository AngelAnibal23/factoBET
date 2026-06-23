# Capa 2 · Pipeline de datos Flashscore (córners + tarjetas + tiros + xG)

**Fecha:** 2026-06-23
**Estado:** Diseño aprobado. Implementación pendiente.
**Fase del bet builder:** Fase 3 (Capa 2), pipeline de datos. El modelo Poisson por familia + gate Brier + integración al techo son el **Sub-proyecto B** (spec aparte, después).

---

## 1. Contexto y motivación

El Sub-proyecto A (FBref) ya cargó **tarjetas internacionales** (`estadisticas_partido`, 2.964 filas, tarjetas 100%). Pero FBref **no trae córners** para selecciones, sus **tiros llegan al 50%**, y **no cubre Liga 1 Perú**. Esos huecos dejan exóticos sin resolver: córners (cualquier liga), tiros completos, y todo lo de Liga 1.

El sondeo del 2026-06-23 ([[reference-capa2-datasources]]) determinó que **Flashscore es la única fuente que combina completitud + accesibilidad a escala**:
- Sofascore: datos limpios pero `api.sofascore.com` tras Cloudflare de subdominio, inaccesible a escala (probado: requests/curl_cffi/UC/Scrapling todos 403).
- FBref: sin córners para selecciones, sin Liga 1.
- **Flashscore: córners + amarillas + rojas + tiros + tiros al arco + faltas + offsides + posesión + xG, vía feed liviano.**

### Riesgo #1 (acceso al histórico) — DESPEJADO (2026-06-23)
Probado e2e con el Mundial 2022: la cadena **torneo → event ids → stats** funciona con un patrón **híbrido**:
1. El feed de resultados por torneo (`tr_1_{stage}`, `fs_1_{stage}`) NO es accesible directo (devuelven vacío/HTML de error), aunque se tenga el `stageId` real.
2. **Los event ids salen del DOM renderizado** de `/football/.../results/` (seleniumbase UC, regex `id="g_1_{8char}"`). WC2022 → 126 ids (≈64 partidos ×2, a deduplicar). **Un solo browser-load por edición.**
3. **Las stats se bajan con feed liviano** `df_st_1_{eventId}` (curl_cffi + header `x-fsign: SW9D1eZo`, sin browser, masivo). Verificado: devuelve Corner kicks, Yellow/Red cards, Shots on target, Total shots, Fouls, Offsides, Ball possession, xG con valores local/visitante.

---

## 2. Alcance de este pipeline

**Incluye:** scrapear de Flashscore las estadísticas por partido (córners, tarjetas, tiros, faltas, offsides, posesión, xG) de **INT-World Cup + INT-European Championship + Liga 1 Perú**, resolver identidad de equipos contra `equipos`, y persistir filas crudas **por partido-equipo** en una tabla nueva `estadisticas_flashscore`, con un **reporte de cobertura** (gate antes de modelar).

**NO incluye (es Sub-proyecto B):** modelo Poisson por familia, gate Brier, enchufe al techo del motor, cambios de OCR/validador/frontend.

**Decisiones cerradas:**
1. **Patrón híbrido:** browser (seleniumbase UC) SOLO para enumerar event ids + metadata por edición; feed `df_st` (curl_cffi) para las stats. Minimiza el costo de browser (1 load por edición, no por partido).
2. **Grano: filas crudas por partido-equipo** (2 filas por partido: perspectiva local y visitante), espejo de `estadisticas_partido` de FBref → permite re-fit y time-weighting en B.
3. **Tabla SEPARADA `estadisticas_flashscore`** (no mezclar con `estadisticas_partido` de FBref: convenciones de nombres distintas, evita conflictos de dedup entre fuentes). B decide cuál fuente usa por familia.
4. **Identidad:** reusar `resolver_equipo_id` (fuzzy+alias del validator). Guardar nombre Flashscore crudo + `equipo_id` nullable, loguear huérfanos. Liga 1 puede requerir alta de clubes en `equipos`.
5. **Cobertura inicial:** WC `{2018, 2022, 2026}`, Euro `{2020, 2024}`, Liga 1 `{2023, 2024, 2025}`. Configurable por una lista de torneos (liga, url de resultados, season).

---

## 3. Arquitectura

Dos scripts, espejo del pipeline FBref, ambos corren en `.venv-fbref` (que ya tiene seleniumbase + curl_cffi):

```
[.venv-fbref: seleniumbase UC (ids) + curl_cffi (stats)]      [proyecto: pandas + supabase]
        │                                                            │
  download_flashscore_stats.py ──► flashscore_stats.csv ──► load_flashscore_stats_to_supabase.py
   (browser enumera ids+meta del DOM;                          (resuelve equipo_id → tabla nueva
    curl_cffi baja df_st por partido)                           estadisticas_flashscore + reporte)
```

Funciones puras de parseo/tidy en `flashscore_transform.py` (NO importa seleniumbase ni red; testeable en el entorno del proyecto).

**Por qué híbrido y no solo-browser:** un browser-load por partido (~2-4 min) es inviable para cientos de partidos. El DOM solo se usa para la lista de ids (1 load por edición); las stats van por feed liviano.

**Por qué no Sofascore:** ver [[reference-capa2-datasources]] — inaccesible a escala. Sofascore-live queda como sub-proyecto separado y acotado.

---

## 4. Componentes

### 4.1 `flashscore_transform.py` (puro, testeable sin red)
- `parse_results(html) -> list[dict]`: del DOM de la página de resultados, una entrada por partido: `{event_id, fecha (ISO), home, away}`. Fuente DOM: `id="g_1_{8char}"`, `event__time">DD.MM.YYYY`, dos `data-testid="wcl-participantLogo" ... alt="..."` (home, away).
- `parse_stats_feed(text) -> dict[str, tuple[str,str]]`: del feed packed `df_st` (`SG÷métrica¬SH÷local¬SI÷visitante`), mapea `{métrica: (local, visitante)}`. Toma la **primera ocurrencia** de cada métrica (período "Match"/completo; Flashscore lista el total primero, luego por tiempo).
- `tidy_match(meta, stats, liga, season) -> list[dict]`: 2 filas por-equipo (local y visitante) con columnas canónicas, mapeando nombres Flashscore → columnas vía `METRIC_MAP`. Normaliza posesión (quita `%`) y numéricos.
- Reusa `resolver_equipo_id` (import lazy de `fbref_transform`).

### 4.2 `download_flashscore_stats.py` (en `.venv-fbref`)
- `TOURNAMENTS`: lista de `(liga, results_url, season)`.
- Por torneo: `seleniumbase` UC carga la URL de resultados → `parse_results(page_source)`.
- Por cada `event_id`: `curl_cffi` GET `df_st_1_{id}` (header `x-fsign`) → `parse_stats_feed` → `tidy_match`.
- Concat de todas las filas → `flashscore_stats.csv` (gitignored), dedup por `(event_id, equipo_flashscore)`.

### 4.3 `load_flashscore_stats_to_supabase.py` (entorno del proyecto)
- DDL: crea `estadisticas_flashscore` vía Management API.
- Resuelve `equipo_id`/`rival_id` (reusa `resolver_equipo_id`), upsert idempotente por `(event_id, equipo_flashscore)`, imprime **reporte de cobertura**.

### 4.4 Tabla `estadisticas_flashscore` (nueva)
`id, event_id, fecha, liga, season, equipo_id (FK→equipos, null), equipo_flashscore, rival_id (FK→equipos, null), rival_flashscore, es_local, corners, crd_y, crd_r, sh, sot, fouls, offsides, possession, xg`. `UNIQUE(event_id, equipo_flashscore)`.

---

## 5. Entregable = reporte de cobertura (gate antes de modelar)

- nº de partidos y selecciones/clubes distintos, partidos/equipo (min/mediana/max),
- % de nombres resueltos a `equipo_id` + lista de huérfanos,
- % de filas con córners / tarjetas / tiros / xG no nulos,
- por liga (internacional vs Liga 1).

Con esos números, B decide qué familias modelar y con qué fuente. **Este pipeline NO construye modelo.**

---

## 6. Testing (TDD)

Funciones puras testeables sin red, con fixtures:
- `parse_stats_feed`: feed packed sintético (incluye períodos repetidos → verifica que toma la 1ª ocurrencia).
- `parse_results`: snippet HTML real recortado de una fila de partido (Argentina-Francia WC2022).
- `tidy_match`: meta+stats fake → 2 filas por-equipo, mapeo de métricas, posesión sin `%`, numéricos.
- El scrape no se testea (red); se valida con el reporte de cobertura.
- Regla de oro: la suite actual (166 tests) sigue verde; nada del runtime de la API cambia.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| `x-fsign` estático cambia | aislado en constante `FSIGN`; si rompe, recapturar de una request del sitio |
| Estructura DOM de Flashscore cambia (clases `wcl-`, `event__`) | `parse_results` se basa en `id="g_1_"`, `event__time` y `wcl-participantLogo` (estables); test con fixture; fácil de re-ajustar |
| Período de stats (Match vs tiempos) | tomar 1ª ocurrencia de cada métrica (full match) |
| Nombres Flashscore que no casan con `equipos` (sobre todo clubes Liga 1) | `equipo_id=null` + log; B reconcilia; posible alta de clubes en `equipos` |
| Rate-limit / bloqueo de Flashscore | feed liviano por partido es barato; browser 1×/edición; CSV intermedio reintentable |
| ToS gris | uso offline, dataset propio, no redistribución |

---

## 8. Relación con otras fases

- Complementa al Sub-proyecto A (FBref): Flashscore cubre lo que FBref no (córners, Liga 1, tiros completos).
- Habilita el **Sub-proyecto B** (modelo + integración al techo) con datos para córners/tarjetas/tiros de internacional y Liga 1.
- **Sofascore-live** queda como sub-proyecto separado y acotado (enriquecimiento de pocos partidos próximos vía Scrapling `capture_xhr`).
