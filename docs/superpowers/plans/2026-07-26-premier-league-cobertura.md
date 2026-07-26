# Premier League — cobertura completa (goles + conteos + jugador) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Alimentar el motor existente con datos de la Premier League (2022/23–2024/25) para cubrir goles, conteos por equipo y props por jugador con la misma disciplina de gates, generalizando el ruteo del analyzer de 2 ligas a N.

**Architecture:** Cero tablas nuevas: se reusan `ligas`/`equipos`/`partidos`/`estadisticas_flashscore`/`eventos_jugador_flashscore`/`eventos_sot_jugador`, todo keyed por `liga_id`. El único cambio de fondo es el ruteo del analyzer (binario → registro de N ligas), que además arregla dos contaminaciones latentes descubiertas al inspeccionar la base. Las cuatro capas de datos son hitos publicables independientes; cada una pasa su gate (≥3% de mejora relativa en holdout temporal) o queda `faltante`.

**Tech Stack:** Python 3 (pytest, supabase-py, numpy/scipy, pandas, rapidfuzz), API-Football v3 (plan Free), Flashscore (curl_cffi + seleniumbase en `.venv-fbref`), Supabase Postgres, FastAPI + React (sin trabajo nuevo de frontend salvo un caso demo).

**Spec:** `docs/superpowers/specs/2026-07-26-premier-league-cobertura-design.md`

---

## Hallazgos de la inspección previa (leer antes de empezar)

Cuatro cosas se verificaron contra la API y la base ANTES de escribir este plan. Dos
confirman el spec; dos lo corrigen.

**1. ✅ Probe API-Football resuelto (riesgo del spec).** `GET /leagues?id=39` +
`GET /fixtures?league=39&season=…` con la key del `.env`:
- El plan Free da **exactamente 2022, 2023 y 2024** (`season=2025` responde
  `{'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}`).
  El rango del spec (2022/23–2024/25) es viable tal cual y es el máximo disponible.
- **380 fixtures FT por temporada → 1140 partidos.**
- **24 equipos distintos** en las 3 temporadas (20 por temporada + ascensos/descensos).

**2. ✅ Slugs de archivo de Flashscore confirmados (HTTP 200):**
`https://www.flashscore.com/football/england/premier-league-{2022-2023,2023-2024,2024-2025}/results/`.
(El conteo de bloques `id="g_1_` es 0 por curl porque la lista se renderiza con JS —
por eso `download_flashscore_stats.py` enumera con seleniumbase; el slug es lo que había
que confirmar.)

**3. 🔴 Contaminación latente en el modelo de goles de clubes (el spec no lo sabía).**
`partidos` NO es solo de Liga 1: tiene **~8.100 filas internacionales** (temporadas
2018–2026) junto a las 996 de Liga 1. Y `analyzer._load_and_fit()` (analyzer.py:505) y
`engine_v02.load_matches()` seleccionan por `temporada` **sin filtrar `liga_id`**:

| liga | partidos en temporadas 2022+2023+2024 |
|------|--------------------------------------|
| Liga 1 Peruana | 996 |
| Internacional  | 3.255 |

O sea: el Dixon-Coles que hoy sirve a la Liga 1 se ajusta sobre un pool **77%
selecciones**. Los `alpha/beta` por equipo no se cruzan (son por `equipo_id`), pero
`mu`, `gamma` y `rho` sí salen contaminados. Con la Premier dentro sería peor.

**Consecuencia para el plan:** la Tarea 3 arregla esto filtrando por `liga_id`. Eso
significa que **los números de Liga 1 CAMBIAN** — no se puede "blindar Liga 1 idéntica"
como pedía el spec. Lo que sí se blinda es **Internacional** (params congelados, ruta
aparte) y el *contrato* de Liga 1 (misma forma de respuesta, mismos mercados). El plan
mide y reporta el antes/después de Liga 1 en la Tarea 4b para que Angel lo apruebe.

**4. 🔴 Los fits por-jugador NO separan por liga (el spec asumía que sí).**
`fit_counts_model.py` sí separa (por la columna `liga` de `estadisticas_flashscore`),
pero `fit_player_model.py` y `fit_player_sot.py` **poolean todo** y publican una sola
fila para "Internacional". Composición real hoy:

| tabla | Internacional | Liga 1 Peruana | sin equipo |
|-------|---------------|----------------|------------|
| `eventos_jugador_flashscore` | 61.998 | **11.140** | 305 |
| `eventos_sot_jugador` | 25.624 | 0 | 1.035 |
| `estadisticas_flashscore` | 1.991 | 396 | 11 |

Es decir, el `player_v0.2` publicado como "Internacional" incluye 11.140 filas de la
Liga 1 Peruana. **Consecuencia:** las Tareas 13 y 17 añaden el split por liga; al
re-publicar, los params de Internacional cambian (menos jugadores, más limpios) y hay
que re-verificar el e2e de Messi.

**5. Simplificación (no es un problema).** La capa de goles **no publica params**: la
ruta de clubes reajusta el Dixon-Coles en runtime desde `partidos` (`_load_and_fit`).
El gate de goles de la Premier es un **go/no-go** para seguir, no un `load_*`. La tabla
"publica params DC de la Premier" del spec no aplica.

---

## Estructura de archivos

**Se modifican:**
- `analyzer.py` — registro de N ligas, `_load_team_liga_map`, `_liga_de_parlay`,
  `_load_and_fit(liga)`, `analyze()`, `_analyze_bet_builder_route()`, `warm_up()`.
- `download_fixtures.py` — parametrizado por liga/temporadas (default = Liga 1, sin cambio de comportamiento).
- `download_flashscore_stats.py` — 3 torneos PL + filtro `--liga` y `--salida`.
- `download_player_events.py` — `--entrada`/`--salida`.
- `load_flashscore_stats_to_supabase.py`, `load_player_events_to_supabase.py` — CSV por argumento.
- `download_sot_jugador.py` — `(39, [2022, 2023, 2024])` en el MANIFIESTO.
- `fit_player_model.py`, `fit_player_sot.py` — split por liga.
- `load_counts_to_supabase.py`, `load_player_model_to_supabase.py`, `load_player_sot_to_supabase.py` — publican por liga.
- `main.py` — caso `?demo=premier`.
- `docs/COBERTURA.md` — patas cubiertas por liga.

**Se crean:**
- `set_pl_aliases.py` — alias de casa de apuestas/Flashscore → `nombre_oficial` de los 24 equipos.
- `gate_goles_liga.py` — gate de goles parametrizado por liga (holdout temporal, Brier vs baseline de tasas).
- `tests/test_analyzer_ruteo.py` — ruteo N-ligas + aislamiento del fit por liga.
- `tests/test_gate_goles_liga.py` — funciones puras del gate.
- `tests/test_set_pl_aliases.py` — merge idempotente de alias.
- `tests/test_fit_por_liga.py` — agrupación por liga de los fits por-jugador.
- `tests/test_scripts_args.py` — parseo de argumentos de los scripts de descarga/carga.

**Comando de tests (siempre desde la raíz del repo, venv del proyecto):** `python -m pytest -q`
(baseline al empezar: **306 tests verdes**).

---

# HITO 1 — Ruteo N-ligas (solo código, sin datos)

Desbloquea todo lo demás y se puede mergear solo. Al terminar el hito, la suite debe
estar verde y el comportamiento de Internacional intacto.

---

### Task 1: Registro de ligas y mapa equipo→liga por nombre

**Files:**
- Modify: `analyzer.py:44` (constantes), `analyzer.py:699-715` (`_load_team_liga_map`)
- Test: `tests/test_analyzer_ruteo.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_analyzer_ruteo.py`:

```python
"""Ruteo N-ligas del analyzer: mapa equipo->liga, liga del parlay y aislamiento
del Dixon-Coles por liga. Nada toca Supabase (cliente falso)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import analyzer
from validator import ValidatedParlay, ValidatedSelection, TeamMatch


# ── Cliente Supabase falso ────────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, filas, registro, nombre):
        self._filas, self._reg, self._nombre = list(filas), registro, nombre

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._reg.append((self._nombre, "eq", col, val))
        self._filas = [f for f in self._filas if f.get(col) == val]
        return self

    def in_(self, col, vals):
        self._reg.append((self._nombre, "in", col, list(vals)))
        self._filas = [f for f in self._filas if f.get(col) in vals]
        return self

    def execute(self):
        return SimpleNamespace(data=self._filas)


class _FakeClient:
    def __init__(self, tablas, registro):
        self._tablas, self._reg = tablas, registro

    def table(self, nombre):
        return _FakeTable(self._tablas.get(nombre, []), self._reg, nombre)


LIGAS = [
    {"id": "L-PE", "nombre": "Liga 1 Peruana"},
    {"id": "L-EN", "nombre": "Premier League"},
    {"id": analyzer.LIGA_INTERNACIONAL_ID, "nombre": "Internacional"},
    {"id": "L-XX", "nombre": "Liga Que No Modelamos"},
]

EQUIPOS = [
    {"id": "E-ALI", "liga_id": "L-PE"},
    {"id": "E-ARS", "liga_id": "L-EN"},
    {"id": "E-FRA", "liga_id": analyzer.LIGA_INTERNACIONAL_ID},
    {"id": "E-ZZZ", "liga_id": "L-XX"},
]


def _fake_sb(monkeypatch, tablas):
    registro = []
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    monkeypatch.setenv("SUPABASE_KEY", "fake")
    monkeypatch.setattr(analyzer, "create_client",
                        lambda *_a, **_k: _FakeClient(tablas, registro))
    return registro


# ── Mapa equipo -> liga ───────────────────────────────────────────────────────

def test_mapa_equipo_liga_usa_el_nombre_de_la_liga(monkeypatch):
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert mapa["E-ALI"] == "liga1"
    assert mapa["E-ARS"] == "premier"
    assert mapa["E-FRA"] == "internacional"


def test_equipo_de_liga_no_registrada_queda_fuera_del_mapa(monkeypatch):
    """El ruteo binario mandaba TODO lo no-internacional a Liga 1. Una liga que no
    modelamos no debe heredar el modelo de otra: mejor fuera del mapa."""
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert "E-ZZZ" not in mapa
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_analyzer_ruteo.py -q`
Expected: FAIL — `KeyError: 'E-ARS'` / `assert 'liga1' == 'premier'` (hoy todo lo
no-internacional se mapea a `"liga1"`).

- [ ] **Step 3: Implementar**

En `analyzer.py`, justo debajo de `LIGA_INTERNACIONAL_ID` (línea 44), añadir el registro:

```python
# ── Registro de ligas (ruteo N-ligas) ─────────────────────────────────────────
# slug de ruteo -> nombre EXACTO de la liga en la tabla `ligas`. Añadir una liga
# es añadir una línea aquí + sus datos en `equipos`/`partidos`.
SLUG_A_NOMBRE = {
    "liga1":         "Liga 1 Peruana",
    "premier":       "Premier League",
    "internacional": "Internacional",
}
NOMBRE_A_SLUG = {nombre: slug for slug, nombre in SLUG_A_NOMBRE.items()}

# Ligas de clubes: el DC se reajusta en runtime desde `partidos` (una por liga).
SLUGS_CLUBES = ("liga1", "premier")

# Temporadas de clubes disponibles en `partidos` (API-Football plan Free).
TEMPORADAS_CLUBES = ["2022", "2023", "2024"]
```

Reemplazar `_load_team_liga_map` (analyzer.py:699-715) por:

```python
def _load_team_liga_map() -> dict[str, str]:
    """Mapa equipo_id -> slug de liga ("liga1" | "premier" | "internacional").

    N ligas: el slug sale del NOMBRE de la liga en `ligas` (registro SLUG_A_NOMBRE).
    Un equipo de una liga que no modelamos queda FUERA del mapa; el ruteo binario
    viejo lo habría mandado a Liga 1 por descarte.
    """
    global _cached_team_liga, _team_liga_ts
    now = datetime.now(tz=timezone.utc)
    expired = (
        _team_liga_ts is None or
        (now - _team_liga_ts).total_seconds() > MODEL_TTL_HOURS * 3600
    )
    if expired:
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        ligas = {l["id"]: l["nombre"]
                 for l in sb.table("ligas").select("id, nombre").execute().data}
        rows = sb.table("equipos").select("id, liga_id").execute().data
        mapa = {}
        for r in rows:
            slug = NOMBRE_A_SLUG.get(ligas.get(r["liga_id"], ""))
            if slug:
                mapa[r["id"]] = slug
        _cached_team_liga = mapa
        _team_liga_ts = now
    return _cached_team_liga   # type: ignore[return-value]
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_analyzer_ruteo.py tests/test_analyzer_intl.py -q`
Expected: PASS (los 3 tests de ruteo viejos de `test_analyzer_intl.py` siguen verdes:
el mapa que reciben es un dict literal, no lo construye este código).

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_analyzer_ruteo.py
git commit -m "feat(ruteo): registro de N ligas y mapa equipo->liga por nombre"
```

---

### Task 2: `_liga_de_parlay` con N ligas y mixto general

**Files:**
- Modify: `analyzer.py:718-734` (`_liga_de_parlay`), `analyzer.py:980-984` (mensaje de mixto)
- Test: `tests/test_analyzer_ruteo.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_analyzer_ruteo.py`:

```python
# ── Liga del parlay ───────────────────────────────────────────────────────────

def _tm(nombre, eid):
    return TeamMatch(raw=nombre, canonical=nombre, equipo_id=eid,
                     score=1.0, status="MATCHED")


def _sel(local, lid, vis, vid, cuota=2.0):
    return ValidatedSelection(
        equipo_local_raw=local, equipo_visitante_raw=vis,
        mercado="1X2", seleccion="home", cuota=cuota, linea=None,
        local_match=_tm(local, lid), visitante_match=_tm(vis, vid),
        prob_implicita=round(1 / cuota, 6), mercado_exotico=False,
    )


def _parlay(*sels, cuota_total=2.10, es_bet_builder=False):
    return ValidatedParlay(selecciones=list(sels), cuota_total=cuota_total,
                           casa_apuestas="betano", es_bet_builder=es_bet_builder)


def test_ruteo_premier():
    p = _parlay(_sel("Arsenal", "E-ARS", "Chelsea", "E-CHE"))
    m = {"E-ARS": "premier", "E-CHE": "premier"}
    assert analyzer._liga_de_parlay(p, m) == "premier"


def test_ruteo_premier_mas_liga1_es_mixto():
    p = _parlay(_sel("Arsenal", "E-ARS", "Alianza Lima", "E-ALI"))
    m = {"E-ARS": "premier", "E-ALI": "liga1"}
    assert analyzer._liga_de_parlay(p, m) == "mixto"


def test_ruteo_premier_mas_internacional_es_mixto():
    p = _parlay(_sel("Arsenal", "E-ARS", "France", "E-FRA"))
    m = {"E-ARS": "premier", "E-FRA": "internacional"}
    assert analyzer._liga_de_parlay(p, m) == "mixto"


def test_ruteo_sin_equipos_reconocidos_cae_a_liga1():
    """Comportamiento histórico del fallback: sin match, ruta de clubes por defecto."""
    p = _parlay(_sel("Equipo X", "E-???", "Equipo Y", "E-!!!"))
    assert analyzer._liga_de_parlay(p, {}) == "liga1"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_analyzer_ruteo.py -q -k "premier or reconocidos"`
Expected: FAIL — `test_ruteo_premier` da `"liga1"` y `test_ruteo_premier_mas_liga1_es_mixto`
da `"liga1"` (hoy solo `internacional`+`liga1` produce mixto).

- [ ] **Step 3: Implementar**

Reemplazar `_liga_de_parlay` (analyzer.py:718-734) por:

```python
def _liga_de_parlay(parlay: ValidatedParlay, team_liga_map: dict[str, str]) -> str:
    """Slug de la liga del parlay: "liga1" | "premier" | "internacional" | "mixto".

    Un boleto es de UNA sola liga: CUALQUIER cruce (Liga1+intl, Premier+Liga1,
    Premier+intl) es "mixto" y se rechaza aguas arriba. Sin equipos reconocidos ->
    "liga1" (fallback histórico).
    """
    ligas: set[str] = set()
    for sel in parlay.selecciones:
        ids = [sel.local_match.equipo_id]
        if sel.visitante_match:
            ids.append(sel.visitante_match.equipo_id)
        for tid in ids:
            if tid and tid in team_liga_map:
                ligas.add(team_liga_map[tid])

    if len(ligas) > 1:
        return "mixto"
    if not ligas:
        return "liga1"   # sin equipos reconocidos -> comportamiento original
    return ligas.pop()
```

Y en `analyze()` (analyzer.py:980-984) generalizar el mensaje:

```python
    if liga == "mixto":
        raise ValueError(
            "Parlay mixto: combina equipos de mas de una liga (Liga 1 Peruana, "
            "Premier League o selecciones internacionales). No es analizable como "
            "un solo parlay; sube boletos separados."
        )
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_analyzer_ruteo.py tests/test_analyzer_intl.py -q`
Expected: PASS (incluidos `test_ruteo_internacional`, `test_ruteo_liga1`,
`test_ruteo_mixto` y `test_dispatch_mixto_lanza_error`, que solo espera `ValueError`).

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_analyzer_ruteo.py
git commit -m "feat(ruteo): liga del parlay con N ligas; cualquier cruce es mixto"
```

---

### Task 3: Un Dixon-Coles por liga de clubes (arregla la contaminación)

**Files:**
- Modify: `analyzer.py:497-532` (caché + `_load_and_fit`)
- Test: `tests/test_analyzer_ruteo.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_analyzer_ruteo.py`:

```python
# ── Un DC por liga de clubes ──────────────────────────────────────────────────

PARTIDOS = [
    # Liga 1 (liga_id L-PE)
    {"liga_id": "L-PE", "equipo_local_id": "E-ALI", "equipo_visitante_id": "E-UNI",
     "goles_local": 1, "goles_visitante": 0, "resultado": "HOME",
     "temporada": "2023", "fecha": "2023-05-01T00:00:00+00:00", "estado": "FINISHED"},
    # Premier (liga_id L-EN)
    {"liga_id": "L-EN", "equipo_local_id": "E-ARS", "equipo_visitante_id": "E-CHE",
     "goles_local": 2, "goles_visitante": 1, "resultado": "HOME",
     "temporada": "2023", "fecha": "2023-05-02T00:00:00+00:00", "estado": "FINISHED"},
    # Internacional: vive en la MISMA tabla y no debe entrar a ningún fit de clubes
    {"liga_id": analyzer.LIGA_INTERNACIONAL_ID, "equipo_local_id": "E-FRA",
     "equipo_visitante_id": "E-BRA", "goles_local": 1, "goles_visitante": 1,
     "resultado": "DRAW", "temporada": "2023", "fecha": "2023-05-03T00:00:00+00:00",
     "estado": "FINISHED"},
]


class _FakeDC:
    """Sustituye a DixonColesModel: registra con qué partidos se ajustó.

    `lambdas`/`predict_1x2` son necesarias porque `_prob_for_selection` las llama
    sin comprobar `idx` (analyzer.py:298)."""
    def __init__(self):
        self.matches = None
        self.rho = -0.05
        self.idx = {}

    def fit(self, matches, _ref_date):
        self.matches = list(matches)
        self.idx = {m["equipo_local_id"]: 0 for m in matches}
        return self

    def lambdas(self, _home_id, _away_id):
        return 1.3, 1.1

    def predict_1x2(self, _lh, _la):
        return 0.45, 0.28, 0.27


def _preparar_fit(monkeypatch):
    registro = _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS,
                                      "partidos": PARTIDOS})
    monkeypatch.setattr(analyzer, "DixonColesModel", _FakeDC)
    monkeypatch.setattr(analyzer, "_cached_clubes", {})
    monkeypatch.setattr(analyzer, "_cache_ts_clubes", {})
    monkeypatch.setattr(analyzer, "_cached_liga_ids", {})
    return registro


def test_load_and_fit_solo_usa_partidos_de_su_liga(monkeypatch):
    """El bug latente: sin filtro por liga_id, el DC de Liga 1 se comía los ~3.2k
    partidos internacionales que viven en la misma tabla `partidos`."""
    _preparar_fit(monkeypatch)

    model, matches, counts = analyzer._load_and_fit("liga1")

    assert [m["equipo_local_id"] for m in matches] == ["E-ALI"]
    assert set(counts) == {"E-ALI", "E-UNI"}


def test_load_and_fit_premier_usa_sus_propios_partidos(monkeypatch):
    _preparar_fit(monkeypatch)

    _, matches, counts = analyzer._load_and_fit("premier")

    assert [m["equipo_local_id"] for m in matches] == ["E-ARS"]
    assert set(counts) == {"E-ARS", "E-CHE"}


def test_load_and_fit_cachea_por_liga(monkeypatch):
    _preparar_fit(monkeypatch)

    m_l1, _, _ = analyzer._load_and_fit("liga1")
    m_pl, _, _ = analyzer._load_and_fit("premier")
    m_l1_otra_vez, _, _ = analyzer._load_and_fit("liga1")

    assert m_l1 is not m_pl                 # un modelo por liga
    assert m_l1 is m_l1_otra_vez            # y se cachea, no se reajusta


def test_load_and_fit_liga_inexistente_falla_claro(monkeypatch):
    _preparar_fit(monkeypatch)
    monkeypatch.setitem(analyzer.SLUG_A_NOMBRE, "fantasma", "Liga Fantasma")

    with pytest.raises(RuntimeError, match="Liga Fantasma"):
        analyzer._load_and_fit("fantasma")
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_analyzer_ruteo.py -q -k "load_and_fit"`
Expected: FAIL — `AttributeError: module 'analyzer' has no attribute '_cached_clubes'`.

- [ ] **Step 3: Implementar**

Reemplazar el bloque de caché y `_load_and_fit` (analyzer.py:497-532) por:

```python
# ── Model + data cache por liga de clubes (refit cada MODEL_TTL_HOURS) ────────

_cached_clubes:   dict[str, tuple] = {}       # slug -> (model, matches, counts)
_cache_ts_clubes: dict[str, datetime] = {}    # slug -> timestamp del fit
_cached_liga_ids: dict[str, str] = {}         # nombre de liga -> uuid (solo aciertos)


def _liga_id_por_nombre(nombre: str) -> str | None:
    """UUID de una liga por su nombre en `ligas`. Cachea SOLO el acierto (el id de
    una liga no cambia). El fallo no se cachea: una liga ingestada despues (p.ej.
    la Premier antes de su ingesta) se resuelve sola sin reiniciar el proceso."""
    if _cached_liga_ids.get(nombre) is None:
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        rows = sb.table("ligas").select("id").eq("nombre", nombre).execute().data
        if rows:
            _cached_liga_ids[nombre] = rows[0]["id"]
    return _cached_liga_ids.get(nombre)


def _load_and_fit(liga: str = "liga1") -> tuple[DixonColesModel, list[dict], dict[str, int]]:
    """Ajusta (y cachea 6h) el Dixon-Coles de UNA liga de clubes.

    El filtro por `liga_id` no es cosmético: `partidos` guarda TAMBIÉN los ~8.1k
    partidos internacionales, así que sin filtro el fit de Liga 1 salía de un pool
    con 3.255 partidos de selecciones contra 996 propios (mu/gamma/rho dominados
    por selecciones).
    """
    now = datetime.now(tz=timezone.utc)
    ts = _cache_ts_clubes.get(liga)
    expired = ts is None or (now - ts).total_seconds() > MODEL_TTL_HOURS * 3600
    if expired:
        nombre = SLUG_A_NOMBRE[liga]
        liga_id = _liga_id_por_nombre(nombre)
        if liga_id is None:
            raise RuntimeError(
                f"La liga '{nombre}' no existe en `ligas`: no hay partidos que ajustar. "
                "Corre la ingesta de esa liga antes de analizar sus boletos."
            )
        sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        rows = (
            sb.table("partidos")
            .select("equipo_local_id, equipo_visitante_id, goles_local, goles_visitante, resultado, temporada, fecha")
            .eq("liga_id", liga_id)
            .in_("temporada", TEMPORADAS_CLUBES)
            .eq("estado", "FINISHED")
            .execute()
            .data
        )
        matches = [r for r in rows if r["goles_local"] is not None]
        counts: dict[str, int] = {}
        for m in matches:
            for tid in (m["equipo_local_id"], m["equipo_visitante_id"]):
                counts[tid] = counts.get(tid, 0) + 1
        model = DixonColesModel().fit(matches, now)
        _cached_clubes[liga]   = (model, matches, counts)
        _cache_ts_clubes[liga] = now
    return _cached_clubes[liga]
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_analyzer_ruteo.py -q`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_analyzer_ruteo.py
git commit -m "fix(motor): un Dixon-Coles por liga de clubes, filtrado por liga_id

partidos guarda tambien los partidos internacionales; sin filtro el fit de
Liga 1 se ajustaba sobre 3.255 partidos de selecciones y 996 propios."
```

---

### Task 4: `analyze()`, ruta de bet builder y `warm_up()` usan la liga del parlay

**Files:**
- Modify: `analyzer.py:737-741` (`warm_up`), `analyzer.py:908-966` (`_analyze_bet_builder_route`), `analyzer.py:995` (`analyze`)
- Test: `tests/test_analyzer_ruteo.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_analyzer_ruteo.py`:

```python
# ── La ruta de clubes usa el modelo y los params de SU liga ───────────────────

def test_analyze_usa_el_dc_de_la_liga_del_parlay(monkeypatch):
    pedidas = []

    def _fake_load_and_fit(liga="liga1"):
        pedidas.append(liga)
        return _FakeDC().fit([], None), [], {}

    monkeypatch.setattr(analyzer, "_load_and_fit", _fake_load_and_fit)
    monkeypatch.setattr(analyzer, "_load_team_liga_map",
                        lambda: {"E-ARS": "premier", "E-CHE": "premier"})
    p = _parlay(_sel("Arsenal", "E-ARS", "Chelsea", "E-CHE"))

    analyzer.analyze(p)

    assert pedidas == ["premier"]


def test_betbuilder_premier_pide_params_de_premier(monkeypatch):
    pedidas = {"fit": [], "counts": [], "player": [], "sot": []}

    def _fake_load_and_fit(liga="liga1"):
        pedidas["fit"].append(liga)
        return _FakeDC().fit([], None), [], {}

    monkeypatch.setattr(analyzer, "_load_and_fit", _fake_load_and_fit)
    monkeypatch.setattr(analyzer, "_load_counts_model",
                        lambda n: pedidas["counts"].append(n))
    monkeypatch.setattr(analyzer, "_load_player_model",
                        lambda n: pedidas["player"].append(n))
    monkeypatch.setattr(analyzer, "_load_player_sot_model",
                        lambda n: pedidas["sot"].append(n))

    p = _parlay(_sel("Arsenal", "E-ARS", "Chelsea", "E-CHE"),
                cuota_total=2.0, es_bet_builder=True)

    analyzer._analyze_bet_builder_route(p, "premier", 0.06)

    assert pedidas["fit"] == ["premier"]
    assert pedidas["counts"] == ["Premier League"]
    assert pedidas["player"] == ["Premier League"]
    assert pedidas["sot"] == ["Premier League"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_analyzer_ruteo.py -q -k "usa_el_dc or premier_pide"`
Expected: FAIL — `pedidas == []` vs `["premier"]` (hoy `analyze()` llama
`_load_and_fit()` sin argumento y el bet builder pide `"Liga 1 Peruana"`).

- [ ] **Step 3: Implementar**

En `analyze()` (analyzer.py:995) pasar la liga:

```python
    model, _, team_match_count = _load_and_fit(liga)
```

En `_analyze_bet_builder_route()` (analyzer.py:947-952), reemplazar el bloque `else`:

```python
    else:
        nombre = SLUG_A_NOMBRE[liga]
        model, _, _ = _load_and_fit(liga)
        rho, version = model.rho, "v0.2"
        counts     = _load_counts_model(nombre)
        player     = _load_player_model(nombre)
        player_sot = _load_player_sot_model(nombre)
```

Y en `warm_up()` (analyzer.py:737-741):

```python
def warm_up() -> None:
    """Pre-load and fit the models. Call at server startup.

    Una liga de clubes sin datos aún (p.ej. la Premier antes de la ingesta) no
    debe tumbar el arranque: se avisa y se sigue.
    """
    for slug in SLUGS_CLUBES:
        try:
            _load_and_fit(slug)
        except RuntimeError as exc:
            print(f"[warm_up] {slug}: {exc}")
    _load_team_liga_map()       # ruteo
    _load_intl_predictor()      # Internacional: params congelados
```

- [ ] **Step 4: Correr toda la suite**

Run: `python -m pytest -q`
Expected: PASS — 306 tests previos + los nuevos de ruteo, sin fallos.

- [ ] **Step 5: Commit**

```bash
git add analyzer.py tests/test_analyzer_ruteo.py
git commit -m "feat(ruteo): analyze y bet builder resuelven modelo y params por liga"
```

---

### Task 4b: Medir el impacto real del fix en Liga 1 (checkpoint de Angel)

No es refactor: es la evidencia de que el cambio de la Tarea 3 mejora y no rompe.

**Files:**
- Create: `docs/superpowers/notas/2026-07-26-impacto-fix-liga1.md`

- [ ] **Step 1: Medir el antes/después**

Correr desde la raíz:

```bash
python -c "
import os, json
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client
import analyzer
load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
now = datetime.now(tz=timezone.utc)
sel = 'equipo_local_id, equipo_visitante_id, goles_local, goles_visitante, resultado, temporada, fecha'
# ANTES: sin filtro de liga (comportamiento viejo)
viejo = sb.table('partidos').select(sel).in_('temporada', ['2022','2023','2024']).eq('estado','FINISHED').execute().data
viejo = [r for r in viejo if r['goles_local'] is not None]
m_viejo = analyzer.DixonColesModel().fit(viejo, now)
# DESPUES: solo Liga 1
lid = analyzer._liga_id_por_nombre('Liga 1 Peruana')
nuevo = sb.table('partidos').select(sel).eq('liga_id', lid).in_('temporada', ['2022','2023','2024']).eq('estado','FINISHED').execute().data
nuevo = [r for r in nuevo if r['goles_local'] is not None]
m_nuevo = analyzer.DixonColesModel().fit(nuevo, now)
print(f'partidos  antes={len(viejo)}  despues={len(nuevo)}')
print(f'mu    antes={m_viejo.mu:.4f}  despues={m_nuevo.mu:.4f}')
print(f'gamma antes={m_viejo.gamma:.4f}  despues={m_nuevo.gamma:.4f}')
print(f'rho   antes={m_viejo.rho:.4f}  despues={m_nuevo.rho:.4f}')
"
```

- [ ] **Step 2: Escribir la nota con los números reales**

Crear `docs/superpowers/notas/2026-07-26-impacto-fix-liga1.md` con: la salida del paso 1,
la explicación de una línea (el fit de Liga 1 ya no incluye partidos de selecciones) y
el veredicto esperado (`gamma` de Liga 1 debería SUBIR: la ventaja de local en clubes
peruanos es mayor que en partidos de selecciones, muchos en cancha neutral).

- [ ] **Step 3: Commit y CHECKPOINT**

```bash
git add docs/superpowers/notas/2026-07-26-impacto-fix-liga1.md
git commit -m "docs: impacto medido del fix de contaminacion en el DC de Liga 1"
```

**PARAR aquí y mostrarle los números a Angel.** El fix cambia las probabilidades que
la app da para boletos de Liga 1. Es una corrección, pero es su decisión aceptarla.

---

# HITO 2 — Ingesta de goles de la Premier

---

### Task 5: Parametrizar `download_fixtures.py` por liga y temporadas

**Files:**
- Modify: `download_fixtures.py` (entero: envolver en funciones + argparse)
- Test: `tests/test_scripts_args.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_scripts_args.py`:

```python
"""Parseo de argumentos de los scripts de descarga/carga. Los scripts hacen red y
Supabase en main(); aquí solo se prueban las funciones puras de configuración."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


# ── download_fixtures.py ──────────────────────────────────────────────────────

def test_config_fixtures_default_es_liga1():
    from download_fixtures import parsear_args
    cfg = parsear_args([])
    assert cfg.liga_api_id == 281
    assert cfg.temporadas == [2022, 2023, 2024]
    assert cfg.nombre == "Liga 1 Peruana"
    assert cfg.pais == "Peru"


def test_config_fixtures_premier():
    from download_fixtures import parsear_args
    cfg = parsear_args(["--liga", "39", "--nombre", "Premier League",
                        "--pais", "England"])
    assert cfg.liga_api_id == 39
    assert cfg.nombre == "Premier League"
    assert cfg.pais == "England"
    assert cfg.temporadas == [2022, 2023, 2024]


def test_config_fixtures_temporadas_explicitas():
    from download_fixtures import parsear_args
    cfg = parsear_args(["--temporadas", "2023,2024"])
    assert cfg.temporadas == [2023, 2024]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: FAIL — `ImportError: cannot import name 'parsear_args'` (y hoy el import del
módulo dispara la descarga entera, porque todo es código de nivel superior).

- [ ] **Step 3: Implementar**

Reescribir `download_fixtures.py` moviendo TODO el código de nivel superior a funciones.
El archivo queda así (los helpers `result_from_goals` y `STATUS_MAP` no cambian):

```python
"""
Descarga fixtures de una liga de clubes a Supabase (ligas + equipos + partidos).

Por defecto, la Liga 1 Peruana (comportamiento histórico). Para la Premier:

    python download_fixtures.py --liga 39 --nombre "Premier League" --pais England

Usa 1 request de API-Football por temporada (3 en total). El plan Free solo da
2022, 2023 y 2024 (verificado 2026-07-26: season=2025 responde "Free plans do not
have access to this season").
"""

import argparse
import os
import sys
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from supabase import create_client

API_URL = "https://v3.football.api-sports.io"
BATCH = 50


@dataclass
class Config:
    liga_api_id: int
    temporadas: list[int]
    nombre: str
    pais: str
    cobertura: str


def parsear_args(argv: list[str]) -> Config:
    p = argparse.ArgumentParser(description="Ingesta de fixtures por liga.")
    p.add_argument("--liga", type=int, default=281, help="league id de API-Football")
    p.add_argument("--temporadas", default="2022,2023,2024")
    p.add_argument("--nombre", default="Liga 1 Peruana", help="nombre en la tabla `ligas`")
    p.add_argument("--pais", default="Peru")
    p.add_argument("--cobertura", default="MEDIA", choices=["ALTA", "MEDIA", "BAJA", "NULA"])
    a = p.parse_args(argv)
    return Config(
        liga_api_id=a.liga,
        temporadas=[int(t) for t in a.temporadas.split(",") if t.strip()],
        nombre=a.nombre, pais=a.pais, cobertura=a.cobertura,
    )


def api_get(endpoint, params, api_key):
    r = requests.get(f"{API_URL}/{endpoint}",
                     headers={"x-apisports-key": api_key}, params=params, timeout=20)
    r.raise_for_status()
    payload = r.json()
    # API-Football señala cuota agotada con HTTP 200 + `errors` poblado.
    if payload.get("errors"):
        raise RuntimeError(f"API-Football: {payload['errors']}")
    return payload.get("response", []), r.headers.get("x-ratelimit-requests-remaining", "?")


def result_from_goals(gh, ga):
    if gh is None or ga is None:
        return None
    if gh > ga:
        return "HOME"
    if gh < ga:
        return "AWAY"
    return "DRAW"


STATUS_MAP = {
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "NS": "SCHEDULED", "TBD": "SCHEDULED",
    "1H": "LIVE", "HT": "LIVE", "2H": "LIVE", "ET": "LIVE", "P": "LIVE",
    "SUSP": "SUSPENDED", "PST": "POSTPONED",
    "CANC": "CANCELLED", "ABD": "CANCELLED",
}


def filas_equipos(fixtures, liga_id, pais):
    vistos = {}
    for f in fixtures:
        for side in ("home", "away"):
            t = f["teams"][side]
            if t["id"] not in vistos:
                vistos[t["id"]] = {"api_football_id": t["id"],
                                   "nombre_oficial": t["name"],
                                   "liga_id": liga_id, "pais": pais}
    return list(vistos.values())


def filas_partidos(fixtures, liga_id, equipo_map):
    filas, saltados = [], 0
    for f in fixtures:
        fix, goals, score = f["fixture"], f.get("goals", {}), f.get("score", {})
        local_id = equipo_map.get(f["teams"]["home"]["id"])
        visit_id = equipo_map.get(f["teams"]["away"]["id"])
        if not local_id or not visit_id:
            saltados += 1
            continue
        gh, ga = goals.get("home"), goals.get("away")
        ht = score.get("halftime", {})
        estado = STATUS_MAP.get(fix["status"]["short"], "SCHEDULED")
        filas.append({
            "api_football_id": fix["id"], "liga_id": liga_id,
            "equipo_local_id": local_id, "equipo_visitante_id": visit_id,
            "fecha": fix["date"], "temporada": str(f["league"].get("season", "")),
            "jornada": f["league"].get("round", ""), "estado": estado,
            "goles_local": gh, "goles_visitante": ga,
            "resultado": result_from_goals(gh, ga) if estado == "FINISHED" else None,
            "goles_ht_local": ht.get("home"), "goles_ht_visitante": ht.get("away"),
            "estadio_nombre": fix.get("venue", {}).get("name"),
            "arbitro": fix.get("referee"),
            "datos_completos": gh is not None and ga is not None,
            "fuente": "api_football",
        })
    return filas, saltados


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = parsear_args(sys.argv[1:] if argv is None else argv)
    load_dotenv()
    api_key = os.environ["API_FOOTBALL_KEY"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print(f"\n[1/4] Upsert de la liga {cfg.nombre} (api id {cfg.liga_api_id})...")
    resp = sb.table("ligas").upsert({
        "api_football_id": cfg.liga_api_id, "nombre": cfg.nombre, "pais": cfg.pais,
        "nivel_cobertura": cfg.cobertura, "modelo": "dixon_coles_local",
        "temporadas_disponibles": len(cfg.temporadas),
    }, on_conflict="api_football_id").execute()
    liga_id = resp.data[0]["id"]
    print(f"  liga_id: {liga_id}")

    print("\n[2/4] Bajando fixtures...")
    fixtures = []
    for season in cfg.temporadas:
        fx, rem = api_get("fixtures", {"league": cfg.liga_api_id, "season": season}, api_key)
        fixtures.extend(fx)
        print(f"  {season}: {len(fx)} fixtures | API remaining: {rem}")
        time.sleep(0.3)
    print(f"  total: {len(fixtures)}")

    print("\n[3/4] Upsert de equipos...")
    equipos = filas_equipos(fixtures, liga_id, cfg.pais)
    for i in range(0, len(equipos), BATCH):
        sb.table("equipos").upsert(equipos[i:i + BATCH],
                                   on_conflict="api_football_id").execute()
    equipo_map = {e["api_football_id"]: e["id"] for e in
                  sb.table("equipos").select("id,api_football_id").execute().data}
    print(f"  equipos de esta liga: {len(equipos)}")

    print("\n[4/4] Upsert de partidos...")
    filas, saltados = filas_partidos(fixtures, liga_id, equipo_map)
    insertados = 0
    for i in range(0, len(filas), BATCH):
        sb.table("partidos").upsert(filas[i:i + BATCH],
                                    on_conflict="api_football_id").execute()
        insertados += len(filas[i:i + BATCH])

    print("\n" + "=" * 55)
    print(f"  Liga            : {cfg.nombre} ({liga_id})")
    print(f"  Equipos         : {len(equipos)}")
    print(f"  Partidos        : {insertados}")
    print(f"  Saltados        : {saltados}")
    print("=" * 55)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add download_fixtures.py tests/test_scripts_args.py
git commit -m "refactor(ingesta): download_fixtures parametrizado por liga y temporadas"
```

---

### Task 6: Ingesta real de la Premier (3 requests de API)

**Files:**
- Run: `download_fixtures.py`

- [ ] **Step 1: Correr la ingesta**

```bash
python download_fixtures.py --liga 39 --nombre "Premier League" --pais England --cobertura ALTA
```

Expected: `2022: 380 fixtures`, `2023: 380`, `2024: 380`, `equipos de esta liga: 24`,
`Partidos: 1140`, `Saltados: 0`.

- [ ] **Step 2: Verificar en Supabase**

```bash
python -c "
import os
from collections import Counter
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
ligas = {l['id']: l['nombre'] for l in sb.table('ligas').select('id,nombre').execute().data}
pl = [k for k, v in ligas.items() if v == 'Premier League'][0]
eq = sb.table('equipos').select('nombre_oficial').eq('liga_id', pl).execute().data
c = Counter()
desde = 0
while True:
    ch = sb.table('partidos').select('liga_id,temporada,estado').range(desde, desde+999).execute().data
    for r in ch:
        if r['liga_id'] == pl:
            c[(r['temporada'], r['estado'])] += 1
    if len(ch) < 1000: break
    desde += 1000
print('equipos PL:', len(eq), sorted(e['nombre_oficial'] for e in eq))
print('partidos PL:', dict(c))
"
```

Expected: 24 equipos; `{('2022','FINISHED'): 380, ('2023','FINISHED'): 380, ('2024','FINISHED'): 380}`.

- [ ] **Step 3: Verificar que Liga 1 e Internacional no se movieron**

```bash
python -c "
import os
from collections import Counter
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
ligas = {l['id']: l['nombre'] for l in sb.table('ligas').select('id,nombre').execute().data}
c, desde = Counter(), 0
while True:
    ch = sb.table('partidos').select('liga_id').range(desde, desde+999).execute().data
    for r in ch: c[ligas.get(r['liga_id'], '?')] += 1
    if len(ch) < 1000: break
    desde += 1000
print(dict(c))
"
```

Expected: `Liga 1 Peruana: 996`, `Internacional: ~8120`, `Premier League: 1140`.

- [ ] **Step 4: No hay commit de código** (esto es data). Anotar los números en el
mensaje del commit de la tarea siguiente.

---

### Task 7: Alias de la Premier (`set_pl_aliases.py`)

Sin alias, el OCR de un boleto ("Man City", "Wolves", "Spurs") no resuelve el equipo, y
el scrape de Flashscore ("Manchester Utd", "Nottingham", "Wolverhampton") deja huérfanos.

**Files:**
- Create: `set_pl_aliases.py`, `tests/test_set_pl_aliases.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_set_pl_aliases.py`:

```python
"""Merge idempotente de alias (misma lógica que set_intl_aliases, sin tocar red)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_merge_agrega_sin_duplicar():
    from set_pl_aliases import merge_alias
    assert merge_alias(["Man City"], ["Manchester City", "Man City"]) == \
        ["Man City", "Manchester City"]


def test_merge_es_case_insensitive():
    from set_pl_aliases import merge_alias
    assert merge_alias(["man city"], ["Man City"]) == ["man city"]


def test_merge_preserva_los_existentes_y_su_orden():
    from set_pl_aliases import merge_alias
    assert merge_alias(["Z", "A"], ["B"]) == ["Z", "A", "B"]


def test_alias_cubren_los_24_equipos_de_2022_2024():
    """Los 24 nombres son los que devolvió /teams?league=39 para 2022, 2023 y 2024."""
    from set_pl_aliases import ALIAS_PL
    esperados = {
        "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Burnley",
        "Chelsea", "Crystal Palace", "Everton", "Fulham", "Ipswich", "Leeds",
        "Leicester", "Liverpool", "Luton", "Manchester City", "Manchester United",
        "Newcastle", "Nottingham Forest", "Sheffield Utd", "Southampton",
        "Tottenham", "West Ham", "Wolves",
    }
    assert set(ALIAS_PL) == esperados


def test_cada_equipo_tiene_al_menos_un_alias():
    from set_pl_aliases import ALIAS_PL
    assert all(len(v) >= 1 for v in ALIAS_PL.values())
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_set_pl_aliases.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'set_pl_aliases'`.

- [ ] **Step 3: Implementar**

Crear `set_pl_aliases.py`:

```python
"""
Carga de alias para los equipos de la Premier League.

API-Football los nombra corto ("Man…" no: "Manchester United", "Tottenham",
"Wolves"), Flashscore usa otras variantes ("Manchester Utd", "Nottingham",
"Wolverhampton") y las casas de apuestas peruanas mezclan español e inglés
("Manchester Utd.", "Tottenham Hotspur", "Newcastle United"). El validator ya
matchea por `aliases`; este script solo los CARGA en `equipos`.

Updater idempotente: MERGE de los alias nuevos con los existentes (sin duplicar,
sin borrar). Re-ejecutarlo es seguro.

    python set_pl_aliases.py
"""

import os
import sys

from dotenv import load_dotenv
from supabase import create_client

LIGA_NOMBRE = "Premier League"

# Clave = nombre_oficial EXACTO como lo entrega API-Football (verificado con
# /teams?league=39&season=2022|2023|2024 el 2026-07-26).
ALIAS_PL = {
    "Arsenal": ["Arsenal FC"],
    "Aston Villa": ["Villa", "Aston Villa FC"],
    "Bournemouth": ["AFC Bournemouth"],
    "Brentford": ["Brentford FC"],
    "Brighton": ["Brighton & Hove Albion", "Brighton and Hove Albion", "Brighton Hove"],
    "Burnley": ["Burnley FC"],
    "Chelsea": ["Chelsea FC"],
    "Crystal Palace": ["Palace", "Crystal Palace FC"],
    "Everton": ["Everton FC"],
    "Fulham": ["Fulham FC"],
    "Ipswich": ["Ipswich Town"],
    "Leeds": ["Leeds United", "Leeds Utd"],
    "Leicester": ["Leicester City", "Leicester"],
    "Liverpool": ["Liverpool FC"],
    "Luton": ["Luton Town"],
    "Manchester City": ["Man City", "Manchester City FC", "City"],
    "Manchester United": ["Man United", "Man Utd", "Manchester Utd", "Manchester United FC"],
    "Newcastle": ["Newcastle United", "Newcastle Utd"],
    "Nottingham Forest": ["Nottingham", "Nott'm Forest", "Forest"],
    "Sheffield Utd": ["Sheffield United", "Sheffield"],
    "Southampton": ["Southampton FC", "Saints"],
    "Tottenham": ["Tottenham Hotspur", "Spurs"],
    "West Ham": ["West Ham United", "West Ham Utd"],
    "Wolves": ["Wolverhampton", "Wolverhampton Wanderers"],
}


def merge_alias(existentes: list[str], nuevos: list[str]) -> list[str]:
    """Une preservando los existentes y su orden, sin duplicar (case-insensitive)."""
    vistos = {a.lower() for a in existentes}
    salida = list(existentes)
    for a in nuevos:
        if a.lower() not in vistos:
            salida.append(a)
            vistos.add(a.lower())
    return salida


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    liga = sb.table("ligas").select("id").eq("nombre", LIGA_NOMBRE).execute().data
    if not liga:
        print(f"⚠ la liga '{LIGA_NOMBRE}' no existe en `ligas`. "
              "Corre primero: python download_fixtures.py --liga 39 "
              '--nombre "Premier League" --pais England')
        sys.exit(1)

    equipos = (sb.table("equipos").select("id, nombre_oficial, aliases")
               .eq("liga_id", liga[0]["id"]).execute().data)
    por_nombre = {e["nombre_oficial"]: e for e in equipos}
    print(f"Equipos en {LIGA_NOMBRE}: {len(equipos)}")

    actualizados, sin_cambio, no_encontrados = 0, 0, []
    for nombre, nuevos in ALIAS_PL.items():
        e = por_nombre.get(nombre)
        if e is None:
            no_encontrados.append(nombre)
            continue
        existentes = e.get("aliases") or []
        merged = merge_alias(existentes, nuevos)
        if merged == existentes:
            sin_cambio += 1
            continue
        sb.table("equipos").update({"aliases": merged}).eq("id", e["id"]).execute()
        actualizados += 1

    print(f"  Actualizados   : {actualizados}")
    print(f"  Sin cambio     : {sin_cambio}")
    if no_encontrados:
        print(f"  No encontrados : {no_encontrados}")
    print("✅ Alias de la Premier cargados.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr los tests y luego el script**

Run: `python -m pytest tests/test_set_pl_aliases.py -q`
Expected: PASS (5 tests).

Run: `python set_pl_aliases.py`
Expected: `Equipos en Premier League: 24`, `Actualizados: 24`, `No encontrados` ausente.
Si aparece algún nombre en "No encontrados", corregir la clave en `ALIAS_PL` con el
nombre exacto que muestra la verificación de la Tarea 6 y volver a correr.

- [ ] **Step 5: Commit**

```bash
git add set_pl_aliases.py tests/test_set_pl_aliases.py
git commit -m "feat(premier): alias de los 24 equipos (casa de apuestas y Flashscore)

Ingesta hecha: 1140 partidos (380 por temporada 2022-2024), 24 equipos."
```

---

### Task 8: Gate de goles por liga (`gate_goles_liga.py`)

**Files:**
- Create: `gate_goles_liga.py`, `tests/test_gate_goles_liga.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_gate_goles_liga.py`:

```python
"""Funciones puras del gate de goles por liga (sin red ni Supabase)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


def _m(resultado, fecha):
    return {"resultado": resultado, "fecha": fecha,
            "equipo_local_id": "A", "equipo_visitante_id": "B",
            "goles_local": 1, "goles_visitante": 0}


def test_baseline_tasas_son_las_frecuencias_del_train():
    from gate_goles_liga import baseline_tasas
    train = [_m("HOME", "2022-01-01"), _m("HOME", "2022-01-02"),
             _m("DRAW", "2022-01-03"), _m("AWAY", "2022-01-04")]
    ph, pd, pa = baseline_tasas(train)
    assert (ph, pd, pa) == (0.5, 0.25, 0.25)


def test_baseline_tasas_sin_partidos_es_uniforme():
    from gate_goles_liga import baseline_tasas
    ph, pd, pa = baseline_tasas([])
    assert ph == pytest.approx(1 / 3) and pd == pytest.approx(1 / 3)


def test_split_temporal_respeta_la_fecha():
    from gate_goles_liga import split_temporal
    partidos = [_m("HOME", f"2022-01-{d:02d}") for d in range(1, 11)]
    train, test = split_temporal(list(reversed(partidos)), test_frac=0.30)
    assert len(train) == 7 and len(test) == 3
    assert train[0]["fecha"] == "2022-01-01"
    assert test[-1]["fecha"] == "2022-01-10"


def test_gate_pasa_con_mejora_suficiente():
    from gate_goles_liga import decidir_gate
    mejora, ok = decidir_gate(bs_modelo=0.20, bs_baseline=0.25)
    assert ok and mejora == pytest.approx(0.20)


def test_gate_no_pasa_con_mejora_chica():
    from gate_goles_liga import decidir_gate
    mejora, ok = decidir_gate(bs_modelo=0.2450, bs_baseline=0.2500)
    assert not ok and mejora == pytest.approx(0.02)


def test_gate_no_pasa_si_el_modelo_es_peor():
    from gate_goles_liga import decidir_gate
    _, ok = decidir_gate(bs_modelo=0.30, bs_baseline=0.25)
    assert not ok
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_gate_goles_liga.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gate_goles_liga'`.

- [ ] **Step 3: Implementar**

Crear `gate_goles_liga.py`:

```python
"""Gate de goles (Dixon-Coles) para UNA liga de clubes.

Holdout temporal: se ordena por fecha, el último 30% es test. El baseline es
ingenuo: las frecuencias HOME/DRAW/AWAY del train (lo que sabe cualquiera que
mire la tabla). El modelo tiene que batirlo por >= 3% relativo de Brier.

NO publica nada: la ruta de clubes del analyzer reajusta el Dixon-Coles en
runtime desde `partidos`, así que este gate es un go/no-go antes de servir
boletos de esa liga.

    python gate_goles_liga.py --liga "Premier League"
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

GATE_MIN_MEJORA = 0.03
TEST_FRAC = 0.30
TEMPORADAS = ["2022", "2023", "2024"]
RESULTADOS = ("HOME", "DRAW", "AWAY")


def baseline_tasas(train: list[dict]) -> tuple[float, float, float]:
    """Frecuencias (home, draw, away) del train. Sin partidos -> uniforme."""
    c = Counter(m["resultado"] for m in train if m["resultado"] in RESULTADOS)
    n = sum(c.values())
    if n == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (c["HOME"] / n, c["DRAW"] / n, c["AWAY"] / n)


def split_temporal(partidos: list[dict], test_frac: float = TEST_FRAC):
    """Ordena por fecha y parte: primeros (1-frac) train, últimos frac test."""
    ordenados = sorted(partidos, key=lambda m: m["fecha"])
    corte = int(len(ordenados) * (1 - test_frac))
    return ordenados[:corte], ordenados[corte:]


def brier(preds: list[tuple]) -> float:
    """preds: [(p_home, p_draw, p_away, resultado)]. Brier multiclase normalizado."""
    total = 0.0
    for ph, pd, pa, real in preds:
        obs = (1.0 if real == "HOME" else 0.0,
               1.0 if real == "DRAW" else 0.0,
               1.0 if real == "AWAY" else 0.0)
        total += sum((p - o) ** 2 for p, o in zip((ph, pd, pa), obs)) / 2
    return total / len(preds) if preds else 0.0


def decidir_gate(bs_modelo: float, bs_baseline: float,
                 minimo: float = GATE_MIN_MEJORA) -> tuple[float, bool]:
    """(mejora relativa, pasa el gate). Pasa si el modelo es mejor por >= `minimo`."""
    mejora = (bs_baseline - bs_modelo) / bs_baseline if bs_baseline > 0 else 0.0
    return mejora, bool(bs_modelo < bs_baseline and mejora >= minimo)


def cargar_partidos(sb, liga_nombre: str) -> list[dict]:
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        raise SystemExit(f"La liga '{liga_nombre}' no existe en `ligas`.")
    rows = (sb.table("partidos")
            .select("equipo_local_id, equipo_visitante_id, goles_local, "
                    "goles_visitante, resultado, temporada, fecha")
            .eq("liga_id", liga[0]["id"]).in_("temporada", TEMPORADAS)
            .eq("estado", "FINISHED").execute().data)
    return [r for r in rows if r["goles_local"] is not None]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--liga", default="Premier League")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    load_dotenv()
    from analyzer import DixonColesModel   # import tardío: lee env al importar

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    partidos = cargar_partidos(sb, args.liga)
    train, test = split_temporal(partidos)
    print("=" * 60)
    print(f"GATE DE GOLES — {args.liga}")
    print("=" * 60)
    print(f"  partidos: {len(partidos)}  (train {len(train)} / test {len(test)})")
    if len(train) < 100 or len(test) < 30:
        raise SystemExit("  Muestra insuficiente para un gate honesto.")

    ref = datetime.fromisoformat(min(m["fecha"] for m in test).replace("Z", "+00:00"))
    modelo = DixonColesModel().fit(train, ref.astimezone(timezone.utc))

    ph_b, pd_b, pa_b = baseline_tasas(train)
    preds_m, preds_b, sin_cobertura = [], [], 0
    for m in test:
        if m["resultado"] not in RESULTADOS:
            continue
        if m["equipo_local_id"] not in modelo.idx or m["equipo_visitante_id"] not in modelo.idx:
            sin_cobertura += 1
            continue
        ph, pd, pa = modelo.predict(m["equipo_local_id"], m["equipo_visitante_id"])
        preds_m.append((ph, pd, pa, m["resultado"]))
        preds_b.append((ph_b, pd_b, pa_b, m["resultado"]))

    bs_m, bs_b = brier(preds_m), brier(preds_b)
    mejora, ok = decidir_gate(bs_m, bs_b)
    print(f"  baseline tasas train: H={ph_b:.3f} D={pd_b:.3f} A={pa_b:.3f}")
    print(f"  test evaluado: {len(preds_m)} partidos "
          f"({sin_cobertura} sin cobertura de equipo)")
    print(f"  Brier modelo={bs_m:.4f}  baseline={bs_b:.4f}  "
          f"mejora={mejora * 100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
    print("=" * 60)
    return bs_m, bs_b, ok


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr los tests y el gate real**

Run: `python -m pytest tests/test_gate_goles_liga.py -q`
Expected: PASS (6 tests).

Run: `python gate_goles_liga.py --liga "Premier League"`
Expected: `partidos: 1140 (train 798 / test 342)` y `✅ PASA` (el spec anticipa que
goles pasa casi seguro). **Si no pasa**, PARAR: no se sirve la capa de goles de la
Premier; reportar los números a Angel antes de seguir con los hitos 3-5.

Run: `python gate_goles_liga.py --liga "Liga 1 Peruana"`
Expected: corre sin error (referencia de comparación; anotar el resultado).

- [ ] **Step 5: Commit**

```bash
git add gate_goles_liga.py tests/test_gate_goles_liga.py
git commit -m "feat(gate): gate de goles por liga con holdout temporal y baseline de tasas"
```

---

### Task 9: e2e — un boleto real de goles de la Premier

La app solo expone `/api/v1/parlay/analizar` (imagen + OCR) y `/api/v1/parlay/demo`, así
que el e2e sin OCR se hace por el mismo camino que usa el demo: `validate()` + `analyze()`
contra la Supabase real.

**Files:**
- Run: script inline (sin código nuevo)

- [ ] **Step 1: Analizar un boleto de Premier de punta a punta**

```bash
python -c "
from main import _get_teams
from validator import validate
from analyzer import analyze
ocr = {'selecciones': [
  {'equipo_local': 'Man City', 'equipo_visitante': 'Arsenal',
   'mercado': '1X2', 'seleccion': 'home', 'cuota': 2.10, 'linea': None},
  {'equipo_local': 'Man City', 'equipo_visitante': 'Arsenal',
   'mercado': 'over_under', 'seleccion': 'over', 'cuota': 1.75, 'linea': 2.5}],
  'cuota_total': 3.67, 'casa_apuestas': 'Betano'}
p = validate(ocr, _get_teams())
for s in p.selecciones:
    print('match:', s.local_match.canonical, '|', s.visitante_match.canonical,
          '| score', round(s.local_match.score, 3))
r = analyze(p)
print('version:', r.version_modelo, '| nivel:', r.nivel_confianza)
for s in r.selecciones:
    print(f'  {s.mercado:11} {s.seleccion:5} prob_modelo={s.prob_modelo} edge={s.edge}')
print('alertas:', r.alertas)
"
```

Expected:
- los alias resuelven `Man City` → **Manchester City** y `Arsenal` → **Arsenal**
  (score alto, sin `needs_confirmation`);
- `prob_modelo` no nulo en las dos patas;
- sin alertas de cobertura por pocos partidos (cada equipo PL tiene ~114).

- [ ] **Step 2: Verificar el rechazo de parlay mixto**

```bash
python -c "
from main import _get_teams
from validator import validate
from analyzer import analyze
ocr = {'selecciones': [
  {'equipo_local': 'Man City', 'equipo_visitante': 'Arsenal',
   'mercado': '1X2', 'seleccion': 'home', 'cuota': 2.10, 'linea': None},
  {'equipo_local': 'Alianza Lima', 'equipo_visitante': 'Universitario',
   'mercado': '1X2', 'seleccion': 'home', 'cuota': 1.90, 'linea': None}],
  'cuota_total': 3.99, 'casa_apuestas': 'Betano'}
p = validate(ocr, _get_teams())
try:
    analyze(p)
    print('❌ NO rechazó el mixto')
except ValueError as e:
    print('✅ rechazado:', e)
"
```

Expected: `✅ rechazado: Parlay mixto: combina equipos de mas de una liga …`

- [ ] **Step 3: Verificar que el arranque del servidor sigue sano**

```bash
python -c "import analyzer; analyzer.warm_up(); print('warm_up OK')"
```

Expected: `warm_up OK` sin excepciones y **sin** la línea
`[warm_up] premier: La liga 'Premier League' no existe` (los datos ya están).

- [ ] **Step 4: CHECKPOINT con Angel**

Mostrarle la salida del paso 1. Si aprueba, seguir al Hito 3.

---

# HITO 3 — Conteos por equipo (Flashscore)

---

### Task 10: Torneos de la Premier y filtros en el scrape

**Files:**
- Modify: `download_flashscore_stats.py`, `load_flashscore_stats_to_supabase.py`
- Test: `tests/test_scripts_args.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_scripts_args.py`:

```python
# ── download_flashscore_stats.py ──────────────────────────────────────────────

def test_torneos_incluye_las_3_temporadas_de_premier():
    """Slugs verificados el 2026-07-26 (HTTP 200 en flashscore.com)."""
    import download_flashscore_stats as d
    pl = [t for t in d.TOURNAMENTS if t[0] == "Premier League"]
    assert [t[2] for t in pl] == ["2022", "2023", "2024"]
    assert pl[0][1] == ("https://www.flashscore.com/football/england/"
                        "premier-league-2022-2023/results/")


def test_filtrar_torneos_por_liga():
    import download_flashscore_stats as d
    solo_pl = d.filtrar_torneos(d.TOURNAMENTS, "Premier League")
    assert len(solo_pl) == 3
    assert all(t[0] == "Premier League" for t in solo_pl)


def test_filtrar_torneos_sin_filtro_devuelve_todo():
    import download_flashscore_stats as d
    assert d.filtrar_torneos(d.TOURNAMENTS, None) == d.TOURNAMENTS
```

**Nota:** este test importa `download_flashscore_stats`, que importa `seleniumbase` y
`curl_cffi` (solo existen en `.venv-fbref`). Para que corra en el venv del proyecto,
el import de esas libs debe ser **lazy** (dentro de las funciones que las usan).

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_scripts_args.py -q -k "torneos"`
Expected: FAIL — `ModuleNotFoundError: No module named 'seleniumbase'` (import de
nivel superior) o `AttributeError: filtrar_torneos`.

- [ ] **Step 3: Implementar**

En `download_flashscore_stats.py`:

1. Mover los imports de red adentro de las funciones:

```python
import sys
import time

import pandas as pd

from flashscore_transform import parse_results, parse_stats_feed, tidy_match
```

y dentro de `bajar_stats` / `descargar`:

```python
def bajar_stats(event_id):
    from curl_cffi import requests as cr     # solo existe en .venv-fbref
    r = cr.get(f"{FEED}/df_st_1_{event_id}", headers=HDR, impersonate="chrome", timeout=20)
    return parse_stats_feed(r.content.decode("utf-8", "replace"))
```

```python
def descargar(tournaments=None, salida=SALIDA):
    from seleniumbase import SB              # solo existe en .venv-fbref
    tournaments = TOURNAMENTS if tournaments is None else tournaments
    filas = []
    with SB(uc=True, headless=True) as sb:
        for liga, url, season in tournaments:
            ...
    out = pd.DataFrame(filas).drop_duplicates(subset=["event_id", "equipo_flashscore"])
    out.to_csv(salida, index=False, encoding="utf-8")
    return out
```

2. Añadir los 3 torneos de la Premier al final de `TOURNAMENTS`:

```python
    # ── Premier League: 3 temporadas (paridad con los fixtures de API-Football).
    # Slugs de archivo verificados el 2026-07-26 (HTTP 200); el patrón fechado
    # `premier-league-YYYY-YYYY` sí se archiva (a diferencia de los Euros).
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2022-2023/results/", "2022"),
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2023-2024/results/", "2023"),
    ("Premier League", "https://www.flashscore.com/football/england/premier-league-2024-2025/results/", "2024"),
```

3. Añadir el filtro y el CLI:

```python
def filtrar_torneos(tournaments, liga=None):
    """Solo los torneos de una liga (o todos si liga es None). Re-scrapear TODO
    son horas de browser; para añadir una liga se corre solo la suya."""
    if liga is None:
        return tournaments
    return [t for t in tournaments if t[0] == liga]


if __name__ == "__main__":
    import argparse
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--liga", default=None, help='p.ej. "Premier League"')
    p.add_argument("--salida", default=SALIDA)
    a = p.parse_args()
    tours = filtrar_torneos(TOURNAMENTS, a.liga)
    print(f"Scrapeando Flashscore: {len(tours)} torneos -> {a.salida}")
    out = descargar(tours, a.salida)
    print(f"Guardado {len(out)} filas (partido-equipo) en {a.salida}")
    print(f"Equipos distintos: {out['equipo_flashscore'].nunique()}")
```

4. En `load_flashscore_stats_to_supabase.py`, aceptar el CSV por argumento —
reemplazar `df = pd.read_csv(CSV)` por:

```python
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV
    print(f"  CSV: {csv_path}")
    df = pd.read_csv(csv_path)
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add download_flashscore_stats.py load_flashscore_stats_to_supabase.py tests/test_scripts_args.py
git commit -m "feat(capa2): torneos de la Premier en el scrape + filtro por liga y CSV por argumento"
```

---

### Task 11: Scrape y carga de los conteos de la Premier

**Files:**
- Run: `download_flashscore_stats.py`, `load_flashscore_stats_to_supabase.py`
- Data: `flashscore_stats_pl.csv` (nuevo, ignorado por git si aplica)

- [ ] **Step 1: Correr el scrape (largo: ~1140 partidos)**

```bash
.venv-fbref/Scripts/python download_flashscore_stats.py --liga "Premier League" --salida flashscore_stats_pl.csv
```

Expected: 3 líneas `Premier League 202X: ~380 partidos` y al final ~2280 filas
(partido-equipo). Es de horas: correr en background y revisar el log.

- [ ] **Step 2: Cargar a Supabase**

```bash
python load_flashscore_stats_to_supabase.py flashscore_stats_pl.csv
```

Expected: `por liga: {'Premier League': ~2280}`, `equipos distintos: 24`,
**`nombres resueltos: 24/24 (100%)`** gracias a los alias de la Tarea 7.
Si quedan huérfanos, añadir la variante exacta a `ALIAS_PL`, re-correr
`set_pl_aliases.py` y volver a cargar (el upsert es idempotente).

- [ ] **Step 3: Verificar cobertura de métricas**

Expected en el reporte: `corners`, `crd_y`, `sh`, `sot` con cobertura alta (>90%);
la Premier es la liga mejor cubierta de Flashscore.

- [ ] **Step 4: Commit** (solo si el CSV va al repo; si está en `.gitignore`, saltar)

```bash
git add -A
git commit -m "data(capa2): conteos de la Premier scrapeados y cargados"
```

---

### Task 12: Fit, gate y publicación de conteos de la Premier

**Files:**
- Modify: `load_counts_to_supabase.py:23` (`LIGA_NOMBRE`)
- Test: `tests/test_scripts_args.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_scripts_args.py`:

```python
# ── load_counts_to_supabase.py ────────────────────────────────────────────────

def test_mapa_de_ligas_de_conteos_incluye_premier():
    """fit_counts_model agrupa por la columna `liga` del scrape; el loader traduce
    esa etiqueta al nombre de la tabla `ligas`."""
    from load_counts_to_supabase import LIGA_NOMBRE
    assert LIGA_NOMBRE["Premier League"] == "Premier League"
    assert LIGA_NOMBRE["INT"] == "Internacional"
    assert LIGA_NOMBRE["Liga 1 Peru"] == "Liga 1 Peruana"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_scripts_args.py -q -k conteos`
Expected: FAIL — `KeyError: 'Premier League'`.

- [ ] **Step 3: Implementar**

En `load_counts_to_supabase.py:23`:

```python
# etiqueta de liga del scrape (columna `liga`) -> nombre en la tabla `ligas`
LIGA_NOMBRE = {"INT": "Internacional", "Liga 1 Peru": "Liga 1 Peruana",
               "Premier League": "Premier League"}
```

- [ ] **Step 4: Correr el test, el fit y la publicación**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: PASS.

Run: `python fit_counts_model.py`
Expected: una sección `── Liga: Premier League ──` con las 4 métricas y su veredicto.
Anotar cuáles pasan. Expectativa honesta del spec: `shots` y `sot` probablemente pasan;
`corners` y `cards` probablemente NO (son situacionales) — eso es un resultado válido.

Run: `python load_counts_to_supabase.py`
Expected: `Premier League (Premier League): cargadas [...]` con solo las métricas que
pasaron. Verificar que las líneas de `INT` y `Liga 1 Peru` siguen publicándose igual
que antes (el script re-publica las tres ligas; comparar contra la salida previa).

- [ ] **Step 5: Commit**

```bash
git add load_counts_to_supabase.py tests/test_scripts_args.py
git commit -m "feat(conteos): publicar counts_v0.1 de la Premier"
```

---

# HITO 4 — Anota / asiste por jugador

---

### Task 13: Split por liga en `fit_player_model.py`

Corrige el hallazgo 4: hoy los 11.140 registros de Liga 1 Peruana se publican dentro de
los params de "Internacional".

**Files:**
- Modify: `fit_player_model.py` (`_cargar`, `main`, nuevo `agrupar_por_liga`)
- Test: `tests/test_fit_por_liga.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_fit_por_liga.py`:

```python
"""Los fits por-jugador deben separar por liga: un solo pool mezclaba 11.140
registros de Liga 1 Peruana dentro de los params publicados como 'Internacional'."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


LIGA_DE_EQUIPO = {
    "Argentina": "Internacional",
    "France": "Internacional",
    "Arsenal": "Premier League",
    "Chelsea": "Premier League",
    "Alianza Lima": "Liga 1 Peruana",
}


def _reg(equipo, pid):
    return {"event_id": f"e-{pid}", "player_id": pid, "nombre": pid,
            "equipo": equipo, "goles_jugador": 0, "asist_jugador": 0,
            "goles_equipo": 1, "n_titulares": 11}


def test_agrupa_registros_por_liga():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("Arsenal", "p2"), _reg("Alianza Lima", "p3")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert set(por_liga) == {"Internacional", "Premier League", "Liga 1 Peruana"}
    assert [r["player_id"] for r in por_liga["Premier League"]] == ["p2"]


def test_descarta_equipos_sin_liga_conocida():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("Equipo Fantasma", "p9")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert list(por_liga) == ["Internacional"]


def test_ninguna_liga_se_contamina_con_otra():
    from fit_player_model import agrupar_por_liga
    regs = [_reg("Argentina", "p1"), _reg("France", "p2"),
            _reg("Arsenal", "p3"), _reg("Chelsea", "p4")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert len(por_liga["Internacional"]) == 2
    assert len(por_liga["Premier League"]) == 2
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_fit_por_liga.py -q`
Expected: FAIL — `ImportError: cannot import name 'agrupar_por_liga'`.

- [ ] **Step 3: Implementar**

En `fit_player_model.py`, añadir la constante y la función pura (después de `K_LAMBDA`):

```python
MIN_REGISTROS_LIGA = 500   # por debajo de esto el gate de una liga no dice nada


def agrupar_por_liga(regs: list[dict], liga_de_equipo: dict[str, str]) -> dict[str, list[dict]]:
    """{liga: [registros]} usando la liga del equipo del registro.

    Los registros de equipos sin liga conocida se descartan: mezclarlos fue lo que
    metió 11.140 filas de Liga 1 Peruana en los params publicados como
    'Internacional'.
    """
    por_liga = defaultdict(list)
    for r in regs:
        liga = liga_de_equipo.get(r["equipo"])
        if liga:
            por_liga[liga].append(r)
    return dict(por_liga)
```

En `_cargar(sb)`, devolver también el mapa equipo→liga. Reemplazar el bloque inicial:

```python
def _cargar(sb):
    """Eventos (con equipo canónico), titulares por (event,equipo), fecha por event
    y el mapa nombre_de_equipo -> liga (para el split por liga)."""
    ligas = {l["id"]: l["nombre"]
             for l in sb.table("ligas").select("id,nombre").execute().data}
    eq, liga_de_equipo = {}, {}
    for e in sb.table("equipos").select("id,nombre_oficial,liga_id").execute().data:
        eq[e["id"]] = e["nombre_oficial"]
        liga_de_equipo[e["nombre_oficial"]] = ligas.get(e["liga_id"])
```

y cambiar el `return` final de `_cargar` por:

```python
    return eventos, dict(titulares), fecha_ev, liga_de_equipo
```

Reemplazar `main()` por:

```python
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    eventos, titulares, fecha_ev, liga_de_equipo = _cargar(sb)
    regs = registros_desde_eventos(eventos, titulares)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], ""))

    print("=" * 60, "\nFIT MODELO POR-JUGADOR — gate por liga\n", "=" * 60)
    salida = {}
    for liga, regs_liga in sorted(agrupar_por_liga(regs, liga_de_equipo).items()):
        print(f"\n── Liga: {liga} ({len(regs_liga)} registros) ──")
        if len(regs_liga) < MIN_REGISTROS_LIGA:
            print(f"  muestra insuficiente (< {MIN_REGISTROS_LIGA}) — SKIP")
            continue
        corte = int(len(regs_liga) * (1 - TEST_FRAC))
        train, test = regs_liga[:corte], regs_liga[corte:]
        metricas_ok = []
        for metrica in ("goal", "assist"):
            bm, bb = _gate(train, test, metrica)
            mejora = (bb - bm) / bb if bb > 0 else 0.0
            ok = bm < bb and mejora >= GATE_MIN_MEJORA
            print(f"  {metrica:6}: Brier modelo={bm:.4f} base={bb:.4f} "
                  f"mejora={mejora * 100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
            if ok:
                metricas_ok.append(metrica)
        cuotas_prod = estimar_cuotas(regs_liga, k=K_SHRINK, min_partidos=MIN_PARTIDOS)
        print(f"  jugadores publicables: {len(cuotas_prod)}")
        salida[liga] = {"metricas": metricas_ok, "jugadores": cuotas_prod}
    return salida
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_fit_por_liga.py tests/test_fit_player_model.py -q`
Expected: PASS. Si algún test viejo de `test_fit_player_model.py` llamaba a `main()`
esperando el dict plano `{"metricas": …}`, actualizarlo al nuevo contrato
`{liga: {"metricas": …}}` (los tests de `registros_desde_eventos`, `lambdas_por_equipo`
y `_gate` no cambian).

- [ ] **Step 5: Commit**

```bash
git add fit_player_model.py tests/test_fit_por_liga.py
git commit -m "fix(jugador): separar el fit por liga

El pool unico publicaba 11.140 registros de Liga 1 Peruana dentro de los
params de 'Internacional'."
```

---

### Task 14: Publicar `player_v0.2` por liga

**Files:**
- Modify: `load_player_model_to_supabase.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_fit_por_liga.py`:

```python
# ── loaders por liga ──────────────────────────────────────────────────────────

def test_ligas_publicables_filtra_las_que_no_pasaron_el_gate():
    from load_player_model_to_supabase import ligas_publicables
    params = {
        "Internacional": {"metricas": ["goal", "assist"], "jugadores": {"p1": {}}},
        "Premier League": {"metricas": [], "jugadores": {"p2": {}}},
    }
    assert list(ligas_publicables(params)) == ["Internacional"]


def test_ligas_publicables_vacio_si_ninguna_pasa():
    from load_player_model_to_supabase import ligas_publicables
    assert ligas_publicables({"X": {"metricas": [], "jugadores": {}}}) == {}
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_fit_por_liga.py -q -k publicables`
Expected: FAIL — `ImportError: cannot import name 'ligas_publicables'`.

- [ ] **Step 3: Implementar**

Reemplazar `load_player_model_to_supabase.py` (cuerpo, manteniendo el docstring
actualizado y `VERSION`):

```python
VERSION = "player_v0.2"   # v0.2: k=3 (calibración cola elite) + gate con λ por-equipo


def ligas_publicables(params_por_liga: dict) -> dict:
    """Solo las ligas cuyo gate pasó al menos una métrica."""
    return {liga: p for liga, p in params_por_liga.items() if p["metricas"]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    publicables = ligas_publicables(fit_main())
    if not publicables:
        print("Nada que cargar (ninguna liga pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ligas = {l["nombre"]: l["id"]
             for l in sb.table("ligas").select("id,nombre").execute().data}

    for liga_nombre, params in publicables.items():
        liga_id = ligas.get(liga_nombre)
        if liga_id is None:
            print(f"  ⚠ liga '{liga_nombre}' no existe en `ligas` — SKIP")
            continue
        (sb.table("parametros_modelo").delete()
         .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
        sb.table("parametros_modelo").insert({
            "liga_id": liga_id, "version_modelo": VERSION,
            "attack_params": {}, "defense_params": {}, "is_production": True,
            "notas": json.dumps(params),
        }).execute()
        print(f"  ✅ {liga_nombre}: métricas {params['metricas']}, "
              f"{len(params['jugadores'])} jugadores.")
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_fit_por_liga.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add load_player_model_to_supabase.py tests/test_fit_por_liga.py
git commit -m "feat(jugador): publicar player_v0.2 por liga"
```

---

### Task 15: Eventos por jugador de la Premier (scrape + carga)

**Files:**
- Modify: `download_player_events.py`, `load_player_events_to_supabase.py`
- Test: `tests/test_scripts_args.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_scripts_args.py`:

```python
# ── download_player_events.py ─────────────────────────────────────────────────

def test_rutas_player_events_por_defecto():
    from download_player_events import parsear_args
    a = parsear_args([])
    assert a.entrada == "flashscore_stats.csv"
    assert a.salida == "player_events.csv"


def test_rutas_player_events_premier():
    from download_player_events import parsear_args
    a = parsear_args(["--entrada", "flashscore_stats_pl.csv",
                      "--salida", "player_events_pl.csv"])
    assert a.entrada == "flashscore_stats_pl.csv"
    assert a.salida == "player_events_pl.csv"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_scripts_args.py -q -k player_events`
Expected: FAIL — `ImportError: cannot import name 'parsear_args'` (o
`ModuleNotFoundError: curl_cffi` si el import sigue en el nivel superior).

- [ ] **Step 3: Implementar**

En `download_player_events.py`: mover el import de `curl_cffi` dentro de `_feed`,
añadir `parsear_args` y usar las rutas:

```python
import argparse
import csv
import sys
import time

from player_events_transform import eventos_completos, parse_lineup


def _feed(nombre: str) -> str:
    from curl_cffi import requests as cr     # solo existe en .venv-fbref
    r = cr.get(f"{FEED}/{nombre}", headers=HDR, impersonate="chrome", timeout=20)
    return r.content.decode("utf-8", "replace")


def parsear_args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--entrada", default=ENTRADA, help="CSV con los event_id ya scrapeados")
    p.add_argument("--salida", default=SALIDA)
    return p.parse_args(argv)
```

`_event_ids()` pasa a recibir la ruta:

```python
def _event_ids(entrada):
    """event_ids distintos del CSV de stats (ya scrapeados)."""
    ids, visto = [], set()
    with open(entrada, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            eid = r.get("event_id")
            if eid and eid not in visto:
                visto.add(eid)
                ids.append(eid)
    return ids
```

y `main()`:

```python
def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    args = parsear_args(sys.argv[1:] if argv is None else argv)
    ids = _event_ids(args.entrada)
    print(f"{len(ids)} partidos a procesar (desde {args.entrada})")
    todos = []
    for i, eid in enumerate(ids, 1):
        try:
            todos.extend(bajar_partido(eid))
        except Exception as ex:   # noqa: BLE001 — scraper offline, log y sigue
            print(f"  WARN {eid}: {ex}")
        if i % 50 == 0:
            print(f"  {i}/{len(ids)}…")
        time.sleep(0.2)
    with open(args.salida, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "player_id", "nombre",
                                          "tipo", "lado", "fue_titular"])
        w.writeheader()
        w.writerows(todos)
    print(f"✅ {len(todos)} filas -> {args.salida}")
```

En `load_player_events_to_supabase.py`, aceptar el CSV por argumento: reemplazar
`with open("player_events.csv", encoding="utf-8") as f:` por:

```python
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "player_events.csv"
    print(f"  CSV: {csv_path}")
    with open(csv_path, encoding="utf-8") as f:
```

- [ ] **Step 4: Correr los tests y luego el pipeline real**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: PASS (8 tests).

Run (largo, ~2 feeds por partido × 1140):
```bash
.venv-fbref/Scripts/python download_player_events.py --entrada flashscore_stats_pl.csv --salida player_events_pl.csv
python load_player_events_to_supabase.py player_events_pl.csv
```
Expected: identidad de equipo ≥95% (se resuelve por `(event_id, lado)` contra
`estadisticas_flashscore`, ya cargado en la Tarea 11).

- [ ] **Step 5: Commit**

```bash
git add download_player_events.py load_player_events_to_supabase.py tests/test_scripts_args.py
git commit -m "feat(jugador): eventos por jugador de la Premier (CSV por argumento)"
```

---

### Task 16: Gate y publicación de anota/asiste + re-verificación de Internacional

**Files:**
- Run: `fit_player_model.py`, `load_player_model_to_supabase.py`

- [ ] **Step 1: Correr el fit con el split por liga**

```bash
python fit_player_model.py
```

Expected: tres secciones (`Internacional`, `Liga 1 Peruana`, `Premier League`) con su
gate. Anotar los tres resultados. **Ojo con Internacional:** ahora se ajusta SIN las
11.140 filas de Liga 1 — sus números cambian respecto de lo publicado. Comparar contra
el histórico conocido (goal +6.9%, assist +4.1%).

- [ ] **Step 2: Publicar**

```bash
python load_player_model_to_supabase.py
```

Expected: una línea `✅` por liga que pasó. Si `Premier League` no pasa, esa pata queda
`faltante` — es un resultado válido, no un bug.

- [ ] **Step 3: Re-verificar el e2e de Internacional (regresión de producción)**

```bash
python -c "
import os, json
from dotenv import load_dotenv
from supabase import create_client
load_dotenv()
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
ligas = {l['nombre']: l['id'] for l in sb.table('ligas').select('id,nombre').execute().data}
for nombre in ('Internacional', 'Premier League'):
    if nombre not in ligas: continue
    rows = sb.table('parametros_modelo').select('notas').eq('liga_id', ligas[nombre]).eq('version_modelo','player_v0.2').eq('is_production', True).execute().data
    if not rows:
        print(f'{nombre}: sin params'); continue
    p = json.loads(rows[0]['notas'])
    print(f\"{nombre}: metricas={p['metricas']} jugadores={len(p['jugadores'])}\")
    ejemplos = [j for j in p['jugadores'].values() if 'Messi' in (j.get('nombre') or '') or 'Haaland' in (j.get('nombre') or '') or 'Salah' in (j.get('nombre') or '')]
    for j in ejemplos[:5]: print('   ', j.get('nombre'), j.get('equipo'), round(j.get('cuota_gol', 0), 3))
"
```

Expected: Internacional sigue teniendo a Messi con una cuota de gol razonable
(~0.30); Premier debería mostrar a Haaland/Salah arriba si la liga se publicó.

- [ ] **Step 4: CHECKPOINT con Angel** — los params de Internacional cambiaron (menos
jugadores, sin Liga 1 dentro). Mostrarle el antes/después antes de seguir.

- [ ] **Step 5: Commit** (sin cambios de código; anotar los resultados en la memoria del proyecto)

---

# HITO 5 — Tiros al arco por jugador (background, ~13 días)

Arranca en paralelo con los hitos 3-4: son ~1140 fixtures a ~90/día de presupuesto de
API-Football.

---

### Task 17: Manifiesto de la Premier en el backfill de SoT

**Files:**
- Modify: `download_sot_jugador.py:33-40` (MANIFIESTO)
- Test: `tests/test_scripts_args.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_scripts_args.py`:

```python
# ── download_sot_jugador.py ───────────────────────────────────────────────────

def test_manifiesto_incluye_la_premier():
    from download_sot_jugador import MANIFIESTO
    pl = [t for t in MANIFIESTO if t[0] == 39]
    assert pl and pl[0][1] == [2022, 2023, 2024]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_scripts_args.py -q -k manifiesto`
Expected: FAIL — `assert []`.

- [ ] **Step 3: Implementar**

En `download_sot_jugador.py`, añadir al final de `MANIFIESTO`:

```python
    (39, [2022, 2023, 2024]),  # Premier League (plan Free: solo estas 3)
```

- [ ] **Step 4: Correr el test y arrancar el backfill**

Run: `python -m pytest tests/test_scripts_args.py -q`
Expected: PASS.

Run: `python download_sot_jugador.py descubrir`
Expected: `liga 39 2022: 380 fixtures`, idem 2023 y 2024 → 1140 marcados `pendiente`
(3 requests). Los fixtures internacionales ya procesados no se tocan
(`ignore_duplicates=True`).

Luego, la hidratación diaria (ya existe `hidratar_diario.cmd`):
```bash
python download_sot_jugador.py hidratar 90
```
Expected: `✅ hidratados 90 fixtures`. Repetir a diario (~13 días) hasta que no queden
pendientes. **Ojo (lección conocida):** si aparece `⛔ API-Football: …`, la cuota diaria
se agotó — el script para solo y los fixtures quedan `pendiente`; NO son `sin_datos`.

- [ ] **Step 5: Commit**

```bash
git add download_sot_jugador.py tests/test_scripts_args.py
git commit -m "feat(sot): Premier League en el manifiesto del backfill por-jugador"
```

---

### Task 18: Split por liga en `fit_player_sot.py` + publicación

**Files:**
- Modify: `fit_player_sot.py` (`_cargar`, `main`), `load_player_sot_to_supabase.py`
- Test: `tests/test_fit_por_liga.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_fit_por_liga.py`:

```python
# ── fit_player_sot ────────────────────────────────────────────────────────────

def _reg_sot(equipo, pid):
    return {"event_id": f"e-{pid}", "player_id": pid, "nombre": pid,
            "equipo": equipo, "sot_jugador": 1, "sot_equipo": 5, "n_titulares": 11}


def test_sot_agrupa_registros_por_liga():
    from fit_player_sot import agrupar_por_liga
    regs = [_reg_sot("Argentina", "p1"), _reg_sot("Arsenal", "p2")]

    por_liga = agrupar_por_liga(regs, LIGA_DE_EQUIPO)

    assert set(por_liga) == {"Internacional", "Premier League"}


def test_sot_descarta_equipos_sin_liga():
    from fit_player_sot import agrupar_por_liga
    regs = [_reg_sot("Arsenal", "p1"), _reg_sot("Equipo Fantasma", "p2")]

    assert list(agrupar_por_liga(regs, LIGA_DE_EQUIPO)) == ["Premier League"]


def test_sot_ligas_publicables():
    from load_player_sot_to_supabase import ligas_publicables
    params = {"Internacional": {"metricas": ["sot"], "jugadores": {"p": {}}},
              "Premier League": {"metricas": [], "jugadores": {"q": {}}}}
    assert list(ligas_publicables(params)) == ["Internacional"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_fit_por_liga.py -q -k sot`
Expected: FAIL — `ImportError: cannot import name 'agrupar_por_liga'` desde `fit_player_sot`.

- [ ] **Step 3: Implementar**

En `fit_player_sot.py`, añadir la constante y la función (después de `MIN_PARTIDOS`):

```python
MIN_REGISTROS_LIGA = 500   # por debajo de esto el gate de una liga no dice nada


def agrupar_por_liga(regs: list[dict], liga_de_equipo: dict[str, str]) -> dict[str, list[dict]]:
    """{liga: [registros]} usando la liga del equipo. Los equipos sin liga conocida
    se descartan (mismo criterio que fit_player_model)."""
    por_liga = defaultdict(list)
    for r in regs:
        liga = liga_de_equipo.get(r["equipo"])
        if liga:
            por_liga[liga].append(r)
    return dict(por_liga)
```

En `_cargar(sb)`, construir también el mapa de ligas — reemplazar el bloque inicial:

```python
def _cargar(sb):
    """Filas de eventos_sot_jugador con equipo canónico + fecha, y el mapa
    nombre_de_equipo -> liga. Pagina de a 1000."""
    ligas = {l["id"]: l["nombre"]
             for l in sb.table("ligas").select("id,nombre").execute().data}
    eq, liga_de_equipo = {}, {}
    for e in sb.table("equipos").select("id,nombre_oficial,liga_id").execute().data:
        eq[e["id"]] = e["nombre_oficial"]
        liga_de_equipo[e["nombre_oficial"]] = ligas.get(e["liga_id"])
```

y su `return`:

```python
    return filas, liga_de_equipo
```

Reemplazar `main()`:

```python
def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    filas, liga_de_equipo = _cargar(sb)
    fecha_ev = {f["event_id"]: f["fecha"] for f in filas}
    regs = registros_desde_filas(filas)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], "") or "")

    print("=" * 60, "\nFIT MODELO SoT POR-JUGADOR — gate por liga\n", "=" * 60)
    salida = {}
    for liga, regs_liga in sorted(agrupar_por_liga(regs, liga_de_equipo).items()):
        print(f"\n── Liga: {liga} ({len(regs_liga)} registros) ──")
        if len(regs_liga) < MIN_REGISTROS_LIGA:
            print(f"  muestra insuficiente (< {MIN_REGISTROS_LIGA}) — SKIP")
            continue
        corte = int(len(regs_liga) * (1 - TEST_FRAC))
        train, test = regs_liga[:corte], regs_liga[corte:]
        bm, bb = _gate(train, test)
        mejora = (bb - bm) / bb if bb > 0 else 0.0
        ok = bm < bb and mejora >= GATE_MIN_MEJORA
        print(f"  sot: Brier modelo={bm:.4f} base={bb:.4f} "
              f"mejora={mejora * 100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
        print(f"  (lambda_sot real train = {_lambda_sot_real(train):.2f}/equipo)")
        cuotas_prod = estimar_cuotas_sot(regs_liga, k=K_SHRINK, min_partidos=MIN_PARTIDOS)
        salida[liga] = {"metricas": ["sot"] if ok else [], "jugadores": cuotas_prod}
    return salida
```

En `load_player_sot_to_supabase.py`, misma forma que la Tarea 14:

```python
VERSION = "player_sot_v0.1"


def ligas_publicables(params_por_liga: dict) -> dict:
    """Solo las ligas cuyo gate de `sot` pasó."""
    return {liga: p for liga, p in params_por_liga.items() if p["metricas"]}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    publicables = ligas_publicables(fit_main())
    if not publicables:
        print("Nada que cargar (sot no pasó el gate en ninguna liga).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ligas = {l["nombre"]: l["id"]
             for l in sb.table("ligas").select("id,nombre").execute().data}

    for liga_nombre, params in publicables.items():
        liga_id = ligas.get(liga_nombre)
        if liga_id is None:
            print(f"  ⚠ liga '{liga_nombre}' no existe en `ligas` — SKIP")
            continue
        (sb.table("parametros_modelo").delete()
         .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
        sb.table("parametros_modelo").insert({
            "liga_id": liga_id, "version_modelo": VERSION,
            "attack_params": {}, "defense_params": {}, "is_production": True,
            "notas": json.dumps(params),
        }).execute()
        print(f"  ✅ {liga_nombre}: {len(params['jugadores'])} jugadores.")
```

- [ ] **Step 4: Correr los tests y, cuando el backfill drene, el fit**

Run: `python -m pytest tests/test_fit_por_liga.py tests/test_fit_player_sot.py -q`
Expected: PASS (ajustar los tests viejos de `test_fit_player_sot.py` que llamen a
`main()` al nuevo contrato `{liga: {...}}`).

Cuando el backfill termine (sin pendientes):
```bash
python fit_player_sot.py
python load_player_sot_to_supabase.py
```
Expected: sección por liga; publicar solo las que pasan.

- [ ] **Step 5: Commit**

```bash
git add fit_player_sot.py load_player_sot_to_supabase.py tests/test_fit_por_liga.py
git commit -m "fix(sot): separar el fit por liga y publicar player_sot_v0.1 por liga"
```

---

# HITO 6 — Demo, docs y cierre

---

### Task 19: Caso `?demo=premier`

**Files:**
- Modify: `main.py:311-367` (endpoint `/api/v1/parlay/demo`)
- Test: `tests/test_demo_premier.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_demo_premier.py`:

```python
"""El demo de Premier corre el motor real sin OCR y sin red de ausencias."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


def test_demo_premier_arma_el_parlay_de_la_premier():
    from main import _ocr_demo
    ocr = _ocr_demo("premier")
    equipos = {s["equipo_local"] for s in ocr["selecciones"]}
    assert equipos == {"Man City"}
    assert {s["mercado"] for s in ocr["selecciones"]} == {"1X2", "over_under", "count"}


def test_demo_sin_case_sigue_siendo_el_parlay_internacional():
    """Regresión: `?demo` sin case y `?case=ausencias` no cambian."""
    from main import _ocr_demo
    for case in ("", "ausencias"):
        ocr = _ocr_demo(case)
        assert {s["equipo_local"] for s in ocr["selecciones"]} == {"Argentina"}


def test_demo_premier_no_inyecta_ausentes():
    from main import _payload_ausencias_demo
    assert _payload_ausencias_demo("premier") == {"sin_dato": True}
    assert "equipos" in _payload_ausencias_demo("ausencias")
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_demo_premier.py -q`
Expected: FAIL — `ImportError: cannot import name '_ocr_demo' from 'main'`.

- [ ] **Step 3: Implementar**

En `main.py`, extraer los dos datos fijos del endpoint a funciones puras (justo encima
de `@app.get("/api/v1/parlay/demo")`) y usarlas dentro:

```python
_OCR_DEMO_INTL = {
    "selecciones": [
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "1X2", "seleccion": "home", "cuota": None, "linea": None},
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 1.5},
        {"equipo_local": "Argentina", "equipo_visitante": "Austria",
         "mercado": "player", "seleccion": "yes", "player": "Lionel Messi",
         "metric": "sot", "umbral": 1, "faltante": False,
         "cuota": None, "linea": None},
    ],
    "cuota_total": 1.87,
    "casa_apuestas": "Betano",
}

# Boleto de Premier: una pata de goles, una de total de goles y una de conteo por
# equipo. Los nombres van como los escribe una casa ("Man City") a propósito: el
# demo también verifica que los alias resuelvan.
_OCR_DEMO_PREMIER = {
    "selecciones": [
        {"equipo_local": "Man City", "equipo_visitante": "Arsenal",
         "mercado": "1X2", "seleccion": "home", "cuota": None, "linea": None},
        {"equipo_local": "Man City", "equipo_visitante": "Arsenal",
         "mercado": "over_under", "seleccion": "over", "cuota": None, "linea": 2.5},
        {"equipo_local": "Man City", "equipo_visitante": "Arsenal",
         "mercado": "count", "seleccion": "over", "metric": "sot",
         "ambito": "total", "cuota": None, "linea": 8.5},
    ],
    "cuota_total": 2.45,
    "casa_apuestas": "Betano",
}

_AUSENTES_DEMO = {
    "equipos": {
        "Argentina": [
            {"nombre": "Lionel Messi", "estado": "out",
             "motivo": "Injured - Muscle", "posicion": None},
            {"nombre": "Angel Di Maria", "estado": "doubtful",
             "motivo": "Knock", "posicion": None}],
        "Austria": [
            {"nombre": "David Alaba", "estado": "out",
             "motivo": "Suspended", "posicion": "D"}]},
    "url": "https://www.sofascore.com/football/match/argentina-austria/demo",
    "scrapeado_en": "2026-07-22T12:00:00",
}


def _ocr_demo(case: str) -> dict:
    """Boleto fijo del demo según el caso pedido."""
    return _OCR_DEMO_PREMIER if case == "premier" else _OCR_DEMO_INTL


def _payload_ausencias_demo(case: str) -> dict:
    """Caché de ausencias inyectada: solo `?case=ausencias` trae ausentes."""
    return _AUSENTES_DEMO if case == "ausencias" else {"sin_dato": True}
```

Y reemplazar el cuerpo del endpoint (main.py:320-352) por:

```python
    import os as _os
    import ausencias_sofascore as _aus
    t0 = time.monotonic()
    ocr_data = _ocr_demo(case)
    _payload = _payload_ausencias_demo(case)
    _local = ocr_data["selecciones"][0]["equipo_local"]
    _visit = ocr_data["selecciones"][0]["equipo_visitante"]
    _cache = _aus._cache_path(_local, _visit)
    _aus._escribir_cache(_cache, _payload)
```

(El resto del endpoint —`try/except/finally`, serialización y respuesta— no cambia;
solo hay que dejar el `_cache_path` calculado con los equipos del caso, no con
"Argentina"/"Austria" fijos.) Actualizar el docstring del endpoint añadiendo:
`?case=premier` inyecta un boleto de la Premier (goles + conteo) con ausencias `sin_dato`.

- [ ] **Step 4: Correr los tests y ver el demo en el navegador**

Run: `python -m pytest -q`
Expected: toda la suite verde.

Levantar backend y frontend, abrir `http://localhost:5173/?demo=premier` y confirmar
que las cards renderizan las tres patas con el veredicto.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_demo_premier.py
git commit -m "feat(demo): caso ?demo=premier para el gate visual sin red"
```

---

### Task 20: Documentación y cierre

**Files:**
- Modify: `docs/COBERTURA.md`

- [ ] **Step 1: Actualizar el mapa de cobertura**

En `docs/COBERTURA.md`: cambiar `Última actualización` a la fecha del día, añadir la
Premier a la columna **Ligas** de cada familia que pasó su gate, y añadir bajo el aviso
de foco un párrafo nuevo (los `…` se rellenan con los resultados REALES de las Tareas
8, 12, 16 y 18 — no inventar):

```markdown
> **Premier League (2026-07-26):** post-Mundial se ingestaron 3 temporadas
> (2022/23–2024/25, 1140 partidos, 24 equipos) y el ruteo del analyzer pasó de binario
> (Liga1/Internacional) a N ligas. Publicado: goles (Dixon-Coles, gate …),
> conteos … , anota/asiste … , tiros-al-arco jugador … . No publicado (queda
> `FALTANTE`): … . Un boleto que mezcle Premier con otra liga se rechaza como mixto.
```

Y en la tabla de **Pendiente**, una fila por cada métrica de la Premier que no pasó
su gate, con el motivo medido (no "por hacer": el gate corrió y no pasó).

- [ ] **Step 2: Correr la suite completa una última vez**

Run: `python -m pytest -q`
Expected: verde.

- [ ] **Step 3: Commit**

```bash
git add docs/COBERTURA.md
git commit -m "docs(cobertura): patas cubiertas por la Premier League"
```

- [ ] **Step 4: Verificación visual de Angel**

Levantar backend + frontend, subir un boleto real de Premier (o abrir `?demo=premier`)
y confirmar que las cards se ven bien.

- [ ] **Step 5: Cierre de rama**

Usar `superpowers:finishing-a-development-branch` para decidir merge/PR de
`feat/premier-league`.

---

## Notas de ejecución

- **Orden:** Hitos 1→2 son secuenciales y obligatorios. El Hito 5 (backfill SoT) se
  arranca apenas termina el Hito 2 (necesita solo el manifiesto) y corre en paralelo a
  los hitos 3-4.
- **Checkpoints con Angel:** Tarea 4b (cambio en Liga 1), Tarea 9 (e2e de goles) y
  Tarea 16 (cambio en los params de Internacional). No seguir sin su OK en esos tres.
- **Presupuesto de API-Football:** Tarea 6 = 3 requests, Tarea 17 `descubrir` = 3,
  luego 90/día durante ~13 días. Si `payload["errors"]` viene poblado con HTTP 200, la
  cuota se agotó (reset 7 PM Lima).
- **Gates que no pasan no son fracasos:** la pata queda `faltante` y el veredicto lo
  refleja. Publicar un número malo sí sería el fracaso.
