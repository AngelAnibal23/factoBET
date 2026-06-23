# Capa 2 · Pipeline de datos Flashscore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrapear de Flashscore las estadísticas por partido-equipo (córners, tarjetas, tiros, faltas, offsides, posesión, xG) de Mundial + Euro + Liga 1, resolver identidad de equipos, y persistirlas en una tabla nueva de Supabase con un reporte de cobertura que sirva de gate antes de modelar.

**Architecture:** Patrón híbrido en dos scripts (espejo del pipeline FBref). Un browser stealth (seleniumbase UC) enumera los event ids + metadata del DOM de la página de resultados (1 load por edición); las stats se bajan con un feed liviano (`df_st_1_{id}`, curl_cffi + `x-fsign`). Las funciones puras de parseo/tidy viven en `flashscore_transform.py` (sin red, testeables). Corre en `.venv-fbref` (ya tiene seleniumbase + curl_cffi). Spec: `docs/superpowers/specs/2026-06-23-capa2-flashscore-pipeline-design.md`.

**Tech Stack:** Python 3.12, seleniumbase (UC mode, en `.venv-fbref`), curl_cffi, pandas, rapidfuzz (vía `validator._best_match`), supabase-py, Supabase Management API (DDL), pytest.

**Regla de oro:** la suite actual (166 tests) sigue verde; nada del runtime de la API cambia. Reusa `resolver_equipo_id` de `fbref_transform.py`.

---

### Task 1: `flashscore_transform.parse_stats_feed` (función pura, TDD)

Parsea el feed packed `df_st` (`SG÷métrica¬SH÷local¬SI÷visitante`) a un dict `{métrica: (local, visitante)}`, tomando la primera ocurrencia de cada métrica (período full-match).

**Files:**
- Create: `flashscore_transform.py`
- Test: `tests/test_flashscore_transform.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_flashscore_transform.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flashscore_transform import parse_stats_feed

SEP_F = "¬"   # ¬
SEP_KV = "÷"  # ÷


def _feed(rows):
    return SEP_F.join(f"{k}{SEP_KV}{v}" for k, v in rows)


def test_parse_stats_feed_basic():
    feed = _feed([
        ("SG", "Ball possession"), ("SH", "40%"), ("SI", "60%"),
        ("SG", "Corner kicks"), ("SH", "4"), ("SI", "2"),
        ("SG", "Yellow cards"), ("SH", "1"), ("SI", "3"),
    ])
    out = parse_stats_feed(feed)
    assert out["Ball possession"] == ("40%", "60%")
    assert out["Corner kicks"] == ("4", "2")
    assert out["Yellow cards"] == ("1", "3")


def test_parse_stats_feed_keeps_first_occurrence_per_period():
    # La misma métrica se repite por período; debe quedar la PRIMERA (full match).
    feed = _feed([
        ("SG", "Total shots"), ("SH", "12"), ("SI", "9"),   # full match
        ("SG", "Total shots"), ("SH", "5"), ("SI", "4"),    # 1er tiempo
    ])
    out = parse_stats_feed(feed)
    assert out["Total shots"] == ("12", "9")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_flashscore_transform.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'flashscore_transform'`.

- [ ] **Step 3: Write minimal implementation**

```python
# flashscore_transform.py
"""Funciones puras del pipeline Flashscore (Capa 2). NO importa seleniumbase ni
lee red al importar: corre en el entorno del proyecto y es testeable sin red."""

import re

SEP_F = "¬"   # ¬  separador de campo del feed packed
SEP_KV = "÷"  # ÷  separador clave-valor


def parse_stats_feed(text: str) -> dict:
    """Feed df_st packed -> {métrica: (local, visitante)}. Toma la 1ª ocurrencia
    de cada métrica (período full-match; Flashscore lista el total primero)."""
    out = {}
    metric = None
    home = None
    for chunk in text.split(SEP_F):
        if SEP_KV not in chunk:
            continue
        k, v = chunk.split(SEP_KV, 1)
        if k == "SG":
            metric, home = v, None
        elif k == "SH" and metric is not None:
            home = v
        elif k == "SI" and metric is not None and metric not in out:
            out[metric] = (home, v)
            metric = None
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_flashscore_transform.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add flashscore_transform.py tests/test_flashscore_transform.py
git commit -m "feat: flashscore_transform.parse_stats_feed (parse feed df_st packed)"
```

---

### Task 2: `flashscore_transform.parse_results` (función pura, TDD)

Del HTML de la página de resultados, extrae una entrada por partido: `{event_id, fecha (ISO), home, away}`.

**Files:**
- Modify: `flashscore_transform.py`
- Test: `tests/test_flashscore_transform.py`

- [ ] **Step 1: Write the failing test**

```python
# añadir a tests/test_flashscore_transform.py
from flashscore_transform import parse_results

# snippet real recortado de la fila Argentina-Francia (WC2022 results)
_ROW_HTML = '''
<div id="g_1_rBfk6fO7" class="event__match event__match--withRowLink event__match--twoLine" data-event-row="true">
<a href="https://www.flashscore.com/match/football/argentina-f9OppQjp/france-QkGeVG1n/?mid=rBfk6fO7" class="eventRowLink"></a>
<div class="event__time">18.12.2022<div class="event__stage"><div class="event__stage--block">Pen</div></div></div>
<div class="wcl-participant_bctDY event__homeParticipant" data-testid="wcl-matchRow-participant">
<img data-testid="wcl-participantLogo" data-size="xxs" aria-hidden="true" class="wcl-logo_UrSpU" alt="Argentina" loading="lazy" src="https://x.png">
</div>
<div class="wcl-participant_bctDY event__awayParticipant" data-testid="wcl-matchRow-participant">
<img data-testid="wcl-participantLogo" data-size="xxs" aria-hidden="true" class="wcl-logo_UrSpU" alt="France" loading="lazy" src="https://y.png">
</div></div>
'''


def test_parse_results_extracts_match():
    out = parse_results(_ROW_HTML)
    assert len(out) == 1
    m = out[0]
    assert m["event_id"] == "rBfk6fO7"
    assert m["fecha"] == "2022-12-18"
    assert m["home"] == "Argentina"
    assert m["away"] == "France"


def test_parse_results_ignores_blocks_without_teams():
    # un id sin participantes no debe romper ni emitir fila
    html = '<div id="g_1_ABCD1234" class="event__match"></div>'
    assert parse_results(html) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_flashscore_transform.py -k parse_results -v`
Expected: FAIL con `ImportError: cannot import name 'parse_results'`.

- [ ] **Step 3: Write minimal implementation**

```python
# añadir a flashscore_transform.py

_DATE_RE = re.compile(r'event__time">(\d{2})\.(\d{2})\.(\d{4})')
_ALT_RE = re.compile(r'data-testid="wcl-participantLogo"[^>]*?alt="([^"]+)"')


def parse_results(html: str) -> list:
    """Del HTML de la página de resultados, una entrada por partido:
    {event_id, fecha (ISO), home, away}."""
    out = []
    bloques = html.split('id="g_1_')[1:]
    for b in bloques:
        eid = b[:8]
        if not eid.isalnum():
            continue
        dm = _DATE_RE.search(b[:1200])
        alts = _ALT_RE.findall(b[:2500])
        if dm and len(alts) >= 2:
            d, mth, y = dm.groups()
            out.append({
                "event_id": eid,
                "fecha": f"{y}-{mth}-{d}",
                "home": alts[0],
                "away": alts[1],
            })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_flashscore_transform.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add flashscore_transform.py tests/test_flashscore_transform.py
git commit -m "feat: flashscore_transform.parse_results (event ids + meta del DOM)"
```

---

### Task 3: `flashscore_transform.tidy_match` (función pura, TDD)

Combina metadata + stats en 2 filas por-equipo (local y visitante) con columnas canónicas.

**Files:**
- Modify: `flashscore_transform.py`
- Test: `tests/test_flashscore_transform.py`

- [ ] **Step 1: Write the failing test**

```python
# añadir a tests/test_flashscore_transform.py
from flashscore_transform import tidy_match


def test_tidy_match_two_team_rows():
    meta = {"event_id": "rBfk6fO7", "fecha": "2022-12-18",
            "home": "Argentina", "away": "France"}
    stats = {
        "Corner kicks": ("4", "2"),
        "Yellow cards": ("1", "3"),
        "Total shots": ("12", "9"),
        "Shots on target": ("5", "4"),
        "Ball possession": ("54%", "46%"),
        "Expected goals (xG)": ("2.3", "1.1"),
    }
    rows = tidy_match(meta, stats, liga="INT-World Cup", season="2022")
    assert len(rows) == 2

    local = rows[0]
    assert local["equipo_flashscore"] == "Argentina"
    assert local["rival_flashscore"] == "France"
    assert local["es_local"] is True
    assert local["corners"] == 4
    assert local["crd_y"] == 1
    assert local["sot"] == 5
    assert local["possession"] == 54        # sin '%'
    assert local["xg"] == 2.3
    assert local["liga"] == "INT-World Cup"

    visit = rows[1]
    assert visit["equipo_flashscore"] == "France"
    assert visit["es_local"] is False
    assert visit["corners"] == 2
    assert visit["crd_y"] == 3


def test_tidy_match_missing_metric_is_none():
    meta = {"event_id": "x", "fecha": "2024-06-01", "home": "A", "away": "B"}
    rows = tidy_match(meta, {"Corner kicks": ("5", "1")}, liga="L", season="2024")
    assert rows[0]["corners"] == 5
    assert rows[0]["xg"] is None          # métrica ausente -> None
    assert rows[0]["sot"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_flashscore_transform.py -k tidy -v`
Expected: FAIL con `ImportError: cannot import name 'tidy_match'`.

- [ ] **Step 3: Write minimal implementation**

```python
# añadir a flashscore_transform.py

# nombre de métrica Flashscore -> columna canónica
METRIC_MAP = {
    "Corner kicks": "corners",
    "Yellow cards": "crd_y",
    "Red cards": "crd_r",
    "Total shots": "sh",
    "Shots on target": "sot",
    "Fouls": "fouls",
    "Offsides": "offsides",
    "Ball possession": "possession",
    "Expected goals (xG)": "xg",
}


def _num(raw):
    """'54%' -> 54, '2.3' -> 2.3, '4' -> 4, None/'' -> None."""
    if raw is None:
        return None
    s = str(raw).replace("%", "").strip()
    if s == "":
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def tidy_match(meta: dict, stats: dict, liga: str, season: str) -> list:
    """meta {event_id,fecha,home,away} + stats {métrica:(local,visit)} ->
    2 filas por-equipo con columnas canónicas."""
    rows = []
    perspectivas = [
        (meta["home"], meta["away"], True, 0),
        (meta["away"], meta["home"], False, 1),
    ]
    for equipo, rival, es_local, idx in perspectivas:
        row = {
            "event_id": meta["event_id"], "fecha": meta["fecha"],
            "liga": liga, "season": season,
            "equipo_flashscore": equipo, "rival_flashscore": rival,
            "es_local": es_local,
        }
        for fs_name, col in METRIC_MAP.items():
            par = stats.get(fs_name)
            row[col] = _num(par[idx]) if par else None
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_flashscore_transform.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add flashscore_transform.py tests/test_flashscore_transform.py
git commit -m "feat: flashscore_transform.tidy_match (2 filas por-equipo + mapeo de metricas)"
```

---

### Task 4: `download_flashscore_stats.py` (scrape híbrido, corre en `.venv-fbref`)

Sin test unitario (depende de red/browser). Se valida ejecutándolo y revisando el CSV.

**Files:**
- Create: `download_flashscore_stats.py`

- [ ] **Step 1: Escribir el script**

```python
# download_flashscore_stats.py
"""Scrapea stats por partido (córners+tarjetas+tiros+xG) de Flashscore y guarda
flashscore_stats.csv. CORRE EN EL VENV AISLADO .venv-fbref:
    .venv-fbref/Scripts/python download_flashscore_stats.py

Patrón híbrido: seleniumbase UC enumera event ids del DOM de la página de
resultados (1 load por edición); curl_cffi baja el feed df_st de cada partido."""

import sys
import time
import pandas as pd
from curl_cffi import requests as cr
from seleniumbase import SB

from flashscore_transform import parse_results, parse_stats_feed, tidy_match

FSIGN = "SW9D1eZo"
FEED = "https://2.flashscore.ninja/2/x/feed"
HDR = {"x-fsign": FSIGN, "Referer": "https://www.flashscore.com/"}
SALIDA = "flashscore_stats.csv"

# (liga, url de resultados, season)
TOURNAMENTS = [
    ("INT-World Cup", "https://www.flashscore.com/football/world/world-cup-2018/results/", "2018"),
    ("INT-World Cup", "https://www.flashscore.com/football/world/world-cup-2022/results/", "2022"),
    ("INT-European Championship", "https://www.flashscore.com/football/europe/euro-2020/results/", "2020"),
    ("INT-European Championship", "https://www.flashscore.com/football/europe/euro-2024/results/", "2024"),
    ("Liga 1 Peru", "https://www.flashscore.com/football/peru/liga-1-2024/results/", "2024"),
    ("Liga 1 Peru", "https://www.flashscore.com/football/peru/liga-1-2025/results/", "2025"),
]


def enumerar_partidos(sb, url):
    sb.uc_open_with_reconnect(url, reconnect_time=6)
    sb.sleep(8)
    try:
        sb.click("button#onetrust-accept-btn-handler")
        sb.sleep(2)
    except Exception:
        pass
    sb.sleep(3)
    return parse_results(sb.get_page_source())


def bajar_stats(event_id):
    r = cr.get(f"{FEED}/df_st_1_{event_id}", headers=HDR, impersonate="chrome", timeout=20)
    return parse_stats_feed(r.content.decode("utf-8", "replace"))


def descargar():
    filas = []
    with SB(uc=True, headless=True) as sb:
        for liga, url, season in TOURNAMENTS:
            try:
                partidos = enumerar_partidos(sb, url)
            except Exception as e:
                print(f"  WARN {liga} {season}: no se pudo cargar ({e})")
                continue
            print(f"  {liga} {season}: {len(partidos)} partidos")
            for m in partidos:
                try:
                    stats = bajar_stats(m["event_id"])
                except Exception:
                    stats = {}
                if stats:
                    filas.extend(tidy_match(m, stats, liga, season))
                time.sleep(0.3)   # cortesía con el feed
    out = pd.DataFrame(filas).drop_duplicates(subset=["event_id", "equipo_flashscore"])
    out.to_csv(SALIDA, index=False, encoding="utf-8")
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Scrapeando Flashscore (browser por edición + feed por partido)...")
    out = descargar()
    print(f"Guardado {len(out)} filas (partido-equipo) en {SALIDA}")
    print(f"Equipos distintos: {out['equipo_flashscore'].nunique()}")
    print("Columnas:", list(out.columns))
```

- [ ] **Step 2: Ejecutar el scrape en el venv aislado**

Run:
```bash
.venv-fbref/Scripts/python download_flashscore_stats.py
```
Expected: imprime nº de partidos por torneo y crea `flashscore_stats.csv`. (Si alguna URL de torneo no existe en Flashscore, ese torneo loguea WARN y se saltea; ajustar la URL en `TOURNAMENTS` mirando el sitio.)

- [ ] **Step 3: Sanity-check del CSV**

Run:
```bash
python -c "import pandas as pd; d=pd.read_csv('flashscore_stats.csv'); print(d.shape); print(d['liga'].value_counts().to_dict()); print('con corners:', d['corners'].notna().mean()); print(d[['equipo_flashscore','rival_flashscore','fecha','corners','crd_y','sot']].head())"
```
Expected: cientos de filas; `corners` poblado en la mayoría.

- [ ] **Step 4: Commit (solo el script; el CSV está gitignored)**

Añadir `flashscore_stats.csv` a `.gitignore` primero:
```bash
printf 'flashscore_stats.csv\n' >> .gitignore
git add download_flashscore_stats.py .gitignore
git commit -m "feat: download_flashscore_stats.py (scrape hibrido corners+tarjetas+tiros+xG)"
```

---

### Task 5: `load_flashscore_stats_to_supabase.py` — DDL de la tabla nueva

**Files:**
- Create: `load_flashscore_stats_to_supabase.py`

- [ ] **Step 1: Escribir el esqueleto con DDL**

```python
# load_flashscore_stats_to_supabase.py
"""Carga flashscore_stats.csv a Supabase: resuelve equipo_id, crea la tabla
estadisticas_flashscore e inserta filas crudas por partido-equipo. Imprime un
reporte de cobertura (gate antes de modelar). CORRE EN EL ENTORNO DEL PROYECTO:
    python load_flashscore_stats_to_supabase.py
"""

import os
import sys

import pandas as pd
import requests
from dotenv import load_dotenv
from supabase import create_client

from fbref_transform import resolver_equipo_id

CSV = "flashscore_stats.csv"
PROJECT_REF = "aahaivisyghpgqarqpak"

DDL = """
CREATE TABLE IF NOT EXISTS estadisticas_flashscore (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id           TEXT NOT NULL,
    fecha              DATE,
    liga               TEXT,
    season             TEXT,
    equipo_id          UUID REFERENCES equipos(id),
    equipo_flashscore  TEXT NOT NULL,
    rival_id           UUID REFERENCES equipos(id),
    rival_flashscore   TEXT NOT NULL,
    es_local           BOOLEAN,
    corners            INTEGER,
    crd_y              INTEGER,
    crd_r              INTEGER,
    sh                 INTEGER,
    sot                INTEGER,
    fouls              INTEGER,
    offsides           INTEGER,
    possession         INTEGER,
    xg                 REAL,
    UNIQUE (event_id, equipo_flashscore)
);
ALTER TABLE estadisticas_flashscore DISABLE ROW LEVEL SECURITY;
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
    print("[1/3] DDL: tabla estadisticas_flashscore...")
    run_ddl(DDL, mgmt_token)
    print("  tabla lista")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar la creación de la tabla**

Run: `python load_flashscore_stats_to_supabase.py`
Expected: imprime "tabla lista" sin error.

- [ ] **Step 3: Verificar que la tabla existe**

Run:
```bash
python -c "import os; from dotenv import load_dotenv; from supabase import create_client; load_dotenv(); sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_KEY']); print(sb.table('estadisticas_flashscore').select('id', count='exact').execute().count)"
```
Expected: `0` (tabla vacía existe).

- [ ] **Step 4: Commit**

```bash
git add load_flashscore_stats_to_supabase.py
git commit -m "feat: load script crea tabla estadisticas_flashscore (DDL)"
```

---

### Task 6: `load_flashscore_stats_to_supabase.py` — resolución, upsert y reporte de cobertura

**Files:**
- Modify: `load_flashscore_stats_to_supabase.py`

- [ ] **Step 1: Reemplazar el cuerpo de `main()`**

```python
def _int(v):
    return None if pd.isna(v) else int(v)


def _real(v):
    return None if pd.isna(v) else float(v)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    mgmt_token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    print("[1/3] DDL: tabla estadisticas_flashscore...")
    run_ddl(DDL, mgmt_token)

    print("[2/3] Resolviendo equipos y construyendo filas...")
    df = pd.read_csv(CSV)
    teams = sb.table("equipos").select("id, nombre_oficial, aliases").execute().data

    cache = {}
    def resolver(n):
        if n not in cache:
            cache[n] = resolver_equipo_id(str(n), teams)
        return cache[n]

    filas = []
    for _, r in df.iterrows():
        eid, _, _ = resolver(r["equipo_flashscore"])
        rid, _, _ = resolver(r["rival_flashscore"])
        filas.append({
            "event_id": r["event_id"], "fecha": r["fecha"],
            "liga": r["liga"], "season": str(r["season"]),
            "equipo_id": eid, "equipo_flashscore": r["equipo_flashscore"],
            "rival_id": rid, "rival_flashscore": r["rival_flashscore"],
            "es_local": bool(r["es_local"]),
            "corners": _int(r.get("corners")), "crd_y": _int(r.get("crd_y")),
            "crd_r": _int(r.get("crd_r")), "sh": _int(r.get("sh")),
            "sot": _int(r.get("sot")), "fouls": _int(r.get("fouls")),
            "offsides": _int(r.get("offsides")), "possession": _int(r.get("possession")),
            "xg": _real(r.get("xg")),
        })

    for i in range(0, len(filas), 500):
        sb.table("estadisticas_flashscore").upsert(
            filas[i:i+500], on_conflict="event_id,equipo_flashscore"
        ).execute()

    # ── [3/3] Reporte de cobertura ──
    print("[3/3] Reporte de cobertura:")
    nombres = sorted(set(df["equipo_flashscore"]) | set(df["rival_flashscore"]))
    huerfanos = [n for n in nombres if resolver(n)[0] is None]
    vc = df["equipo_flashscore"].value_counts()
    print(f"  filas (partido-equipo): {len(df)}")
    print(f"  por liga              : {df['liga'].value_counts().to_dict()}")
    print(f"  equipos distintos     : {df['equipo_flashscore'].nunique()}")
    print(f"  partidos/equipo       : min={int(vc.min())} med={int(vc.median())} max={int(vc.max())}")
    print(f"  nombres resueltos     : {len(nombres)-len(huerfanos)}/{len(nombres)}"
          f" ({100*(len(nombres)-len(huerfanos))/len(nombres):.0f}%)")
    print(f"  huerfanos ({len(huerfanos)}): {huerfanos[:25]}")
    for col in ["corners", "crd_y", "sh", "sot", "xg"]:
        print(f"  filas con {col:9}: {df[col].notna().mean()*100:.0f}%")
    print("\n✅ Datos cargados. Revisar el reporte para decidir el Sub-proyecto B.")
```

- [ ] **Step 2: Ejecutar la carga completa**

Run: `python load_flashscore_stats_to_supabase.py`
Expected: imprime el reporte de cobertura con números reales; sin errores.

- [ ] **Step 3: Verificar filas insertadas e idempotencia**

Run:
```bash
python -c "import os; from dotenv import load_dotenv; from supabase import create_client; load_dotenv(); sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_KEY']); print('filas:', sb.table('estadisticas_flashscore').select('id', count='exact').execute().count); print('con corners:', sb.table('estadisticas_flashscore').select('id', count='exact').not_.is_('corners','null').execute().count)"
```
Expected: nº de filas > 0; re-correr el load no duplica.

- [ ] **Step 4: Commit**

```bash
git add load_flashscore_stats_to_supabase.py
git commit -m "feat: load resuelve equipos, upsert idempotente y reporte de cobertura flashscore"
```

---

### Task 7: Verificación end-to-end y suite

**Files:** ninguno (verificación).

- [ ] **Step 1: Confirmar que la suite del proyecto sigue verde**

Run: `python -m pytest -q`
Expected: `172 passed` (166 previos + 6 nuevos de `tests/test_flashscore_transform.py`). Sin regresiones.

- [ ] **Step 2: Releer el reporte de cobertura del Task 6**

Decisión-gate: ¿hay densidad y % de resolución suficientes para modelar córners/tarjetas/tiros (internacional y Liga 1) con skill? Documentar los números en una nota para arrancar el Sub-proyecto B. Atención especial a la cobertura de **Liga 1** (clubes peruanos pueden requerir alta en `equipos`) y de **córners** (la familia que justifica todo este pipeline).

- [ ] **Step 3: Commit (si se añadió alguna nota/doc)**

```bash
git add -A
git commit -m "docs: reporte de cobertura Capa 2 Flashscore"
```

---

## Notas de implementación

- **Entornos:** Task 4 corre en `.venv-fbref/Scripts/python` (seleniumbase + curl_cffi ya instalados). Tasks 1-3, 5-7 corren en el `python` del entorno del proyecto.
- **`flashscore_transform.py` no debe importar seleniumbase ni curl_cffi** a nivel de módulo (solo `re`); el download los importa. Eso lo hace testeable sin red.
- **Reusa `resolver_equipo_id` de `fbref_transform`** (import directo): no reimplementar el matcher.
- **`x-fsign`:** constante `FSIGN="SW9D1eZo"`. Si Flashscore la rota y el feed empieza a dar 403, recapturarla de un request del sitio.
- **Período de stats:** `parse_stats_feed` toma la 1ª ocurrencia de cada métrica = full match.
- **Idempotencia:** upsert por `(event_id, equipo_flashscore)`; re-correr no duplica.
- **Este pipeline NO crea modelo.** Entregable: `estadisticas_flashscore` poblada + reporte de cobertura.
- **URLs de torneo:** verificar en flashscore.com que cada URL de `TOURNAMENTS` existe (el slug de edición puede variar, ej. `world-cup-2018` vs `world-cup-2018-russia`); ajustar si un torneo loguea WARN.
```
