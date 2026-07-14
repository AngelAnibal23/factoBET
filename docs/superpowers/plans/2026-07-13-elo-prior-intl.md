# ELO Prior para el Dixon-Coles Internacional — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anclar el ataque/defensa de cada selección a su ELO histórico para que equipos con pocos partidos (o fuera del modelo) dejen de tratarse como "equipo promedio", mejorando todas las patas que salen de los λ del DC intl.

**Architecture:** Módulo puro `elo_intl.py` (World Football Elo sobre martj42) produce z-scores por selección. El fit de `engine_intl_v01.py` cambia su penalización L2-hacia-0 por L2-hacia-anclas (`α₀=c·z`, `β₀=−c·z`) con fuerza propia `l2_prior`; `c` se estima por regresión de los α̂ del v0.1 sobre z (no se inventa). El serving sintetiza α/β desde ELO para equipos fuera del fit. Gate: DC+ELO vs DC v0.1 (global no empeora >0.5% + segmento sparse mejora ≥3%).

**Tech Stack:** Python puro + numpy/scipy (ya en el stack), pytest, Supabase (`parametros_modelo`), Management API para DDL.

**Spec:** `docs/superpowers/specs/2026-07-13-elo-prior-design.md`

**⚠ Desviación del spec (corrección técnica, ver Task 8 para la enmienda):** el spec
decía "grid de c {0.1,0.2,0.3,0.5} con la l2 existente". La l2 existente es 0.001 y
su curvatura (2·l2 = 0.002) es despreciable frente a la de la verosimilitud incluso
para equipos con 5 partidos (~curvatura 5-10) — el prior no movería NADA. Corrección:
(1) `c` (dónde está el ancla) se estima por regresión sobre los equipos bien
muestreados del v0.1; (2) la fuerza del prior es un parámetro nuevo `l2_prior` con
grid {0.25, 0.5, 1.0, 2.0, 4.0} (interpretable como pseudo-partidos de evidencia).
El grid sigue decidiendo con datos, que era la intención del spec.

**Convenciones del repo:** tests en `tests/`, correr con `python -m pytest`. Los
commits terminan con la línea `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
Suite completa actual: 249 tests verdes — debe seguir así al final de cada task.

---

## Task 1: Rama + `elo_intl.py` (núcleo del rating)

**Files:**
- Create: `elo_intl.py`
- Test: `tests/test_elo_intl.py`

- [ ] **Step 1.1: Crear la rama**

```bash
git checkout -b feat/elo-prior-intl
```

- [ ] **Step 1.2: Escribir los tests que fallan**

Crear `tests/test_elo_intl.py` completo:

```python
"""Tests de elo_intl: World Football Elo sobre el histórico martj42."""
from elo_intl import (
    ELO_INICIAL, K_DEFAULT, k_torneo, multiplicador_goles, calcular_elo,
    estandarizar, blend_z, cargar_partidos_elo,
)


def _p(home, away, gl, gv, fecha, neutral=False, tournament="Friendly"):
    return {"home": home, "away": away, "gl": gl, "gv": gv,
            "fecha": fecha, "neutral": neutral, "tournament": tournament}


def test_k_por_torneo():
    assert k_torneo("FIFA World Cup") == 60.0
    # 'qualification' contiene 'FIFA World Cup': el orden del match importa
    assert k_torneo("FIFA World Cup qualification") == 40.0
    assert k_torneo("Copa América") == 50.0
    assert k_torneo("UEFA Euro") == 50.0
    assert k_torneo("UEFA Euro qualification") == 40.0
    assert k_torneo("UEFA Nations League") == 40.0
    assert k_torneo("Friendly") == 20.0
    assert k_torneo("Torneo Inventado 1999") == K_DEFAULT


def test_multiplicador_goles():
    assert multiplicador_goles(0) == 1.0
    assert multiplicador_goles(1) == 1.0
    assert multiplicador_goles(-2) == 1.5   # valor absoluto
    assert multiplicador_goles(3) == 1.75
    assert multiplicador_goles(4) == 1.875  # 1.75 + (4-3)/8


def test_elo_ganador_sube_perdedor_baja_suma_cero():
    elos = calcular_elo([_p("A", "B", 2, 0, "2020-01-01", neutral=True)])
    assert elos["A"] > ELO_INICIAL > elos["B"]
    assert abs((elos["A"] - ELO_INICIAL) + (elos["B"] - ELO_INICIAL)) < 1e-9


def test_elo_ventaja_local_solo_si_no_neutral():
    # Empate con iguales: en casa el local partía favorito (+100) => pierde puntos.
    en_casa = calcular_elo([_p("A", "B", 1, 1, "2020-01-01", neutral=False)])
    neutral = calcular_elo([_p("A", "B", 1, 1, "2020-01-01", neutral=True)])
    assert en_casa["A"] < ELO_INICIAL
    assert abs(neutral["A"] - ELO_INICIAL) < 1e-9


def test_elo_converge_direccional():
    # El que siempre gana 2-0 durante 48 partidos termina MUY arriba del otro.
    partidos = [
        _p("Fuerte", "Debil", 2, 0, f"{2010 + i // 12}-{i % 12 + 1:02d}-01", neutral=True)
        for i in range(48)
    ]
    elos = calcular_elo(partidos)
    assert elos["Fuerte"] - elos["Debil"] > 300


def test_calcular_elo_respeta_corte():
    # 'hasta' es exclusivo: el partido del día de corte NO cuenta (anti-fuga).
    partidos = [_p("A", "B", 3, 0, "2020-01-01", neutral=True),
                _p("A", "B", 3, 0, "2021-01-01", neutral=True)]
    con_corte = calcular_elo(partidos, hasta="2021-01-01")
    sin_corte = calcular_elo(partidos)
    assert con_corte["A"] < sin_corte["A"]


def test_estandarizar_media_cero_y_orden():
    z = estandarizar({"A": 1600.0, "B": 1500.0, "C": 1400.0})
    assert abs(sum(z.values())) < 1e-9
    assert z["A"] > 0 > z["C"]


def test_blend_z_predominante_y_fallback():
    za = {"A": 1.0, "B": -1.0}
    zb = {"A": 0.0}
    out = blend_z(za, zb, w=0.7)
    assert abs(out["A"] - 0.7) < 1e-9   # 0.7*1.0 + 0.3*0.0
    assert out["B"] == -1.0             # sin señal FIFA -> solo la nuestra


def test_cargar_partidos_elo_normaliza_y_ordena(tmp_path):
    csv_content = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,TRUE\n"
        "2019-06-01,France,Brazil,2,1,Friendly,Paris,France,FALSE\n"
    )
    p = tmp_path / "mini_elo.csv"
    p.write_text(csv_content, encoding="utf-8")
    partidos = cargar_partidos_elo(str(p))
    assert len(partidos) == 2
    assert partidos[0]["fecha"] == "2019-06-01"      # ordenado por fecha
    assert partidos[0]["tournament"] == "Friendly"
    assert partidos[1]["neutral"] is True
    assert partidos[1]["gl"] == 3
```

- [ ] **Step 1.3: Verificar que fallan**

Run: `python -m pytest tests/test_elo_intl.py -q`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'elo_intl'`

- [ ] **Step 1.4: Implementar `elo_intl.py`**

```python
"""ELO internacional (fórmula World Football Elo, la de eloratings.net) calculado
sobre el histórico martj42. Produce z-scores por selección para usarse como PRIOR
del Dixon-Coles internacional (ver spec 2026-07-13-elo-prior-design.md).

Puro y sin red: lee CSVs locales. `intl_results_elo.csv` se genera con
`python download_intl_results.py elo` (histórico desde 1990, misma fuente).
"""
import csv
import math
import os

CSV_ELO = "intl_results_elo.csv"
FIFA_CSV = "fifa_ranking.csv"
ELO_INICIAL = 1500.0
VENTAJA_LOCAL = 100.0
K_DEFAULT = 30.0

# (patrón, K) — se matchea por substring en minúsculas; el orden importa:
# 'fifa world cup qualification' contiene 'fifa world cup', va primero.
K_TORNEOS = [
    ("fifa world cup qualification", 40.0),
    ("fifa world cup", 60.0),
    ("uefa euro qualification", 40.0),
    ("uefa euro", 50.0),
    ("copa américa", 50.0),
    ("copa america", 50.0),
    ("african cup of nations", 50.0),
    ("afc asian cup", 50.0),
    ("gold cup", 50.0),
    ("uefa nations league", 40.0),
    ("friendly", 20.0),
]


def k_torneo(tournament: str) -> float:
    t = tournament.strip().lower()
    for patron, k in K_TORNEOS:
        if patron in t:
            return k
    return K_DEFAULT


def multiplicador_goles(diff: int) -> float:
    """Estándar World Football Elo: 1 gol ->x1, 2 ->x1.5, 3 ->x1.75, +1/8 por gol extra."""
    d = abs(diff)
    if d <= 1:
        return 1.0
    if d == 2:
        return 1.5
    return 1.75 + (d - 3) / 8.0


def calcular_elo(partidos: list[dict], hasta: str | None = None) -> dict[str, float]:
    """Recorre partidos ORDENADOS por fecha y devuelve {selección: elo}.

    `hasta` (ISO, exclusivo) corta el recorrido: para el gate, el ELO del train
    se calcula con hasta=TEST_DESDE para no fugar resultados del test.
    El intercambio es suma-cero: delta = K * G * (W - We).
    """
    elos: dict[str, float] = {}
    for m in partidos:
        if hasta is not None and m["fecha"] >= hasta:
            break
        eh = elos.setdefault(m["home"], ELO_INICIAL)
        ea = elos.setdefault(m["away"], ELO_INICIAL)
        dr = eh - ea + (0.0 if m["neutral"] else VENTAJA_LOCAL)
        we = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        if m["gl"] > m["gv"]:
            w = 1.0
        elif m["gl"] == m["gv"]:
            w = 0.5
        else:
            w = 0.0
        delta = k_torneo(m["tournament"]) * multiplicador_goles(m["gl"] - m["gv"]) * (w - we)
        elos[m["home"]] = eh + delta
        elos[m["away"]] = ea - delta
    return elos


def estandarizar(valores: dict[str, float]) -> dict[str, float]:
    """z-scores sobre el conjunto dado. Es lo que consume el prior del DC."""
    vals = list(valores.values())
    media = sum(vals) / len(vals)
    var = sum((v - media) ** 2 for v in vals) / len(vals)
    sd = math.sqrt(var) or 1.0
    return {t: (v - media) / sd for t, v in valores.items()}


def blend_z(z_propio: dict, z_fifa: dict, w: float = 0.7) -> dict[str, float]:
    """Mezcla con el nuestro predominante; equipos sin señal FIFA usan solo la nuestra."""
    return {t: (w * z + (1.0 - w) * z_fifa[t]) if t in z_fifa else z
            for t, z in z_propio.items()}


def cargar_partidos_elo(path: str = CSV_ELO) -> list[dict]:
    """Lee el CSV histórico (mismas columnas martj42) incluyendo `tournament`,
    ordenado por fecha ascendente."""
    partidos = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        partidos.append({
            "home": r["home_team"], "away": r["away_team"],
            "gl": int(r["home_score"]), "gv": int(r["away_score"]),
            "fecha": r["date"],
            "neutral": r["neutral"].strip().upper() == "TRUE",
            "tournament": r["tournament"],
        })
    partidos.sort(key=lambda m: m["fecha"])
    return partidos


def cargar_z_fifa(path: str = FIFA_CSV) -> dict[str, float] | None:
    """z-scores del ranking FIFA, o None si no hay archivo (el blend es opcional).
    Espera columnas `team,points` (snapshot más reciente, nombres ya en el
    espacio martj42 — el casado se hace al generar el archivo, Task 6)."""
    if not os.path.exists(path):
        return None
    puntos = {r["team"]: float(r["points"])
              for r in csv.DictReader(open(path, encoding="utf-8"))}
    return estandarizar(puntos)
```

- [ ] **Step 1.5: Verificar que pasan**

Run: `python -m pytest tests/test_elo_intl.py -q`
Expected: `9 passed`

- [ ] **Step 1.6: Commit**

```bash
git add elo_intl.py tests/test_elo_intl.py
git commit -m "feat(elo): modulo World Football Elo puro sobre historico martj42

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: Descarga del histórico ELO (misma fuente, filtro relajado)

**Files:**
- Modify: `download_intl_results.py:44-49` (solo el `__main__`)

`descargar_filtrar()` ya está parametrizado (`desde`, `salida`); NO se toca la
función ni `intl_results.csv` (el input del DC queda intacto — si metiéramos
1990-2017 al fit, el decay XI los anula pero engordan el set de equipos al pedo).
Solo se añade un modo CLI. Sin test unitario (script de red, patrón del repo).

- [ ] **Step 2.1: Añadir el modo `elo` al `__main__`**

Reemplazar el bloque `if __name__ == "__main__":` por:

```python
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "elo":
        # Histórico profundo para calcular ELO (desde 1990: ratings maduros
        # al llegar a la era del modelo). NO pisa intl_results.csv.
        total, n = descargar_filtrar(desde="1990-01-01", salida="intl_results_elo.csv")
        print(f"Descargados {total} partidos, {n} tras filtrar (>= 1990, con marcador).")
        print("Guardado en intl_results_elo.csv")
    else:
        total, n = descargar_filtrar()
        print(f"Descargados {total} partidos, {n} tras filtrar (>= {DESDE}, con marcador).")
        print(f"Guardado en {SALIDA}")
```

- [ ] **Step 2.2: Correrlo de verdad**

Run: `python download_intl_results.py elo`
Expected: `Descargados ~48000 partidos, ~20000+ tras filtrar (>= 1990, con marcador).` y existe `intl_results_elo.csv`.

- [ ] **Step 2.3: Ignorar el CSV nuevo y sanity-check del ELO real**

Añadir `intl_results_elo.csv` a `.gitignore` (junto a los otros csv ignorados).
Sanity-check manual (no es test, es verificación de cordura del dato):

```bash
python -c "
from elo_intl import cargar_partidos_elo, calcular_elo
elos = calcular_elo(cargar_partidos_elo())
top = sorted(elos.items(), key=lambda kv: -kv[1])[:10]
print(*top, sep=chr(10))
print('Peru:', elos.get('Peru'))
"
```

Expected: el top-10 son potencias reales (Argentina/Brazil/France/Spain...). Si sale
basura, revisar antes de seguir.

- [ ] **Step 2.4: Verificar suite y commit**

Run: `python -m pytest -q` → Expected: `258 passed` (249 + 9 de Task 1)

```bash
git add download_intl_results.py .gitignore
git commit -m "feat(elo): modo 'elo' en download_intl_results (historico 1990+, archivo aparte)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: Prior en el fit de `engine_intl_v01.py`

**Files:**
- Modify: `engine_intl_v01.py` — `precompute_matches` (~:94), `nll_and_grad` (~:128), `neg_log_likelihood` (~:219), `DixonColesIntl.fit` (~:250)
- Test: `tests/test_engine_intl.py` (añadir al final)

- [ ] **Step 3.1: Escribir los tests que fallan** (añadir a `tests/test_engine_intl.py`)

```python
# ── ELO prior (Fase 3) ────────────────────────────────────────────────────────

from engine_intl_v01 import escala_c_desde_v01


def test_gradiente_analitico_con_prior_elo():
    # Mismo setup que test_gradiente_analitico_coincide_con_numerico pero con
    # anclas alpha0/beta0 no-cero y l2 fuerte: el gradiente del prior también
    # tiene que coincidir con diferencias finitas.
    teams = ["A", "B", "C", "D"]
    scores = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 1), (3, 2), (0, 2), (2, 2)]
    matches = []
    for k, (gl, gv) in enumerate(scores):
        matches.append({
            "home": teams[k % 4], "away": teams[(k + 1) % 4],
            "gl": gl, "gv": gv, "fecha": "2024-01-01", "neutral": (k % 2 == 0),
        })
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    w = np.array([time_weight(m["fecha"], ref) for m in matches])
    w /= w.mean()
    a0 = np.array([0.3, -0.1, 0.2, 0.0])
    b0 = np.array([-0.3, 0.1, -0.2, 0.0])
    pre = precompute_matches(matches, teams, w, a0=a0, b0=b0)
    n = len(teams)

    np.random.seed(0)
    x = np.random.randn(2 * n + 3) * 0.2
    x[2*n], x[2*n + 1], x[2*n + 2] = 0.2, 0.3, -0.05

    f = lambda p: neg_log_likelihood(p, pre, n, 2.0)   # l2_prior fuerte
    g = lambda p: nll_and_grad(p, pre, n, 2.0)[1]
    assert check_grad(f, g, x, epsilon=1.5e-8) < 1e-4


def test_precompute_sin_anclas_es_cero():
    # Backward compat: sin a0/b0, las anclas son 0 (comportamiento actual).
    matches = [{"home": "A", "away": "B", "gl": 1, "gv": 0,
                "fecha": "2024-01-01", "neutral": False}]
    pre = precompute_matches(matches, ["A", "B"], np.array([1.0]))
    assert np.allclose(pre["a0"], 0.0) and np.allclose(pre["b0"], 0.0)


def test_fit_con_prior_fuerte_ancla_equipos_con_pocos_datos():
    # 2 partidos y un prior fortísimo: los alphas quedan pegados al ancla c*z.
    partidos = [
        {"home": "A", "away": "B", "gl": 1, "gv": 1, "fecha": "2024-01-01",
         "neutral": True, "resultado": "DRAW"},
        {"home": "B", "away": "A", "gl": 1, "gv": 1, "fecha": "2024-02-01",
         "neutral": True, "resultado": "DRAW"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    elo_z = {"A": 2.0, "B": -2.0}
    model = DixonColesIntl().fit(partidos, ref, elo_z=elo_z,
                                 prior_scale=0.5, l2_prior=50.0)
    ia, ib = model.idx["A"], model.idx["B"]
    assert abs(model.alphas[ia] - 1.0) < 0.1    # ancla = 0.5*2.0
    assert abs(model.alphas[ib] + 1.0) < 0.1
    assert abs(model.betas[ia] + 1.0) < 0.1     # beta0 = -c*z
    assert model.prior_scale == 0.5
    assert model.elo_z == elo_z


def test_fit_sin_elo_no_cambia_interfaz():
    # El camino por defecto sigue funcionando y no guarda prior.
    partidos = [
        {"home": "A", "away": "B", "gl": 2, "gv": 1, "fecha": "2024-01-01",
         "neutral": False, "resultado": "HOME"},
    ]
    ref = datetime(2024, 3, 1, tzinfo=timezone.utc)
    model = DixonColesIntl().fit(partidos, ref)
    assert model.elo_z is None
    assert model.prior_scale == 0.0


def test_escala_c_desde_v01_recupera_pendiente():
    # Si los alphas del modelo son exactamente 0.3*z en los equipos elegibles,
    # la regresión devuelve c=0.3.
    z = {"A": 1.0, "B": -1.0, "C": 2.0, "D": 0.5}
    attack = {t: 0.3 * z[t] for t in z}
    defense = {t: -0.3 * z[t] for t in z}
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack=attack, defense=defense)
    conteos = {"A": 50, "B": 40, "C": 35, "D": 5}   # D no elegible (<30)
    c = escala_c_desde_v01(model, z, conteos, min_partidos=30)
    assert abs(c - 0.3) < 1e-9
```

- [ ] **Step 3.2: Verificar que fallan**

Run: `python -m pytest tests/test_engine_intl.py -q`
Expected: FAIL — `ImportError: cannot import name 'escala_c_desde_v01'`

- [ ] **Step 3.3: Implementar en `engine_intl_v01.py`**

(a) `precompute_matches` — nueva firma y dos claves más en el dict de retorno:

```python
def precompute_matches(matches, teams, weights, a0=None, b0=None):
```

y antes del `return`, añadir:

```python
    n_teams = len(teams)
    if a0 is None:
        a0 = np.zeros(n_teams)
    if b0 is None:
        b0 = np.zeros(n_teams)
```

y dentro del dict retornado: `"a0": np.asarray(a0, dtype=np.float64), "b0": np.asarray(b0, dtype=np.float64),`

(b) `nll_and_grad` — el docstring gana una línea ("`l2` penaliza la distancia a las
anclas `pre['a0']/pre['b0']` (cero por defecto = comportamiento clásico)") y cambian
exactamente estas líneas:

```python
    da = alphas - pre["a0"]
    db = betas  - pre["b0"]
    penalty = l2 * (np.dot(da, da) + np.dot(db, db))
```

(en lugar de `penalty = l2 * (np.dot(alphas, alphas) + np.dot(betas, betas))`), y en el gradiente:

```python
    grad[:n]      = -grad_alpha + 2.0 * l2 * da
    grad[n:2*n]   = -grad_beta  + 2.0 * l2 * db
```

(c) `DixonColesIntl.fit` — nueva firma y cuerpo (solo cambian las líneas marcadas):

```python
    def fit(self, matches, ref_date, elo_z=None, prior_scale=0.0, l2_prior=None):
        """elo_z: {equipo: z-score ELO} para anclar el prior (None = clásico).
        prior_scale (c): ancla alpha0=c*z, beta0=-c*z.
        l2_prior: fuerza del prior (pseudo-partidos); solo aplica si hay elo_z."""
        self.teams = sorted(set(
            [m["home"] for m in matches] + [m["away"] for m in matches]
        ))
        n = len(self.teams)
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.elo_z = dict(elo_z) if elo_z else None
        self.prior_scale = float(prior_scale) if elo_z else 0.0

        weights = np.array([time_weight(m["fecha"], ref_date) for m in matches])
        weights /= weights.mean()
        if elo_z:
            z = np.array([elo_z.get(t, 0.0) for t in self.teams])
            a0, b0 = prior_scale * z, -prior_scale * z
            l2 = float(l2_prior) if l2_prior is not None else 0.001
        else:
            a0 = b0 = None
            l2 = 0.001
        pre = precompute_matches(matches, self.teams, weights, a0=a0, b0=b0)
        ...
        result = minimize(
            nll_and_grad, x0,
            args=(pre, n, l2), jac=True,
            ...
```

(el resto del método queda igual; solo `args=(pre, n)` pasa a `args=(pre, n, l2)`).

(d) Función nueva al nivel de módulo (después de la clase):

```python
def escala_c_desde_v01(model, elo_z, conteos, min_partidos=30):
    """Escala c del ancla: pendiente de la regresión alpha_hat ~ z sobre los
    equipos BIEN muestreados del fit clásico. El dato fija c; el grid solo
    decide la FUERZA del prior (l2_prior)."""
    zs, als = [], []
    for t in model.teams:
        if conteos.get(t, 0) >= min_partidos and t in elo_z:
            zs.append(elo_z[t])
            als.append(float(model.alphas[model.idx[t]]))
    zs, als = np.array(zs), np.array(als)
    dz = zs - zs.mean()
    return float(np.dot(dz, als - als.mean()) / np.dot(dz, dz))
```

- [ ] **Step 3.4: Verificar que pasan (los nuevos y TODOS los viejos)**

Run: `python -m pytest tests/test_engine_intl.py tests/test_elo_intl.py -q`
Expected: todos passed (los tests viejos del gradiente/fit no cambian: anclas 0 = comportamiento idéntico).

- [ ] **Step 3.5: Commit**

```bash
git add engine_intl_v01.py tests/test_engine_intl.py
git commit -m "feat(elo): prior L2-hacia-anclas ELO en el fit del DC intl (c por regresion, l2_prior propio)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: Fallback ELO en serving (`from_params` / `lambdas`)

**Files:**
- Modify: `engine_intl_v01.py` — `from_params` (~:229), `lambdas` (~:295)
- Test: `tests/test_engine_intl.py` (añadir al final)

- [ ] **Step 4.1: Tests que fallan**

```python
def test_from_params_equipo_fuera_del_fit_usa_elo():
    model = DixonColesIntl.from_params(
        mu=0.2, gamma=0.3, rho=-0.05,
        attack={"A": 0.5}, defense={"A": -0.2},
        elo_z={"A": 1.0, "Z": 1.5, "Y": -1.5}, prior_scale=0.4,
    )
    # Z e Y no están en el fit pero SÍ tienen ELO: alpha=c*z, beta=-c*z
    lh, la = model.lambdas("Z", "Y", neutral=True)
    assert abs(lh - math.exp(0.2 + 0.4 * 1.5 + (-0.4 * -1.5))) < 1e-9
    assert abs(la - math.exp(0.2 + 0.4 * -1.5 + (-0.4 * 1.5))) < 1e-9
    assert lh > la   # el de mejor ELO mete más


def test_from_params_sin_elo_conserva_fallback_promedio():
    # Sin tabla ELO, el desconocido cae a exp(mu) como siempre (cero regresión).
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.5}, defense={"A": -0.2})
    lh, la = model.lambdas("Z", "Y", neutral=True)
    assert abs(lh - math.exp(0.2)) < 1e-9
    assert abs(la - math.exp(0.2)) < 1e-9


def test_from_params_equipo_en_fit_ignora_elo():
    # Si el equipo está en el fit, manda su alpha ajustado, no el ELO.
    model = DixonColesIntl.from_params(
        mu=0.2, gamma=0.0, rho=-0.05,
        attack={"A": 0.5, "B": -0.3}, defense={"A": -0.2, "B": 0.1},
        elo_z={"A": -5.0, "B": 5.0}, prior_scale=0.4,   # ELO absurdo a propósito
    )
    lh, la = model.lambdas("A", "B", neutral=True)
    assert abs(lh - math.exp(0.2 + 0.5 + 0.1)) < 1e-9
```

- [ ] **Step 4.2: Verificar que fallan**

Run: `python -m pytest tests/test_engine_intl.py -q`
Expected: FAIL — `from_params() got an unexpected keyword argument 'elo_z'`

- [ ] **Step 4.3: Implementar**

(a) `from_params` — firma `def from_params(cls, mu, gamma, rho, attack, defense, elo_z=None, prior_scale=0.0):` y antes del `return model`:

```python
        model.elo_z = dict(elo_z) if elo_z else None
        model.prior_scale = float(prior_scale)
```

(b) Reemplazar `lambdas` por la versión con `_fuerza` (mismo resultado para los
casos existentes — los tests viejos lo verifican):

```python
    def _fuerza(self, team):
        """(alpha, beta) del equipo. Si no está en el fit pero tiene ELO,
        se sintetiza con el mismo mapeo del prior; si tampoco, (0,0) = promedio."""
        if team in self.idx:
            i = self.idx[team]
            return float(self.alphas[i]), float(self.betas[i])
        z = (self.elo_z or {}).get(team)
        if z is not None:
            return self.prior_scale * z, -self.prior_scale * z
        return 0.0, 0.0

    def lambdas(self, home, away, neutral):
        g = 0.0 if neutral else self.gamma
        a_h, b_h = self._fuerza(home)
        a_a, b_a = self._fuerza(away)
        lh = math.exp(self.mu + a_h + b_a + g)
        la = math.exp(self.mu + a_a + b_h)
        return lh, la
```

- [ ] **Step 4.4: Verificar que pasan (incluye los viejos de `lambdas`/`from_params`)**

Run: `python -m pytest tests/test_engine_intl.py -q`
Expected: todos passed.

- [ ] **Step 4.5: Commit**

```bash
git add engine_intl_v01.py tests/test_engine_intl.py
git commit -m "feat(elo): fallback ELO sintetizado en lambdas() para equipos fuera del fit

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 5: Gate extendido (DC+ELO vs DC v0.1)

**Files:**
- Modify: `engine_intl_v01.py` — constantes arriba + funciones nuevas + `main()`
- Test: `tests/test_engine_intl.py`

- [ ] **Step 5.1: Tests que fallan** (funciones puras del gate)

```python
from engine_intl_v01 import conteo_partidos_train, evaluar_en_test


def test_conteo_partidos_train():
    train = [
        {"home": "A", "away": "B"}, {"home": "A", "away": "C"},
        {"home": "B", "away": "A"},
    ]
    c = conteo_partidos_train(train)
    assert c == {"A": 3, "B": 2, "C": 1}


def test_evaluar_en_test_separa_segmento_sparse():
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.5, "B": -0.3, "C": 0.0},
                                       defense={"A": -0.2, "B": 0.1, "C": 0.0})
    test = [
        {"home": "A", "away": "B", "neutral": True, "resultado": "HOME"},
        {"home": "A", "away": "C", "neutral": True, "resultado": "DRAW"},
    ]
    conteos = {"A": 50, "B": 40, "C": 3}   # C es sparse
    bs_g, bs_s, n_sparse = evaluar_en_test(model, test, conteos, umbral=15)
    assert n_sparse == 1                    # solo el partido con C
    assert 0.0 <= bs_g <= 1.0 and 0.0 <= bs_s <= 1.0


def test_evaluar_en_test_sin_sparse_devuelve_none():
    model = DixonColesIntl.from_params(mu=0.2, gamma=0.3, rho=-0.05,
                                       attack={"A": 0.5, "B": -0.3},
                                       defense={"A": -0.2, "B": 0.1})
    test = [{"home": "A", "away": "B", "neutral": True, "resultado": "HOME"}]
    bs_g, bs_s, n_sparse = evaluar_en_test(model, test, {"A": 50, "B": 50}, umbral=15)
    assert bs_s is None and n_sparse == 0
```

- [ ] **Step 5.2: Verificar que fallan**

Run: `python -m pytest tests/test_engine_intl.py -q`
Expected: FAIL — `ImportError: cannot import name 'conteo_partidos_train'`

- [ ] **Step 5.3: Implementar funciones + constantes**

Constantes junto a las existentes (debajo de `TEST_DESDE`):

```python
# ── Gate ELO (Fase 3) ─────────────────────────────────────────────────────────
UMBRAL_SPARSE = 15          # partidos en train; revisar contra la distribución real
GRID_L2_PRIOR = [0.25, 0.5, 1.0, 2.0, 4.0]   # fuerza del prior (pseudo-partidos)
TOLERANCIA_GLOBAL = 0.005   # el Brier global no puede empeorar más de 0.5% rel
GATE_SPARSE_MIN = 0.03      # mejora mínima en el segmento sparse
```

Funciones (después de `predecir_baseline`):

```python
def conteo_partidos_train(train):
    """Partidos por equipo en el train (crudo; para segmentar el gate)."""
    c = {}
    for m in train:
        c[m["home"]] = c.get(m["home"], 0) + 1
        c[m["away"]] = c.get(m["away"], 0) + 1
    return c


def evaluar_en_test(model, test, conteos, umbral=UMBRAL_SPARSE):
    """(brier_global, brier_sparse|None, n_sparse). Sparse = algún equipo del
    partido tiene < umbral partidos en train."""
    preds_all, preds_sparse = [], []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        pred = (*model.predict(m["home"], m["away"], m["neutral"]), m["resultado"])
        preds_all.append(pred)
        if min(conteos.get(m["home"], 0), conteos.get(m["away"], 0)) < umbral:
            preds_sparse.append(pred)
    bs_g = brier_score(preds_all)
    bs_s = brier_score(preds_sparse) if preds_sparse else None
    return bs_g, bs_s, len(preds_sparse)
```

- [ ] **Step 5.4: Verificar que pasan**

Run: `python -m pytest tests/test_engine_intl.py -q` → Expected: todos passed.

- [ ] **Step 5.5: Extender `main()` con el gate ELO**

Añadir al final de `main()` (antes del `return`), reemplazando el `return` actual
por el nuevo al final:

```python
    # ══ GATE ELO (Fase 3): DC+prior vs DC v0.1 — ver spec 2026-07-13 ══
    try:
        from elo_intl import cargar_partidos_elo, calcular_elo, estandarizar, blend_z, cargar_z_fifa
        partidos_elo = cargar_partidos_elo()
    except FileNotFoundError:
        print("\n(gate ELO saltado: falta intl_results_elo.csv — `python download_intl_results.py elo`)")
        return bs_modelo, bs_baseline, model

    print("\n" + "=" * 60)
    print("GATE ELO — prior vs DC v0.1 (rival = modelo actual, no baseline)")
    print("=" * 60)

    conteos = conteo_partidos_train(train)
    dist = sorted(conteos.values())
    print(f"  partidos/equipo en train: p10={dist[len(dist)//10]} "
          f"p50={dist[len(dist)//2]} p90={dist[9*len(dist)//10]} | umbral sparse={UMBRAL_SPARSE}")

    # ELO del train CON CORTE (anti-fuga: nada del test entra al prior)
    z_propio = estandarizar(calcular_elo(partidos_elo, hasta=TEST_DESDE))
    variantes = {"elo_propio": z_propio}
    z_fifa = cargar_z_fifa()
    if z_fifa is not None:
        variantes["blend_fifa"] = blend_z(z_propio, z_fifa, w=0.7)
    else:
        print("  (sin fifa_ranking.csv: variante blend_fifa no compite)")

    c = escala_c_desde_v01(model, z_propio, conteos)
    print(f"  escala c (regresión alpha~z, equipos >=30 partidos): {c:.4f}")

    bs_g0, bs_s0, n_sp = evaluar_en_test(model, test, conteos)
    if bs_s0 is None:
        print("  ⚠ Sin partidos sparse en el test con este umbral — subir UMBRAL_SPARSE y re-correr.")
        return bs_modelo, bs_baseline, model
    print(f"  v0.1 (sin prior): global={bs_g0:.4f} sparse={bs_s0:.4f} (n={n_sp})")

    candidatas = []
    for nombre, z in variantes.items():
        for l2p in GRID_L2_PRIOR:
            m2 = DixonColesIntl().fit(train, ref_date, elo_z=z,
                                      prior_scale=c, l2_prior=l2p)
            bs_g, bs_s, _ = evaluar_en_test(m2, test, conteos)
            ok_global = bs_g <= bs_g0 * (1.0 + TOLERANCIA_GLOBAL)
            mejora_s = (bs_s0 - bs_s) / bs_s0
            pasa = ok_global and mejora_s >= GATE_SPARSE_MIN
            marca = "✅" if pasa else "❌"
            print(f"  {nombre:12s} l2_prior={l2p:<5} global={bs_g:.4f} "
                  f"sparse={bs_s:.4f} ({mejora_s*100:+.1f}%) {marca}")
            if pasa:
                candidatas.append((mejora_s, nombre, l2p, bs_g, bs_s))

    if candidatas:
        mejora_s, nombre, l2p, bs_g, bs_s = max(candidatas)
        print(f"\n  🏆 GANADORA: {nombre} l2_prior={l2p} c={c:.4f} "
              f"(sparse {mejora_s*100:+.1f}%, global {bs_g:.4f})")
        print(f"  Siguiente paso: python load_intl_to_supabase.py {c:.4f} {l2p} {nombre}")
    else:
        print("\n  ❌ NINGUNA variante ELO pasa el gate. NO publicar; guardar diagnóstico.")
    print("=" * 60)
    return bs_modelo, bs_baseline, model
```

- [ ] **Step 5.6: Smoke run del gate completo (necesita `intl_results.csv` e `intl_results_elo.csv` locales)**

Run: `python engine_intl_v01.py`
Expected: el gate v0.1 clásico imprime como siempre, y la sección GATE ELO imprime
la distribución, c, y la tabla de variantes sin crashear. (El veredicto es el que
sea — este run es de humo; el análisis va en Task 9.)

**Ojo:** si la distribución impresa muestra que `UMBRAL_SPARSE=15` deja un segmento
ridículo (n_sparse < 40 partidos) o gigante (> 60% del test), ajustar la constante a
un valor que capture el ~20-30% inferior, commitearlo y ANOTAR el valor final elegido
en el spec (Task 8).

- [ ] **Step 5.7: Suite completa + commit**

Run: `python -m pytest -q` → Expected: todos passed.

```bash
git add engine_intl_v01.py tests/test_engine_intl.py
git commit -m "feat(elo): gate DC+prior vs DC v0.1 (global + segmento sparse, grid l2_prior)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 6: Fuente FIFA (opcional — puede terminar en 'se pospone')

**Files:**
- Create (si hay fuente): `fifa_ranking.csv` (LOCAL, gitignored — dato, no código)
- Modify: `.gitignore`

Esta task es operacional y PUEDE FALLAR SIN BLOQUEAR: el spec dice que si no hay
fuente decente sin scraping frágil, el blend se pospone y se anota.

- [ ] **Step 6.1: Buscar CSV público del ranking FIFA**

Con WebSearch/WebFetch, buscar un CSV histórico/actual del ranking FIFA masculino
(candidatos conocidos: mirrors en GitHub del dataset de Kaggle "FIFA World Ranking";
data.world). Criterios de aceptación: (a) descargable como CSV sin login, (b) trae
nombre de selección y puntos, (c) tiene snapshot de 2025 o más nuevo.

- [ ] **Step 6.2: Si hay fuente — generar `fifa_ranking.csv`**

Transformar al formato `team,points` (solo el snapshot más reciente) con un script
efímero en el scratchpad. Mapear nombres al espacio martj42: matchear contra
`sorted(set(homes+aways))` de `intl_results_elo.csv`; para no-exactos usar
`rapidfuzz.fuzz.ratio >= 90` y revisar a mano la lista de mapeos difusos impresa.
Si > 20% de las selecciones del modelo quedan sin mapear, tratar como "sin fuente".
Añadir `fifa_ranking.csv` a `.gitignore`.

- [ ] **Step 6.3: Si NO hay fuente — posponer sin drama**

No crear el archivo (el gate ya imprime "variante blend_fifa no compite" y sigue).
Anotar en el spec (Task 8) que el blend quedó pospuesto y por qué.

- [ ] **Step 6.4: Commit (solo si cambió .gitignore)**

```bash
git add .gitignore
git commit -m "chore(elo): fifa_ranking.csv local e ignorado (blend opcional)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 7: Publicación `intl_v0.2` (`load_intl_to_supabase.py`)

**Files:**
- Modify: `load_intl_to_supabase.py`

El script conserva su modo clásico (sin args = v0.1, intacto como rollback
re-ejecutable) y gana el modo ELO: `python load_intl_to_supabase.py <c> <l2_prior> <variante>`
(los 3 valores los imprime la línea "Siguiente paso" del gate ganador, Task 5).

- [ ] **Step 7.1: DDL de columnas nuevas**

En `main()`, junto al `run_ddl` existente del paso 1, añadir:

```python
    run_ddl("ALTER TABLE parametros_modelo ADD COLUMN IF NOT EXISTS elo_params JSONB;")
    run_ddl("ALTER TABLE parametros_modelo ADD COLUMN IF NOT EXISTS prior_scale NUMERIC(10,6);")
```

- [ ] **Step 7.2: Parseo de CLI + gate defensivo ELO**

Arriba del archivo, tras las constantes:

```python
def parsear_args(argv):
    """(c, l2_prior, variante) o None para el modo clásico v0.1."""
    if len(argv) < 4:
        return None
    return float(argv[1]), float(argv[2]), argv[3]
```

En `main()`, tras calcular train/test, reemplazar el bloque del gate defensivo por:

```python
    modo_elo = parsear_args(sys.argv)
    if modo_elo is None:
        # ── Modo clásico v0.1 (rollback): gate vs baseline ingenuo, como siempre ──
        print(f"\n[gate] Re-chequeando Brier v0.1 (train {len(train)} / test {len(test)})...")
        bs_m, bs_b, mejora = rechequear_gate(train, test)
        print(f"  Brier modelo={bs_m:.4f}  baseline={bs_b:.4f}  mejora={mejora*100:+.1f}%")
        if not (bs_m < bs_b and mejora >= GATE_MIN_MEJORA):
            print("  ❌ NO PASA el gate. ABORTANDO carga (Supabase intacto).")
            sys.exit(1)
        version, elo_z_full, c, l2p = "intl_v0.1", None, 0.0, None
    else:
        # ── Modo ELO v0.2: gate defensivo vs DC v0.1 (réplica exacta del gate) ──
        from elo_intl import cargar_partidos_elo, calcular_elo, estandarizar, blend_z, cargar_z_fifa
        from engine_intl_v01 import conteo_partidos_train, evaluar_en_test, TOLERANCIA_GLOBAL, GATE_SPARSE_MIN

        c, l2p, variante = modo_elo
        partidos_elo = cargar_partidos_elo()
        z_train = estandarizar(calcular_elo(partidos_elo, hasta=TEST_DESDE))
        if variante == "blend_fifa":
            z_train = blend_z(z_train, cargar_z_fifa(), w=0.7)

        ref = datetime.fromisoformat(TEST_DESDE).replace(tzinfo=timezone.utc)
        conteos = conteo_partidos_train(train)
        m_v01 = DixonColesIntl().fit(train, ref)
        m_elo = DixonColesIntl().fit(train, ref, elo_z=z_train, prior_scale=c, l2_prior=l2p)
        bs_g0, bs_s0, _ = evaluar_en_test(m_v01, test, conteos)
        bs_g1, bs_s1, n_sp = evaluar_en_test(m_elo, test, conteos)
        mejora_s = (bs_s0 - bs_s1) / bs_s0
        print(f"\n[gate ELO] global {bs_g1:.4f} vs {bs_g0:.4f} | "
              f"sparse {bs_s1:.4f} vs {bs_s0:.4f} ({mejora_s*100:+.1f}%, n={n_sp})")
        if not (bs_g1 <= bs_g0 * (1.0 + TOLERANCIA_GLOBAL) and mejora_s >= GATE_SPARSE_MIN):
            print("  ❌ NO PASA el gate ELO. ABORTANDO carga (Supabase intacto).")
            sys.exit(1)
        bs_m = bs_g1   # se guarda como brier_score de la versión
        print("  ✅ GREENLIGHT ELO — se procede a cargar intl_v0.2.")
        version = "intl_v0.2"
        # ELO de producción: SIN corte (todo el histórico, lo más fresco)
        elo_z_full = estandarizar(calcular_elo(partidos_elo))
        if variante == "blend_fifa":
            elo_z_full = blend_z(elo_z_full, cargar_z_fifa(), w=0.7)
```

- [ ] **Step 7.3: Fit de producción + insert con los campos nuevos**

En el paso 5 del script, el fit de producción pasa a:

```python
    if elo_z_full is not None:
        modelo = DixonColesIntl().fit(partidos, ref_prod, elo_z=elo_z_full,
                                      prior_scale=c, l2_prior=l2p)
    else:
        modelo = DixonColesIntl().fit(partidos, ref_prod)
```

y el `insert` usa `"version_modelo": version,` más dos campos nuevos:

```python
        "elo_params":  modelo.elo_z,          # None en modo clásico
        "prior_scale": modelo.prior_scale,
```

y en `notas`, si es v0.2, anteponer:
`f"PRIOR ELO ({variante}, c={c:.4f}, l2_prior={l2p}). "`.
El título del print inicial pasa de `(intl_v0.1)` a `({version})` (mover el print
después del parseo de args).

- [ ] **Step 7.4: Verificación sintáctica + suite**

Run: `python -c "import ast; ast.parse(open('load_intl_to_supabase.py', encoding='utf-8').read())" ; python -m pytest -q`
Expected: sin error de sintaxis; suite completa verde (el script no tiene tests —
patrón del repo para loaders gated — su defensa es el gate interno).

- [ ] **Step 7.5: Commit**

```bash
git add load_intl_to_supabase.py
git commit -m "feat(elo): modo intl_v0.2 en el loader (gate defensivo vs v0.1, elo_params+prior_scale)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 8: Loader del analyzer + enmienda del spec

**Files:**
- Modify: `analyzer.py:548-565` (`_load_intl_predictor`)
- Modify: `docs/superpowers/specs/2026-07-13-elo-prior-design.md`

- [ ] **Step 8.1: Pasar los 2 campos nuevos en `_load_intl_predictor`**

El `select` pasa a:

```python
            .select("mu, gamma, rho, attack_params, defense_params, elo_params, prior_scale")
```

y la construcción a:

```python
        _cached_intl_model = DixonColesIntl.from_params(
            mu=float(r["mu"]), gamma=float(r["gamma"]), rho=float(r["rho"]),
            attack=r["attack_params"], defense=r["defense_params"],
            elo_z=r.get("elo_params") or None,
            prior_scale=float(r.get("prior_scale") or 0.0),
        )
```

(`or None`/`or 0.0`: las filas v0.1 viejas traen NULL y todo sigue funcionando.)

- [ ] **Step 8.2: Suite completa**

Run: `python -m pytest -q`
Expected: todos passed (los mocks/params de tests existentes no traen los campos
nuevos y el `.get(...) or ...` los tolera; si algún test construye la fila con
`select` estricto, actualizarlo con los 2 campos en NULL).

- [ ] **Step 8.3: Enmendar el spec** (sección "2. Prior en `engine_intl_v01.fit`")

Añadir al final de esa sección del spec:

```markdown
> **Enmienda (plan 2026-07-13):** la l2 existente (0.001) tiene curvatura
> despreciable frente a la verosimilitud — un grid solo sobre c no movería nada.
> Mecanismo final: c (ancla) se estima por regresión α̂~z sobre equipos ≥30
> partidos del v0.1; la FUERZA del prior es un parámetro nuevo l2_prior con grid
> {0.25, 0.5, 1.0, 2.0, 4.0} (pseudo-partidos). El umbral sparse definitivo y el
> estado del blend FIFA se anotan aquí tras correr el gate: UMBRAL_SPARSE=___,
> blend_fifa=___ .
```

(rellenar los `___` con los valores reales de Task 5/6 — este es el único momento
en que un placeholder es legítimo porque lo rellena el gate.)

- [ ] **Step 8.4: Commit**

```bash
git add analyzer.py docs/superpowers/specs/2026-07-13-elo-prior-design.md
git commit -m "feat(elo): analyzer pasa elo_params/prior_scale al predictor intl + enmienda spec

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 9: Operación final — gate real, publicar, e2e, docs

Esta task es operacional (decisiones con datos reales, no código nuevo).

- [ ] **Step 9.1: Correr el gate definitivo**

Run: `python engine_intl_v01.py` (con `intl_results.csv` fresco — si tiene más de
unas semanas, correr antes `python download_intl_results.py` y `python download_intl_results.py elo`
para que ambos CSVs sean coherentes).
Analizar la tabla: ¿el segmento sparse mejora ≥3% sin dañar el global?

- [ ] **Step 9.2: Decidir según el resultado**

- **Alguna variante PASA** → `python load_intl_to_supabase.py <c> <l2_prior> <variante>`
  (los valores exactos los imprime la línea "Siguiente paso" del gate).
  ⚠ El insert re-carga también los partidos (recarga limpia) — es idempotente y
  esperado. Confirmar con Angel ANTES de publicar (escribe en Supabase compartida).
- **Ninguna PASA** → NO publicar. Guardar el diagnóstico en la memoria del proyecto
  (tabla completa del grid) y cerrar la rama solo con el código (el prior con
  `elo_z=None` es no-op; cero regresión). El fallback ELO del serving NO queda
  activo sin publicación (las filas v0.1 no traen elo_params) — anotarlo.

- [ ] **Step 9.3: E2E si se publicó**

Levantar el server (`python -m uvicorn main:app --port 8123`) y pegarle a
`http://127.0.0.1:8123/api/v1/parlay/demo`: las probs de las patas 1X2/over deben
seguir siendo sensatas (Argentina favorito claro vs Austria). Verificar en un
partido con selección chica (vía test de `lambdas()` con el modelo publicado o un
boleto demo) que el no-visto ya NO es "equipo promedio".

- [ ] **Step 9.4: Docs + cierre**

- `docs/COBERTURA.md`: en la fila de la familia Goles, actualizar el modelo a
  `Dixon-Coles + prior ELO (intl_v0.2)` con el resultado del gate (o anotar que no
  pasó, si no pasó).
- Rellenar los `___` de la enmienda del spec (Task 8.3) con los valores reales.
- Suite completa: `python -m pytest -q` → verde.
- Cierre de rama con el ritual de siempre (superpowers:finishing-a-development-branch):
  merge a master + push, borrar rama, actualizar memoria (roadmap: Fase 3 punto 5).

```bash
git add docs/COBERTURA.md docs/superpowers/specs/2026-07-13-elo-prior-design.md
git commit -m "docs(elo): resultado del gate ELO + cobertura actualizada

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
