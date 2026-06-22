# Capa 2 · Sub-proyecto A — Pipeline de datos FBref · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Descargar de FBref las estadísticas por partido-equipo (tarjetas + tiros) de competiciones internacionales, resolver la identidad de equipos contra `equipos`, y persistirlas en una tabla nueva de Supabase con un reporte de cobertura que sirva de gate antes de modelar.

**Architecture:** Pipeline de dos scripts (espejo de `download_intl_results.py` + `load_intl_to_supabase.py`). El scrape vive en un venv aislado (`.venv-fbref`, deps pesadas: soccerdata/pandas3/selenium) y produce un CSV; la carga corre en el entorno del proyecto y escribe a Supabase. Las funciones puras (reshape de columnas, resolución de nombres) viven en `fbref_transform.py`, que NO importa soccerdata ni lee env al importar, para ser testeables en el entorno del proyecto.

**Tech Stack:** Python 3.12, soccerdata 1.9 (solo en `.venv-fbref`), pandas, rapidfuzz (vía `validator._best_match`), supabase-py, Supabase Management API (DDL), pytest.

**Regla de oro:** la suite actual (135 tests) sigue verde; nada del runtime de la API cambia. Spec: `docs/superpowers/specs/2026-06-22-capa2-subproyecto-a-datos-fbref-design.md`.

---

### Task 0: Aislamiento del entorno y gitignore

**Files:**
- Create: `.venv-fbref/` (venv, no se commitea)
- Create: `requirements-fbref.txt`
- Modify: `.gitignore`

- [ ] **Step 1: Crear el venv aislado e instalar soccerdata ahí**

Run:
```bash
python -m venv .venv-fbref
.venv-fbref/Scripts/python -m pip install soccerdata
```
Expected: instalación OK; `.venv-fbref/Scripts/python -c "import soccerdata"` no falla.

- [ ] **Step 2: Congelar las deps del scrape**

Run:
```bash
.venv-fbref/Scripts/python -m pip freeze > requirements-fbref.txt
```

- [ ] **Step 3: Ignorar el venv y el CSV intermedio**

Añadir a `.gitignore` (al final):
```
.venv-fbref/
fbref_stats.csv
```

- [ ] **Step 4: Desinstalar soccerdata del entorno principal (limpia el conflicto websockets<16) y verificar que la suite sigue verde**

Run:
```bash
python -m pip uninstall -y soccerdata seleniumbase selenium
python -m pytest -q
```
Expected: `135 passed`. (Si pandas/websockets quedaron en versión incompatible y algún test falla, fijar `pandas` y `websockets` a la versión previa con pip; el objetivo es 135 verdes.)

- [ ] **Step 5: Commit**

```bash
git add .gitignore requirements-fbref.txt
git commit -m "chore: venv aislado .venv-fbref para el scrape de FBref"
```

---

### Task 1: `fbref_transform.merge_misc_shooting` (función pura, TDD)

Reshape de los DataFrames crudos de soccerdata (columnas MultiIndex) a una tabla tidy de una fila por partido-equipo con nombres de columna canónicos.

**Files:**
- Create: `fbref_transform.py`
- Test: `tests/test_fbref_transform.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fbref_transform.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
from fbref_transform import merge_misc_shooting


def _idx():
    return pd.MultiIndex.from_tuples(
        [("INT-World Cup", "2022", "Argentina", "2022-11-22 Argentina-Saudi Arabia")],
        names=["league", "season", "team", "game"],
    )


def _misc_df():
    cols = pd.MultiIndex.from_tuples([
        ("date", ""), ("venue", ""), ("opponent", ""), ("GF", ""), ("GA", ""),
        ("Performance", "CrdY"), ("Performance", "CrdR"), ("Performance", "2CrdY"),
        ("Performance", "Fls"), ("Performance", "Crs"), ("Performance", "Off"),
    ])
    return pd.DataFrame(
        [["2022-11-22", "Neutral", "Saudi Arabia", 1, 2, 3, 0, 0, 15, 18, 4]],
        index=_idx(), columns=cols,
    )


def _shooting_df():
    cols = pd.MultiIndex.from_tuples([
        ("date", ""), ("venue", ""), ("opponent", ""),
        ("Standard", "Sh"), ("Standard", "SoT"),
    ])
    return pd.DataFrame(
        [["2022-11-22", "Neutral", "Saudi Arabia", 14, 6]],
        index=_idx(), columns=cols,
    )


def test_merge_produces_tidy_row():
    out = merge_misc_shooting(_misc_df(), _shooting_df())
    assert len(out) == 1
    row = out.iloc[0]
    assert row["liga"] == "INT-World Cup"
    assert row["season"] == "2022"
    assert row["equipo_fbref"] == "Argentina"
    assert row["rival_fbref"] == "Saudi Arabia"
    assert row["fecha"] == "2022-11-22"
    assert row["gf"] == 1 and row["ga"] == 2
    assert row["crd_y"] == 3 and row["crd_r"] == 0 and row["crd_2y"] == 0
    assert row["fls"] == 15 and row["crs"] == 18 and row["off"] == 4
    assert row["sh"] == 14 and row["sot"] == 6


def test_merge_keeps_one_row_per_team_match_when_shooting_missing():
    # Si shooting no tiene la fila, la tarjeta se conserva con tiros NaN.
    out = merge_misc_shooting(_misc_df(), _shooting_df().iloc[0:0])
    assert len(out) == 1
    assert pd.isna(out.iloc[0]["sh"])
    assert out.iloc[0]["crd_y"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fbref_transform.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'fbref_transform'`.

- [ ] **Step 3: Write minimal implementation**

```python
# fbref_transform.py
"""Funciones puras del pipeline FBref (Capa 2). NO importa soccerdata ni lee
env al importar: corre en el entorno del proyecto y es testeable sin red."""

import pandas as pd

MISC_RENAME = {"CrdY": "crd_y", "CrdR": "crd_r", "2CrdY": "crd_2y",
               "Fls": "fls", "Crs": "crs", "Off": "off"}
SHOOT_RENAME = {"Sh": "sh", "SoT": "sot"}

_KEY = ["league", "season", "team", "game"]
_CTX = ["date", "venue", "opponent", "GF", "GA"]


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """reset_index + aplana columnas MultiIndex: ('Performance','CrdY')->'CrdY',
    ('league','')->'league'."""
    df = df.reset_index()
    nuevas = []
    for c in df.columns:
        if isinstance(c, tuple):
            nuevas.append(c[1] if len(c) > 1 and c[1] else c[0])
        else:
            nuevas.append(c)
    df = df.copy()
    df.columns = nuevas
    return df


def merge_misc_shooting(misc_df: pd.DataFrame, shooting_df: pd.DataFrame) -> pd.DataFrame:
    """Une las stats 'misc' (tarjetas+derivados) y 'shooting' (tiros) de
    soccerdata en una tabla tidy de una fila por partido-equipo."""
    m = _flatten(misc_df).rename(columns=MISC_RENAME)
    s = _flatten(shooting_df).rename(columns=SHOOT_RENAME)

    cols_m = [c for c in (_KEY + _CTX + list(MISC_RENAME.values())) if c in m.columns]
    cols_s = [c for c in (_KEY + list(SHOOT_RENAME.values())) if c in s.columns]
    m = m[cols_m]
    s = s[cols_s]

    out = m.merge(s, on=_KEY, how="left")
    return out.rename(columns={
        "league": "liga", "date": "fecha", "opponent": "rival_fbref",
        "team": "equipo_fbref", "GF": "gf", "GA": "ga",
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fbref_transform.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add fbref_transform.py tests/test_fbref_transform.py
git commit -m "feat: fbref_transform.merge_misc_shooting (reshape tidy de stats FBref)"
```

---

### Task 2: `fbref_transform.resolver_equipo_id` (función pura, TDD)

Resuelve un nombre crudo de FBref a `equipo_id` reusando el matcher fuzzy+alias del validator. Política de bulk: solo acepta match automático (`score >= umbral`); por debajo devuelve `None` (huérfano), para evitar falsos positivos sin humano en el loop.

**Files:**
- Modify: `fbref_transform.py`
- Test: `tests/test_fbref_transform.py`

- [ ] **Step 1: Write the failing test**

```python
# añadir a tests/test_fbref_transform.py
from fbref_transform import resolver_equipo_id

_TEAMS = [
    {"id": "kr", "nombre_oficial": "South Korea", "aliases": ["Corea del Sur", "Korea Republic"]},
    {"id": "ar", "nombre_oficial": "Argentina", "aliases": []},
]


def test_resolver_match_por_alias():
    # FBref dice "Korea Republic"; el alias lo lleva a South Korea.
    eid, canon, score = resolver_equipo_id("Korea Republic", _TEAMS)
    assert eid == "kr"
    assert canon == "South Korea"
    assert score >= 0.85


def test_resolver_huerfano_devuelve_none():
    eid, canon, score = resolver_equipo_id("Atlantis United", _TEAMS)
    assert eid is None
    assert canon == ""


def test_resolver_umbral_estricto_descarta_match_debil():
    # Forzando umbral 0.99, incluso un match razonable cae a huérfano.
    eid, _, _ = resolver_equipo_id("Argentin", _TEAMS, umbral=0.99)
    assert eid is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fbref_transform.py -k resolver -v`
Expected: FAIL con `ImportError: cannot import name 'resolver_equipo_id'`.

- [ ] **Step 3: Write minimal implementation**

```python
# añadir a fbref_transform.py
from validator import _best_match, MATCH_AUTO  # _best_match no lee env al importar


def resolver_equipo_id(nombre: str, teams: list[dict], umbral: float = MATCH_AUTO):
    """(equipo_id | None, canonical, score). Solo acepta match >= umbral
    (bulk, sin confirmación humana). Por debajo -> huérfano (None)."""
    m = _best_match(nombre, teams)
    if m.score >= umbral and m.equipo_id:
        return m.equipo_id, m.canonical, m.score
    return None, "", m.score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fbref_transform.py -v`
Expected: PASS (5 tests en total en el archivo).

- [ ] **Step 5: Commit**

```bash
git add fbref_transform.py tests/test_fbref_transform.py
git commit -m "feat: fbref_transform.resolver_equipo_id (nombre FBref -> equipo_id)"
```

---

### Task 3: `download_fbref_stats.py` (scrape, corre en `.venv-fbref`)

Sin test unitario (depende de red). Se valida ejecutándolo en el venv aislado y revisando el CSV.

**Files:**
- Create: `download_fbref_stats.py`

- [ ] **Step 1: Escribir el script de scrape**

```python
# download_fbref_stats.py
"""Descarga stats por partido-equipo (tarjetas+tiros) de FBref via soccerdata
y las guarda en fbref_stats.csv. CORRE EN EL VENV AISLADO .venv-fbref:
    .venv-fbref/Scripts/python download_fbref_stats.py

Cobertura: INT-World Cup + INT-European Championship, ediciones disponibles.
Cada edición devuelve el match-log del año de sus participantes."""

import sys
import pandas as pd
import soccerdata as sd

from fbref_transform import merge_misc_shooting

LEAGUES = ["INT-World Cup", "INT-European Championship"]
SEASONS = [2018, 2020, 2022, 2024, 2026]   # ediciones; soccerdata ignora las inexistentes
SALIDA = "fbref_stats.csv"


def descargar():
    fb = sd.FBref(leagues=LEAGUES, seasons=SEASONS)
    misc = fb.read_team_match_stats(stat_type="misc")
    shooting = fb.read_team_match_stats(stat_type="shooting")
    tidy = merge_misc_shooting(misc, shooting)
    tidy.to_csv(SALIDA, index=False, encoding="utf-8")
    return tidy


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Descargando misc + shooting de FBref (puede tardar varios minutos)...")
    tidy = descargar()
    print(f"Guardado {len(tidy)} filas (partido-equipo) en {SALIDA}")
    print(f"Selecciones distintas: {tidy['equipo_fbref'].nunique()}")
    print("Columnas:", list(tidy.columns))
```

- [ ] **Step 2: Ejecutar el scrape en el venv aislado**

Run:
```bash
.venv-fbref/Scripts/python download_fbref_stats.py
```
Expected: imprime nº de filas y selecciones; crea `fbref_stats.csv`. (Si `shooting` usa otra etiqueta de columna distinta de `Sh`/`SoT`, ajustar `SHOOT_RENAME` en `fbref_transform.py` mirando `list(shooting.columns)` y re-correr; el test de Task 1 con datos sintéticos sigue verde porque define su propia forma.)

- [ ] **Step 3: Sanity-check del CSV**

Run:
```bash
python -c "import pandas as pd; d=pd.read_csv('fbref_stats.csv'); print(d.shape); print(d[['equipo_fbref','rival_fbref','crd_y','sh']].head()); print('con tarjetas:', d['crd_y'].notna().mean()); print('con tiros:', d['sh'].notna().mean())"
```
Expected: cientos/miles de filas; columnas pobladas.

- [ ] **Step 4: Commit (solo el script; el CSV está gitignored)**

```bash
git add download_fbref_stats.py
git commit -m "feat: download_fbref_stats.py (scrape tarjetas+tiros FBref a CSV)"
```

---

### Task 4: `load_fbref_stats_to_supabase.py` — DDL de la tabla nueva

Crea la tabla `estadisticas_partido` vía Management API (patrón de `load_intl_to_supabase.py`).

**Files:**
- Create: `load_fbref_stats_to_supabase.py`

- [ ] **Step 1: Escribir el esqueleto con DDL**

```python
# load_fbref_stats_to_supabase.py
"""Carga fbref_stats.csv a Supabase: resuelve equipo_id, crea la tabla
estadisticas_partido e inserta filas crudas por partido-equipo. Imprime un
reporte de cobertura (gate antes de modelar). CORRE EN EL ENTORNO DEL PROYECTO:
    python load_fbref_stats_to_supabase.py
"""

import os
import sys

import pandas as pd
import requests
from dotenv import load_dotenv
from supabase import create_client

from fbref_transform import resolver_equipo_id

CSV = "fbref_stats.csv"
PROJECT_REF = "aahaivisyghpgqarqpak"

DDL = """
CREATE TABLE IF NOT EXISTS estadisticas_partido (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fecha         DATE,
    liga          TEXT,
    season        TEXT,
    equipo_id     UUID REFERENCES equipos(id),
    equipo_fbref  TEXT NOT NULL,
    rival_id      UUID REFERENCES equipos(id),
    rival_fbref   TEXT NOT NULL,
    venue         TEXT,
    gf            INTEGER,
    ga            INTEGER,
    crd_y         INTEGER,
    crd_r         INTEGER,
    crd_2y        INTEGER,
    fls           INTEGER,
    crs           INTEGER,
    "off"         INTEGER,
    sh            INTEGER,
    sot           INTEGER,
    UNIQUE (fecha, equipo_fbref, rival_fbref)
);
ALTER TABLE estadisticas_partido DISABLE ROW LEVEL SECURITY;
"""


def run_ddl(sql, mgmt_token):
    resp = requests.post(
        f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query",
        headers={"Authorization": f"Bearer {mgmt_token}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    print("[1/3] DDL: tabla estadisticas_partido...")
    run_ddl(DDL, mgmt_token)
    print("  tabla lista")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar la creación de la tabla**

Run: `python load_fbref_stats_to_supabase.py`
Expected: imprime "tabla lista" sin error (tras `[1/3] DDL`).

- [ ] **Step 3: Verificar que la tabla existe**

Run:
```bash
python -c "import os; from dotenv import load_dotenv; from supabase import create_client; load_dotenv(); sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_KEY']); print(sb.table('estadisticas_partido').select('id', count='exact').execute().count)"
```
Expected: `0` (tabla vacía existe).

- [ ] **Step 4: Commit**

```bash
git add load_fbref_stats_to_supabase.py
git commit -m "feat: load script crea tabla estadisticas_partido (DDL)"
```

---

### Task 5: `load_fbref_stats_to_supabase.py` — resolución, upsert y reporte de cobertura

**Files:**
- Modify: `load_fbref_stats_to_supabase.py`

- [ ] **Step 1: Añadir resolución de equipos + upsert + reporte**

Reemplazar el cuerpo de `main()` por:

```python
def _to_int(v):
    return None if pd.isna(v) else int(v)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print("[1/3] DDL: tabla estadisticas_partido...")
    run_ddl(DDL, mgmt_token)

    print("[2/3] Resolviendo equipos y construyendo filas...")
    df = pd.read_csv(CSV)
    teams = sb.table("equipos").select("id, nombre_oficial, aliases").execute().data

    # cache de resolución por nombre FBref
    cache = {}
    def resolver(n):
        if n not in cache:
            cache[n] = resolver_equipo_id(str(n), teams)
        return cache[n]

    filas = []
    for _, r in df.iterrows():
        eid, _, _ = resolver(r["equipo_fbref"])
        rid, _, _ = resolver(r["rival_fbref"])
        filas.append({
            "fecha": r["fecha"], "liga": r["liga"], "season": str(r["season"]),
            "equipo_id": eid, "equipo_fbref": r["equipo_fbref"],
            "rival_id": rid, "rival_fbref": r["rival_fbref"],
            "venue": r.get("venue"),
            "gf": _to_int(r.get("gf")), "ga": _to_int(r.get("ga")),
            "crd_y": _to_int(r.get("crd_y")), "crd_r": _to_int(r.get("crd_r")),
            "crd_2y": _to_int(r.get("crd_2y")), "fls": _to_int(r.get("fls")),
            "crs": _to_int(r.get("crs")), "off": _to_int(r.get("off")),
            "sh": _to_int(r.get("sh")), "sot": _to_int(r.get("sot")),
        })

    # upsert idempotente por la clave única
    for i in range(0, len(filas), 500):
        sb.table("estadisticas_partido").upsert(
            filas[i:i+500], on_conflict="fecha,equipo_fbref,rival_fbref"
        ).execute()

    # ── [3/3] Reporte de cobertura (gate antes de modelar) ──
    print("[3/3] Reporte de cobertura:")
    nombres = sorted(set(df["equipo_fbref"]) | set(df["rival_fbref"]))
    huerfanos = [n for n in nombres if resolver(n)[0] is None]
    vc = df["equipo_fbref"].value_counts()
    print(f"  filas (partido-equipo): {len(df)}")
    print(f"  selecciones distintas : {df['equipo_fbref'].nunique()}")
    print(f"  partidos/seleccion    : min={int(vc.min())} med={int(vc.median())} max={int(vc.max())}")
    print(f"  nombres resueltos     : {len(nombres)-len(huerfanos)}/{len(nombres)}"
          f" ({100*(len(nombres)-len(huerfanos))/len(nombres):.0f}%)")
    print(f"  huerfanos ({len(huerfanos)}): {huerfanos[:20]}")
    print(f"  filas con tarjetas    : {df['crd_y'].notna().mean()*100:.0f}%")
    print(f"  filas con tiros       : {df['sh'].notna().mean()*100:.0f}%")
    print("\n✅ Datos cargados. Revisar el reporte para decidir el Sub-proyecto B.")
```

- [ ] **Step 2: Ejecutar la carga completa**

Run: `python load_fbref_stats_to_supabase.py`
Expected: imprime el reporte de cobertura con números reales; sin errores.

- [ ] **Step 3: Verificar filas insertadas e idempotencia**

Run:
```bash
python -c "import os; from dotenv import load_dotenv; from supabase import create_client; load_dotenv(); sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_KEY']); print('filas:', sb.table('estadisticas_partido').select('id', count='exact').execute().count); print('con equipo_id:', sb.table('estadisticas_partido').select('id', count='exact').not_.is_('equipo_id','null').execute().count)"
```
Expected: nº de filas > 0 y coincide tras re-correr el script (no duplica).

- [ ] **Step 4: Commit**

```bash
git add load_fbref_stats_to_supabase.py
git commit -m "feat: load resuelve equipos, upsert idempotente y reporte de cobertura"
```

---

### Task 6: Verificación end-to-end y suite

**Files:** ninguno (verificación).

- [ ] **Step 1: Confirmar que la suite del proyecto sigue verde**

Run: `python -m pytest -q`
Expected: `140 passed` (135 previos + 5 nuevos de `tests/test_fbref_transform.py`). Confirmar que no hay regresiones.

- [ ] **Step 2: Releer el reporte de cobertura del Task 5**

Decisión-gate: ¿hay densidad suficiente (partidos/selección) y % de resolución de nombres aceptable para modelar tarjetas/tiros con skill? Documentar los números en una nota para arrancar el Sub-proyecto B. Si la cobertura es pobre, B reconsidera (prior/fallback o más temporadas/competiciones).

- [ ] **Step 3: Commit (si se añadió alguna nota/doc)**

```bash
git add -A
git commit -m "docs: reporte de cobertura Capa 2 sub-proyecto A"
```

---

## Notas de implementación

- **Orden de entornos:** Task 0 y Task 3 usan `.venv-fbref/Scripts/python`. Todo lo demás (tests, load) usa el `python` del entorno del proyecto.
- **`fbref_transform.py` no debe importar soccerdata** (solo pandas + validator). Eso lo hace testeable sin el venv aislado.
- **`validator._best_match` no lee env al importar** (el `create_client` está dentro de `_load_teams`), por eso se puede importar en `fbref_transform` y en los tests sin DB.
- **Columnas de `shooting`:** el sondeo confirmó la forma de `misc`; la de `shooting` (`Sh`/`SoT`) se confirma al correr Task 3 paso 2. Si difiere, ajustar `SHOOT_RENAME`.
- **Idempotencia:** el upsert usa la clave única `(fecha, equipo_fbref, rival_fbref)`; re-correr la carga no duplica.
- **Este sub-proyecto NO crea modelo.** Su entregable es la tabla `estadisticas_partido` poblada + el reporte de cobertura.
