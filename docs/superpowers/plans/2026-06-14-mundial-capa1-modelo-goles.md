# Mundial Capa 1 (Modelo de Goles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir y validar (vía Brier vs baseline) un modelo Dixon-Coles de goles para selecciones nacionales, y cargarlo a Supabase solo si supera el gate.

**Architecture:** `engine_intl_v01.py` espejea `engine_v02.py` pero ajusta desde un CSV (no Supabase) y condiciona la ventaja de local `gamma` al flag `neutral` de cada partido. Un gate de Brier decide si se ejecuta la carga a Supabase. No se toca el motor de Liga 1.

**Tech Stack:** Python 3.12, numpy, scipy (`minimize`, `poisson`), requests, supabase, pytest. Todo ya instalado.

---

## Estructura de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `download_intl_results.py` | Descarga CSV martj42, filtra 2018+ con marcador, guarda `intl_results.csv` local |
| Crear | `engine_intl_v01.py` | Dixon-Coles con `neutral`, ajuste desde CSV, Brier vs baseline, veredicto |
| Crear | `tests/test_engine_intl.py` | Tests de funciones puras del motor |
| Crear | `load_intl_to_supabase.py` | (Gated) DDL + carga equipos/partidos/parámetros |

**Sin tocar:** `engine_v02.py`, `analyzer.py`, `validator.py`, `main.py`, `resolver.py`, frontend.

**Representación interna de un partido** (producida por el loader del CSV, consumida por el motor):
```python
{
    "home": str,            # nombre selección local (ej. "France")
    "away": str,            # nombre selección visitante
    "gl": int,              # goles local
    "gv": int,              # goles visitante
    "fecha": str,           # ISO "YYYY-MM-DD"
    "neutral": bool,        # True si cancha neutral (sin ventaja de local)
    "resultado": str,       # "HOME" | "DRAW" | "AWAY"
}
```

---

## Task 1: `download_intl_results.py` — descargar y filtrar el dataset

**Files:**
- Create: `download_intl_results.py`

- [ ] **Step 1: Crear `download_intl_results.py`**

```python
"""
Descarga el dataset abierto martj42/international_results y lo filtra a los
partidos relevantes para el modelo de selecciones (2018+ con marcador no nulo).
Guarda una copia local en intl_results.csv.
"""

import csv
import io
import sys

import requests

CSV_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DESDE = "2018-01-01"
SALIDA = "intl_results.csv"


def descargar_filtrar(url=CSV_URL, desde=DESDE, salida=SALIDA):
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    filtrados = []
    for r in rows:
        if r["date"] < desde:
            continue
        if r["home_score"] == "" or r["away_score"] == "":
            continue
        filtrados.append(r)

    with open(salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(filtrados)

    return len(rows), len(filtrados)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    total, n = descargar_filtrar()
    print(f"Descargados {total} partidos, {n} tras filtrar (>= {DESDE}, con marcador).")
    print(f"Guardado en {SALIDA}")
```

- [ ] **Step 2: Ejecutar y verificar la descarga**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python download_intl_results.py`
Expected: imprime algo como `Descargados 49xxx partidos, 4xxx tras filtrar...` y crea `intl_results.csv`.

- [ ] **Step 3: Verificar el archivo**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python -c "import csv; rows=list(csv.DictReader(open('intl_results.csv',encoding='utf-8'))); print('filas:', len(rows)); print('cols:', list(rows[0].keys())); print('min fecha:', min(r['date'] for r in rows))"`
Expected: `cols` incluye `date, home_team, away_team, home_score, away_score, tournament, city, country, neutral`; `min fecha` >= 2018-01-01.

- [ ] **Step 4: Asegurar que el CSV no se commitee**

Agregar `intl_results.csv` a `.gitignore` (es un artefacto de datos, no código). Verificar que no aparezca en `git status`.

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && echo "intl_results.csv" >> .gitignore && git status --short`
Expected: `intl_results.csv` NO aparece como untracked.

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add download_intl_results.py .gitignore && git commit -m "feat: add international results downloader for Mundial model"
```

---

## Task 2: `engine_intl_v01.py` — funciones puras (tau, time_weight, brier) + loader CSV

**Files:**
- Create: `engine_intl_v01.py`
- Create: `tests/test_engine_intl.py`

- [ ] **Step 1: Escribir los tests de las funciones puras**

Crear `tests/test_engine_intl.py`:

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine_intl_v01 import tau, brier_score, cargar_csv


def test_tau_caso_neutro():
    # marcadores que no son 0-0/1-0/0-1/1-1 devuelven 1.0
    assert tau(3, 2, 1.5, 1.2, -0.05) == 1.0

def test_tau_0_0():
    # 1 - lh*la*rho con rho negativo => > 1
    assert tau(0, 0, 1.5, 1.2, -0.05) > 1.0

def test_tau_1_1():
    # 1 - rho con rho negativo => > 1
    assert tau(1, 1, 1.5, 1.2, -0.05) == 1 - (-0.05)


def test_brier_prediccion_perfecta_es_cero():
    preds = [(1.0, 0.0, 0.0, "HOME"), (0.0, 0.0, 1.0, "AWAY")]
    assert brier_score(preds) == 0.0

def test_brier_un_tercio():
    # 1/3,1/3,1/3 siempre => Brier = (2/3)/... valor conocido ~0.2222
    preds = [(1/3, 1/3, 1/3, "HOME")]
    bs = brier_score(preds)
    assert abs(bs - 0.2222) < 0.001


def test_cargar_csv_normaliza(tmp_path):
    csv_content = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2019-06-01,France,Brazil,2,1,Friendly,Paris,France,FALSE\n"
        "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,TRUE\n"
    )
    p = tmp_path / "mini.csv"
    p.write_text(csv_content, encoding="utf-8")
    partidos = cargar_csv(str(p))
    assert len(partidos) == 2
    m0 = partidos[0]
    assert m0["home"] == "France"
    assert m0["gl"] == 2 and m0["gv"] == 1
    assert m0["neutral"] is False
    assert m0["resultado"] == "HOME"
    m1 = partidos[1]
    assert m1["neutral"] is True
    assert m1["resultado"] == "DRAW"
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -v`
Expected: `ModuleNotFoundError: No module named 'engine_intl_v01'`

- [ ] **Step 3: Crear `engine_intl_v01.py` con las funciones puras y el loader**

```python
"""
Motor Estadistico Internacional v0.1 — Dixon-Coles para selecciones.
Espejea engine_v02.py pero:
  - Ajusta desde un CSV (martj42/international_results), no Supabase.
  - La ventaja de local (gamma) solo aplica cuando neutral == False.

Train: 2018-2024 | Test: 2025+
Gate: superar al baseline ingenuo (tasas globales neutral-aware) por >= 3% relativo.
"""

import csv
import math
import warnings
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

warnings.filterwarnings("ignore")

MAX_GOALS = 10
XI = 0.004   # mismo decay que Liga 1 v0.2
CSV_PATH = "intl_results.csv"
TRAIN_HASTA = "2024-12-31"
TEST_DESDE = "2025-01-01"


# ── Loader CSV ────────────────────────────────────────────────────────────────

def cargar_csv(path=CSV_PATH):
    """Lee el CSV filtrado y devuelve la lista de partidos normalizados."""
    partidos = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        gl = int(r["home_score"])
        gv = int(r["away_score"])
        if gl > gv:
            res = "HOME"
        elif gl == gv:
            res = "DRAW"
        else:
            res = "AWAY"
        partidos.append({
            "home":      r["home_team"],
            "away":      r["away_team"],
            "gl":        gl,
            "gv":        gv,
            "fecha":     r["date"],
            "neutral":   r["neutral"].strip().upper() == "TRUE",
            "resultado": res,
        })
    return partidos


# ── Time weighting ────────────────────────────────────────────────────────────

def time_weight(fecha_str, ref_date, xi=XI):
    dt = datetime.fromisoformat(fecha_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (ref_date - dt).days)
    return math.exp(-xi * days)


# ── Dixon-Coles correction ────────────────────────────────────────────────────

def tau(x, y, lh, la, rho):
    if x == 0 and y == 0:
        return max(1e-10, 1 - lh * la * rho)
    elif x == 1 and y == 0:
        return 1 + la * rho
    elif x == 0 and y == 1:
        return 1 + lh * rho
    elif x == 1 and y == 1:
        return max(1e-10, 1 - rho)
    return 1.0


# ── Brier Score (normalizado 0-1) ─────────────────────────────────────────────

def brier_score(predictions):
    total = 0.0
    for ph, pd, pa, result in predictions:
        o_h = 1.0 if result == "HOME" else 0.0
        o_d = 1.0 if result == "DRAW" else 0.0
        o_a = 1.0 if result == "AWAY" else 0.0
        total += (ph - o_h)**2 + (pd - o_d)**2 + (pa - o_a)**2
    return (total / len(predictions)) / 2
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -v`
Expected: 6 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add engine_intl_v01.py tests/test_engine_intl.py && git commit -m "feat: add intl engine pure functions (tau, brier, csv loader)"
```

---

## Task 3: Modelo Dixon-Coles con `neutral` (fit + predict)

**Files:**
- Modify: `engine_intl_v01.py`
- Modify: `tests/test_engine_intl.py`

- [ ] **Step 1: Agregar tests de la ventaja neutral al final de `tests/test_engine_intl.py`**

Primero, agregar este import al inicio del archivo (debajo del `sys.path.insert(...)` existente):

```python
from datetime import datetime, timezone
```

Luego agregar al final del archivo:

```python
from engine_intl_v01 import DixonColesIntl


def _modelo_dos_equipos():
    # Modelo sintético: 2 partidos entre A y B, uno en casa y otro neutral,
    # suficiente para que fit() corra. Lo importante es probar lambdas/predict.
    partidos = [
        {"home": "A", "away": "B", "gl": 2, "gv": 1, "fecha": "2024-01-01",
         "neutral": False, "resultado": "HOME"},
        {"home": "B", "away": "A", "gl": 1, "gv": 1, "fecha": "2024-02-01",
         "neutral": True, "resultado": "DRAW"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    return DixonColesIntl().fit(partidos, ref), partidos


def test_predict_suma_uno():
    model, _ = _modelo_dos_equipos()
    ph, pd, pa = model.predict("A", "B", neutral=False)
    assert abs((ph + pd + pa) - 1.0) < 1e-9

def test_ventaja_neutral_reduce_lambda_home():
    model, _ = _modelo_dos_equipos()
    lh_casa, _ = model.lambdas("A", "B", neutral=False)
    lh_neutral, _ = model.lambdas("A", "B", neutral=True)
    # con gamma >= 0, el mismo local mete >= goles en casa que en neutral
    assert lh_casa >= lh_neutral

def test_lambda_away_no_cambia_con_neutral():
    model, _ = _modelo_dos_equipos()
    _, la_casa = model.lambdas("A", "B", neutral=False)
    _, la_neutral = model.lambdas("A", "B", neutral=True)
    # la ventaja de local no afecta al visitante
    assert abs(la_casa - la_neutral) < 1e-12
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -k "predict_suma_uno or ventaja_neutral or lambda_away" -v`
Expected: `ImportError: cannot import name 'DixonColesIntl'`

- [ ] **Step 3: Agregar `neg_log_likelihood` y la clase `DixonColesIntl` a `engine_intl_v01.py`**

Agregar después de `brier_score`:

```python
# ── Log-likelihood (gamma condicional a neutral) ──────────────────────────────

def neg_log_likelihood(params, matches, teams, weights, l2=0.001):
    n = len(teams)
    alphas = params[:n]
    betas  = params[n:2*n]
    mu     = params[2*n]
    gamma  = params[2*n + 1]
    rho    = params[2*n + 2]

    idx = {t: i for i, t in enumerate(teams)}
    ll  = 0.0

    for k, m in enumerate(matches):
        i = idx[m["home"]]
        j = idx[m["away"]]
        x = m["gl"]
        y = m["gv"]

        g = 0.0 if m["neutral"] else gamma
        lh = math.exp(mu + alphas[i] + betas[j] + g)
        la = math.exp(mu + alphas[j] + betas[i])

        t = tau(x, y, lh, la, rho)
        if t <= 0:
            return 1e12

        ll += weights[k] * (
            math.log(t)
            + x * math.log(lh) - lh - math.lgamma(x + 1)
            + y * math.log(la) - la - math.lgamma(y + 1)
        )

    penalty = l2 * (np.sum(alphas**2) + np.sum(betas**2))
    return -ll + penalty


# ── Modelo Dixon-Coles internacional ──────────────────────────────────────────

class DixonColesIntl:

    def fit(self, matches, ref_date):
        self.teams = sorted(set(
            [m["home"] for m in matches] + [m["away"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}

        weights = np.array([time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()

        x0 = np.zeros(2 * n + 3)
        x0[2*n]     =  0.20   # mu
        x0[2*n + 1] =  0.30   # gamma
        x0[2*n + 2] = -0.05   # rho

        bounds = (
            [(-2.0, 2.0)] * n +
            [(-2.0, 2.0)] * n +
            [(-1.0, 1.5)] +
            [( 0.0, 1.5)] +
            [(-0.5, 0.5)]
        )

        result = minimize(
            neg_log_likelihood, x0,
            args=(matches, self.teams, weights),
            method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8},
        )
        p = result.x
        self.alphas = p[:n]
        self.betas  = p[n:2*n]
        self.mu     = p[2*n]
        self.gamma  = p[2*n + 1]
        self.rho    = p[2*n + 2]
        self.converged = result.success
        self.n_iter = result.nit
        return self

    def lambdas(self, home, away, neutral):
        g = 0.0 if neutral else self.gamma
        if home in self.idx and away in self.idx:
            i, j = self.idx[home], self.idx[away]
            lh = math.exp(self.mu + self.alphas[i] + self.betas[j] + g)
            la = math.exp(self.mu + self.alphas[j] + self.betas[i])
        else:
            lh = math.exp(self.mu + g)
            la = math.exp(self.mu)
        return lh, la

    def predict(self, home, away, neutral):
        lh, la = self.lambdas(home, away, neutral)
        p_home = p_draw = p_away = 0.0
        for x in range(MAX_GOALS + 1):
            for y in range(MAX_GOALS + 1):
                p = poisson.pmf(x, lh) * poisson.pmf(y, la) * tau(x, y, lh, la, self.rho)
                if x > y:    p_home += p
                elif x == y: p_draw += p
                else:        p_away += p
        total = p_home + p_draw + p_away
        return p_home / total, p_draw / total, p_away / total
```

- [ ] **Step 4: Ejecutar todos los tests y verificar que pasan**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -v`
Expected: 9 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add engine_intl_v01.py tests/test_engine_intl.py && git commit -m "feat: add DixonColesIntl model with neutral-venue handling"
```

---

## Task 4: Baseline ingenuo + `main()` con holdout y gate de Brier

**Files:**
- Modify: `engine_intl_v01.py`
- Modify: `tests/test_engine_intl.py`

- [ ] **Step 1: Agregar test del baseline al final de `tests/test_engine_intl.py`**

```python
from engine_intl_v01 import baseline_tasas, predecir_baseline


def test_baseline_tasas_separa_neutral():
    partidos = [
        {"resultado": "HOME", "neutral": False},
        {"resultado": "HOME", "neutral": False},
        {"resultado": "AWAY", "neutral": False},
        {"resultado": "DRAW", "neutral": True},
        {"resultado": "AWAY", "neutral": True},
    ]
    tasas = baseline_tasas(partidos)
    # con local: 2 HOME, 0 DRAW, 1 AWAY -> P(home)=2/3
    assert abs(tasas[False][0] - 2/3) < 1e-9
    # neutral: 0 HOME, 1 DRAW, 1 AWAY -> P(home)=0
    assert abs(tasas[True][0] - 0.0) < 1e-9

def test_predecir_baseline_usa_neutral():
    tasas = {False: (0.5, 0.3, 0.2), True: (0.33, 0.34, 0.33)}
    assert predecir_baseline(tasas, neutral=False) == (0.5, 0.3, 0.2)
    assert predecir_baseline(tasas, neutral=True) == (0.33, 0.34, 0.33)
```

- [ ] **Step 2: Ejecutar y verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -k baseline -v`
Expected: `ImportError: cannot import name 'baseline_tasas'`

- [ ] **Step 3: Agregar el baseline y `main()` a `engine_intl_v01.py`**

Agregar después de la clase `DixonColesIntl`:

```python
# ── Baseline ingenuo (tasas globales, neutral-aware) ──────────────────────────

def baseline_tasas(train):
    """Devuelve {neutral_bool: (p_home, p_draw, p_away)} con las frecuencias del train."""
    tasas = {}
    for neutral in (False, True):
        subset = [m for m in train if m["neutral"] == neutral]
        if not subset:
            tasas[neutral] = (1/3, 1/3, 1/3)
            continue
        n = len(subset)
        h = sum(1 for m in subset if m["resultado"] == "HOME") / n
        d = sum(1 for m in subset if m["resultado"] == "DRAW") / n
        a = sum(1 for m in subset if m["resultado"] == "AWAY") / n
        tasas[neutral] = (h, d, a)
    return tasas


def predecir_baseline(tasas, neutral):
    return tasas[neutral]


# ── Main: holdout temporal + gate de Brier ────────────────────────────────────

def main():
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    print("\n" + "=" * 60)
    print("HELPBETOR — MOTOR INTERNACIONAL v0.1 (Dixon-Coles + neutral)")
    print("=" * 60)

    partidos = cargar_csv()
    train = [m for m in partidos if m["fecha"] <= TRAIN_HASTA]
    test  = [m for m in partidos if m["fecha"] >= TEST_DESDE]
    print(f"\nTrain (<= {TRAIN_HASTA}): {len(train)} partidos")
    print(f"Test  (>= {TEST_DESDE}): {len(test)} partidos")

    ref_date = datetime.fromisoformat(TEST_DESDE).replace(tzinfo=timezone.utc)

    print("\nAjustando Dixon-Coles internacional...")
    model = DixonColesIntl().fit(train, ref_date)
    print(f"  Convergio: {model.converged} | iteraciones: {model.n_iter}")
    print(f"  mu={model.mu:.4f}  gamma={model.gamma:.4f}  rho={model.rho:.4f}  xi={XI}")
    print(f"  Equipos en el modelo: {len(model.teams)}")

    # Predicciones del modelo
    preds_modelo = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = model.predict(m["home"], m["away"], m["neutral"])
        preds_modelo.append((ph, pd, pa, m["resultado"]))

    # Predicciones del baseline
    tasas = baseline_tasas(train)
    preds_baseline = []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        ph, pd, pa = predecir_baseline(tasas, m["neutral"])
        preds_baseline.append((ph, pd, pa, m["resultado"]))

    bs_modelo = brier_score(preds_modelo)
    bs_baseline = brier_score(preds_baseline)
    mejora_rel = (bs_baseline - bs_modelo) / bs_baseline

    print("\n" + "-" * 60)
    print(f"  Brier baseline (tasas neutral-aware): {bs_baseline:.4f}")
    print(f"  Brier modelo Dixon-Coles            : {bs_modelo:.4f}")
    print(f"  Mejora relativa                     : {mejora_rel*100:+.1f}%")
    print(f"  (Referencia Liga 1 v0.2 = 0.2797)")
    print("-" * 60)

    greenlight = (bs_modelo < bs_baseline) and (mejora_rel >= 0.03)
    if greenlight:
        print("  VEREDICTO: ✅ GREENLIGHT — el modelo supera el baseline (>= 3%).")
        print("  Siguiente paso: python load_intl_to_supabase.py")
    else:
        print("  VEREDICTO: ❌ NO PASA — el modelo no aporta señal suficiente.")
        print("  NO cargar a Supabase. Reconsiderar (ponderacion por torneo, ventana).")
    print("=" * 60)

    return bs_modelo, bs_baseline, model


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Ejecutar tests y verificar que pasan**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_engine_intl.py -v`
Expected: 11 tests PASSED

- [ ] **Step 5: Ejecutar el motor completo sobre los datos reales (requiere intl_results.csv de la Task 1)**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python engine_intl_v01.py`
Expected: ajusta el modelo (puede tardar 1-3 min por el número de equipos), imprime Brier del modelo vs baseline y el VEREDICTO. **Anotar el resultado** — define si se ejecuta la Task 5.

- [ ] **Step 6: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add engine_intl_v01.py tests/test_engine_intl.py && git commit -m "feat: add naive baseline and Brier gate to intl engine main"
```

---

## Task 5: `load_intl_to_supabase.py` — carga GATED (solo si el veredicto fue GREENLIGHT)

**Files:**
- Create: `load_intl_to_supabase.py`

> **GATE:** Ejecutar esta task solo si la Task 4 Step 5 imprimió `GREENLIGHT`. Si imprimió `NO PASA`, detenerse: crear el archivo igual (queda listo para cuando el modelo mejore) pero NO ejecutarlo, y reportar el Brier al usuario para decidir.

- [ ] **Step 1: Crear `load_intl_to_supabase.py`**

```python
"""
Carga GATED del modelo internacional a Supabase. Ejecutar SOLO si
engine_intl_v01.py imprimio GREENLIGHT.

Pasos:
  1. DDL via Management API: columna `neutral` en partidos + liga "Internacional".
  2. Selecciones nacionales -> equipos.
  3. Partidos -> partidos (con neutral).
  4. Modelo ajustado -> parametros_modelo.
"""

import os
import sys
import requests
from datetime import datetime, timezone

from supabase import create_client
from dotenv import load_dotenv

from engine_intl_v01 import cargar_csv, DixonColesIntl, TRAIN_HASTA, TEST_DESDE, XI

load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
PROJECT_REF = "aahaivisyghpgqarqpak"
MGMT_TOKEN = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
MGMT_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"


def run_ddl(sql):
    resp = requests.post(
        MGMT_URL,
        headers={"Authorization": f"Bearer {MGMT_TOKEN}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sb = create_client(SUPA_URL, SUPA_KEY)

    print("[1/4] DDL: columna neutral + liga Internacional...")
    run_ddl("ALTER TABLE partidos ADD COLUMN IF NOT EXISTS neutral BOOLEAN DEFAULT false;")
    # liga Internacional (idempotente por nombre)
    existing = sb.table("ligas").select("id").eq("nombre", "Internacional").execute().data
    if existing:
        liga_id = existing[0]["id"]
    else:
        liga_id = sb.table("ligas").insert({
            "nombre": "Internacional",
            "pais": None,
            "nivel_cobertura": "MEDIA",
        }).execute().data[0]["id"]
    print(f"  liga_id = {liga_id}")

    print("[2/4] Cargando partidos del CSV y ajustando modelo...")
    partidos = cargar_csv()
    train = [m for m in partidos if m["fecha"] <= TRAIN_HASTA]
    test  = [m for m in partidos if m["fecha"] >= TEST_DESDE]
    ref_date = datetime.fromisoformat(TEST_DESDE).replace(tzinfo=timezone.utc)
    model = DixonColesIntl().fit(train, ref_date)

    print("[3/4] Cargando selecciones a equipos...")
    nombres = sorted(set([m["home"] for m in partidos] + [m["away"] for m in partidos]))
    # idempotencia: traer equipos ya existentes de esta liga
    ya = {e["nombre_oficial"]: e["id"]
          for e in sb.table("equipos").select("id, nombre_oficial").eq("liga_id", liga_id).execute().data}
    equipo_id = dict(ya)
    nuevos = [{"nombre_oficial": n, "liga_id": liga_id} for n in nombres if n not in ya]
    for i in range(0, len(nuevos), 100):
        chunk = nuevos[i:i+100]
        inserted = sb.table("equipos").insert(chunk).execute().data
        for row in inserted:
            equipo_id[row["nombre_oficial"]] = row["id"]
    print(f"  {len(nombres)} selecciones ({len(nuevos)} nuevas)")

    print("[4/4] Cargando partidos a la tabla partidos...")
    filas = []
    for m in partidos:
        filas.append({
            "liga_id":              liga_id,
            "equipo_local_id":      equipo_id[m["home"]],
            "equipo_visitante_id":  equipo_id[m["away"]],
            "fecha":                m["fecha"],
            "temporada":            m["fecha"][:4],
            "estado":               "FINISHED",
            "goles_local":          m["gl"],
            "goles_visitante":      m["gv"],
            "resultado":            m["resultado"],
            "neutral":              m["neutral"],
            "fuente":               "martj42",
        })
    for i in range(0, len(filas), 500):
        sb.table("partidos").insert(filas[i:i+500]).execute()
    print(f"  {len(filas)} partidos cargados")

    # Parametros del modelo
    attack = {t: float(model.alphas[model.idx[t]]) for t in model.teams}
    defense = {t: float(model.betas[model.idx[t]]) for t in model.teams}
    sb.table("parametros_modelo").insert({
        "liga_id":         liga_id,
        "version_modelo":  "intl_v0.1",
        "temporada_fit":   f"2018..{TRAIN_HASTA[:4]}",
        "mu":              float(model.mu),
        "gamma":           float(model.gamma),
        "rho":             float(model.rho),
        "xi":              XI,
        "attack_params":   attack,
        "defense_params":  defense,
        "n_matches_fit":   len(train),
        "n_matches_val":   len(test),
        "is_production":   True,
    }).execute()
    print("  parametros_modelo: intl_v0.1 guardado (is_production=true)")
    print("\nCarga completa. Listo para Sub-proyecto B.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar que el módulo importa sin ejecutar la carga**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python -c "import load_intl_to_supabase; print('OK')"`
Expected: `OK` (no ejecuta `main()` al importar).

- [ ] **Step 3: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add load_intl_to_supabase.py && git commit -m "feat: add gated Supabase loader for international model"
```

- [ ] **Step 4: (Solo si GREENLIGHT) Ejecutar la carga**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python load_intl_to_supabase.py`
Expected: imprime los 4 pasos sin error y termina con "Carga completa". Verificar en Supabase que `ligas` tiene "Internacional", `equipos` tiene las selecciones y `partidos` tiene los internacionales.

> Si la Task 4 dio NO PASA, **saltar este Step 4** y reportar al usuario el Brier obtenido para decidir cómo seguir.

---

## Checklist de spec coverage

| Requisito del spec | Task |
|---|---|
| Descargar dataset martj42, filtrar 2018+ con marcador | Task 1 |
| CSV local no commiteado (.gitignore) | Task 1 |
| Motor espejea Dixon-Coles de engine_v02 | Task 2-3 |
| gamma condicional a neutral (fit y predict) | Task 3 (`neg_log_likelihood`, `lambdas`) |
| Time-weighting exponencial xi=0.004 | Task 2 (`time_weight`) |
| Holdout temporal train 2018-2024 / test 2025+ | Task 4 (`main`) |
| Baseline ingenuo neutral-aware | Task 4 (`baseline_tasas`) |
| Brier modelo vs baseline + veredicto >= 3% | Task 4 (`main`) |
| Gate antes de cargar Supabase | Task 5 (GATE note + Step 4) |
| Columna neutral via Management API | Task 5 (`run_ddl`) |
| Liga Internacional + equipos + partidos | Task 5 |
| Modelo a parametros_modelo (intl_v0.1) | Task 5 |
| No tocar engine_v02/analyzer/validator/main/resolver | (ningún task los modifica) |
| Tests de funciones puras | Task 2-4 (`tests/test_engine_intl.py`) |
