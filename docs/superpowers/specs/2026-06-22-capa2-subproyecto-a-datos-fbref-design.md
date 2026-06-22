# Capa 2 · Sub-proyecto A — Pipeline de datos FBref (tarjetas y tiros)

**Fecha:** 2026-06-22
**Estado:** Diseño aprobado. Implementación pendiente.
**Fase del bet builder:** Fase 3 (Capa 2), Sub-proyecto A (datos). El modelo + gate de Brier + integración al motor son el Sub-proyecto B (spec aparte, después).

---

## 1. Contexto y motivación

El motor de bet builder (Fase 1) valora la familia **goles** sobre la matriz Dixon-Coles y emite un veredicto por techo. Las patas de **córners, tarjetas y tiros** caen hoy a "exótico" (bajan el techo, no se modelan). La Capa 2 añade familias nuevas que se multiplican en el techo (`ceiling = P_goles × P_familia × …`), arquitectura ya prevista en Fase 1; el núcleo de goles NO se re-diseña.

El riesgo real de la Capa 2 nunca fue la arquitectura (multiplicar una probabilidad en el techo es trivial) sino **la DATA**: a diferencia de goles (CSV masivo martj42, 8.120 partidos), los córners/tarjetas/tiros no tienen un dataset masivo y la obtención es por-partido.

### Sondeo empírico de fuentes (2026-06-22, vía `soccerdata` 1.9.0)

| Familia | Fuente viable | Veredicto |
|---|---|---|
| **Tarjetas** | FBref `read_team_match_stats(stat_type='misc')` | ✅ viable, gratis, denso |
| **Tiros** | FBref `stat_type='shooting'` | ✅ viable, gratis |
| **Córners** | ninguna fácil (FBref no los trae para selecciones; Sofascore-soccerdata sin stats por partido; WhoScored bloqueado por Cloudflare) | ❌ caro/frágil → fase de scraping posterior |

Hallazgos clave del sondeo:
- FBref/soccerdata cubre `INT-World Cup` e `INT-European Championship`; **Liga 1 Perú NO** está por defecto.
- `read_team_match_stats(leagues='INT-World Cup', seasons='2022')` devuelve el **match-log completo del año** de cada selección participante (amistosos, eliminatorias incluidos): **13–29 partidos/selección por año** → densidad suficiente para Poisson.
- `stat_type` válidos para selecciones: `['schedule','shooting','keeper','misc']`. `misc` trae `CrdY/CrdR/2CrdY` + `Fls/Crs/Off/Int/TklW`; `shooting` trae tiros y tiros a puerta. **No hay córners** en este tier.
- Hueco de cobertura: una selección que no jugó esa edición no aparece en ese dataset; la temporada **2026** trae a las 48 del Mundial 2026.
- `pip install soccerdata` sube pandas a 3.0 y websockets a 16 (choca con `realtime<16`). **Decisión: aislar soccerdata en su propio venv.** Verificado que la suite (135 tests) sigue verde bajo pandas 3.0, así que el entorno principal está sano.

Decisión derivada del sondeo: **el plan se invierte** respecto a lo asumido. Tarjetas (y tiros) son lo barato; córners es lo caro. La Capa 2 empieza por tarjetas/tiros vía FBref.

---

## 2. Alcance de este sub-proyecto

**Incluye:** descargar de FBref las estadísticas por partido-equipo (tarjetas + tiros + derivados) de competiciones internacionales 2018–2026, resolver la identidad de equipos contra `equipos`, y persistir las filas crudas en una tabla nueva de Supabase, junto con un **reporte de cobertura** que sirve de checkpoint antes de modelar.

**NO incluye (es Sub-proyecto B):** el modelo Poisson por familia, el gate de Brier, el enchufe al techo del motor, ni los cambios de OCR/validador/frontend.

**Decisiones cerradas (todas de Angel, 2026-06-22):**
1. Persistir **filas crudas por partido-equipo** (no tasas agregadas) → permite re-ajuste, time-weighting y Brier.
2. Bajar **`misc` + `shooting`** en una sola pasada (el fetch es lo caro; deja tiros listos aunque modelemos tarjetas primero).
3. Cobertura: **`INT-World Cup` + `INT-European Championship`, solo internacional.** Liga 1 Perú diferida. Temporadas = ediciones disponibles en FBref: World Cup `{2018, 2022, 2026}`, Euro `{2020, 2024}` (cada edición devuelve el match-log del año de sus participantes; no hay temporadas intermedias). Confirmar en implementación con `FBref.available_seasons()` por si 2026 aún no está poblada.
4. Identidad de equipos: **guardar nombre FBref crudo + `equipo_id` resuelto** (fuzzy+alias del validator, nullable, loguear huérfanos). Nada se descarta.

---

## 3. Arquitectura

Patrón de dos scripts, espejo del pipeline del Mundial (`download_intl_results.py` + `load_intl_to_supabase.py`):

```
[venv aislado: .venv-fbref]                  [entorno del proyecto]
  soccerdata + pandas3 + selenium              pandas + supabase
        │                                            │
  download_fbref_stats.py ──► fbref_stats.csv ──► load_fbref_stats_to_supabase.py
   (offline, scrape FBref)     (gitignored)        (resuelve equipo_id → tabla nueva + reporte)
```

**Por qué dos scripts y dos entornos:** separa el scraping (dependencias pesadas y en conflicto con el runtime: pandas 3.0, websockets 16, selenium) del load (entorno normal del proyecto). Resuelve de raíz el conflicto de dependencias.

**Alternativas descartadas:**
- Script único scrape+load: acopla soccerdata con el runtime de la API (conflicto websockets/pandas).
- Solo CSV sin Supabase: rompe el patrón de storage y de params congelados del proyecto.

### Paso 0 — aislamiento
Crear `.venv-fbref` con soccerdata para el scraping. Desinstalar soccerdata del entorno principal una vez exista el venv aislado (para limpiar el conflicto websockets<16, hoy inofensivo). El `.venv-fbref` y `fbref_stats.csv` van a `.gitignore`.

---

## 4. Componentes

### 4.1 `download_fbref_stats.py` (corre en `.venv-fbref`, offline)
- `FBref(leagues=['INT-World Cup','INT-European Championship'], seasons=[2018, 2020, 2022, 2024, 2026])` (ediciones; soccerdata ignora las que no existan para cada competición).
- Lee `read_team_match_stats(stat_type='misc')` y `read_team_match_stats(stat_type='shooting')`.
- Une ambos por la clave de partido-equipo: (liga, season, fecha, equipo, rival, venue).
- Escribe `fbref_stats.csv` (gitignored) con columnas tidy:
  `fecha, liga, season, equipo_fbref, rival_fbref, venue, gf, ga, crd_y, crd_r, crd_2y, fls, crs, off, sh, sot`.
- Respeta el rate-limit y la caché incorporados de soccerdata. Tolera temporadas/competiciones sin datos (continúa, loguea).

### 4.2 `load_fbref_stats_to_supabase.py` (corre en el entorno del proyecto)
- Lee `fbref_stats.csv`.
- Para cada `equipo_fbref` y `rival_fbref`, resuelve `equipo_id` reusando el matcher fuzzy+alias del validator (`_best_match` contra la tabla `equipos`). Sin match → `equipo_id = null` + log del huérfano.
- Crea (si no existe) la tabla **`estadisticas_partido`** vía Supabase Management API:
  `id, fecha, liga, season, equipo_id (FK→equipos, nullable), equipo_fbref, rival_id (FK→equipos, nullable), rival_fbref, venue, gf, ga, crd_y, crd_r, crd_2y, fls, crs, off, sh, sot`.
- Dedupe / upsert idempotente por la clave (fecha, equipo_fbref, rival_fbref): re-correr no duplica.
- Al final imprime el **reporte de cobertura** (sección 5).

### 4.3 Tabla `estadisticas_partido` (nueva, separada de `partidos`)
Separada porque las filas FBref no mapean 1:1 a los partidos martj42 de la tabla `partidos` (fuentes distintas), y porque su grano es partido-equipo (una fila por equipo y partido). El Sub-proyecto B la unirá a `equipos` por `equipo_id` para fittear.

---

## 5. Entregable = checkpoint de datos (gate antes de modelar)

El load termina imprimiendo un reporte que es la decisión-gate del Sub-proyecto B:
- nº de partidos y nº de selecciones distintas,
- distribución partidos/selección (min / mediana / max),
- **% de nombres resueltos a `equipo_id`** y lista de huérfanos,
- % de filas con tarjetas no nulas y con tiros no nulos.

Con esos números se decide si tarjetas/tiros tienen densidad para un Poisson con skill. **Este sub-proyecto NO construye modelo.**

---

## 6. Testing (TDD)

- **Funciones puras, testeables sin red:**
  - el tidy/merge de las columnas `misc`+`shooting` (a partir de DataFrames fake),
  - el resolvedor nombre_fbref → `equipo_id` (con una tabla `equipos` fake; cubre match exacto, alias ES/EN, huérfano).
- El scrape en sí no se testea (depende de red); se valida con el reporte de cobertura.
- Regla de oro: la suite actual (135 tests) sigue verde; nada del runtime de la API cambia en este sub-proyecto.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| FBref rate-limit / bloqueo durante la descarga | delay+caché de soccerdata; correr offline, reintentable; CSV intermedio persistente |
| Nombres FBref que no casan con `equipos` | se guardan crudos con `equipo_id=null` + log; B los reconcilia, no se pierde dato |
| Cobertura de equipos 2026 incompleta en temporadas viejas | la temporada 2026 trae a las 48; las viejas suman historial de las que participaron |
| Densidad insuficiente para algún equipo | el reporte de cobertura lo expone antes de modelar; B aplicará prior/fallback |
| pandas 3.0 / websockets 16 en el entorno principal | soccerdata aislado en `.venv-fbref`; suite verde confirma que el runtime está sano |

---

## 8. Relación con otras fases

- Depende del modelo de goles internacional (`intl_v0.1`) y de la tabla `equipos` ya cargadas.
- Habilita el **Sub-proyecto B** (modelo Poisson de tarjetas/tiros + Brier + integración al techo).
- Córners queda fuera, en una **fase de scraping posterior** (WhoScored anti-bot / ESPN summary / scraping directo).
