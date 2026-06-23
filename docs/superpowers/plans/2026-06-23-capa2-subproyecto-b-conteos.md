# Sub-proyecto B · Modelo de conteos (córners/tarjetas/tiros) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modelar córners/tarjetas/tiros/tiros-al-arco desde `estadisticas_flashscore` con shrinkage por equipo, e integrarlos al motor de bet builder como segunda familia ("count") para que dejen de contar como patas exóticas.

**Architecture:** Modelo multiplicativo ataque/defensa por equipo estimado por método de momentos con shrinkage empírico-Bayes (robusto a la muestra fina del Mundial), distribución Poisson para over/under (closed-form). Ajuste offline con gate por (métrica, liga); params congelados en Supabase `parametros_modelo`; el motor combina familias por techo conservador (min) + estimado por independencia. Espejo del patrón intl (`engine_intl_v01.py` → `load_intl_to_supabase.py` → `analyzer._load_intl_predictor`).

**Tech Stack:** Python 3.12, numpy, scipy.stats.poisson, supabase-py, pytest. Sin red en las funciones puras de `counts_model.py`.

**Spec:** `docs/superpowers/specs/2026-06-23-capa2-subproyecto-b-conteos-design.md`

**Regla de oro:** la suite actual (172 tests) sigue verde; el motor de goles no cambia su comportamiento; el contrato externo de la API no cambia.

---

## Estructura de archivos

- **Create** `counts_model.py` — funciones puras de estimación (shrinkage) + clase `CountsModel` (λ por métrica, Poisson over/under). Sin red.
- **Create** `fit_counts_model.py` — ajuste offline + gate por (métrica, liga) + reporte. Lee `estadisticas_flashscore`.
- **Create** `load_counts_to_supabase.py` — persiste params gateados en `parametros_modelo` (version `counts_v0.1`).
- **Create** `tests/test_counts_model.py` — TDD de las funciones puras.
- **Modify** `betbuilder.py` — familia COUNT, techo=min entre familias, estimado por independencia, `prob_estimada`.
- **Modify** `analyzer.py` — `prob_estimada` en `ParlayAnalysis`; `_load_counts_model`; pasar el modelo a `analyze_bet_builder`; ruteo de mercados count.
- **Modify** `ocr.py` — el prompt emite mercados count estructurados en vez de `"exotic"`.
- **Modify** `tests/test_analyzer_betbuilder.py` — cobertura de la familia count en el motor.

**Métricas y columnas** (de `estadisticas_flashscore`): `corners`, `crd_y` (tarjetas), `sh` (tiros), `sot` (tiros al arco). Cada fila es partido-equipo con `es_local`, `equipo_id`, `equipo_flashscore`, `liga`, `fecha`. Para un partido, el valor "en contra" de un equipo = el valor "a favor" de la otra fila del mismo `event_id`.

**Convención de claves del modelo:** internamente las métricas se nombran `corners|cards|shots|sot`. El mapeo de columna CSV→métrica: `{"corners":"corners", "crd_y":"cards", "sh":"shots", "sot":"sot"}`.

---

### Task 1: `counts_model` — estimación con shrinkage (función pura, TDD)

Estima, para una métrica y una lista de partidos, los multiplicadores de ataque/defensa por equipo con regresión a la media (shrinkage por nº de partidos), y las bases local/visitante de la liga.

**Files:**
- Create: `counts_model.py`
- Test: `tests/test_counts_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_counts_model.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from counts_model import estimar_metrica

# 4 partidos, equipos A,B,C,D. A genera muchos corners de local; D pocos.
# Cada partido = dict {home, away, val_home, val_away}.
PARTIDOS = [
    {"home": "A", "away": "B", "val_home": 10, "val_away": 4},
    {"home": "A", "away": "C", "val_home": 8,  "val_away": 5},
    {"home": "B", "away": "A", "val_home": 5,  "val_away": 7},
    {"home": "D", "away": "C", "val_home": 2,  "val_away": 6},
]


def test_estimar_metrica_bases_y_multiplicadores():
    est = estimar_metrica(PARTIDOS, k=2.0)
    # base local = media de val_home; base visitante = media de val_away
    assert round(est["base_home"], 4) == round((10 + 8 + 5 + 2) / 4, 4)
    assert round(est["base_away"], 4) == round((4 + 5 + 7 + 6) / 4, 4)
    # multiplicadores existen para cada equipo visto
    assert set(est["atk"]) == {"A", "B", "C", "D"}
    assert set(est["def"]) == {"A", "B", "C", "D"}
    # A genera por encima de la media -> atk > 1 ; D por debajo -> atk < 1
    assert est["atk"]["A"] > 1.0
    assert est["atk"]["D"] < 1.0


def test_shrinkage_acerca_a_uno_con_pocos_datos():
    # D tiene 1 solo partido: con k alto, su atk se pega a 1.0
    est_flojo = estimar_metrica(PARTIDOS, k=0.1)
    est_fuerte = estimar_metrica(PARTIDOS, k=50.0)
    assert abs(est_fuerte["atk"]["D"] - 1.0) < abs(est_flojo["atk"]["D"] - 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_counts_model.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'counts_model'`.

- [ ] **Step 3: Write minimal implementation**

```python
# counts_model.py
"""Modelo de conteos (córners/tarjetas/tiros) de la Capa 2.

Multiplicativo ataque/defensa por equipo, estimado por método de momentos con
shrinkage empírico-Bayes (robusto a muestra fina), distribución Poisson para
over/under. NO lee red al importar: funciones puras testeables.
"""

from scipy.stats import poisson

METRICAS = ("corners", "cards", "shots", "sot")
COL_A_METRICA = {"corners": "corners", "crd_y": "cards", "sh": "shots", "sot": "sot"}


def estimar_metrica(partidos: list[dict], k: float = 5.0) -> dict:
    """Estima bases de liga y multiplicadores atk/def por equipo para UNA métrica.

    partidos: lista de {home, away, val_home, val_away} (valores de la métrica).
    k: fuerza del prior de shrinkage (nº de "partidos virtuales" en la media de liga).

    Devuelve {base_home, base_away, atk:{equipo:mult}, def:{equipo:mult}}.
    El equipo promedio tiene atk=def=1.0. atk = cuánto GENERA; def = cuánto CONCEDE.
    """
    if not partidos:
        return {"base_home": 0.0, "base_away": 0.0, "atk": {}, "def": {}}

    base_home = sum(p["val_home"] for p in partidos) / len(partidos)
    base_away = sum(p["val_away"] for p in partidos) / len(partidos)
    base_home = max(base_home, 1e-6)
    base_away = max(base_away, 1e-6)

    # Ratios crudos normalizados por sede: cuánto generó/concedió un equipo
    # respecto a la base de la sede en que jugó cada partido.
    gen = {}   # equipo -> [ratios de generación]
    con = {}   # equipo -> [ratios de concesión]
    for p in partidos:
        h, a = p["home"], p["away"]
        gen.setdefault(h, []).append(p["val_home"] / base_home)
        gen.setdefault(a, []).append(p["val_away"] / base_away)
        # concede = lo que generó el rival, normalizado por la sede del rival
        con.setdefault(h, []).append(p["val_away"] / base_away)
        con.setdefault(a, []).append(p["val_home"] / base_home)

    def _shrink(ratios):
        n = len(ratios)
        return (sum(ratios) + k * 1.0) / (n + k)   # media bayesiana hacia 1.0

    atk = {t: _shrink(r) for t, r in gen.items()}
    dfn = {t: _shrink(r) for t, r in con.items()}
    return {"base_home": base_home, "base_away": base_away, "atk": atk, "def": dfn}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_counts_model.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add counts_model.py tests/test_counts_model.py
git commit -m "feat: counts_model.estimar_metrica (shrinkage atk/def por equipo)"
```

---

### Task 2: `CountsModel` — λ por métrica + Poisson over/under (función pura, TDD)

Clase que congela params (patrón `from_params`), calcula λ local/visitante por métrica y la probabilidad over/under por equipo y total.

**Files:**
- Modify: `counts_model.py`
- Test: `tests/test_counts_model.py`

- [ ] **Step 1: Write the failing test**

```python
# añadir a tests/test_counts_model.py
from counts_model import CountsModel

PARAMS = {
    "corners": {
        "base_home": 6.0, "base_away": 4.0, "factor_neutral": 1.0,
        "atk": {"A": 1.5, "B": 1.0}, "def": {"A": 1.0, "B": 1.2},
    }
}


def test_lambdas_local_visitante():
    m = CountsModel.from_params(PARAMS)
    lh, la = m.lambdas("corners", "A", "B", neutral=False)
    # lh = base_home * atk[A] * def[B] = 6 * 1.5 * 1.2 = 10.8
    assert round(lh, 4) == 10.8
    # la = base_away * atk[B] * def[A] = 4 * 1.0 * 1.0 = 4.0
    assert round(la, 4) == 4.0


def test_lambdas_neutral_usa_base_promedio():
    m = CountsModel.from_params(PARAMS)
    lh_n, la_n = m.lambdas("corners", "A", "B", neutral=True)
    # en neutral, ambas usan la base neutra (promedio de home/away = 5.0)
    assert round(lh_n, 4) == round(5.0 * 1.5 * 1.2, 4)   # 9.0
    assert round(la_n, 4) == round(5.0 * 1.0 * 1.0, 4)   # 5.0


def test_prob_over_under_equipo_y_total():
    m = CountsModel.from_params(PARAMS)
    # equipo local over 9.5: P(X>9.5) con X~Poisson(10.8)
    from scipy.stats import poisson
    p_home_over = m.prob_over_under("corners", "home", "over", 9.5, "A", "B", False)
    assert abs(p_home_over - (1 - poisson.cdf(9, 10.8))) < 1e-9
    # total over 13.5: X~Poisson(10.8+4.0=14.8)
    p_total_over = m.prob_over_under("corners", "total", "over", 13.5, "A", "B", False)
    assert abs(p_total_over - (1 - poisson.cdf(13, 14.8))) < 1e-9
    # under es complemento
    p_total_under = m.prob_over_under("corners", "total", "under", 13.5, "A", "B", False)
    assert abs(p_total_under - poisson.cdf(13, 14.8)) < 1e-9


def test_equipo_desconocido_cae_a_multiplicador_neutro():
    m = CountsModel.from_params(PARAMS)
    lh, la = m.lambdas("corners", "DESCONOCIDO", "B", neutral=False)
    # atk/def de un equipo no visto = 1.0
    assert round(lh, 4) == round(6.0 * 1.0 * 1.2, 4)   # 7.2


def test_tiene_metrica():
    m = CountsModel.from_params(PARAMS)
    assert m.tiene("corners") is True
    assert m.tiene("cards") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_counts_model.py -k "lambdas or prob_over or desconocido or tiene_metrica" -v`
Expected: FAIL con `ImportError: cannot import name 'CountsModel'`.

- [ ] **Step 3: Write minimal implementation**

```python
# añadir a counts_model.py

class CountsModel:
    """Predictor de conteos con params congelados. params: {metrica: {base_home,
    base_away, factor_neutral, atk:{equipo:mult}, def:{equipo:mult}}}.

    Solo contiene las métricas que pasaron el gate para esta liga; el motor
    consulta `tiene(metrica)` antes de usarla.
    """

    @classmethod
    def from_params(cls, params: dict) -> "CountsModel":
        m = cls()
        m.params = params
        return m

    def tiene(self, metrica: str) -> bool:
        return metrica in self.params

    def lambdas(self, metrica: str, home: str, away: str, neutral: bool) -> tuple[float, float]:
        p = self.params[metrica]
        atk, dfn = p["atk"], p["def"]
        ah = atk.get(home, 1.0)
        aa = atk.get(away, 1.0)
        dh = dfn.get(home, 1.0)
        da = dfn.get(away, 1.0)
        if neutral:
            base = 0.5 * (p["base_home"] + p["base_away"]) * p.get("factor_neutral", 1.0)
            lh = base * ah * da
            la = base * aa * dh
        else:
            lh = p["base_home"] * ah * da
            la = p["base_away"] * aa * dh
        return lh, la

    def prob_over_under(self, metrica: str, scope: str, sel: str, linea: float,
                        home: str, away: str, neutral: bool) -> float:
        """P(over/under) de la métrica en el scope dado. scope: total|home|away."""
        lh, la = self.lambdas(metrica, home, away, neutral)
        if scope == "home":
            lam = lh
        elif scope == "away":
            lam = la
        elif scope == "total":
            lam = lh + la
        else:
            raise ValueError(f"scope inválido: {scope!r}")
        # P(X > linea) con linea semientera: usa floor(linea)
        k = int(linea)            # over 9.5 -> P(X>=10) = 1 - cdf(9)
        p_over = 1.0 - poisson.cdf(k, lam)
        return p_over if sel == "over" else (1.0 - p_over)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_counts_model.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add counts_model.py tests/test_counts_model.py
git commit -m "feat: CountsModel.lambdas + prob_over_under (Poisson por metrica/scope)"
```

---

### Task 3: `fit_counts_model.py` — ajuste offline + gate por (métrica, liga)

Sin test unitario (depende de Supabase/datos). Se valida ejecutándolo y leyendo el reporte.

**Files:**
- Create: `fit_counts_model.py`

- [ ] **Step 1: Escribir el script**

```python
# fit_counts_model.py
"""Ajuste offline del modelo de conteos + gate por (métrica, liga).

Lee estadisticas_flashscore de Supabase, separa por liga, estima atk/def con
shrinkage (counts_model.estimar_metrica), valida cada métrica contra un baseline
de promedio-liga en un holdout temporal, e imprime qué (métrica, liga) pasan el
gate. NO escribe a Supabase (eso lo hace load_counts_to_supabase.py).

    python fit_counts_model.py
"""

import os
import sys
from collections import defaultdict

import numpy as np
from dotenv import load_dotenv
from scipy.stats import poisson
from supabase import create_client

from counts_model import METRICAS, COL_A_METRICA, estimar_metrica, CountsModel

# Líneas típicas de mercado para evaluar el gate (over/under TOTAL del partido).
LINEAS_GATE = {"corners": [8.5, 9.5, 10.5], "cards": [3.5, 4.5],
               "shots": [21.5, 24.5], "sot": [7.5, 8.5]}
GATE_MIN_MEJORA = 0.03
K_SHRINK = 5.0
FECHA_CORTE = "2024-06-01"   # train < corte, test >= corte (holdout temporal)


def cargar_filas():
    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    filas, paso = [], 1000
    desde = 0
    while True:
        chunk = (sb.table("estadisticas_flashscore")
                 .select("event_id,fecha,liga,equipo_flashscore,es_local,corners,crd_y,sh,sot")
                 .range(desde, desde + paso - 1).execute().data)
        filas.extend(chunk)
        if len(chunk) < paso:
            break
        desde += paso
    return filas


def a_partidos(filas, col):
    """Reconstruye partidos {home,away,val_home,val_away,fecha,liga} para una
    columna métrica, uniendo las 2 filas por event_id. Descarta valores nulos."""
    por_evento = defaultdict(dict)
    for f in filas:
        lado = "home" if f["es_local"] else "away"
        por_evento[f["event_id"]][lado] = f
    partidos = []
    for ev in por_evento.values():
        if "home" not in ev or "away" not in ev:
            continue
        vh, va = ev["home"].get(col), ev["away"].get(col)
        if vh is None or va is None:
            continue
        partidos.append({
            "home": ev["home"]["equipo_flashscore"], "away": ev["away"]["equipo_flashscore"],
            "val_home": float(vh), "val_away": float(va),
            "fecha": ev["home"]["fecha"], "liga": ev["home"]["liga"],
        })
    return partidos


def brier_ou(prob_over_list, ocurrio_over_list):
    p = np.asarray(prob_over_list)
    o = np.asarray(ocurrio_over_list, dtype=float)
    return float(np.mean((p - o) ** 2))


def evaluar(modelo_params, test, metrica, lineas, baseline=False):
    """Brier promedio sobre las líneas, en el test, para una métrica/liga."""
    m = CountsModel.from_params({metrica: modelo_params})
    briers = []
    for linea in lineas:
        probs, occ = [], []
        for p in test:
            home, away = p["home"], p["away"]
            if baseline:
                lam = modelo_params["base_home"] + modelo_params["base_away"]
                p_over = 1.0 - poisson.cdf(int(linea), lam)
            else:
                p_over = m.prob_over_under(metrica, "total", "over", linea, home, away, False)
            probs.append(p_over)
            occ.append(1.0 if (p["val_home"] + p["val_away"]) > linea else 0.0)
        briers.append(brier_ou(probs, occ))
    return float(np.mean(briers))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 64)
    print("FIT MODELO DE CONTEOS — gate por (métrica, liga)")
    print("=" * 64)
    filas = cargar_filas()
    ligas = sorted(set(f["liga"] for f in filas))
    # Agrupar las dos ligas internacionales en un solo pool "INT".
    def liga_key(lg):
        return "INT" if lg.startswith("INT-") else lg

    publicables = {}   # liga_key -> {metrica: est_params (fit sobre TODO)}
    for lk in sorted(set(liga_key(l) for l in ligas)):
        print(f"\n── Liga: {lk} ──")
        for col, metrica in COL_A_METRICA.items():
            partidos = [p for p in a_partidos(filas, col) if liga_key(p["liga"]) == lk]
            if len(partidos) < 30:
                print(f"  {metrica:8}: muestra insuficiente ({len(partidos)} partidos) — SKIP")
                continue
            train = [p for p in partidos if p["fecha"] < FECHA_CORTE]
            test  = [p for p in partidos if p["fecha"] >= FECHA_CORTE]
            if len(train) < 20 or len(test) < 10:
                print(f"  {metrica:8}: holdout chico (train {len(train)}/test {len(test)}) — SKIP")
                continue
            est = estimar_metrica(train, k=K_SHRINK)
            est["factor_neutral"] = 1.0
            lineas = LINEAS_GATE[metrica]
            bs_m = evaluar(est, test, metrica, lineas, baseline=False)
            bs_b = evaluar(est, test, metrica, lineas, baseline=True)
            mejora = (bs_b - bs_m) / bs_b if bs_b > 0 else 0.0
            ok = bs_m < bs_b and mejora >= GATE_MIN_MEJORA
            print(f"  {metrica:8}: Brier modelo={bs_m:.4f} base={bs_b:.4f} "
                  f"mejora={mejora*100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
            if ok:
                # params de PRODUCCIÓN = re-fit sobre TODOS los partidos de la liga
                prod = estimar_metrica(partidos, k=K_SHRINK)
                prod["factor_neutral"] = 1.0
                publicables.setdefault(lk, {})[metrica] = prod

    print("\n" + "=" * 64)
    for lk, metricas in publicables.items():
        print(f"  {lk}: publicables -> {sorted(metricas)}")
    if not publicables:
        print("  ⚠ NINGUNA métrica pasó el gate. Revisar datos/shrinkage antes de cargar.")
    print("=" * 64)
    return publicables


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar el fit + gate**

Run: `python fit_counts_model.py`
Expected: imprime el Brier modelo vs baseline por (métrica, liga) y qué pasa el gate. Atención a **corners** y **cards** en **INT** (criterio de éxito #1 del spec). Si nada pasa, NO seguir a Task 4: subir `K_SHRINK`, revisar líneas, o documentar que la liga no es modelable.

- [ ] **Step 3: Commit**

```bash
git add fit_counts_model.py
git commit -m "feat: fit_counts_model con gate de Brier por (metrica, liga)"
```

---

### Task 4: `load_counts_to_supabase.py` — persistir params gateados

**Files:**
- Create: `load_counts_to_supabase.py`

- [ ] **Step 1: Escribir el script**

```python
# load_counts_to_supabase.py
"""Carga los params de conteos GATEADOS a parametros_modelo (counts_v0.1).

Reusa fit_counts_model.main() (que ya corre el gate) y persiste una fila por
(liga, métrica) con los multiplicadores atk/def en attack_params/defense_params
y las bases en notas/JSON. Idempotente: borra las filas counts_v0.1 de cada liga
antes de reinsertar.

    python load_counts_to_supabase.py
"""

import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from fit_counts_model import main as fit_main

VERSION = "counts_v0.1"
# nombre de liga en `ligas` para cada liga_key del fit
LIGA_NOMBRE = {"INT": "Internacional", "Liga 1 Peru": "Liga 1"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    publicables = fit_main()
    if not publicables:
        print("Nada que cargar (ninguna métrica pasó el gate).")
        sys.exit(1)

    load_dotenv()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    ligas = {l["nombre"]: l["id"] for l in sb.table("ligas").select("id,nombre").execute().data}

    for lk, metricas in publicables.items():
        nombre = LIGA_NOMBRE.get(lk)
        liga_id = ligas.get(nombre)
        if liga_id is None:
            print(f"  ⚠ liga '{nombre}' no existe en `ligas` — SKIP {lk}")
            continue
        # idempotencia: borrar counts previos de esta liga
        (sb.table("parametros_modelo").delete()
         .eq("liga_id", liga_id).eq("version_modelo", VERSION).execute())
        for metrica, est in metricas.items():
            sb.table("parametros_modelo").insert({
                "liga_id": liga_id,
                "version_modelo": VERSION,
                "attack_params": est["atk"],
                "defense_params": est["def"],
                "is_production": True,
                "notas": json.dumps({
                    "metrica": metrica,
                    "base_home": est["base_home"], "base_away": est["base_away"],
                    "factor_neutral": est["factor_neutral"],
                }),
            }).execute()
        print(f"  {lk} ({nombre}): cargadas {sorted(metricas)}")
    print("✅ Params de conteos cargados.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar la carga**

Run: `python load_counts_to_supabase.py`
Expected: corre el gate, imprime las métricas cargadas por liga, sin error.

- [ ] **Step 3: Verificar en Supabase**

Run:
```bash
python -c "import os,json; from dotenv import load_dotenv; from supabase import create_client; load_dotenv(); sb=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_KEY']); rows=sb.table('parametros_modelo').select('liga_id,version_modelo,notas').eq('version_modelo','counts_v0.1').execute().data; print(len(rows),'filas'); [print(json.loads(r['notas'])['metrica']) for r in rows]"
```
Expected: una fila por (liga, métrica) gateada.

- [ ] **Step 4: Commit**

```bash
git add load_counts_to_supabase.py
git commit -m "feat: load_counts_to_supabase persiste params gateados (counts_v0.1)"
```

---

### Task 5: `betbuilder.py` — familia COUNT, techo=min, estimado por independencia

Integra los mercados count al motor: marginal por Poisson, techo conservador como min entre familias, y un estimado por independencia. Añade `prob_estimada` a `ParlayAnalysis`.

**Files:**
- Modify: `analyzer.py` (dataclass `ParlayAnalysis`: nuevo campo)
- Modify: `betbuilder.py`
- Test: `tests/test_analyzer_betbuilder.py`

- [ ] **Step 1: Añadir el campo `prob_estimada` a ParlayAnalysis**

En `analyzer.py`, en el dataclass `ParlayAnalysis`, tras `prob_techo: Optional[float] = None` añadir:

```python
    prob_estimada:        Optional[float] = None   # estimado por independencia (familias mezcladas)
```

- [ ] **Step 2: Write the failing test**

```python
# añadir a tests/test_analyzer_betbuilder.py
from counts_model import CountsModel

_COUNTS = CountsModel.from_params({
    "corners": {"base_home": 6.0, "base_away": 4.0, "factor_neutral": 1.0,
                "atk": {}, "def": {}},
})


def _sel(mercado, seleccion, linea=None, metric=None, scope=None):
    # helper mínimo: objeto selección con los atributos que lee betbuilder
    from types import SimpleNamespace
    lm = SimpleNamespace(canonical="A", equipo_id="A")
    vm = SimpleNamespace(canonical="B", equipo_id="B")
    return SimpleNamespace(
        mercado=mercado, seleccion=seleccion, linea=linea,
        metric=metric, scope=scope, mercado_exotico=(mercado not in ("1X2","over_under","btts","handicap","resultado_exacto","count")),
        local_match=lm, visitante_match=vm,
    )


def test_count_leg_baja_n_exoticas():
    from betbuilder import analyze_bet_builder
    from types import SimpleNamespace
    parlay = SimpleNamespace(
        cuota_total=5.0, casa_apuestas="bet365",
        selecciones=[
            _sel("1X2", "home"),
            _sel("count", "over", linea=8.5, metric="corners", scope="total"),
        ],
    )
    res = analyze_bet_builder(parlay, lh=1.6, la=1.1, rho=-0.05,
                              version_modelo="intl_v0.1", margin=0.05,
                              counts_model=_COUNTS, neutral=False)
    # la pata de córners es modelable -> 0 exóticas, 2 modelables
    assert res.n_exoticas == 0
    assert res.n_modelables == 2
    # estimado por independencia poblado
    assert res.prob_estimada is not None


def test_count_sin_modelo_cuenta_exotica():
    from betbuilder import analyze_bet_builder
    from types import SimpleNamespace
    parlay = SimpleNamespace(
        cuota_total=5.0, casa_apuestas="bet365",
        selecciones=[_sel("count", "over", linea=3.5, metric="cards", scope="total")],
    )
    # _COUNTS no tiene 'cards' -> esa métrica no está gateada -> exótica
    res = analyze_bet_builder(parlay, lh=1.6, la=1.1, rho=-0.05,
                              version_modelo="intl_v0.1", margin=0.05,
                              counts_model=_COUNTS, neutral=False)
    assert res.n_exoticas == 1
    assert res.n_modelables == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_analyzer_betbuilder.py -k "count_leg or count_sin" -v`
Expected: FAIL (`analyze_bet_builder() got an unexpected keyword argument 'counts_model'`).

- [ ] **Step 4: Implementación en `betbuilder.py`**

Añadir la constante de familia y un helper, y extender `analyze_bet_builder`.

Tras `GOAL_MARKETS = {...}` añadir:

```python
COUNT_MARKET = "count"   # mercado genérico de conteos (metric + scope en la selección)


def count_leg_prob(model, sel, home, away, neutral) -> float | None:
    """Marginal de una pata count vía Poisson. None si la métrica no está
    gateada en el modelo de esta liga (entonces la pata es exótica)."""
    if model is None or not model.tiene(sel.metric):
        return None
    return model.prob_over_under(
        sel.metric, sel.scope, sel.seleccion, sel.linea, home, away, neutral
    )
```

Reemplazar la firma y el cuerpo de clasificación de `analyze_bet_builder`. La firma pasa a:

```python
def analyze_bet_builder(parlay, lh, la, rho, version_modelo: str, margin: float,
                        counts_model=None, neutral: bool = False):
```

Dentro, tras `matrix = scoreline_matrix(...) if covered else None`, obtener nombres del partido para el modelo de conteos:

```python
    match_sel = next((s for s in parlay.selecciones if s.visitante_match), None)
    c_home = match_sel.local_match.canonical if match_sel else None
    c_away = match_sel.visitante_match.canonical if match_sel else None
```

En el bucle de selecciones, sustituir la rama de clasificación por:

```python
        is_goal = sel.mercado in GOAL_MARKETS
        is_count = sel.mercado == COUNT_MARKET
        count_p = count_leg_prob(counts_model, sel, c_home, c_away, neutral) if is_count else None

        if is_goal and covered:
            leg = (sel.mercado, sel.seleccion, sel.linea)
            prob_mod = round(marginal_prob(matrix, leg), 6)
            goal_legs.append(leg)
            nivel_cov, alertas = "ALTA", []
        elif is_count and count_p is not None:
            prob_mod = round(count_p, 6)
            count_marginals.append(count_p)
            nivel_cov, alertas = "MEDIA", ["Mercado de conteo: marginal Poisson con shrinkage."]
        else:
            prob_mod = None
            exoticas_desc.append(sel.seleccion)
            nivel_cov, alertas = "NULA", ["Mercado exótico: el modelo no puede validar esta selección."]
```

Antes del bucle, inicializar `count_marginals = []`. Tras el bucle, reemplazar el cálculo de techo/conteos:

```python
    n_modelables = len(goal_legs) + len(count_marginals)
    n_exoticas = len(parlay.selecciones) - n_modelables

    joint_goles = joint_ceiling(matrix, goal_legs) if (covered and goal_legs) else None
    partes_techo = [p for p in ([joint_goles] if joint_goles is not None else []) + count_marginals]
    ceiling = min(partes_techo) if partes_techo else None

    # estimado por independencia: producto de las familias (goles exacto × Π count)
    if partes_techo:
        prob_estimada = 1.0
        if joint_goles is not None:
            prob_estimada *= joint_goles
        for p in count_marginals:
            prob_estimada *= p
        prob_estimada = round(prob_estimada, 6)
    else:
        prob_estimada = None
```

En el `return ParlayAnalysis(...)`, añadir `prob_estimada=prob_estimada,` y mantener `prob_techo=round(ceiling, 6) if ceiling is not None else None`.

> NOTA: el bloque del marcador (`if covered and version_modelo == "intl_v0.1":`) y el `verdict(...)`/`bb_confidence(...)` se mantienen igual; ahora reciben el `n_exoticas` ya reducido por las patas count. La firma de `verdict` no cambia.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_analyzer_betbuilder.py -v`
Expected: PASS (los nuevos + los existentes del archivo).

- [ ] **Step 6: Commit**

```bash
git add betbuilder.py analyzer.py tests/test_analyzer_betbuilder.py
git commit -m "feat: familia COUNT en betbuilder (techo min + estimado por independencia)"
```

---

### Task 6: `ocr.py` — taxonomía de mercados count

El prompt del OCR clasifica córners/tarjetas/tiros como `count` estructurado en vez de `exotic`.

**Files:**
- Modify: `ocr.py`
- Test: `tests/test_ocr_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# añadir a tests/test_ocr_prompt.py
from ocr import SYSTEM_PROMPT  # el string del prompt del sistema (ocr.py:101)


def test_prompt_documenta_mercado_count():
    # el prompt debe instruir el mercado estructurado de conteos
    assert "count" in SYSTEM_PROMPT
    assert "metric" in SYSTEM_PROMPT and "scope" in SYSTEM_PROMPT
    # las 4 métricas nombradas
    for kw in ("corners", "cards", "shots", "sot"):
        assert kw in SYSTEM_PROMPT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ocr_prompt.py -k count -v`
Expected: FAIL (el prompt aún no menciona `count`/`metric`/`scope`).

- [ ] **Step 3: Editar el prompt en `ocr.py`**

En la sección de mercados del prompt (donde hoy dice clasificar córners/tarjetas/tiros como `exotic`, ~líneas 107-119), reemplazar por instrucciones del mercado `count`. Añadir al JSON de salida documentado los campos `metric` y `scope`, y la regla:

```
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, resultado_exacto, count, exotic
   - over_under: SOLO goles de partido completo (over/under de goles).
   - count: mercados de CONTEO con línea over/under. Rellena además:
       "metric": "corners" | "cards" | "shots" | "sot"
            corners=córners/tiros de esquina; cards=tarjetas (amarillas/total);
            shots=remates/tiros totales; sot=tiros/remates al arco/puerta.
       "scope": "total" (del partido) | "home" (equipo local) | "away" (equipo visitante)
       "seleccion": "over" | "under" ; "linea": el número (ej 8.5)
     Ejemplos: "Más de 9.5 córners" -> count/corners/total/over/9.5 ;
               "Tarjetas local más de 2.5" -> count/cards/home/over/2.5 ;
               "Remates al arco +7.5" -> count/sot/total/over/7.5
4b. CLASIFICA COMO "exotic" SOLO lo no modelable: goleador, asistencias, jugador
    amonestado, eventos de 1ª/2ª mitad, minuto del gol, etc.
```

Asegurar que el parser (`setdefault` ~línea 242) también haga `s.setdefault("metric", None)` y `s.setdefault("scope", None)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ocr_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ocr.py tests/test_ocr_prompt.py
git commit -m "feat: OCR clasifica cornes/tarjetas/tiros como mercado count estructurado"
```

---

### Task 7: `analyzer.py` — cargar modelo de conteos y rutearlo

Carga `CountsModel` desde `parametros_modelo` y lo pasa al motor; rutea la liga correcta.

**Files:**
- Modify: `analyzer.py`

- [ ] **Step 1: Loader del modelo de conteos**

Tras `_load_intl_predictor()` (~línea 528) añadir:

```python
_cached_counts_model: dict[str, "CountsModel"] = {}


def _load_counts_model(liga_nombre: str):
    """Carga el CountsModel de una liga desde parametros_modelo (counts_v0.1).
    liga_nombre: 'Internacional' | 'Liga 1'. Devuelve None si no hay params."""
    import json
    from counts_model import CountsModel
    if liga_nombre in _cached_counts_model:
        return _cached_counts_model[liga_nombre]
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        _cached_counts_model[liga_nombre] = None
        return None
    rows = (sb.table("parametros_modelo")
            .select("attack_params,defense_params,notas")
            .eq("liga_id", liga[0]["id"]).eq("version_modelo", "counts_v0.1")
            .eq("is_production", True).execute().data)
    if not rows:
        _cached_counts_model[liga_nombre] = None
        return None
    params = {}
    for r in rows:
        meta = json.loads(r["notas"])
        params[meta["metrica"]] = {
            "base_home": meta["base_home"], "base_away": meta["base_away"],
            "factor_neutral": meta["factor_neutral"],
            "atk": r["attack_params"], "def": r["defense_params"],
        }
    model = CountsModel.from_params(params)
    _cached_counts_model[liga_nombre] = model
    return model
```

> `create_client` y `os` ya están importados en `analyzer.py` (líneas 28 y cabecera); `HOSTS_2026` existe (línea 44). Es el mismo patrón inline que usan `_load_intl_predictor` y `_load_and_fit`.

- [ ] **Step 2: Pasar el modelo y `neutral` a `analyze_bet_builder`**

En `_analyze_bet_builder_route` (~línea 723), antes del `return`, calcular el modelo de conteos y el flag neutral, y pasarlos:

```python
    if liga == "internacional":
        counts = _load_counts_model("Internacional")
        neutral_flag = bool(match_sel) and (match_sel.local_match.canonical not in HOSTS_2026)
    else:
        counts = _load_counts_model("Liga 1")
        neutral_flag = False

    return analyze_bet_builder(parlay, lh, la, rho, version, margin,
                               counts_model=counts, neutral=neutral_flag)
```

(El bloque que calcula `lh, la, rho, version` se mantiene; solo se añaden estas líneas y se cambia el `return`.)

- [ ] **Step 3: Run the suite**

Run: `python -m pytest -q`
Expected: todo verde (172 previos + nuevos). Si una selección count llega sin `metric`/`scope` (boleto viejo), `count_leg_prob` la trata como exótica (no rompe).

- [ ] **Step 4: Commit**

```bash
git add analyzer.py
git commit -m "feat: analyzer carga CountsModel y lo rutea al motor de bet builder"
```

---

### Task 8: Verificación end-to-end

**Files:** ninguno (verificación).

- [ ] **Step 1: Suite completa verde**

Run: `python -m pytest -q`
Expected: `>= 181 passed` (172 previos + ~9 nuevos), sin regresiones.

- [ ] **Step 2: Smoke test del flujo de conteos**

Run:
```bash
python -c "
from counts_model import CountsModel
m = CountsModel.from_params({'corners': {'base_home':6.0,'base_away':4.0,'factor_neutral':1.0,'atk':{'Francia':1.3},'def':{'Croacia':1.1}}})
print('lambda Francia-Croacia corners:', m.lambdas('corners','Francia','Croacia',neutral=True))
print('P(total corners > 9.5):', round(m.prob_over_under('corners','total','over',9.5,'Francia','Croacia',True),3))
print('tiene cards?', m.tiene('cards'))
"
```
Expected: imprime λ y una probabilidad razonable (0<p<1); `tiene cards? False`.

- [ ] **Step 3: Releer el reporte del gate (Task 3) y documentar**

Confirmar qué (métrica, liga) quedaron modelables. Criterio de éxito #1: córners y tarjetas en INT. Si alguna métrica clave NO pasó, anotarlo (queda exótica para esa liga; no es bug, es honestidad del gate).

- [ ] **Step 4: Commit (si se añadió nota/doc)**

```bash
git add -A
git commit -m "docs: reporte de gate del modelo de conteos (Sub-proyecto B)"
```

---

## Notas de implementación

- **Sin red en `counts_model.py`** — solo `scipy.stats.poisson`. Testeable sin Supabase.
- **Reusa el patrón intl:** fit offline → gate → `parametros_modelo` → `from_params` congelado en warm-up. NO se reajusta por request.
- **Pool INT:** Mundial + Euro comparten params (liga `Internacional`), igual que el modelo de goles intl. Liga 1 va por su lado.
- **`neutral`:** en INT, neutral=True salvo que el local sea sede 2026 (`HOSTS_2026`, ya existe en analyzer). En Liga 1 siempre False.
- **Techo = cota superior:** `min` entre familias preserva el "cero falsos positivos"; el `verdict` existente no cambia de firma. El `estimado` es informativo, NO altera el veredicto.
- **Compatibilidad OCR:** selecciones viejas (`exotic`) o count sin `metric`/`scope` caen al path exótico sin romper.
- **Gate honesto:** una métrica que no vence al baseline en una liga queda fuera para esa liga (su pata sigue contando exótica). Es correcto, no una falla.
- **Líneas del gate** (`LINEAS_GATE`) son aproximaciones de mercado; si una métrica queda muy cerca del umbral, revisar líneas reales de las casas antes de subir `K_SHRINK` o pasar a Negative Binomial.
