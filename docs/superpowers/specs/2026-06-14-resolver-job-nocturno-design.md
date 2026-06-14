# Diseño: Resolver (Job Nocturno) — Phase 4

**Fecha:** 2026-06-14
**Estado:** En revisión por Angel

---

## Objetivo

Marcar el resultado real de cada selección de parlay ya analizada: ¿acertó o no? Esto convierte cada análisis guardado en un ejemplo etiquetado para calibrar el modelo a futuro. El job consulta resultados reales de partidos en ESPN, calcula `acierto` por selección, y actualiza Supabase.

---

## Fuente de datos: ESPN hidden API

**Endpoint:** `https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard`

**League slugs:**
- Liga 1 Peruana → `per.1`
- Mundial → `fifa.world` (Phase 5, ya soportado por diseño)

**Query por rango de fechas (una sola request):**
```
?dates=YYYYMMDD-YYYYMMDD
```
Verificado en vivo: un mes entero de Liga 1 = 45 partidos en 1 request (~422 KB). Esto elimina el problema de rate limit del diseño viejo basado en API-Football.

**Por qué ESPN y no Sofascore/API-Football:** Sofascore bloqueado por Cloudflare (403 challenge, probado en vivo). API-Football free tier bloquea `season=2025` y `last=N`. ESPN está abierto y cubre Liga 1 + Mundial. Detalle en `project_resolver_design.md` (memoria).

**Estructura de cada evento ESPN:**
```json
{
  "date": "2026-05-31T18:15Z",
  "status": { "type": { "name": "STATUS_FULL_TIME", "completed": true } },
  "competitions": [{
    "competitors": [
      { "homeAway": "home", "score": "1", "team": { "displayName": "FC Cajamarca", "abbreviation": "CAJ" } },
      { "homeAway": "away", "score": "1", "team": { "displayName": "Alianza Lima", "abbreviation": "ALI" } }
    ]
  }]
}
```

---

## Arquitectura

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `resolver.py` | Toda la lógica: fetch ESPN, matching, cálculo de acierto, updates |
| Crear | `tests/test_resolver.py` | Tests de funciones puras (acierto, matching, status mapping) |
| Modificar | `main.py` | Endpoint `POST /api/v1/admin/resolver-resultados` |

**Sin cambios de schema en Supabase.** Se usan columnas existentes: `selecciones_parlay.resultado_real`, `.acierto`, `.resolved_at`, `analisis_parlays.resultado_parlay`, `.resolved_at`.

---

## Interfaz pública de `resolver.py`

```python
def resolver_resultados(league: str = "per.1", dry_run: bool = False) -> dict:
    """
    Resuelve todas las selecciones pendientes (acierto IS NULL).
    Retorna un resumen: {resueltas, pendientes, sin_match, especiales,
    errores, parlays_completados, detalle}.
    Si dry_run=True, calcula pero no escribe en Supabase.
    """
```

Funciones internas (puras, testeables sin red ni DB):
```python
def _calcular_acierto(mercado, seleccion, linea, goles_local, goles_visitante) -> bool | None
def _match_evento(nombre_local, nombre_visitante, eventos_espn) -> dict | None
def _mapear_status(status_name: str) -> str   # "FINALIZADO" | "PENDIENTE" | "ESPECIAL"
def _resultado_parlay(estados: list[str]) -> str  # ver tabla; recibe estado por selección NO exótica
```

donde cada `estado` ∈ `{"GANADA", "PERDIDA", "PENDIENTE", "ESPECIAL"}`.

---

## Flujo del job

1. **Query pendientes:** `selecciones_parlay` donde `acierto IS NULL`, join con `analisis_parlays` para traer `created_at`. (Las exóticas se omiten: `es_mercado_exotico = false`.)

2. **Agrupar por ventana temporal:** rango = `min(created_at)` de las pendientes → hoy. Una request a ESPN por liga cubre todo el rango.

3. **Fetch ESPN:** `GET scoreboard?dates={inicio}-{hoy}` para `per.1`. Una sola llamada.

4. **Por cada selección pendiente:**
   - Obtener nombre canónico: `features_snapshot.equipo_local_id` → tabla `equipos` → `nombre_oficial` (+ `aliases`). Igual para visitante.
   - `_match_evento`: fuzzy match (rapidfuzz, `max(partial_ratio, token_sort_ratio)`, umbral 80%) de ambos nombres contra los `displayName` de los eventos ESPN. Debe matchear local Y visitante del mismo evento.
   - Si no hay match → contar en `sin_match`, dejar `acierto = NULL`, seguir.
   - Si hay match → `_mapear_status`:
     - **FINALIZADO** (`completed=true`, name en FULL_TIME/FINAL): calcular `acierto` con `_calcular_acierto`, escribir `resultado_real = "2-1"`, `acierto`, `resolved_at = NOW()`.
     - **PENDIENTE** (no completado, partido futuro/en curso): dejar `acierto = NULL`, no escribir.
     - **ESPECIAL** (POSTPONED/CANCELED/ABANDONED/SUSPENDED, o FINAL_PEN): `acierto = NULL`, `resultado_real = "<ESTADO>"` (ej. "POSPUESTO", "PENALES_REVISAR"), no se considera ganada ni perdida.

5. **Actualizar parlays completos:** para cada `parlay_id` afectado, recolectar el estado de sus selecciones **no exóticas** (las exóticas se ignoran: no son resolubles). Calcular `resultado_parlay` con `_resultado_parlay`. Solo escribir en `analisis_parlays` (+ `resolved_at`) si el resultado no es `PENDIENTE`.

6. **Retornar resumen.**

---

## Lógica de acierto por mercado (`_calcular_acierto`)

`goles_local` y `goles_visitante` son enteros del marcador ESPN.

| Mercado | Selección | Condición (retorna True/False) |
|---|---|---|
| 1X2 | home | `goles_local > goles_visitante` |
| 1X2 | draw | `goles_local == goles_visitante` |
| 1X2 | away | `goles_local < goles_visitante` |
| over_under | over | `goles_local + goles_visitante > linea` |
| over_under | under | `goles_local + goles_visitante < linea` |
| btts | yes | `goles_local > 0 and goles_visitante > 0` |
| btts | no | `not (goles_local > 0 and goles_visitante > 0)` |
| handicap | home | `goles_local + linea > goles_visitante` |
| handicap | away | `goles_visitante - linea > goles_local` |
| (cualquier otro / exotic) | — | `None` (no resoluble) |

Nota over/under: cuando `goles + goles == linea` exacto (imposible con líneas .5, pero por robustez con líneas enteras tipo push) → retorna `False` para ambos (no acierto). Las líneas de Liga 1 son .5, así que no aplica en la práctica.

---

## Lógica de resultado del parlay (`_resultado_parlay`)

Entrada: lista de `estado` de las selecciones **no exóticas** del parlay. Las exóticas se excluyen porque no son resolubles; un parlay con solo exóticas nunca recibe `resultado_parlay` (queda `PENDIENTE`).

Reglas por **orden de precedencia** (se evalúa de arriba a abajo, primera que aplica gana):

| # | Condición | `resultado_parlay` |
|---|---|---|
| 1 | Alguna selección `PERDIDA` | `PERDIDO` (un leg perdido mata el parlay, sin importar los demás) |
| 2 | Alguna selección `PENDIENTE` | `PENDIENTE` (no escribir aún — aún puede perderse) |
| 3 | Alguna selección `ESPECIAL` (anulada/pospuesta) | `ANULADO` |
| 4 | Todas `GANADA` | `GANADO` |

**Por qué este orden:** en apuestas reales, un leg perdido liquida el parlay como perdido de inmediato (precedencia 1, antes que pendientes). Si no hay perdidas pero sí pendientes, aún no se puede concluir (precedencia 2). Solo si no hay perdidas ni pendientes, una selección anulada vuelve el parlay anulado (3).

**Distinción `acierto = NULL`:** dos causas — (a) partido no jugado → `estado=PENDIENTE`; (b) partido especial → `estado=ESPECIAL`. El resolver las distingue por el `resultado_real` escrito en la selección (vacío = pendiente; con texto de estado = especial).

---

## Endpoint en `main.py`

```
POST /api/v1/admin/resolver-resultados
Query params opcionales: ?league=per.1&dry_run=false
```

- Llama `resolver_resultados(league, dry_run)`.
- Envuelve en el envelope estándar (`_ok` / `_err`).
- Trigger MVP: manual con curl/Postman. Cron real = Phase 5.
- **Nota de seguridad:** endpoint `admin` sin auth por ahora (deploy local únicamente, ver memoria `feedback-decisions`). Agregar token simple antes de cualquier deploy público.

Respuesta:
```json
{
  "success": true,
  "data": {
    "resueltas": 5,
    "pendientes": 2,
    "sin_match": 1,
    "especiales": 0,
    "parlays_completados": 2,
    "detalle": [
      {"seleccion_id": "...", "match": "FC Cajamarca vs Alianza Lima",
       "resultado_real": "1-1", "acierto": false}
    ]
  }
}
```

---

## Error handling

- Fallo de red ESPN → la request entera falla con `_err("ESPN_FETCH_FAILED", ...)`. No se escribe nada (no hay datos parciales corruptos).
- Selección sin match → se cuenta en `sin_match`, no rompe el job, sigue con las demás.
- Excepción inesperada por selección → se cuenta en `errores`, se loguea, el job continúa con las siguientes. "Fail loudly" en el log, pero el job no muere por una selección.
- `dry_run=true` permite probar el cálculo completo sin escribir en Supabase.

---

## Testing

`tests/test_resolver.py` cubre las funciones puras (sin red ni DB):

- `_calcular_acierto`: una assertion por fila de la tabla de mercados (mín. 12 casos), incluyendo over/under con línea, handicap con línea negativa, btts, y `None` para exotic.
- `_mapear_status`: FULL_TIME→FINALIZADO, SCHEDULED→PENDIENTE, POSTPONED→ESPECIAL, FINAL_PEN→ESPECIAL.
- `_match_evento`: match correcto con nombres canónicos vs displayName ESPN (ej. "FBC Melgar" vs "Melgar"), no-match cuando los equipos no coinciden, requiere que local Y visitante coincidan.
- `_resultado_parlay`: GANADO (todas GANADA), PERDIDO (una PERDIDA aunque haya pendientes — verifica precedencia), PENDIENTE (sin perdidas pero con una PENDIENTE), ANULADO (sin perdidas ni pendientes, con una ESPECIAL).

El fetch ESPN y los updates a Supabase se prueban en una verificación manual end-to-end (Task final), no en unit tests.

---

## Fuera de scope (Phase 5)

- Análisis de parlays del Mundial (cargar selecciones nacionales, datos históricos, reentrenar Dixon-Coles).
- Scheduler automático (cron).
- Auth real en el endpoint admin.
- Sofascore + scrapling para datos ricos (xG) — mejora del modelo, no del resolver.
