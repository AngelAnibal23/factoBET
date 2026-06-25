# Tiros al arco POR-JUGADOR (SoT) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir la pata "tiros al arco por jugador" (`metric="sot"`, familia `player`) de mercado `faltante` a mercado servible, para selecciones internacionales / Mundial.

**Architecture:** Top-down (arquitectura A del spec): `λ_jugador_sot = counts_model.lambdas("sot")[lado] × cuota_sot`. Reutiliza `counts_model` (ya modela SoT por-equipo del Mundial) como techo con ajuste de enfrentamiento, y la mecánica de cuota+shrinkage de `player_model`. Datos de API-Football `/fixtures/players` (`shots.on`), pipeline de backfill resumable (~100 req/día). Segundo `PlayerModel` independiente (IDs de API-Football), publicado como `player_sot_v0.1`, separado del `player_v0.1` de goal/assist (IDs de Flashscore).

**Tech Stack:** Python 3.12, `requests` (API-Football), `supabase-py`, `scipy.stats` (Poisson), `rapidfuzz` (resolver de nombres), `pytest`. DDL vía Supabase Management API (`curl_cffi`). Estilo del proyecto: funciones puras testeables, sin red al importar.

**Spec:** `docs/superpowers/specs/2026-06-25-tiros-al-arco-por-jugador-design.md`

---

## File Structure

**Nuevos:**
- `sot_ddl.py` — crea las dos tablas vía Management API (idempotente).
- `sot_transform.py` — JSON de `/fixtures/players` → filas (puro, testeable).
- `download_sot_jugador.py` — backfill resumable (descubrimiento + hidratación).
- `fit_player_sot.py` — registros + gate de la métrica `sot`.
- `load_player_sot_to_supabase.py` — publica `player_sot_v0.1` si el gate pasa.
- `tests/test_sot_transform.py`, `tests/test_fit_player_sot.py`.

**Modificados:**
- `player_model.py` — helper `_shrink_share`, `estimar_cuotas_sot`, rama `sot` en `PlayerModel.prob`, `METRICAS_PLAYER`.
- `betbuilder.py` — `player_leg_prob` toma λ de `counts_model` para `sot`; `analyze_bet_builder` recibe `player_sot_model` y enruta; fallback a `faltante`.
- `analyzer.py` — `_load_player_sot_model` + cableado en `_analyze_bet_builder_route`.
- `ocr.py` — des-exotizar: `faltante:false` para `sot`.
- `tests/test_player_model.py`, `tests/test_betbuilder.py` — extender.

---

## Task 1: DDL de las tablas (eventos_sot_jugador + sot_backfill_progreso)

**Files:**
- Create: `sot_ddl.py`

- [ ] **Step 1: Escribir el script DDL (idempotente, vía Management API)**

```python
# sot_ddl.py
"""Crea las tablas del pipeline de SoT por-jugador vía Supabase Management API.

Idempotente (CREATE TABLE IF NOT EXISTS). Corre con el python del sistema.

    python sot_ddl.py
"""
import os
import sys

from curl_cffi import requests as cr
from dotenv import load_dotenv

PROJECT_REF = "aahaivisyghpgqarqpak"
URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"

DDL = """
create table if not exists eventos_sot_jugador (
  event_id      bigint not null,
  player_id     text   not null,
  player_nombre text,
  equipo_id     uuid,
  sot           int    not null default 0,
  fue_titular   boolean,
  minutos       int,
  liga_api_id   int,
  fecha         timestamptz,
  primary key (event_id, player_id)
);
create table if not exists sot_backfill_progreso (
  event_id      bigint primary key,
  liga_api_id   int,
  temporada     int,
  estado        text not null default 'pendiente',
  fecha_proceso timestamptz
);
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    token = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
    r = cr.post(URL, headers={"Authorization": f"Bearer {token}"},
                json={"query": DDL}, impersonate="chrome", timeout=30)
    print(f"status {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    print("✅ tablas eventos_sot_jugador + sot_backfill_progreso listas.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar y confirmar**

Run: `python sot_ddl.py`
Expected: `status 201` (o 200) y el mensaje `✅ tablas ... listas.`

- [ ] **Step 3: Commit**

```bash
git add sot_ddl.py
git commit -m "feat(sot): DDL de eventos_sot_jugador + sot_backfill_progreso"
```

---

## Task 2: Transform puro de /fixtures/players → filas

**Files:**
- Create: `sot_transform.py`
- Test: `tests/test_sot_transform.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_sot_transform.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sot_transform import parse_fixtures_players

# Forma real (abreviada) de /fixtures/players: "response" es una lista con una
# entrada por equipo; cada equipo trae team{id,name} y players[] con statistics[0].
RESPONSE = [
    {"team": {"id": 10, "name": "Portugal"},
     "players": [
        {"player": {"id": 100, "name": "Cristiano Ronaldo"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 5, "on": 3}}]},
        {"player": {"id": 101, "name": "Bruno Fernandes"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 2, "on": 1}}]},
        {"player": {"id": 102, "name": "Suplente"},
         "statistics": [{"games": {"minutes": 12, "substitute": True},
                         "shots": {"total": 0, "on": None}}]},
     ]},
    {"team": {"id": 20, "name": "Spain"},
     "players": [
        {"player": {"id": 200, "name": "Alvaro Morata"},
         "statistics": [{"games": {"minutes": 90, "substitute": False},
                         "shots": {"total": 4, "on": 2}}]},
     ]},
]


def test_parse_estructura_y_sot():
    filas = parse_fixtures_players(RESPONSE, event_id=999)
    by_pid = {f["player_id"]: f for f in filas}
    assert len(filas) == 4
    # sot leído de shots.on; null -> 0
    assert by_pid["100"]["sot"] == 3
    assert by_pid["102"]["sot"] == 0
    # substitute:false -> fue_titular True ; substitute:true -> False
    assert by_pid["100"]["fue_titular"] is True
    assert by_pid["102"]["fue_titular"] is False
    # nombre de equipo crudo (la resolución a equipo_id se hace en el loader)
    assert by_pid["100"]["equipo_nombre"] == "Portugal"
    assert by_pid["200"]["equipo_nombre"] == "Spain"
    # event_id e ids como str (espacio de IDs de API-Football)
    assert by_pid["100"]["event_id"] == 999
    assert by_pid["100"]["player_nombre"] == "Cristiano Ronaldo"
    assert by_pid["100"]["minutos"] == 90


def test_jugador_sin_statistics_se_omite():
    resp = [{"team": {"id": 10, "name": "Portugal"},
             "players": [{"player": {"id": 1, "name": "X"}, "statistics": []}]}]
    assert parse_fixtures_players(resp, event_id=1) == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_sot_transform.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'sot_transform'`

- [ ] **Step 3: Implementar el transform**

```python
# sot_transform.py
"""Transforma la respuesta de API-Football /fixtures/players en filas por jugador.

Puro (no toca red ni DB). La resolución de equipo_nombre -> equipo_id se hace en el
loader (download_sot_jugador.py) contra la tabla equipos, no aquí.
"""


def parse_fixtures_players(response: list, event_id: int) -> list[dict]:
    """response: lista 'response' de /fixtures/players (una entrada por equipo).

    Devuelve una fila por jugador con statistics no vacío:
      {event_id, player_id(str), player_nombre, equipo_nombre, sot, fue_titular, minutos}.
    sot = statistics[0].shots.on (null -> 0). fue_titular = not games.substitute.
    """
    filas = []
    for equipo in response:
        nombre_eq = equipo["team"]["name"]
        for p in equipo.get("players", []):
            stats = p.get("statistics") or []
            if not stats:
                continue
            st = stats[0]
            shots = st.get("shots") or {}
            games = st.get("games") or {}
            filas.append({
                "event_id": event_id,
                "player_id": str(p["player"]["id"]),
                "player_nombre": p["player"]["name"],
                "equipo_nombre": nombre_eq,
                "sot": shots.get("on") or 0,
                "fue_titular": not bool(games.get("substitute")),
                "minutos": games.get("minutes"),
            })
    return filas
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_sot_transform.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add sot_transform.py tests/test_sot_transform.py
git commit -m "feat(sot): transform puro de /fixtures/players a filas"
```

---

## Task 3: player_model — helper de shrinkage + estimar_cuotas_sot

**Files:**
- Modify: `player_model.py`
- Test: `tests/test_player_model.py`

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `tests/test_player_model.py`:

```python
from player_model import estimar_cuotas_sot

# 2 titulares de "POR": Ronaldo dispara mucho al arco, Suplente casi nada.
REGS_SOT = [
    {"player_id": "p1", "nombre": "Ronaldo", "equipo": "Portugal",
     "sot_jugador": 3, "sot_equipo": 5, "n_titulares": 11},
    {"player_id": "p1", "nombre": "Ronaldo", "equipo": "Portugal",
     "sot_jugador": 2, "sot_equipo": 4, "n_titulares": 11},
    {"player_id": "p2", "nombre": "Defensa", "equipo": "Portugal",
     "sot_jugador": 0, "sot_equipo": 5, "n_titulares": 11},
]


def test_estimar_cuotas_sot_estructura_y_rango():
    out = estimar_cuotas_sot(REGS_SOT, k=2.0)
    assert set(out) == {"p1", "p2"}
    assert out["p1"]["nombre"] == "Ronaldo"
    assert out["p1"]["equipo"] == "Portugal"
    # el que dispara al arco tiene cuota_sot mucho mayor
    assert out["p1"]["cuota_sot"] > out["p2"]["cuota_sot"]
    for v in out.values():
        assert 0.0 < v["cuota_sot"] < 1.0
        assert set(v) == {"nombre", "equipo", "cuota_sot"}   # sin cuota_gol/asist


def test_estimar_cuotas_sot_min_partidos():
    # p1 tiene 2 partidos, p2 tiene 1 -> min_partidos=2 deja solo p1
    out = estimar_cuotas_sot(REGS_SOT, k=2.0, min_partidos=2)
    assert set(out) == {"p1"}


def test_estimar_cuotas_sot_excluye_sot_equipo_cero():
    # partido con sot_equipo==0: share indefinido, no debe reventar; cae al prior con k>0
    regs = [{"player_id": "pz", "nombre": "Z", "equipo": "W",
             "sot_jugador": 0, "sot_equipo": 0, "n_titulares": 11}]
    out = estimar_cuotas_sot(regs, k=2.0)
    prior = 1.0 / 11
    assert abs(out["pz"]["cuota_sot"] - prior) < 1e-9
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_player_model.py -k sot -v`
Expected: FAIL con `ImportError: cannot import name 'estimar_cuotas_sot'`

- [ ] **Step 3: Implementar en player_model.py**

En `player_model.py`, extraer el helper de shrinkage a nivel de módulo (justo antes de `estimar_cuotas`) y reusarlo dentro de `estimar_cuotas`. Reemplazar el `_cuota` local por el helper:

```python
def _shrink_share(shares: list[float], prior: float, k: float) -> float:
    """Media bayesiana de `shares` hacia `prior` con fuerza `k`. Si no hay shares
    (denom==0 con k==0) cae al prior."""
    denom = len(shares) + k
    return (sum(shares) + k * prior) / denom if denom > 0 else prior
```

Dentro de `estimar_cuotas`, reemplazar el bloque:

```python
        def _cuota(shares):
            denom = len(shares) + k
            return (sum(shares) + k * prior) / denom if denom > 0 else prior

        cuota_gol = _cuota(shares_gol)
        cuota_ast = _cuota(shares_ast)
```

por:

```python
        cuota_gol = _shrink_share(shares_gol, prior, k)
        cuota_ast = _shrink_share(shares_ast, prior, k)
```

Y añadir la función nueva después de `estimar_cuotas`:

```python
def estimar_cuotas_sot(registros: list[dict], k: float = 5.0,
                       min_partidos: int = 1) -> dict:
    """Estima cuota_sot por jugador con shrinkage hacia 1/n_titulares.

    registros: partidos-como-titular {player_id, nombre, equipo, sot_jugador,
      sot_equipo, n_titulares}. cuota_sot = fracción de los SoT del equipo que hizo
      el jugador. Partidos con sot_equipo==0 se excluyen del promedio (share
      indefinido); su prior 1/n_titulares sí informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        if len(regs) < min_partidos:
            continue
        prior = sum(1.0 / max(r["n_titulares"], 1) for r in regs) / len(regs)
        shares = [r["sot_jugador"] / r["sot_equipo"]
                  for r in regs if r["sot_equipo"] > 0]
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_sot": _shrink_share(shares, prior, k),
        }
    return out
```

- [ ] **Step 4: Correr los tests (nuevos + viejos) para verificar verde**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: PASS (todos — los nuevos de sot y los viejos de goal/assist, que confirman que el refactor de `_shrink_share` no rompió nada)

- [ ] **Step 5: Commit**

```bash
git add player_model.py tests/test_player_model.py
git commit -m "feat(sot): estimar_cuotas_sot + helper _shrink_share compartido"
```

---

## Task 4: player_model — rama `sot` en PlayerModel.prob

**Files:**
- Modify: `player_model.py`
- Test: `tests/test_player_model.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/test_player_model.py`:

```python
def test_prob_sot_top_down():
    from player_model import PlayerModel
    import math
    params = {"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Ronaldo", "equipo": "Portugal", "cuota_sot": 0.35},
    }}
    m = PlayerModel.from_params(params)
    assert m.tiene("p1", "sot") is True
    assert m.tiene("p1", "goal") is False        # este modelo solo publica sot
    # lambda_jugador = lambda_sot_equipo(4.0) * cuota_sot(0.35) = 1.4
    p = m.prob("p1", "sot", lambda_equipo=4.0, umbral=1)
    assert abs(p - (1 - math.exp(-1.4))) < 1e-9
    # umbral 2+: P(X>=2) = 1 - cdf(1)
    from scipy.stats import poisson
    p2 = m.prob("p1", "sot", lambda_equipo=4.0, umbral=2)
    assert abs(p2 - (1 - poisson.cdf(1, 1.4))) < 1e-9
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_player_model.py::test_prob_sot_top_down -v`
Expected: FAIL con `ValueError: métrica player inválida: 'sot'`

- [ ] **Step 3: Implementar la rama sot**

En `player_model.py`, cambiar la constante:

```python
METRICAS_PLAYER = ("goal", "assist", "goal_or_assist", "sot")
```

En `PlayerModel.prob`, añadir la rama `sot` antes del `else` que lanza el error:

```python
        elif metric == "sot":
            lam = lambda_equipo * j["cuota_sot"]
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add player_model.py tests/test_player_model.py
git commit -m "feat(sot): rama sot en PlayerModel.prob (top-down)"
```

---

## Task 5: fit_player_sot — registros + gate

**Files:**
- Create: `fit_player_sot.py`
- Test: `tests/test_fit_player_sot.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_fit_player_sot.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fit_player_sot import registros_desde_filas, _gate

# Dos partidos del equipo "POR" con 2 jugadores cada uno.
FILAS = [
    # partido A
    {"event_id": 1, "equipo": "POR", "player_id": "p1", "player_nombre": "Sniper",
     "sot": 4, "fue_titular": True},
    {"event_id": 1, "equipo": "POR", "player_id": "p2", "player_nombre": "Back",
     "sot": 0, "fue_titular": True},
    # partido B
    {"event_id": 2, "equipo": "POR", "player_id": "p1", "player_nombre": "Sniper",
     "sot": 3, "fue_titular": True},
    {"event_id": 2, "equipo": "POR", "player_id": "p2", "player_nombre": "Back",
     "sot": 1, "fue_titular": True},
]


def test_registros_arma_sot_equipo_y_n_titulares():
    regs = registros_desde_filas(FILAS)
    by = {(r["event_id"], r["player_id"]): r for r in regs}
    # sot_equipo del partido 1 = 4+0 = 4 ; n_titulares = 2
    assert by[(1, "p1")]["sot_equipo"] == 4
    assert by[(1, "p1")]["sot_jugador"] == 4
    assert by[(1, "p1")]["n_titulares"] == 2
    assert by[(2, "p2")]["sot_equipo"] == 4   # 3+1
    # solo titulares producen registro
    assert len(regs) == 4


def test_gate_premia_al_que_dispara():
    # Construir train/test donde p1 domina los SoT: el modelo (cuota) debe
    # batir al baseline igualitario (1/n_titulares) en Brier.
    regs = registros_desde_filas(FILAS * 5)   # 10 partidos por jugador (elegibles)
    bm, bb = _gate(regs, regs, min_partidos=2)
    assert bm < bb   # modelo mejor (Brier menor) que baseline
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_fit_player_sot.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'fit_player_sot'`

- [ ] **Step 3: Implementar fit_player_sot.py**

```python
# fit_player_sot.py
"""Ajuste offline del modelo SoT por-jugador + gate de la métrica `sot`.

Lee eventos_sot_jugador (vía Supabase), arma registros por (jugador, partido como
titular), estima cuota_sot y valida contra un baseline igualitario (1/n_titulares)
en un holdout temporal por Brier. El lambda_sot del equipo en el gate es la TASA
REAL OBSERVADA del dataset (no un proxy), para no repetir la miscalibración de
goal/assist. NO escribe a Supabase (eso lo hace load_player_sot_to_supabase.py).

    python fit_player_sot.py
"""
import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

from player_model import estimar_cuotas_sot, PlayerModel

GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
TEST_FRAC = 0.30
MIN_PARTIDOS = 10     # historial mínimo (titular) para publicar/evaluar un jugador


def registros_desde_filas(filas: list[dict]) -> list[dict]:
    """filas: [{event_id, equipo, player_id, player_nombre, sot, fue_titular}].

    Devuelve un registro POR titular: {event_id, player_id, nombre, equipo,
    sot_jugador, sot_equipo, n_titulares}. sot_equipo = suma de SoT de TODO el
    equipo en ese partido (titulares + suplentes)."""
    sot_eq = defaultdict(int)            # (event_id, equipo) -> sot del equipo
    titulares = defaultdict(dict)        # (event_id, equipo) -> {pid: nombre}
    for f in filas:
        sot_eq[(f["event_id"], f["equipo"])] += f["sot"]
        if f["fue_titular"]:
            titulares[(f["event_id"], f["equipo"])][f["player_id"]] = f["player_nombre"]
    sot_jug = {(f["event_id"], f["player_id"]): f["sot"] for f in filas}

    regs = []
    for (eid, equipo), starters in titulares.items():
        n_tit = len(starters)
        for pid, nombre in starters.items():
            regs.append({
                "event_id": eid, "player_id": pid, "nombre": nombre, "equipo": equipo,
                "sot_jugador": sot_jug.get((eid, pid), 0),
                "sot_equipo": sot_eq[(eid, equipo)], "n_titulares": n_tit,
            })
    return regs


def _brier(probs, occ):
    return float(np.mean((np.asarray(probs) - np.asarray(occ, float)) ** 2))


def _lambda_sot_real(registros: list[dict]) -> float:
    """Tasa real observada de SoT por equipo-partido (media de sot_equipo sobre
    equipos-partido únicos). Es el techo del baseline y del modelo en el gate."""
    por_eq = {(r["event_id"], r["equipo"]): r["sot_equipo"] for r in registros}
    vals = list(por_eq.values())
    return float(np.mean(vals)) if vals else 0.0


def _gate(train, test, min_partidos=MIN_PARTIDOS):
    """Brier del modelo (cuota_sot) vs baseline (1/n_titulares) en el holdout.
    Solo evalúa jugadores elegibles (>= min_partidos en train)."""
    cuotas = estimar_cuotas_sot(train, k=K_SHRINK, min_partidos=min_partidos)
    m = PlayerModel.from_params({"metricas": ["sot"], "jugadores": cuotas})
    lam_sot = _lambda_sot_real(train)
    probs_m, probs_b, occ = [], [], []
    for r in test:
        pid = r["player_id"]
        if not m.tiene(pid, "sot"):
            continue
        probs_m.append(m.prob(pid, "sot", lam_sot, umbral=1))
        probs_b.append(1 - np.exp(-lam_sot / max(r["n_titulares"], 1)))
        occ.append(1.0 if r["sot_jugador"] >= 1 else 0.0)
    return _brier(probs_m, occ), _brier(probs_b, occ)


def _cargar(sb):
    """Filas de eventos_sot_jugador con equipo canónico + fecha. Pagina de a 1000."""
    eq = {e["id"]: e["nombre_oficial"]
          for e in sb.table("equipos").select("id,nombre_oficial").execute().data}
    filas, desde, paso = [], 0, 1000
    while True:
        chunk = (sb.table("eventos_sot_jugador")
                 .select("event_id,equipo_id,player_id,player_nombre,sot,fue_titular,fecha")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            equipo = eq.get(r["equipo_id"])
            if equipo is None:
                continue
            filas.append({"event_id": r["event_id"], "equipo": equipo,
                          "player_id": r["player_id"], "player_nombre": r["player_nombre"],
                          "sot": r["sot"] or 0, "fue_titular": r["fue_titular"],
                          "fecha": r["fecha"]})
        if len(chunk) < paso:
            break
        desde += paso
    return filas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    filas = _cargar(sb)
    fecha_ev = {f["event_id"]: f["fecha"] for f in filas}
    regs = registros_desde_filas(filas)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], "") or "")
    corte = int(len(regs) * (1 - TEST_FRAC))
    train, test = regs[:corte], regs[corte:]

    print("=" * 60, "\nFIT MODELO SoT POR-JUGADOR — gate (liga INT)\n", "=" * 60)
    bm, bb = _gate(train, test)
    mejora = (bb - bm) / bb if bb > 0 else 0.0
    ok = bm < bb and mejora >= GATE_MIN_MEJORA
    print(f"  sot: Brier modelo={bm:.4f} base={bb:.4f} "
          f"mejora={mejora*100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
    print(f"  (lambda_sot real train = {_lambda_sot_real(train):.2f}/equipo)")

    cuotas_prod = estimar_cuotas_sot(regs, k=K_SHRINK, min_partidos=MIN_PARTIDOS)
    return {"metricas": ["sot"] if ok else [], "jugadores": cuotas_prod}


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_fit_player_sot.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add fit_player_sot.py tests/test_fit_player_sot.py
git commit -m "feat(sot): fit_player_sot con gate (lambda_sot real observado)"
```

---

## Task 6: load_player_sot_to_supabase

**Files:**
- Create: `load_player_sot_to_supabase.py`

- [ ] **Step 1: Escribir el loader (clónico de load_player_model_to_supabase)**

```python
# load_player_sot_to_supabase.py
"""Carga los params del modelo SoT por-jugador GATEADOS a parametros_modelo
(player_sot_v0.1). Reusa fit_player_sot.main() (corre el gate). Idempotente.

    python load_player_sot_to_supabase.py
"""
import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_player_sot import main as fit_main

VERSION = "player_sot_v0.1"
LIGA_NOMBRE = "Internacional"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    params = fit_main()
    if not params["metricas"]:
        print("Nada que cargar (sot no pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", LIGA_NOMBRE).execute().data
    if not liga:
        print(f"⚠ liga '{LIGA_NOMBRE}' no existe en `ligas`.")
        sys.exit(1)
    liga_id = liga[0]["id"]

    (sb.table("parametros_modelo").delete()
     .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
    sb.table("parametros_modelo").insert({
        "liga_id": liga_id, "version_modelo": VERSION,
        "attack_params": {}, "defense_params": {}, "is_production": True,
        "notas": json.dumps(params),
    }).execute()
    print(f"✅ player_sot_v0.1 cargado: {len(params['jugadores'])} jugadores.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar que importa sin error (no corre el gate sin datos aún)**

Run: `python -c "import load_player_sot_to_supabase; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add load_player_sot_to_supabase.py
git commit -m "feat(sot): loader player_sot_v0.1 a parametros_modelo"
```

---

## Task 7: betbuilder — player_leg_prob enruta λ_sot de counts_model

**Files:**
- Modify: `betbuilder.py:35-57`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_betbuilder.py` (imports al estilo del archivo; ver cabecera existente):

```python
def test_player_leg_prob_sot_usa_counts_lambda():
    import math
    from types import SimpleNamespace
    from player_model import PlayerModel
    from counts_model import CountsModel
    from betbuilder import player_leg_prob

    player_sot = PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40},
    }})
    # counts con sot: base_home=4, sin multiplicadores -> lambda_sot local = 4
    counts = CountsModel.from_params({"sot": {
        "base_home": 4.0, "base_away": 3.0, "factor_neutral": 1.0, "disp": 1.0,
        "atk": {}, "def": {},
    }})
    sel = SimpleNamespace(metric="sot", faltante=False, player="Ronaldo",
                          scope="total", seleccion="yes", linea=0.5, umbral=1)
    # Ronaldo (Portugal) es local -> lambda_sot = 4.0 ; lam_jugador = 4.0*0.40 = 1.6
    p = player_leg_prob(player_sot, sel, lh=1.2, la=0.9,
                        home="Portugal", away="Spain",
                        counts_model=counts, c_home="ID_POR", c_away="ID_SPA",
                        neutral=False)
    assert abs(p - (1 - math.exp(-1.6))) < 1e-9


def test_player_leg_prob_sot_sin_counts_devuelve_none():
    from types import SimpleNamespace
    from player_model import PlayerModel
    from betbuilder import player_leg_prob
    player_sot = PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40},
    }})
    sel = SimpleNamespace(metric="sot", faltante=False, player="Ronaldo",
                          scope="total", seleccion="yes", linea=0.5, umbral=1)
    assert player_leg_prob(player_sot, sel, 1.2, 0.9, "Portugal", "Spain",
                           counts_model=None, c_home="A", c_away="B") is None
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_betbuilder.py -k sot -v`
Expected: FAIL (TypeError: `player_leg_prob()` no acepta `counts_model`)

- [ ] **Step 3: Modificar player_leg_prob**

Reemplazar la firma y el cuerpo de `player_leg_prob` (betbuilder.py:35-57) por:

```python
def player_leg_prob(model, sel, lh, la, home, away,
                    counts_model=None, c_home=None, c_away=None,
                    neutral: bool = False) -> float | None:
    """Marginal de una pata player vía Poisson top-down. None si: es faltante, no hay
    modelo, el nombre no resuelve, la métrica no está gateada, o no se puede ubicar al
    jugador / obtener el λ de su equipo.

    Para goal/assist el λ del equipo es el de goles (lh/la). Para `sot` el λ del equipo
    sale de counts_model.lambdas("sot", ...) (tiros al arco por-equipo), que aporta el
    ajuste de enfrentamiento. home/away son los nombres CANÓNICOS; c_home/c_away son los
    equipo_id (clave del counts_model)."""
    from rapidfuzz import fuzz
    if model is None or sel.faltante or not sel.player:
        return None
    pid = model.resolver(sel.player)
    if pid is None or not model.tiene(pid, sel.metric):
        return None
    equipo = model.equipo_de(pid)
    if equipo is None or home is None or away is None:
        return None
    s_home = fuzz.token_set_ratio(equipo.lower(), home.lower())
    s_away = fuzz.token_set_ratio(equipo.lower(), away.lower())
    if max(s_home, s_away) < 60:
        return None
    es_local = s_home >= s_away
    if sel.metric == "sot":
        if counts_model is None or not counts_model.tiene("sot"):
            return None
        lhs, las = counts_model.lambdas("sot", c_home, c_away, neutral)
        lam = lhs if es_local else las
    else:
        lam = lh if es_local else la
    return model.prob(pid, sel.metric, lam, umbral=sel.umbral)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_betbuilder.py -v`
Expected: PASS (los nuevos de sot y los existentes — la firma nueva es retrocompatible para goal/assist porque los args nuevos tienen default)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat(sot): player_leg_prob enruta lambda_sot de counts_model"
```

---

## Task 8: betbuilder — analyze_bet_builder recibe player_sot_model y enruta + fallback faltante

**Files:**
- Modify: `betbuilder.py:179-259`
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_betbuilder.py`. Usa los builders de parlay/selección ya presentes en el archivo (revisar cómo se construye un `ValidatedParlay` con una selección player en los tests existentes y replicar). Test mínimo de comportamiento:

```python
def test_analyze_bb_sot_resuelve_y_faltante_si_no_modelo():
    # Parlay con una pata player/sot. Con player_sot_model + counts_model -> prob_modelo
    # no nula. Sin player_sot_model -> faltante (no exótica).
    from betbuilder import analyze_bet_builder
    from player_model import PlayerModel
    from counts_model import CountsModel
    parlay = _parlay_una_pata_sot()   # helper local: construye ValidatedParlay con
                                      # una selección mercado="player", metric="sot",
                                      # player="Ronaldo", umbral=1, faltante=False,
                                      # equipos Portugal(local)/Spain con equipo_id.
    player_sot = PlayerModel.from_params({"metricas": ["sot"], "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal", "cuota_sot": 0.40}}})
    counts = CountsModel.from_params({"sot": {
        "base_home": 4.0, "base_away": 3.0, "factor_neutral": 1.0, "disp": 1.0,
        "atk": {}, "def": {}}})

    res = analyze_bet_builder(parlay, lh=1.2, la=0.9, rho=-0.05,
                              version_modelo="intl_v0.1", margin=0.0,
                              counts_model=counts, neutral=False,
                              player_model=None, player_sot_model=player_sot)
    assert res.selecciones[0].prob_modelo is not None
    assert res.selecciones[0].faltante is False

    res2 = analyze_bet_builder(parlay, lh=1.2, la=0.9, rho=-0.05,
                               version_modelo="intl_v0.1", margin=0.0,
                               counts_model=counts, neutral=False,
                               player_model=None, player_sot_model=None)
    assert res2.selecciones[0].prob_modelo is None
    assert res2.selecciones[0].faltante is True
    assert "Ronaldo" in (res2.faltantes_desc[0] if res2.faltantes_desc else "")
```

> Nota para el implementador: si construir `_parlay_una_pata_sot()` es laborioso, reutiliza el helper de parlay player que ya exista en `tests/test_betbuilder.py` (busca los tests de `goal`/`assist`) y cámbiale `metric` a `"sot"`, `faltante=False`.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_betbuilder.py -k sot_resuelve -v`
Expected: FAIL (TypeError: `analyze_bet_builder()` no acepta `player_sot_model`)

- [ ] **Step 3: Modificar analyze_bet_builder**

(a) Firma (betbuilder.py:179-180), añadir el param:

```python
def analyze_bet_builder(parlay, lh, la, rho, version_modelo: str, margin: float,
                        counts_model=None, neutral: bool = False, player_model=None,
                        player_sot_model=None):
```

(b) Cálculo de `player_p` en el loop (betbuilder.py:215-216), reemplazar por:

```python
        if is_player and sel.metric == "sot":
            player_p = player_leg_prob(player_sot_model, sel, lh, la, p_home, p_away,
                                       counts_model=counts_model, c_home=c_home,
                                       c_away=c_away, neutral=neutral)
        elif is_player and covered:
            player_p = player_leg_prob(player_model, sel, lh, la, p_home, p_away)
        else:
            player_p = None
```

(c) Rama de faltante (betbuilder.py:231-234), generalizar la condición y el mensaje:

```python
        elif is_player and player_p is None and (sel.faltante or sel.metric == "sot"):
            prob_mod = None
            faltantes_desc.append(sel.player or sel.seleccion)
            nivel_cov, alertas = "NULA", ["Mercado conocido pero sin datos para esta pata por jugador."]
```

(d) Campo `faltante` del `SelectionAnalysis` (betbuilder.py:258), reflejar el fallback real:

```python
            faltante=(is_player and player_p is None and (sel.faltante or sel.metric == "sot")),
```

- [ ] **Step 4: Correr la suite de betbuilder completa**

Run: `python -m pytest tests/test_betbuilder.py -v`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat(sot): analyze_bet_builder enruta player_sot_model + fallback faltante"
```

---

## Task 9: analyzer — cargar player_sot_v0.1 y cablearlo en la ruta

**Files:**
- Modify: `analyzer.py` (añadir `_load_player_sot_model` junto a `_load_player_model`; cablear en `_analyze_bet_builder_route`)

- [ ] **Step 1: Añadir el loader (clónico de _load_player_model, versión player_sot_v0.1)**

Tras `_load_player_model` (analyzer.py:629), añadir:

```python
_cached_player_sot_model: dict = {}


def _load_player_sot_model(liga_nombre: str):
    """Carga el PlayerModel de SoT (player_sot_v0.1) de una liga. None si no hay."""
    import json
    from player_model import PlayerModel
    if liga_nombre in _cached_player_sot_model:
        return _cached_player_sot_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_player_sot_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo").select("notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", "player_sot_v0.1")
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_player_sot_model[liga_nombre] = None
        return None
    model = PlayerModel.from_params(json.loads(rows[0]["notas"]))
    _cached_player_sot_model[liga_nombre] = model
    return model
```

- [ ] **Step 2: Cablear en _analyze_bet_builder_route**

En `_analyze_bet_builder_route` (analyzer.py:791-832): donde se cargan `counts`/`player` para cada liga, añadir la carga de sot, y pasarla a `analyze_bet_builder`.

Para la rama Internacional (tras `player = _load_player_model("Internacional")`):

```python
        player_sot = _load_player_sot_model("Internacional")
```

Para la rama Liga 1 (tras `player = _load_player_model("Liga 1 Peruana")`):

```python
        player_sot = _load_player_sot_model("Liga 1 Peruana")
```

Y el `return` final (analyzer.py:830-832):

```python
    return analyze_bet_builder(parlay, lh, la, rho, version, margin,
                               counts_model=counts, neutral=neutral_flag,
                               player_model=player, player_sot_model=player_sot)
```

- [ ] **Step 3: Verificar que el módulo importa**

Run: `python -c "import analyzer; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Correr la suite completa (no debe romper nada existente)**

Run: `python -m pytest tests/ -q`
Expected: PASS (toda la suite verde; el cableado nuevo es retrocompatible)

- [ ] **Step 5: Commit**

```bash
git add analyzer.py
git commit -m "feat(sot): analyzer carga player_sot_v0.1 y lo pasa al bet builder"
```

---

## Task 10: ocr — des-exotizar la pata sot (faltante:false)

**Files:**
- Modify: `ocr.py:124-132`
- Test: `tests/test_ocr_prompt.py` (si valida el texto del prompt)

- [ ] **Step 1: Ajustar el prompt**

En `ocr.py`, cambiar las instrucciones de la métrica `sot` de la familia player (líneas ~129-132). Reemplazar:

```
    - "seleccion": "yes" ; "faltante": true SOLO si metric=="sot" (tiros al arco por jugador,
      mercado conocido pero aún no modelable). Para goal/assist/goal_or_assist, "faltante": false.
    Ejemplos: "Lionel Messi 1+ Tiros al Arco" -> player/sot/umbral 1/faltante true ;
```

por:

```
    - "seleccion": "yes" ; "faltante": false (todas las métricas player se intentan modelar;
      si no hay datos, el motor lo marca faltante por su cuenta).
    Ejemplos: "Lionel Messi 1+ Tiros al Arco" -> player/sot/umbral 1/faltante false ;
```

- [ ] **Step 2: Revisar test del prompt**

Run: `python -m pytest tests/test_ocr_prompt.py -v`
Expected: PASS. Si algún assert fijaba `faltante true` para sot, actualizarlo a `false` (refleja el nuevo contrato: el motor decide faltante, no el OCR).

- [ ] **Step 3: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ocr.py tests/test_ocr_prompt.py
git commit -m "feat(sot): des-exotizar pata sot en el prompt (faltante lo decide el motor)"
```

---

## Task 11: Backfill de datos (descubrimiento + hidratación resumable)

**Files:**
- Create: `download_sot_jugador.py`
- Test: `tests/test_sot_transform.py` (extender con el helper de selección de pendientes)

> Esta tarea trae datos reales de API-Football. Las partes puras (selección de pendientes, resolución de equipo) se testean; el bucle de red es delgado.

- [ ] **Step 1: Test del helper de selección de pendientes**

Añadir a `tests/test_sot_transform.py`:

```python
from download_sot_jugador import elegir_pendientes


def test_elegir_pendientes_respeta_presupuesto():
    prog = [{"event_id": i, "estado": "pendiente"} for i in range(10)]
    prog += [{"event_id": 100, "estado": "hecho"}]
    elegidos = elegir_pendientes(prog, presupuesto=3)
    assert elegidos == [0, 1, 2]            # solo pendientes, hasta el presupuesto
    assert elegir_pendientes(prog, presupuesto=0) == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_sot_transform.py::test_elegir_pendientes_respeta_presupuesto -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'download_sot_jugador'`)

- [ ] **Step 3: Implementar download_sot_jugador.py**

```python
# download_sot_jugador.py
"""Backfill resumable de SoT por-jugador desde API-Football /fixtures/players.

Dos fases idempotentes:
  descubrir  -> lista fixtures por (liga, temporada) y los marca 'pendiente'.
  hidratar   -> toma N pendientes (presupuesto del día), baja /fixtures/players,
                escribe eventos_sot_jugador, marca 'hecho'/'sin_datos'.

    python download_sot_jugador.py descubrir
    python download_sot_jugador.py hidratar [N]

Plan Free: ~100 req/día, 10/min. Corre 'hidratar' una vez al día hasta agotar
pendientes (o déjalo en /loop). La resolución equipo_nombre->equipo_id es fuzzy
contra equipos.nombre_oficial (nombres en inglés, como martj42); ver alias abajo.
"""
import os
import sys
import time

import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz
from supabase import create_client

from sot_transform import parse_fixtures_players

API_URL = "https://v3.football.api-sports.io"
PRESUPUESTO_DEFAULT = 90        # margen bajo el límite de 100/día
RESOLVER_UMBRAL = 85

# MANIFIESTO: (liga_api_id, [temporadas]). Confirmar IDs con un sondeo a /leagues.
# Selecciones donde se repiten los jugadores bettables (profundidad para el gate).
MANIFIESTO = [
    (1,  [2022]),            # World Cup
    (4,  [2024]),            # Euro
    (5,  [2022, 2024]),      # Nations League
    (9,  [2024]),            # Copa America
    # añadir clasificatorias/amistosos según presupuesto disponible
]

# Alias ES/EN o variantes API-Football -> nombre_oficial en `equipos` (crece a demanda)
ALIAS = {}


def elegir_pendientes(progreso: list[dict], presupuesto: int) -> list[int]:
    """event_ids en estado 'pendiente', hasta `presupuesto`."""
    return [p["event_id"] for p in progreso if p["estado"] == "pendiente"][:presupuesto]


def _api_get(endpoint, params, key):
    r = requests.get(f"{API_URL}/{endpoint}", headers={"x-apisports-key": key},
                     params=params, timeout=25)
    r.raise_for_status()
    remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
    return r.json().get("response", []), remaining


def _resolver_equipo(nombre, mapa_nombre_id):
    n = ALIAS.get(nombre, nombre).lower()
    mejor_id, mejor = None, 0.0
    for nom, _id in mapa_nombre_id.items():
        sc = fuzz.token_set_ratio(n, nom.lower())
        if sc > mejor:
            mejor_id, mejor = _id, sc
    return mejor_id if mejor >= RESOLVER_UMBRAL else None


def descubrir(sb, key):
    total = 0
    for liga_id, temporadas in MANIFIESTO:
        for season in temporadas:
            fixtures, rem = _api_get("fixtures", {"league": liga_id, "season": season}, key)
            rows = [{"event_id": f["fixture"]["id"], "liga_api_id": liga_id,
                     "temporada": season, "estado": "pendiente"} for f in fixtures]
            for i in range(0, len(rows), 100):
                sb.table("sot_backfill_progreso").upsert(
                    rows[i:i+100], on_conflict="event_id").execute()
            total += len(rows)
            print(f"  liga {liga_id} {season}: {len(rows)} fixtures | API rem {rem}")
            time.sleep(0.3)
    print(f"✅ descubrimiento: {total} fixtures marcados pendiente.")


def hidratar(sb, key, presupuesto):
    prog = (sb.table("sot_backfill_progreso").select("event_id,estado")
            .eq("estado", "pendiente").limit(presupuesto).execute().data)
    pendientes = elegir_pendientes(prog, presupuesto)
    mapa = {e["nombre_oficial"]: e["id"]
            for e in sb.table("equipos").select("id,nombre_oficial").execute().data}
    print(f"  {len(pendientes)} pendientes a hidratar (presupuesto {presupuesto}).")
    hechos = 0
    for eid in pendientes:
        resp, rem = _api_get("fixtures/players", {"fixture": eid}, key)
        filas = parse_fixtures_players(resp, eid)
        if not filas:
            sb.table("sot_backfill_progreso").update(
                {"estado": "sin_datos", "fecha_proceso": "now()"}).eq("event_id", eid).execute()
            continue
        rows = []
        for f in filas:
            rows.append({"event_id": f["event_id"], "player_id": f["player_id"],
                         "player_nombre": f["player_nombre"],
                         "equipo_id": _resolver_equipo(f["equipo_nombre"], mapa),
                         "sot": f["sot"], "fue_titular": f["fue_titular"],
                         "minutos": f["minutos"]})
        sb.table("eventos_sot_jugador").upsert(rows, on_conflict="event_id,player_id").execute()
        sb.table("sot_backfill_progreso").update(
            {"estado": "hecho", "fecha_proceso": "now()"}).eq("event_id", eid).execute()
        hechos += 1
        if str(rem).isdigit() and int(rem) <= 5:
            print(f"  ⚠ rate-limit casi agotado (rem {rem}); paro.")
            break
        time.sleep(6.5)   # ~9/min, bajo el límite de 10/min
    print(f"✅ hidratados {hechos} fixtures.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    key = os.environ["API_FOOTBALL_KEY"]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hidratar"
    if cmd == "descubrir":
        descubrir(sb, key)
    elif cmd == "hidratar":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else PRESUPUESTO_DEFAULT
        hidratar(sb, key, n)
    else:
        print("uso: python download_sot_jugador.py [descubrir|hidratar [N]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr el test del helper**

Run: `python -m pytest tests/test_sot_transform.py -v`
Expected: PASS (incluye `test_elegir_pendientes_respeta_presupuesto`)

- [ ] **Step 5: Commit**

```bash
git add download_sot_jugador.py tests/test_sot_transform.py
git commit -m "feat(sot): backfill resumable (descubrir + hidratar) API-Football"
```

---

## Task 12: Ejecución del backfill + gate + decisión (operacional)

**Files:** ninguno nuevo (corre los scripts).

- [ ] **Step 1: Confirmar IDs de liga del manifiesto**

Sondeo rápido a API-Football `/leagues?type=cup` (o el dashboard) para confirmar los `liga_api_id` de Mundial/Euro/Nations/Copa América y completar `MANIFIESTO` en `download_sot_jugador.py`. Ajustar `ALIAS` si algún nombre de selección de API-Football no casa con `equipos.nombre_oficial` (inglés).

- [ ] **Step 2: Crear tablas y descubrir fixtures**

Run:
```bash
python sot_ddl.py
python download_sot_jugador.py descubrir
```
Expected: tablas creadas; N fixtures marcados `pendiente`.

- [ ] **Step 3: Hidratar goteando (resumable, ~90/día)**

Run (una vez al día hasta agotar pendientes; opcionalmente vía `/loop`):
```bash
python download_sot_jugador.py hidratar
```
Expected: cada corrida hidrata hasta ~90 fixtures y se detiene. Repetir hasta que no queden `pendiente` (verificar con un `select count(*) ... where estado='pendiente'`).

- [ ] **Step 4: Correr el gate**

Run: `python fit_player_sot.py`
Expected: imprime el Brier modelo vs base y `✅ PASA` / `❌ no pasa` + la `lambda_sot real`.

- [ ] **Step 5: Decisión según el gate**

- Si **PASA** (mejora ≥3%): `python load_player_sot_to_supabase.py` (publica `player_sot_v0.1`), luego verificación e2e (Task 13).
- Si **NO PASA**: NO publicar. Diagnosticar como en goal/assist (¿muestra fina? ¿concentración? ¿sobre-dispersión → probar NegBin?). Guardar diagnóstico y decidir con Angel. La pata `sot` sigue cayendo a `faltante` con gracia (sin regresión).

- [ ] **Step 6: Commit (si se ajustó el manifiesto/alias)**

```bash
git add download_sot_jugador.py
git commit -m "chore(sot): manifiesto de ligas y alias confirmados"
```

---

## Task 13: Verificación e2e (solo si el gate pasó y se publicó)

**Files:** ninguno (verificación manual).

- [ ] **Step 1: Verificar un boleto con pata sot**

Analizar (vía `?demo` o el flujo normal) un bet builder con una pata tipo "Cristiano Ronaldo 1+ tiros al arco" en un partido de selecciones cubierto por `counts_v0.1` (sot) e `intl_v0.1`.
Expected: la pata `sot` ya NO aparece como exótica/faltante; trae `prob_modelo` y entra al techo del veredicto. Un jugador desconocido o un partido sin λ_sot → `faltante` con gracia.

- [ ] **Step 2: Suite completa verde**

Run: `python -m pytest tests/ -q`
Expected: PASS (toda la suite).

- [ ] **Step 3: Finalizar la rama**

Invocar `superpowers:finishing-a-development-branch` para decidir merge/PR de `feat/tiros-al-arco-por-jugador`.

---

## Self-Review (cobertura del spec)

- **Backfill resumable (2 fases, manifiesto, ~100/día, idempotente):** Tasks 1, 11, 12. ✅
- **Tabla eventos_sot_jugador + sot_backfill_progreso (PK idempotente):** Task 1. ✅
- **Transform /fixtures/players (sot null→0, suplente→titular, equipo):** Task 2. ✅
- **cuota_sot con shrinkage + min_partidos≥10:** Tasks 3, 5. ✅
- **Gate con λ_sot REAL observado (no proxy) + elegibilidad ≥10 + Brier 3% + split 70/30:** Task 5, 12. ✅
- **Poisson (NegBin solo si sobre-dispersión):** Task 4 (Poisson); NegBin diferido como diagnóstico en Task 12 step 5. ✅
- **PlayerModel.prob rama sot + METRICAS_PLAYER:** Task 4. ✅
- **betbuilder λ_sot de counts_model + segundo player model + fallback faltante:** Tasks 7, 8. ✅
- **analyzer carga player_sot_v0.1 y enruta:** Task 9. ✅
- **Des-exotizar (ocr faltante:false):** Task 10. ✅
- **load player_sot_v0.1:** Task 6. ✅
- **Tests TDD (transform, fit, betbuilder):** Tasks 2, 3, 4, 5, 7, 8, 11. ✅
- **Fuera de alcance (Liga1 per-jugador SoT, frontend nuevo):** respetado — Liga1 sot no se publica (manifiesto intl), serving reusa la familia player existente. ✅

**Consistencia de tipos:** `parse_fixtures_players(response, event_id)` devuelve `equipo_nombre` (loader resuelve a `equipo_id`) — coherente entre Task 2 y Task 11. `estimar_cuotas_sot` devuelve `{nombre, equipo, cuota_sot}` — consumido igual en Task 5 (`PlayerModel`) y Task 7 (`prob` usa `j["cuota_sot"]`). `player_leg_prob(...,counts_model,c_home,c_away,neutral)` — misma firma en Task 7 (definición) y Task 8 (llamada). `analyze_bet_builder(..., player_sot_model=None)` — misma en Task 8 (def) y Task 9 (llamada). ✅
