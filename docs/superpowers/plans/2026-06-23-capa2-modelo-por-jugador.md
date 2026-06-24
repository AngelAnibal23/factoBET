# Modelo por-jugador (anota/asiste) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modelar las patas por-jugador (jugador anota / asiste / anota-o-asiste) de un bet builder, top-down repartiendo el λ de goles de Capa 1 por cuota histórica, e integrarlas al motor como tercera familia `player`.

**Architecture:** Espejo del patrón `count` (Sub-proyecto B). Datos Flashscore (`df_sui_1` eventos + `df_li_1` titulares) → tabla `eventos_jugador_flashscore` → `player_model.py` (puro) ← `fit_player_model.py` (gate) → `load_player_model_to_supabase.py` (params `player_v0.1`) → `analyzer._load_player_model` → ruteo en `betbuilder.analyze_bet_builder`. OCR aprende mercado `player`; tiros-al-arco se marca `faltante`. UI mínima en `SelectionCard`.

**Tech Stack:** Python (scipy.stats.poisson, rapidfuzz, supabase, dotenv, curl_cffi en `.venv-fbref`), pytest, React (frontend).

**Convenciones fijas (usadas en todas las tareas):**
- `player_model.METRICAS_PLAYER = ("goal", "assist", "goal_or_assist")`
- params `player_v0.1` (forma): `{"metricas": ["goal","assist"], "jugadores": {player_id: {"nombre": str, "equipo": str_canonico, "cuota_gol": float, "cuota_asist": float}}}`
- `ValidatedSelection` campos nuevos: `player: Optional[str] = None`, `umbral: int = 1`, `faltante: bool = False`
- `betbuilder.PLAYER_MARKET = "player"`
- `ParlayAnalysis.faltantes_desc: list[str]`; `SelectionAnalysis.faltante: bool`

---

## File Structure

- **Create** `player_model.py` — modelo puro: `estimar_cuotas`, `class PlayerModel` (resolver/tiene/prob). Sin red.
- **Create** `tests/test_player_model.py` — tests del modelo puro.
- **Create** `download_player_events.py` — scraper offline (`.venv-fbref`): baja `df_sui_1`/`df_li_1`, parsers puros + orquestación. Escribe CSV.
- **Create** `player_events_transform.py` — parsers puros del feed packed (testables sin red).
- **Create** `tests/test_player_events_transform.py` — tests de parsers con fixtures.
- **Create** `load_player_events_to_supabase.py` — crea/puebla `eventos_jugador_flashscore`.
- **Create** `fit_player_model.py` — agrega registros + gate por métrica (Brier holdout).
- **Create** `tests/test_fit_player_model.py` — tests de la agregación pura.
- **Create** `load_player_model_to_supabase.py` — persiste params `player_v0.1`.
- **Modify** `validator.py:83-99` — campos nuevos en `ValidatedSelection` + parseo `player`/`umbral`/`faltante`.
- **Modify** `ocr.py:101-147` — prompt: mercado `player` + `faltante`.
- **Modify** `betbuilder.py` — `player_leg_prob`, ruteo player/faltante, `faltantes_desc`.
- **Modify** `analyzer.py` — `_load_player_model`, `SelectionAnalysis.faltante`, `ParlayAnalysis.faltantes_desc`, wiring.
- **Modify** `frontend/src/components/SelectionCard.jsx` — etiqueta player + patas faltantes.
- **Modify** `tests/test_betbuilder.py`, `tests/test_analyzer_betbuilder.py`, `tests/test_ocr_prompt.py` — cobertura.

---

## Task 1: `player_model.estimar_cuotas` (cuotas con shrinkage)

**Files:**
- Create: `player_model.py`
- Test: `tests/test_player_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_model.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_model import estimar_cuotas

# 3 jugadores del equipo "POR". Cada registro = un partido como titular.
# goles_equipo = goles totales del equipo ese partido.
REGISTROS = [
    {"player_id": "p1", "nombre": "Ronaldo",  "equipo": "Portugal",
     "goles_jugador": 2, "asist_jugador": 0, "goles_equipo": 3, "n_titulares": 11},
    {"player_id": "p1", "nombre": "Ronaldo",  "equipo": "Portugal",
     "goles_jugador": 1, "asist_jugador": 1, "goles_equipo": 2, "n_titulares": 11},
    {"player_id": "p2", "nombre": "B Fernandes", "equipo": "Portugal",
     "goles_jugador": 0, "asist_jugador": 2, "goles_equipo": 3, "n_titulares": 11},
    {"player_id": "p3", "nombre": "Suplente",  "equipo": "Portugal",
     "goles_jugador": 0, "asist_jugador": 0, "goles_equipo": 2, "n_titulares": 11},
]


def test_estimar_cuotas_estructura_y_rango():
    out = estimar_cuotas(REGISTROS, k=2.0)
    assert set(out) == {"p1", "p2", "p3"}
    assert out["p1"]["nombre"] == "Ronaldo"
    assert out["p1"]["equipo"] == "Portugal"
    # Ronaldo mete muchos goles -> cuota_gol alta; B Fernandes asiste -> cuota_asist alta
    assert out["p1"]["cuota_gol"] > out["p2"]["cuota_gol"]
    assert out["p2"]["cuota_asist"] > out["p1"]["cuota_asist"]
    # cuotas son fracciones en (0,1)
    for v in out.values():
        assert 0.0 < v["cuota_gol"] < 1.0
        assert 0.0 <= v["cuota_asist"] < 1.0


def test_shrinkage_acerca_al_prior_con_pocos_datos():
    # p3 (suplente, 1 partido, 0 goles): con k alto su cuota_gol se pega al prior 1/11
    flojo  = estimar_cuotas(REGISTROS, k=0.1)
    fuerte = estimar_cuotas(REGISTROS, k=50.0)
    prior = 1.0 / 11
    assert abs(fuerte["p3"]["cuota_gol"] - prior) < abs(flojo["p3"]["cuota_gol"] - prior)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'player_model'`

- [ ] **Step 3: Write minimal implementation**

```python
# player_model.py
"""Modelo por-jugador (anota/asiste) de la Capa 2.

Top-down: reparte el λ de goles del equipo (Capa 1) entre jugadores según su
cuota histórica de goles/asistencias, estimada por método de momentos con
shrinkage empírico-Bayes hacia un prior igualitario (1/n_titulares). Poisson
sobre los eventos del jugador. NO lee red al importar: funciones puras.
"""

from scipy.stats import poisson

METRICAS_PLAYER = ("goal", "assist", "goal_or_assist")


def estimar_cuotas(registros: list[dict], k: float = 5.0) -> dict:
    """Estima cuota_gol y cuota_asist por jugador con shrinkage.

    registros: lista de partidos-como-titular, cada uno
      {player_id, nombre, equipo, goles_jugador, asist_jugador, goles_equipo, n_titulares}.
    k: fuerza del prior (nº de "partidos virtuales" hacia el prior igualitario).

    Cuota = fracción de goles del equipo que el jugador anotó/asistió. Los partidos
    con goles_equipo==0 se excluyen del promedio (share indefinido) pero su prior
    1/n_titulares sí informa el shrinkage.
    """
    por_jugador: dict[str, list[dict]] = {}
    for r in registros:
        por_jugador.setdefault(r["player_id"], []).append(r)

    out = {}
    for pid, regs in por_jugador.items():
        prior = sum(1.0 / r["n_titulares"] for r in regs) / len(regs)
        shares_gol = [r["goles_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        shares_ast = [r["asist_jugador"] / r["goles_equipo"]
                      for r in regs if r["goles_equipo"] > 0]
        cuota_gol = (sum(shares_gol) + k * prior) / (len(shares_gol) + k)
        cuota_ast = (sum(shares_ast) + k * prior) / (len(shares_ast) + k)
        out[pid] = {
            "nombre": regs[0]["nombre"], "equipo": regs[0]["equipo"],
            "cuota_gol": cuota_gol, "cuota_asist": cuota_ast,
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add player_model.py tests/test_player_model.py
git commit -m "feat: player_model.estimar_cuotas (cuota gol/asist con shrinkage)"
```

---

## Task 2: `PlayerModel` (resolver / tiene / prob)

**Files:**
- Modify: `player_model.py`
- Test: `tests/test_player_model.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_player_model.py
from player_model import PlayerModel
import math

PARAMS = {
    "metricas": ["goal", "assist"],
    "jugadores": {
        "p1": {"nombre": "Cristiano Ronaldo", "equipo": "Portugal",
               "cuota_gol": 0.40, "cuota_asist": 0.10},
        "p2": {"nombre": "Bruno Fernandes", "equipo": "Portugal",
               "cuota_gol": 0.15, "cuota_asist": 0.30},
    },
}


def test_tiene_respeta_metricas_gateadas():
    m = PlayerModel.from_params(PARAMS)
    assert m.tiene("p1", "goal") is True
    assert m.tiene("p1", "assist") is True
    assert m.tiene("p1", "goal_or_assist") is True   # ambos componentes publicados
    assert m.tiene("p1", "corner") is False
    # si una métrica no está publicada, goal_or_assist tampoco
    solo_goal = PlayerModel.from_params({"metricas": ["goal"], "jugadores": PARAMS["jugadores"]})
    assert solo_goal.tiene("p1", "assist") is False
    assert solo_goal.tiene("p1", "goal_or_assist") is False
    assert solo_goal.tiene("desconocido", "goal") is False


def test_prob_anota_poisson():
    m = PlayerModel.from_params(PARAMS)
    # λ_jugador = λ_equipo(1.6) * cuota_gol(0.40) = 0.64 ; P(anota>=1)=1-e^-0.64
    p = m.prob("p1", "goal", lambda_equipo=1.6, umbral=1)
    assert abs(p - (1 - math.exp(-0.64))) < 1e-9


def test_prob_anota_o_asiste_suma_lambdas():
    m = PlayerModel.from_params(PARAMS)
    # λ = 1.6*(0.40+0.10)=0.80 ; P(>=1)=1-e^-0.80
    p = m.prob("p1", "goal_or_assist", lambda_equipo=1.6, umbral=1)
    assert abs(p - (1 - math.exp(-0.80))) < 1e-9


def test_prob_umbral_dos():
    m = PlayerModel.from_params(PARAMS)
    from scipy.stats import poisson
    lam = 1.6 * 0.40
    p = m.prob("p1", "goal", lambda_equipo=1.6, umbral=2)   # P(X>=2)=1-cdf(1)
    assert abs(p - (1 - poisson.cdf(1, lam))) < 1e-9


def test_resolver_fuzzy_nombre():
    m = PlayerModel.from_params(PARAMS)
    assert m.resolver("Ronaldo") == "p1"           # token subset
    assert m.resolver("B. Fernandes") == "p2"
    assert m.resolver("Lionel Messi") is None       # nadie parecido -> None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'PlayerModel'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to player_model.py
from rapidfuzz import fuzz

RESOLVER_UMBRAL = 80.0   # token_set_ratio mínimo para aceptar un match de nombre


class PlayerModel:
    """Predictor por-jugador con params congelados. Solo contiene las métricas que
    pasaron el gate (en params['metricas']) y los jugadores con cuotas publicadas."""

    @classmethod
    def from_params(cls, params: dict) -> "PlayerModel":
        m = cls()
        m.metricas = set(params.get("metricas", []))
        m.jugadores = params.get("jugadores", {})
        return m

    def tiene(self, player_id: str, metric: str) -> bool:
        if player_id not in self.jugadores:
            return False
        if metric == "goal_or_assist":
            return {"goal", "assist"} <= self.metricas
        return metric in self.metricas

    def equipo_de(self, player_id: str) -> str | None:
        j = self.jugadores.get(player_id)
        return j["equipo"] if j else None

    def resolver(self, nombre: str) -> str | None:
        """Resuelve un nombre de jugador (del boleto) a player_id por fuzzy match."""
        if not nombre:
            return None
        mejor_id, mejor_score = None, 0.0
        for pid, j in self.jugadores.items():
            score = fuzz.token_set_ratio(nombre.lower(), j["nombre"].lower())
            if score > mejor_score:
                mejor_id, mejor_score = pid, score
        return mejor_id if mejor_score >= RESOLVER_UMBRAL else None

    def prob(self, player_id: str, metric: str, lambda_equipo: float,
             umbral: int = 1) -> float:
        """P(el jugador alcanza `umbral` eventos | es titular), Poisson top-down."""
        j = self.jugadores[player_id]
        if metric == "goal":
            lam = lambda_equipo * j["cuota_gol"]
        elif metric == "assist":
            lam = lambda_equipo * j["cuota_asist"]
        elif metric == "goal_or_assist":
            lam = lambda_equipo * (j["cuota_gol"] + j["cuota_asist"])
        else:
            raise ValueError(f"métrica player inválida: {metric!r}")
        return float(1.0 - poisson.cdf(umbral - 1, lam))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_player_model.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add player_model.py tests/test_player_model.py
git commit -m "feat: PlayerModel (resolver fuzzy + tiene + prob Poisson top-down)"
```

---

## Task 3: Parsers del feed por-jugador (puros, con fixtures)

**Files:**
- Create: `player_events_transform.py`
- Test: `tests/test_player_events_transform.py`

**Contexto del formato** (ver [[reference-capa2-datasources]]): el feed packed separa registros por `~` (U+007E) y campos por bytes de control. `df_sui_1`: claves `AC`=mitad, `IB`=minuto, `IK`=tipo, `IF`=jugador, `IM`=playerId, `IU`=url, `IA`=lado(1/2). `df_li_1`: `LP`=id, `LI`/`LN`=nombre, `LH`=posición; un jugador es titular si aparece en el bloque de titulares (no en suplentes). Para el parser usamos el formato campo `clave÷valor` separado por `¬` dentro de cada registro (decodificar `bytes.decode('utf-8')`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_player_events_transform.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from player_events_transform import parse_eventos, parse_titulares

# Fixture mínimo del feed df_sui_1 (2 eventos): un gol de p1 (lado 1) y una
# asistencia de p2 (lado 1). Campos clave÷valor, registros sep por '~'.
SUI = (
    "IK÷Goal¬IF÷Cristiano Ronaldo¬IM÷p1¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Assistance¬IF÷Bruno Fernandes¬IM÷p2¬IA÷1¬IB÷23'¬AC÷1st Half~"
    "IK÷Yellow Card¬IF÷Pepe¬IM÷p9¬IA÷1¬IB÷70'¬AC÷2nd Half"
)

# Fixture df_li_1: titulares lado 1 = p1,p2 ; suplente = p3.
LI = (
    "LP÷p1¬LI÷Cristiano Ronaldo¬LH÷FW¬IA÷1¬ST÷1~"
    "LP÷p2¬LI÷Bruno Fernandes¬LH÷MF¬IA÷1¬ST÷1~"
    "LP÷p3¬LI÷Suplente¬LH÷FW¬IA÷1¬ST÷0"
)


def test_parse_eventos_extrae_goles_y_asistencias():
    evs = parse_eventos(SUI)
    goles = [e for e in evs if e["tipo"] == "Goal"]
    asis  = [e for e in evs if e["tipo"] == "Assistance"]
    assert len(goles) == 1 and goles[0]["player_id"] == "p1"
    assert goles[0]["nombre"] == "Cristiano Ronaldo"
    assert goles[0]["lado"] == 1
    assert len(asis) == 1 and asis[0]["player_id"] == "p2"
    # las tarjetas se parsean pero no son de nuestras métricas (el fit las ignora)
    assert any(e["tipo"] == "Yellow Card" for e in evs)


def test_parse_titulares_marca_solo_starters():
    tit = parse_titulares(LI)
    assert tit["p1"] is True and tit["p2"] is True
    assert tit["p3"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_player_events_transform.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'player_events_transform'`

- [ ] **Step 3: Write minimal implementation**

```python
# player_events_transform.py
"""Parsers puros del feed packed por-jugador de Flashscore (df_sui_1, df_li_1).

Sin red: reciben el string ya decodificado y devuelven dicts/listas. La descarga
vive en download_player_events.py (offline, .venv-fbref)."""

REG_SEP = "~"
FLD_SEP = "¬"   # ¬
KV_SEP = "÷"    # ÷


def _registros(blob: str):
    for reg in blob.split(REG_SEP):
        if not reg.strip():
            continue
        campos = {}
        for kv in reg.split(FLD_SEP):
            if KV_SEP in kv:
                k, v = kv.split(KV_SEP, 1)
                campos[k] = v
        yield campos


def parse_eventos(blob: str) -> list[dict]:
    """Eventos del df_sui_1: tipo (IK), jugador (IF/IM), lado (IA), minuto (IB)."""
    evs = []
    for c in _registros(blob):
        if "IK" not in c or "IM" not in c:
            continue
        evs.append({
            "tipo": c.get("IK", ""),
            "player_id": c.get("IM", ""),
            "nombre": c.get("IF", ""),
            "lado": int(c["IA"]) if c.get("IA", "").isdigit() else None,
            "minuto": c.get("IB", ""),
            "mitad": c.get("AC", ""),
        })
    return evs


def parse_titulares(blob: str) -> dict:
    """df_li_1: {player_id: fue_titular}. Titular si ST==1."""
    out = {}
    for c in _registros(blob):
        if "LP" not in c:
            continue
        out[c["LP"]] = c.get("ST", "0") == "1"
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_player_events_transform.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add player_events_transform.py tests/test_player_events_transform.py
git commit -m "feat: parsers puros del feed por-jugador (df_sui_1/df_li_1)"
```

> **Nota de implementación:** los nombres exactos de las claves de titularidad (`ST`) deben verificarse contra un feed real al ejecutar Task 4; si difieren, ajustar `parse_titulares` y su fixture juntos (test + impl en el mismo commit). El resto del patrón (REG/FLD/KV sep, IK/IF/IM/IA) está confirmado en el sondeo.

---

## Task 4: Scraper offline `download_player_events.py`

**Files:**
- Create: `download_player_events.py`

Este script corre en `.venv-fbref` (tiene `curl_cffi`). No es TDD (es I/O de red); reusa los event_ids ya enumerados por `download_flashscore_stats.py` y los parsers de Task 3. Genera `player_events.csv`.

- [ ] **Step 1: Implement the downloader**

```python
# download_player_events.py
"""Baja eventos por-jugador (df_sui_1) + titulares (df_li_1) de Flashscore para
los event_ids ya enumerados, y escribe player_events.csv. Correr en .venv-fbref.

    python download_player_events.py

Reusa la enumeración de event_ids de download_flashscore_stats.py (misma lista de
torneos / mismo patrón híbrido DOM->ids). Aquí solo bajamos los 2 feeds livianos.
"""

import csv
import sys
import time

from curl_cffi import requests as crequests

from player_events_transform import parse_eventos, parse_titulares
from download_flashscore_stats import enumerar_event_ids, TOURNAMENTS  # reuso

FEED_HOST = "https://2.flashscore.ninja/2/x/feed/"
HEADERS = {"x-fsign": "SW9D1eZo"}


def _feed(nombre: str) -> str:
    url = FEED_HOST + nombre
    r = crequests.get(url, headers=HEADERS, impersonate="chrome", timeout=20)
    return r.content.decode("utf-8", errors="replace")


def bajar_partido(eid: str):
    eventos = parse_eventos(_feed(f"df_sui_1_{eid}"))
    titulares = parse_titulares(_feed(f"df_li_1_{eid}"))
    filas = []
    for e in eventos:
        filas.append({
            "event_id": eid, "player_id": e["player_id"], "nombre": e["nombre"],
            "tipo": e["tipo"], "lado": e["lado"], "minuto": e["minuto"],
            "mitad": e["mitad"], "fue_titular": titulares.get(e["player_id"], False),
        })
    return filas


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    todos = []
    for torneo, eids in enumerar_event_ids(TOURNAMENTS).items():
        print(f"{torneo}: {len(eids)} partidos")
        for eid in eids:
            try:
                todos.extend(bajar_partido(eid))
            except Exception as ex:   # noqa: BLE001 — scraper offline, log y sigue
                print(f"  ⚠ {eid}: {ex}")
            time.sleep(0.2)
    with open("player_events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["event_id", "player_id", "nombre", "tipo",
                                          "lado", "minuto", "mitad", "fue_titular"])
        w.writeheader()
        w.writerows(todos)
    print(f"✅ {len(todos)} filas -> player_events.csv")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it (offline, .venv-fbref) and sanity-check**

Run: `./.venv-fbref/Scripts/python download_player_events.py`
Expected: imprime partidos por torneo y `✅ N filas -> player_events.csv` (N de varios miles). Si `enumerar_event_ids`/`TOURNAMENTS` no son los nombres exactos exportados por `download_flashscore_stats.py`, ajustar el import a los símbolos reales de ese módulo (revisar su `def`/constantes) — sin cambiar la lógica.

- [ ] **Step 3: Commit**

```bash
git add download_player_events.py
git commit -m "feat: download_player_events.py (df_sui_1+df_li_1 -> csv)"
```

---

## Task 5: Cargar eventos a Supabase `load_player_events_to_supabase.py`

**Files:**
- Create: `load_player_events_to_supabase.py`

- [ ] **Step 1: Implement loader (DDL + upsert + resolución de equipo)**

```python
# load_player_events_to_supabase.py
"""Crea/puebla eventos_jugador_flashscore desde player_events.csv.

Resuelve equipo_id por event_id+lado contra estadisticas_flashscore (que ya tiene
event_id, es_local, equipo_id resueltos). Idempotente por (event_id, player_id, tipo, minuto).

    python load_player_events_to_supabase.py
"""

import csv
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

DDL = """
create table if not exists eventos_jugador_flashscore (
  id bigint generated always as identity primary key,
  event_id text not null,
  equipo_id uuid,
  player_id text not null,
  player_nombre text,
  tipo text not null,
  minuto text,
  mitad text,
  fue_titular boolean,
  unique (event_id, player_id, tipo, minuto)
);
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    print("Crear tabla: ejecuta el DDL en el SQL editor de Supabase si no existe:\n", DDL)

    # mapa (event_id, lado) -> equipo_id desde estadisticas_flashscore
    lado_equipo = {}
    desde, paso = 0, 1000
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,es_local,equipo_id")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            lado = 1 if r["es_local"] else 2
            lado_equipo[(r["event_id"], lado)] = r["equipo_id"]
        if len(chunk) < paso:
            break
        desde += paso

    filas = []
    with open("player_events.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            lado = int(r["lado"]) if r["lado"] not in ("", "None") else None
            filas.append({
                "event_id": r["event_id"],
                "equipo_id": lado_equipo.get((r["event_id"], lado)),
                "player_id": r["player_id"], "player_nombre": r["nombre"],
                "tipo": r["tipo"], "minuto": r["minuto"], "mitad": r["mitad"],
                "fue_titular": r["fue_titular"] == "True",
            })
    for i in range(0, len(filas), 500):
        sb.table("eventos_jugador_flashscore").upsert(
            filas[i:i + 500], on_conflict="event_id,player_id,tipo,minuto").execute()
    con_equipo = sum(1 for f in filas if f["equipo_id"])
    print(f"✅ {len(filas)} filas; identidad equipo {con_equipo}/{len(filas)} "
          f"({con_equipo / max(len(filas),1) * 100:.0f}%)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run loader and verify coverage**

Run: `python load_player_events_to_supabase.py`
Expected: tras crear la tabla con el DDL en Supabase, imprime `✅ N filas; identidad equipo M/N (XX%)`. Cobertura de equipo debe ser alta (la base flashscore ya tiene 99% identidad).

- [ ] **Step 3: Commit**

```bash
git add load_player_events_to_supabase.py
git commit -m "feat: load_player_events_to_supabase (DDL + upsert + equipo_id)"
```

---

## Task 6: `fit_player_model.py` (agregación + gate)

**Files:**
- Create: `fit_player_model.py`
- Test: `tests/test_fit_player_model.py`

La parte testeable es la agregación pura `registros_desde_eventos` (eventos crudos → registros por (player, match) que consume `estimar_cuotas`). El gate (red) va en `main()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fit_player_model.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fit_player_model import registros_desde_eventos

# Dos partidos. event A: equipo "POR" mete 2 goles (p1 1 gol + p2 1 gol), p1 titular.
EVENTOS = [
    {"event_id": "A", "equipo": "POR", "player_id": "p1", "player_nombre": "R",
     "tipo": "Goal", "fue_titular": True},
    {"event_id": "A", "equipo": "POR", "player_id": "p2", "player_nombre": "B",
     "tipo": "Goal", "fue_titular": True},
    {"event_id": "A", "equipo": "POR", "player_id": "p2", "player_nombre": "B",
     "tipo": "Assistance", "fue_titular": True},
]
# titulares del equipo POR en event A (para n_titulares y para incluir a los que no anotaron)
TITULARES = {("A", "POR"): {"p1": "R", "p2": "B", "p3": "C"}}


def test_registros_cuenta_goles_y_titulares():
    regs = registros_desde_eventos(EVENTOS, TITULARES)
    by = {(r["event_id"], r["player_id"]): r for r in regs}
    # p1 anotó 1 de los 2 goles del equipo, fue titular, 3 titulares
    assert by[("A", "p1")]["goles_jugador"] == 1
    assert by[("A", "p1")]["goles_equipo"] == 2
    assert by[("A", "p1")]["n_titulares"] == 3
    # p2 anotó 1 y asistió 1
    assert by[("A", "p2")]["goles_jugador"] == 1
    assert by[("A", "p2")]["asist_jugador"] == 1
    # p3 fue titular pero no anotó -> registro con 0 goles (entra al reparto)
    assert by[("A", "p3")]["goles_jugador"] == 0
    assert by[("A", "p3")]["goles_equipo"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fit_player_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fit_player_model'`

- [ ] **Step 3: Write minimal implementation**

```python
# fit_player_model.py
"""Ajuste offline del modelo por-jugador + gate por métrica (goal/assist).

Lee eventos_jugador_flashscore (vía Supabase), arma registros por (jugador, partido
como titular), estima cuotas (player_model.estimar_cuotas) y valida cada métrica
contra un baseline igualitario (1/n_titulares) en un holdout temporal por Brier.
NO escribe a Supabase (eso lo hace load_player_model_to_supabase.py).

    python fit_player_model.py
"""

import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from supabase import create_client

from player_model import estimar_cuotas, PlayerModel

GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
TEST_FRAC = 0.30
LAMBDA_PROXY = 1.35   # goles esperados por equipo (proxy de liga para el gate)


def registros_desde_eventos(eventos: list[dict], titulares: dict) -> list[dict]:
    """Convierte eventos crudos + titulares en registros por (jugador, partido).

    eventos: [{event_id, equipo, player_id, player_nombre, tipo, fue_titular}].
    titulares: {(event_id, equipo): {player_id: nombre}} (todos los titulares).
    Devuelve un registro POR titular (incluye a los que no anotaron, con 0s).
    """
    goles_eq = defaultdict(int)        # (event_id, equipo) -> goles del equipo
    g = defaultdict(int)               # (event_id, player_id) -> goles
    a = defaultdict(int)               # (event_id, player_id) -> asist
    equipo_de = {}                     # (event_id, player_id) -> equipo
    nombre_de = {}
    for e in eventos:
        key = (e["event_id"], e["player_id"])
        equipo_de[key] = e["equipo"]
        nombre_de[key] = e["player_nombre"]
        if e["tipo"] == "Goal":
            g[key] += 1
            goles_eq[(e["event_id"], e["equipo"])] += 1
        elif e["tipo"] == "Assistance":
            a[key] += 1

    regs = []
    for (eid, equipo), starters in titulares.items():
        n_tit = len(starters)
        for pid, nombre in starters.items():
            key = (eid, pid)
            regs.append({
                "event_id": eid, "player_id": pid,
                "nombre": nombre_de.get(key, nombre), "equipo": equipo,
                "goles_jugador": g.get(key, 0), "asist_jugador": a.get(key, 0),
                "goles_equipo": goles_eq.get((eid, equipo), 0), "n_titulares": n_tit,
            })
    return regs


def _brier(probs, occ):
    return float(np.mean((np.asarray(probs) - np.asarray(occ, float)) ** 2))


def _gate(train, test, metrica):
    """Brier del modelo (cuotas) vs baseline (1/n_titulares) en el holdout."""
    cuotas = estimar_cuotas(train, k=K_SHRINK)
    m = PlayerModel.from_params({"metricas": [metrica], "jugadores": cuotas})
    col = "goles_jugador" if metrica == "goal" else "asist_jugador"
    probs_m, probs_b, occ = [], [], []
    for r in test:
        pid = r["player_id"]
        if m.tiene(pid, metrica):
            probs_m.append(m.prob(pid, metrica, LAMBDA_PROXY, umbral=1))
        else:
            probs_m.append(1 - np.exp(-LAMBDA_PROXY / r["n_titulares"]))
        probs_b.append(1 - np.exp(-LAMBDA_PROXY / r["n_titulares"]))
        occ.append(1.0 if r[col] >= 1 else 0.0)
    return _brier(probs_m, occ), _brier(probs_b, occ)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    # cargar eventos con fecha (join a estadisticas_flashscore por event_id) y titulares
    eventos, titulares, fecha_ev = _cargar(sb)
    regs = registros_desde_eventos(eventos, titulares)
    regs.sort(key=lambda r: fecha_ev.get(r["event_id"], ""))
    corte = int(len(regs) * (1 - TEST_FRAC))
    train, test = regs[:corte], regs[corte:]

    metricas_ok = []
    print("=" * 60, "\nFIT MODELO POR-JUGADOR — gate (liga INT)\n", "=" * 60)
    for metrica in ("goal", "assist"):
        bm, bb = _gate(train, test, metrica)
        mejora = (bb - bm) / bb if bb > 0 else 0.0
        ok = bm < bb and mejora >= GATE_MIN_MEJORA
        print(f"  {metrica:6}: Brier modelo={bm:.4f} base={bb:.4f} "
              f"mejora={mejora*100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
        if ok:
            metricas_ok.append(metrica)
    cuotas_prod = estimar_cuotas(regs, k=K_SHRINK)   # producción = todos los datos
    return {"metricas": metricas_ok, "jugadores": cuotas_prod}


def _cargar(sb):
    """Eventos (con equipo canónico), titulares por (event,equipo), y fecha por event."""
    # equipo_id -> nombre canónico
    eq = {e["id"]: e["nombre"] for e in sb.table("equipos").select("id,nombre").execute().data}
    # fecha por event_id
    fecha_ev = {}
    filas_fs = []
    desde, paso = 0, 1000
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,fecha").range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            fecha_ev[r["event_id"]] = r["fecha"]
        filas_fs.extend(chunk)
        if len(chunk) < paso:
            break
        desde += paso
    # eventos por jugador
    eventos, titulares = [], defaultdict(dict)
    desde = 0
    while True:
        chunk = (sb.table("eventos_jugador_flashscore")
                 .select("event_id,equipo_id,player_id,player_nombre,tipo,fue_titular")
                 .range(desde, desde + paso - 1).execute().data)
        for r in chunk:
            equipo = eq.get(r["equipo_id"])
            if equipo is None:
                continue
            eventos.append({"event_id": r["event_id"], "equipo": equipo,
                            "player_id": r["player_id"], "player_nombre": r["player_nombre"],
                            "tipo": r["tipo"], "fue_titular": r["fue_titular"]})
            if r["fue_titular"]:
                titulares[(r["event_id"], equipo)][r["player_id"]] = r["player_nombre"]
        if len(chunk) < paso:
            break
        desde += paso
    return eventos, dict(titulares), fecha_ev


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fit_player_model.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Run the gate (real data)**

Run: `python fit_player_model.py`
Expected: imprime el Brier de `goal` y `assist` con ✅/❌. Anota cuáles pasan (esperado: `goal` pasa; `assist` puede no pasar).

- [ ] **Step 6: Commit**

```bash
git add fit_player_model.py tests/test_fit_player_model.py
git commit -m "feat: fit_player_model (agregacion + gate goal/assist por Brier)"
```

---

## Task 7: `load_player_model_to_supabase.py` (params `player_v0.1`)

**Files:**
- Create: `load_player_model_to_supabase.py`

- [ ] **Step 1: Implement loader**

```python
# load_player_model_to_supabase.py
"""Carga los params del modelo por-jugador GATEADOS a parametros_modelo (player_v0.1).

Reusa fit_player_model.main() (corre el gate). Persiste UNA fila para la liga
Internacional con jugadores+metricas en `notas` (JSON). Idempotente.

    python load_player_model_to_supabase.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_player_model import main as fit_main

VERSION = "player_v0.1"
LIGA_NOMBRE = "Internacional"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    params = fit_main()
    if not params["metricas"]:
        print("Nada que cargar (ninguna métrica pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", LIGA_NOMBRE).execute().data
    if not liga:
        print(f"⚠ liga '{LIGA_NOMBRE}' no existe en `ligas`."); sys.exit(1)
    liga_id = liga[0]["id"]

    (sb.table("parametros_modelo").delete()
     .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
    sb.table("parametros_modelo").insert({
        "liga_id": liga_id, "version_modelo": VERSION,
        "attack_params": {}, "defense_params": {}, "is_production": True,
        "notas": json.dumps(params),
    }).execute()
    print(f"✅ player_v0.1 cargado: métricas {params['metricas']}, "
          f"{len(params['jugadores'])} jugadores.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run loader**

Run: `python load_player_model_to_supabase.py`
Expected: `✅ player_v0.1 cargado: métricas [...], N jugadores.`

- [ ] **Step 3: Commit**

```bash
git add load_player_model_to_supabase.py
git commit -m "feat: load_player_model_to_supabase (params player_v0.1)"
```

---

## Task 8: Validator — campos `player`/`umbral`/`faltante`

**Files:**
- Modify: `validator.py:83-99` (dataclass) y `validator.py:366-374` (construcción)
- Test: `tests/test_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_validator.py  (validate y _TEAMS ya están importados/definidos arriba)
_TEAMS_PLAYER = [
    {"id": "P1", "nombre_oficial": "Portugal", "aliases": []},
    {"id": "U1", "nombre_oficial": "Uzbekistan", "aliases": ["Uzbekistán"]},
]


def test_valida_pata_player():
    ocr = {
        "selecciones": [
            {"equipo_local": "Portugal", "equipo_visitante": "Uzbekistan",
             "mercado": "player", "seleccion": "yes", "cuota": None, "linea": None,
             "player": "Bruno Fernandes", "metric": "goal_or_assist", "umbral": 1},
            {"equipo_local": "Portugal", "equipo_visitante": "Uzbekistan",
             "mercado": "player", "seleccion": "yes", "cuota": None, "linea": None,
             "player": "Cristiano Ronaldo", "metric": "sot", "umbral": 2, "faltante": True},
        ],
        "cuota_total": 3.50, "casa_apuestas": "Betano",
    }
    parlay = validate(ocr, teams=_TEAMS_PLAYER)
    s0, s1 = parlay.selecciones
    assert s0.mercado == "player" and s0.player == "Bruno Fernandes"
    assert s0.metric == "goal_or_assist" and s0.umbral == 1 and s0.faltante is False
    assert s1.faltante is True and s1.metric == "sot"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_validator.py::test_valida_pata_player -v`
Expected: FAIL (AttributeError: `player`/`umbral`/`faltante` no existen)

- [ ] **Step 3: Add fields to the dataclass**

En `validator.py`, en `ValidatedSelection` (después de `scope`):

```python
    scope:                 Optional[str] = None   # total|home|away
    # Mercado por-jugador (familia "player"): nombre + métrica + umbral. faltante=True
    # para mercados conocidos pero aún no modelables (p.ej. tiros al arco por jugador).
    player:                Optional[str] = None   # nombre tal cual el boleto
    umbral:                int = 1                 # X+ eventos (default 1)
    faltante:              bool = False
```

- [ ] **Step 4: Populate fields in construction**

En `validator.py` donde se construye cada `ValidatedSelection` (junto a `metric=`/`scope=`):

```python
            metric               = s.get("metric"),
            scope                = s.get("scope"),
            player               = s.get("player"),
            umbral               = int(s.get("umbral") or 1),
            faltante             = bool(s.get("faltante", False)),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_validator.py -v`
Expected: PASS (incluye el nuevo test; los previos siguen verdes)

- [ ] **Step 6: Commit**

```bash
git add validator.py tests/test_validator.py
git commit -m "feat: validator soporta familia player (player/umbral/faltante)"
```

---

## Task 9: OCR — prompt reconoce mercado `player` y `faltante`

**Files:**
- Modify: `ocr.py:101-147` (SYSTEM_PROMPT)
- Test: `tests/test_ocr_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_ocr_prompt.py
from ocr import SYSTEM_PROMPT


def test_prompt_define_mercado_player_y_faltante():
    p = SYSTEM_PROMPT
    assert "player" in p
    # menciona las métricas por-jugador modelables
    assert "goal_or_assist" in p and "assist" in p
    # instruye marcar tiros al arco por jugador como faltante
    assert "faltante" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ocr_prompt.py::test_prompt_define_mercado_player_y_faltante -v`
Expected: FAIL (assert "player" / "faltante")

- [ ] **Step 3: Edit the prompt**

En `ocr.py`: en la regla 3 añadir `player` a la lista de mercados. Reemplazar la regla 4c (que hoy manda goleador/asistencias a `exotic`) por la familia player:

```
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, resultado_exacto, count, player, exotic
```

```
4c. MERCADO "player" (props de jugador individual). Rellena además "player", "metric", "umbral":
    - "player": nombre del jugador tal cual aparece (ej "Bruno Fernandes", "Lionel Messi")
    - "metric": "goal" (anota/marca gol) | "assist" (da asistencia) |
                "goal_or_assist" (anota o asiste) | "sot" (tiros/remates al arco del jugador)
    - "umbral": el número mínimo de eventos (ej "2+ tiros al arco" -> 2 ; "anota" -> 1)
    - "seleccion": "yes" ; "faltante": true SOLO si metric=="sot" (tiros al arco por jugador,
      mercado conocido pero aún no modelable). Para goal/assist/goal_or_assist, "faltante": false.
    Ejemplos: "Lionel Messi 1+ Tiros al Arco" -> player/sot/umbral 1/faltante true ;
              "Bruno Fernandes anota o da una asistencia" -> player/goal_or_assist/umbral 1/faltante false ;
              "Cristiano Ronaldo marca" -> player/goal/umbral 1/faltante false
4d. CLASIFICA COMO "exotic" SOLO lo no modelable que NO sea de jugador: goles/eventos de
    PRIMER o SEGUNDO TIEMPO, minuto del gol, córners/faltas por equipo no listados arriba.
```

Y en el FORMATO DE SALIDA añadir los campos al ejemplo:

```
      "metric": null,
      "scope": null,
      "player": null,
      "umbral": 1,
      "faltante": false
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ocr_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ocr.py tests/test_ocr_prompt.py
git commit -m "feat: OCR clasifica props de jugador (player) + sot como faltante"
```

---

## Task 10: Betbuilder — ruteo de la familia `player` y faltantes

**Files:**
- Modify: `betbuilder.py` (constantes, `player_leg_prob`, `analyze_bet_builder`)
- Test: `tests/test_betbuilder.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_betbuilder.py
from betbuilder import player_leg_prob, PLAYER_MARKET
from player_model import PlayerModel

PM = PlayerModel.from_params({
    "metricas": ["goal", "assist"],
    "jugadores": {"p2": {"nombre": "Bruno Fernandes", "equipo": "Portugal",
                         "cuota_gol": 0.15, "cuota_asist": 0.30}},
})


class _Sel:   # stub mínimo de ValidatedSelection
    def __init__(self, **kw):
        self.mercado = PLAYER_MARKET
        self.player = kw.get("player")
        self.metric = kw.get("metric")
        self.umbral = kw.get("umbral", 1)
        self.faltante = kw.get("faltante", False)


def test_player_leg_prob_resuelve_y_calcula():
    sel = _Sel(player="B. Fernandes", metric="goal_or_assist")
    # λ del equipo del jugador = lh (Portugal local) = 1.6
    p = player_leg_prob(PM, sel, lh=1.6, la=0.5, home="Portugal", away="Uzbekistan")
    import math
    assert abs(p - (1 - math.exp(-1.6 * (0.15 + 0.30)))) < 1e-9


def test_player_leg_prob_none_si_no_resuelve():
    sel = _Sel(player="Jugador Inexistente", metric="goal")
    assert player_leg_prob(PM, sel, 1.6, 0.5, "Portugal", "Uzbekistan") is None


def test_player_leg_prob_none_si_faltante():
    sel = _Sel(player="B. Fernandes", metric="sot", faltante=True)
    assert player_leg_prob(PM, sel, 1.6, 0.5, "Portugal", "Uzbekistan") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_betbuilder.py -v`
Expected: FAIL (`cannot import name 'player_leg_prob'`)

- [ ] **Step 3: Add `player_leg_prob` and the constant**

En `betbuilder.py`, tras `COUNT_MARKET`:

```python
PLAYER_MARKET = "player"   # props por-jugador (anota/asiste); sot va como faltante


def player_leg_prob(model, sel, lh, la, home, away) -> float | None:
    """Marginal de una pata player vía Poisson top-down. None si: es faltante,
    no hay modelo, el nombre no resuelve, la métrica no está gateada, o no se
    puede ubicar al jugador en el partido (sin λ de su equipo)."""
    from rapidfuzz import fuzz
    if model is None or sel.faltante or not sel.player:
        return None
    pid = model.resolver(sel.player)
    if pid is None or not model.tiene(pid, sel.metric):
        return None
    equipo = model.equipo_de(pid)
    # ubicar al jugador en local/visitante por su equipo (fuzzy contra home/away)
    s_home = fuzz.token_set_ratio(equipo.lower(), home.lower())
    s_away = fuzz.token_set_ratio(equipo.lower(), away.lower())
    if max(s_home, s_away) < 60:
        return None
    lam = lh if s_home >= s_away else la
    return model.prob(pid, sel.metric, lam, umbral=sel.umbral)
```

- [ ] **Step 4: Run unit tests for the helper**

Run: `python -m pytest tests/test_betbuilder.py -k player_leg_prob -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write the failing routing test**

```python
# append to tests/test_betbuilder.py
from betbuilder import analyze_bet_builder
from validator import ValidatedParlay, ValidatedSelection, TeamMatch


def _tm(name):
    return TeamMatch(raw=name, canonical=name, equipo_id=name[:2].upper(),
                     score=1.0, status="MATCHED")


def test_player_baja_exoticas_y_faltante_se_etiqueta():
    sels = [
        ValidatedSelection(
            equipo_local_raw="Portugal", equipo_visitante_raw="Uzbekistan",
            mercado="player", seleccion="yes", cuota=None, linea=None,
            local_match=_tm("Portugal"), visitante_match=_tm("Uzbekistan"),
            prob_implicita=None, mercado_exotico=False,
            player="Bruno Fernandes", metric="goal_or_assist", umbral=1, faltante=False),
        ValidatedSelection(
            equipo_local_raw="Portugal", equipo_visitante_raw="Uzbekistan",
            mercado="player", seleccion="yes", cuota=None, linea=None,
            local_match=_tm("Portugal"), visitante_match=_tm("Uzbekistan"),
            prob_implicita=None, mercado_exotico=False,
            player="Cristiano Ronaldo", metric="sot", umbral=2, faltante=True),
    ]
    parlay = ValidatedParlay(selecciones=sels, cuota_total=3.5, casa_apuestas="Betano")
    res = analyze_bet_builder(parlay, lh=1.6, la=0.5, rho=-0.1,
                              version_modelo="intl_v0.1", margin=0.06,
                              player_model=PM, neutral=True)
    # la pata goal_or_assist es modelable; la faltante NO
    assert res.n_modelables == 1
    assert res.n_exoticas == 1
    assert any("Ronaldo" in d for d in res.faltantes_desc)
```

> Firmas verificadas contra `validator.py`: `TeamMatch(raw, canonical, equipo_id, score, status)`, `ValidatedParlay(selecciones, cuota_total, casa_apuestas, ...)`, `ValidatedSelection(... metric, scope, player, umbral, faltante)`.

- [ ] **Step 6: Run to verify it fails**

Run: `python -m pytest tests/test_betbuilder.py -k player_baja_exoticas -v`
Expected: FAIL (`analyze_bet_builder() got an unexpected keyword argument 'player_model'` y/o `faltantes_desc` inexistente)

- [ ] **Step 7: Add dataclass fields (analyzer.py) then wire routing (betbuilder.py)**

Primero, en `analyzer.py` añadir los campos que la rama de ruteo va a poblar
(necesarios para que el test del Step 5 pase). En `SelectionAnalysis`, como último
campo opcional:

```python
    faltante:             bool = False
```

En `ParlayAnalysis`, junto a `exoticas_desc`:

```python
    faltantes_desc:       list[str] = field(default_factory=list)
```

Luego, en `betbuilder.py`, firma:

```python
def analyze_bet_builder(parlay, lh, la, rho, version_modelo: str, margin: float,
                        counts_model=None, neutral: bool = False, player_model=None):
```

En el loop de selecciones, junto a `is_count`:

```python
        is_count = sel.mercado == COUNT_MARKET
        is_player = sel.mercado == PLAYER_MARKET
        count_p = count_leg_prob(counts_model, sel, c_home, c_away, neutral) if is_count else None
        player_p = (player_leg_prob(player_model, sel, lh, la, c_home, c_away)
                    if (is_player and covered) else None)
```

Añadir las ramas (tras la rama `elif is_count and count_p is not None:`):

```python
        elif is_player and player_p is not None:
            prob_mod = round(player_p, 6)
            count_marginals.append(player_p)   # entra al techo/estimada como una marginal más
            nivel_cov, alertas = "MEDIA", ["Mercado de jugador: marginal Poisson top-down."]
        elif is_player and sel.faltante:
            prob_mod = None
            faltantes_desc.append(sel.player or sel.seleccion)
            nivel_cov, alertas = "NULA", ["Mercado conocido pero sin datos: tiros al arco por jugador (pendiente)."]
```

Inicializar `faltantes_desc = []` junto a `exoticas_desc = []`; al construir cada `SelectionAnalysis` pasar `faltante=(sel.mercado == PLAYER_MARKET and sel.faltante)`; y pasar `faltantes_desc=faltantes_desc` al construir el `ParlayAnalysis`. Las patas faltantes ya cuentan en `n_exoticas` porque no entran en `n_modelables` (la fórmula `n_exoticas = len(selecciones) - n_modelables` las incluye).

- [ ] **Step 8: Run all betbuilder tests**

Run: `python -m pytest tests/test_betbuilder.py -v`
Expected: PASS (nuevos + previos verdes)

- [ ] **Step 9: Commit**

```bash
git add betbuilder.py tests/test_betbuilder.py
git commit -m "feat: betbuilder rutea familia player + etiqueta patas faltantes"
```

---

## Task 11: Analyzer — `_load_player_model`, campos y wiring

**Files:**
- Modify: `analyzer.py` (SelectionAnalysis, ParlayAnalysis, `_load_player_model`, `analyze_bet_builder` call site ~768-797, construcción de SelectionAnalysis en betbuilder)
- Test: `tests/test_analyzer_betbuilder.py`

> Los campos `SelectionAnalysis.faltante` y `ParlayAnalysis.faltantes_desc` ya se
> añadieron en Task 10 (Step 7). Esta tarea solo agrega el loader y el wiring.

- [ ] **Step 2: Write the failing test**

```python
# append to tests/test_analyzer_betbuilder.py
from analyzer import _load_player_model


def test_load_player_model_devuelve_none_sin_params(monkeypatch):
    # con liga inexistente, devuelve None sin reventar (mismo contrato que counts)
    assert _load_player_model("Liga Que No Existe XYZ") is None
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_analyzer_betbuilder.py::test_load_player_model_devuelve_none_sin_params -v`
Expected: FAIL (`cannot import name '_load_player_model'`)

- [ ] **Step 4: Implement `_load_player_model` (espejo de `_load_counts_model`)**

En `analyzer.py`, junto a `_load_counts_model`:

```python
_cached_player_model: dict = {}


def _load_player_model(liga_nombre: str):
    """Carga el PlayerModel de una liga desde parametros_modelo (player_v0.1).
    None si no hay params (mismo contrato que _load_counts_model)."""
    import json
    from player_model import PlayerModel
    if liga_nombre in _cached_player_model:
        return _cached_player_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_player_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo")
            .select("notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", "player_v0.1")
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_player_model[liga_nombre] = None
        return None
    model = PlayerModel.from_params(json.loads(rows[0]["notas"]))
    _cached_player_model[liga_nombre] = model
    return model
```

- [ ] **Step 5: Wire into the bet-builder analysis call**

En `analyzer.py` (~768-797), para la rama internacional, cargar el player model y pasarlo:

```python
    if liga == "internacional":
        model = _load_intl_predictor()
        rho, version = model.rho, "intl_v0.1"
        counts = _load_counts_model("Internacional")
        player = _load_player_model("Internacional")
        ...
    else:
        ...
        counts = _load_counts_model("Liga 1 Peruana")
        player = _load_player_model("Liga 1 Peruana")
        ...

    return analyze_bet_builder(parlay, lh, la, rho, version, margin,
                               counts_model=counts, neutral=neutral_flag,
                               player_model=player)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_analyzer_betbuilder.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite (regression gate)**

Run: `python -m pytest -q`
Expected: todos verdes (los 183 previos + los nuevos).

- [ ] **Step 8: Commit**

```bash
git add analyzer.py tests/test_analyzer_betbuilder.py
git commit -m "feat: analyzer carga PlayerModel y lo rutea; campos faltante/faltantes_desc"
```

---

## Task 12: Frontend — pata player + sección de faltantes

**Files:**
- Modify: `frontend/src/components/SelectionCard.jsx`
- Modify: el componente padre que renderiza la lista (donde hoy se muestran "PATAS NO MODELADAS") — buscar `exoticas_desc` en `frontend/src`.

- [ ] **Step 1: Add player label and faltante badge in SelectionCard**

En `SelectionCard.jsx`, añadir la etiqueta del mercado player y mostrar el nombre del jugador:

```jsx
const MERCADO_LABEL = {
  '1X2': '1X2', over_under: 'Más/Menos', btts: 'Ambos marcan',
  handicap: 'Hándicap', count: 'Conteo', player: 'Jugador', exotic: 'Exótico',
}
```

Dentro del header, tras el matchup, si `sel.faltante` mostrar un badge "datos pendientes":

```jsx
            {sel.faltante && (
              <span className="badge-cob nula" title="Mercado conocido, datos pendientes">
                pendiente
              </span>
            )}
```

Y si la pata es de jugador, mostrar el nombre bajo el matchup:

```jsx
          {sel.mercado === 'player' && sel.player && (
            <div className="sel-player">{sel.player}</div>
          )}
```

- [ ] **Step 2: Render faltantes in the parent (junto a exóticas)**

En el componente que lista `exoticas_desc` (buscar con `grep -r exoticas_desc frontend/src`), añadir una sección análoga para `faltantes_desc` con copy "Datos pendientes (no modelable aún)":

```jsx
{analisis.faltantes_desc?.length > 0 && (
  <div className="faltantes-box">
    <h4>Datos pendientes ({analisis.faltantes_desc.length})</h4>
    <ul>{analisis.faltantes_desc.map((d, i) => <li key={i}>{d}</li>)}</ul>
    <p className="hint">Mercado conocido (tiros al arco por jugador) aún sin fuente de datos.</p>
  </div>
)}
```

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: build sin errores.

- [ ] **Step 4: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): SelectionCard muestra pata player y seccion de faltantes"
```

---

## Task 13: Verificación e2e (BET5) + memoria

**Files:** ninguno (verificación manual) salvo actualización de memoria.

- [ ] **Step 1: Arrancar backend + frontend**

Run (backend): `python -m uvicorn main:app --reload`
Run (frontend): `cd frontend && npm run dev`

- [ ] **Step 2: Analizar BET5.jpeg vía el flujo real (o ?demo)**

Subir `BET5.jpeg`. Verificar en pantalla:
- "Bruno Fernandes — anota o asiste" aparece como **modelable** con su % (ya no exótica).
- "Cristiano Ronaldo — Tiros al Arco" aparece en **"Datos pendientes"** (no en exóticas).
- `n_exoticas` bajó respecto a tratar todo como exótico; el veredicto/confianza son coherentes.

- [ ] **Step 3: Screenshot de verificación (para Angel)**

Guardar captura como `resultadoBET5.png` en la raíz (como las otras de verificación visual).

- [ ] **Step 4: Actualizar memoria**

Actualizar `project_capa2_subproyecto_b.md` / crear `project_capa2_modelo_por_jugador.md` con el resultado del gate (qué métricas pasaron) y el estado e2e. Añadir línea en `MEMORY.md`.

- [ ] **Step 5: Commit + push**

```bash
git add resultadoBET5.png
git commit -m "docs: verificacion visual e2e modelo por-jugador (BET5)"
git push origin master
```

---

## Notas de ejecución
- Tareas 4 y 5 dependen del scrape real; si `enumerar_event_ids`/`TOURNAMENTS` no son los símbolos exactos de `download_flashscore_stats.py`, ajustar imports a los reales (es el ÚNICO acoplamiento a ese módulo).
- El gate (Task 6) puede fallar para `assist`. Si solo pasa `goal`, se publica solo `goal` y `goal_or_assist` queda no disponible (PlayerModel.tiene lo refleja). Es resultado válido, no bloquea el resto.
- Regla de oro en cada commit que toque motor/validator/ocr/analyzer: `python -m pytest -q` verde antes de commitear.
