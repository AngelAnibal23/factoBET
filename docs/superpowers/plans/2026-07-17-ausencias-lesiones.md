# Capa de Ausencias (lesiones/suspensiones) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El analyzer internacional ajusta λ por ausentes confirmados (Sofascore) y mata/degrada patas de jugador cuyo jugador no juega — sin tocar el fit ni Supabase.

**Architecture:** Tres unidades: `ajuste_ausencias.py` (lógica pura: cuotas→multiplicadores, clamp, cruce de nombres), `ausencias_sofascore.py` (caché JSON local + scrape Sofascore vía **subprocess en venv aparte** — Scrapling es incompatible con el runtime por deps), e integración en serving (`analyzer.py` + `betbuilder.py` + frontend). Todo el ajuste es efímero, por-predicción.

**Tech Stack:** Python 3.12, Scrapling (patchright) en `.venv-scrapling`, rapidfuzz, pytest, React (frontend).

**Spec:** `docs/superpowers/specs/2026-07-16-ausencias-lesiones-design.md`. Constantes del spec: `K_AUSENCIA=0.6`, `PENAL_DEF=0.05`, `CLAMP=[0.70,1.30]`, `TTL_CACHE=6h`, fuzzy ≥ 80 (token_set_ratio, mismo umbral que `PlayerModel.RESOLVER_UMBRAL`). Extensión menor acordada en plan: los resultados **sin dato** se cachean con TTL corto (1h) para no pagar ~2 min en cada re-análisis.

**Contexto del repo que cada task debe conocer:**
- `PlayerModel` (`player_model.py:91`): `resolver(nombre) -> player_id|None` (token_set_ratio ≥ 80), `equipo_de(pid)`, `jugadores[pid] = {"nombre","equipo","cuota_gol","cuota_asist"}`.
- `analyzer.py`: `_analyze_intl` (línea ~736), `_prob_for_selection_intl` (~332, calcula `lh, la = model.lambdas(home, away, neutral)` en la línea ~352), `_analyze_bet_builder_route` (~848, rama `liga == "internacional"` calcula `lh, la` en ~868), `ParlayAnalysis` dataclass (~111), `_load_player_model("Internacional")`.
- `betbuilder.py`: `analyze_bet_builder(parlay, lh, la, rho, version_modelo, margin, counts_model=, neutral=, player_model=, player_sot_model=)` (~193); patas player calculan `player_p` (~233-241) y entran al techo como marginal en `count_marginals` (~254); veredicto en `verdict()` (~149) — un `player_p=0.0` hace `ceiling=0` → SIN_VALOR por la lógica existente.
- Patrón Scrapling validado (spike 2026-06-25): `StealthyFetcher.fetch(url, network_idle=False, load_dom=False, timeout=60000)` + esperar ~7s en `page_action` (la app llama su API murada con contexto válido y puebla el DOM) + leer con `page.eval_on_selector_all`/`inner_text`. La API de sofascore está murada; solo sirve el DOM renderizado. Links de partido: `a[href*='/football/match/']`.

---

## Task 1: `ajuste_ausencias.py` — lógica pura (TDD)

**Files:**
- Create: `ajuste_ausencias.py`
- Test: `tests/test_ajuste_ausencias.py`

- [ ] **Step 1.1: Tests que fallan**

```python
"""Tests de la lógica pura de ausencias (spec 2026-07-16)."""
import pytest
from ajuste_ausencias import (
    Ausente, deltas_equipo, aplicar_ajuste, cruzar_pata,
    K_AUSENCIA, PENAL_DEF, CLAMP_MIN, CLAMP_MAX,
)


class _FakePlayerModel:
    """Mismo contrato que PlayerModel: resolver/equipo_de/jugadores."""
    def __init__(self, jugadores):
        self.jugadores = jugadores          # pid -> {nombre, equipo, cuota_gol}
    def resolver(self, nombre):
        for pid, j in self.jugadores.items():
            if nombre.lower() in j["nombre"].lower():
                return pid
        return None
    def equipo_de(self, pid):
        j = self.jugadores.get(pid)
        return j["equipo"] if j else None


PM = _FakePlayerModel({
    "p1": {"nombre": "Lionel Messi", "equipo": "Argentina", "cuota_gol": 0.30},
    "p2": {"nombre": "Suplente Perez", "equipo": "Argentina", "cuota_gol": 0.01},
})


def test_deltas_ofensivo_por_cuota():
    aus = [Ausente(nombre="Lionel Messi", estado="out", motivo="Injured")]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert atk == pytest.approx(1.0 - K_AUSENCIA * 0.30)   # 0.82
    assert dfn == 1.0


def test_deltas_doubtful_no_ajusta():
    aus = [Ausente(nombre="Lionel Messi", estado="doubtful", motivo="Knock")]
    assert deltas_equipo(aus, "Argentina", PM) == (1.0, 1.0)


def test_deltas_defensivo_por_posicion():
    aus = [Ausente(nombre="Central Gomez", estado="out", posicion="D")]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert atk == 1.0 and dfn == pytest.approx(1.0 + PENAL_DEF)


def test_deltas_equipo_equivocado_no_cruza():
    # Messi está en Argentina; el ausente reportado es de Francia -> no ajusta.
    aus = [Ausente(nombre="Lionel Messi", estado="out")]
    assert deltas_equipo(aus, "France", PM) == (1.0, 1.0)


def test_deltas_desconocido_sin_cuota_ni_posicion_no_ajusta():
    aus = [Ausente(nombre="Fulano Nadie", estado="out")]
    assert deltas_equipo(aus, "Argentina", PM) == (1.0, 1.0)


def test_deltas_clamp_equipo_diezmado():
    aus = [Ausente(nombre=f"Central {i}", estado="out", posicion="D") for i in range(9)]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert dfn == pytest.approx(CLAMP_MAX)   # 1.05^9 ≈ 1.55 -> clamp 1.30
    assert CLAMP_MIN <= atk <= CLAMP_MAX


def test_aplicar_ajuste_direcciones():
    # def del visitante debilitada (1.05) SUBE lh; ataque local mermado lo BAJA.
    lh, la = aplicar_ajuste(1.5, 1.0, deltas_home=(0.82, 1.0), deltas_away=(1.0, 1.05))
    assert lh == pytest.approx(1.5 * 0.82 * 1.05)
    assert la == pytest.approx(1.0)


def test_cruzar_pata_exacto_fuzzy_y_none():
    aus = [Ausente(nombre="Lionel Messi", estado="out", motivo="Injured - Muscle")]
    assert cruzar_pata("Messi", aus).estado == "out"
    assert cruzar_pata("L. Messi", aus).motivo == "Injured - Muscle"
    assert cruzar_pata("Julian Alvarez", aus) is None
```

- [ ] **Step 1.2: Verificar que fallan**

Run: `python -m pytest tests/test_ajuste_ausencias.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ajuste_ausencias'`

- [ ] **Step 1.3: Implementación**

```python
"""Lógica pura de la capa de ausencias: ausentes -> multiplicadores de λ y cruce
de patas de jugador. Sin I/O. Spec: docs/superpowers/specs/2026-07-16-ausencias-lesiones-design.md."""
from dataclasses import dataclass
from rapidfuzz import fuzz

K_AUSENCIA = 0.6          # fracción de la cuota del ausente que realmente se pierde
PENAL_DEF = 0.05          # +5% λ concedido por titular defensivo/arquero out
CLAMP_MIN, CLAMP_MAX = 0.70, 1.30
UMBRAL_NOMBRE = 80.0      # token_set_ratio, mismo que PlayerModel.RESOLVER_UMBRAL
POSICIONES_DEFENSIVAS = {"d", "g", "df", "gk", "defender", "goalkeeper", "defensa", "arquero"}


@dataclass
class Ausente:
    nombre: str
    estado: str                     # "out" | "doubtful"
    motivo: str = ""
    posicion: str | None = None


def _clamp(x: float) -> float:
    return max(CLAMP_MIN, min(CLAMP_MAX, x))


def _cuota_ofensiva(nombre: str, equipo: str, player_model) -> float | None:
    """cuota_gol del ausente en el player model, con guard de equipo (un fuzzy
    global sin guard cruzaría homónimos de otra selección)."""
    if player_model is None:
        return None
    pid = player_model.resolver(nombre)
    if pid is None:
        return None
    eq = player_model.equipo_de(pid)
    if not eq or fuzz.token_set_ratio(eq.lower(), equipo.lower()) < UMBRAL_NOMBRE:
        return None
    return player_model.jugadores[pid].get("cuota_gol")


def deltas_equipo(ausentes: list[Ausente], equipo: str, player_model) -> tuple[float, float]:
    """(mult_ataque, mult_defensa) del equipo. Solo estado 'out' ajusta.
    Defensivo/arquero por posición conocida; ofensivo por cuota del player model;
    sin cuota NI posición -> no se inventa ajuste (spec, tabla de errores)."""
    mult_atk, mult_def = 1.0, 1.0
    for a in ausentes:
        if a.estado != "out":
            continue
        if (a.posicion or "").strip().lower() in POSICIONES_DEFENSIVAS:
            mult_def *= (1.0 + PENAL_DEF)
            continue
        q = _cuota_ofensiva(a.nombre, equipo, player_model)
        if q:
            mult_atk *= (1.0 - K_AUSENCIA * q)
    return _clamp(mult_atk), _clamp(mult_def)


def aplicar_ajuste(lh: float, la: float,
                   deltas_home: tuple[float, float],
                   deltas_away: tuple[float, float]) -> tuple[float, float]:
    """lh = goles del local: lo merma su ataque y lo sube la defensa mermada
    del rival. Simétrico para la."""
    atk_h, def_h = deltas_home
    atk_a, def_a = deltas_away
    return lh * atk_h * def_a, la * atk_a * def_h


def cruzar_pata(nombre_pata: str, ausentes: list[Ausente]) -> Ausente | None:
    """Mejor match por nombre entre la pata de jugador y los ausentes (>=80).
    'out' gana sobre 'doubtful' si ambos matchean."""
    hits = [a for a in ausentes
            if fuzz.token_set_ratio(nombre_pata.lower(), a.nombre.lower()) >= UMBRAL_NOMBRE]
    if not hits:
        return None
    return sorted(hits, key=lambda a: a.estado != "out")[0]
```

- [ ] **Step 1.4: Verificar que pasan**

Run: `python -m pytest tests/test_ajuste_ausencias.py -q` → Expected: 8 passed.

- [ ] **Step 1.5: Suite completa + commit**

Run: `python -m pytest -q` → Expected: todos passed (277 + 8).

```bash
git add ajuste_ausencias.py tests/test_ajuste_ausencias.py
git commit -m "feat(ausencias): logica pura — deltas por cuota/posicion, clamp, cruce de patas

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: `ausencias_sofascore.py` — caché + subprocess (TDD)

**Files:**
- Create: `ausencias_sofascore.py` (solo la mitad runtime; el CLI scrape es Task 3)
- Test: `tests/test_ausencias_sofascore.py`
- Modify: `.gitignore` (añadir `cache_ausencias/` y `.venv-scrapling/`)

El runtime de la API NUNCA importa scrapling (deps incompatibles: playwright/patchright
vs supabase/websockets). El scrape corre como subprocess con el python de
`.venv-scrapling`; este módulo solo maneja caché + subprocess + parseo.

- [ ] **Step 2.1: Tests que fallan**

```python
"""Tests del runtime de ausencias: caché TTL + subprocess mockeado. Nunca scrapea."""
import json, subprocess, time
import ausencias_sofascore as mod


PAYLOAD = {
    "equipos": {"Argentina": [{"nombre": "Lionel Messi", "estado": "out",
                               "motivo": "Injured - Muscle", "posicion": None}],
                "France": []},
    "url": "https://www.sofascore.com/football/match/x", "scrapeado_en": "2026-07-17T10:00:00",
}


def _fake_run_ok(*args, **kwargs):
    class R:
        returncode, stdout, stderr = 0, json.dumps(PAYLOAD), ""
    return R()


def test_scrape_ok_parsea_y_cachea(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    r = mod.obtener_ausencias("Argentina", "France")
    assert r["equipos"]["Argentina"][0].nombre == "Lionel Messi"
    assert r["equipos"]["Argentina"][0].estado == "out"
    assert (tmp_path / "argentina__france.json").exists()


def test_cache_vigente_no_llama_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time(), "payload": PAYLOAD}), encoding="utf-8")
    def _boom(*a, **k): raise AssertionError("no debe scrapear con cache vigente")
    monkeypatch.setattr(subprocess, "run", _boom)
    r = mod.obtener_ausencias("Argentina", "France")
    assert r["equipos"]["Argentina"][0].nombre == "Lionel Messi"


def test_cache_vencida_rescrapea(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time() - mod.TTL_SEGUNDOS - 60,
                    "payload": PAYLOAD}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    assert mod.obtener_ausencias("Argentina", "France") is not None


def test_fallo_subprocess_devuelve_none_y_cachea_negativo(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    def _timeout(*a, **k): raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(subprocess, "run", _timeout)
    assert mod.obtener_ausencias("Argentina", "France") is None
    data = json.loads((tmp_path / "argentina__france.json").read_text(encoding="utf-8"))
    assert data["payload"]["sin_dato"] is True


def test_sin_dato_cacheado_respeta_ttl_corto(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time() - mod.TTL_SIN_DATO - 60,
                    "payload": {"sin_dato": True}}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)   # vencido -> re-scrapea
    assert mod.obtener_ausencias("Argentina", "France") is not None


def test_cache_corrupto_se_ignora(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text("{basura", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    assert mod.obtener_ausencias("Argentina", "France") is not None
```

- [ ] **Step 2.2: Verificar que fallan**

Run: `python -m pytest tests/test_ausencias_sofascore.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 2.3: Implementación (mitad runtime)**

```python
"""Fuente de ausencias (Sofascore) para el serving: caché local JSON + scrape en
subprocess. El scrape (CLI `scrape`, Task 3) corre BAJO .venv-scrapling porque
scrapling/patchright es incompatible con el venv del runtime. Este módulo se
importa desde analyzer sin dependencias nuevas.

Contrato de obtener_ausencias: dict {"equipos": {equipo: [Ausente,...]},
"url", "scrapeado_en"} o None (sin dato — el análisis sigue SIN ajuste)."""
import json
import os
import re
import subprocess
import sys
import time

from ajuste_ausencias import Ausente

_REPO = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_REPO, "cache_ausencias")
TTL_SEGUNDOS = 6 * 3600      # spec: TTL_CACHE = 6h
TTL_SIN_DATO = 1 * 3600      # negativo se reintenta antes (extensión acordada en plan)
SCRAPE_TIMEOUT = 240         # s — el browser stealth tarda ~2 min
_PY_SCRAPLING = os.environ.get(
    "SCRAPLING_PYTHON",
    os.path.join(_REPO, ".venv-scrapling", "Scripts", "python.exe"),
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _cache_path(home: str, away: str) -> str:
    return os.path.join(CACHE_DIR, f"{_slug(home)}__{_slug(away)}.json")


def _leer_cache(path: str) -> dict | None:
    """payload cacheado y vigente, o None. TTL corto para payloads sin_dato."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        payload = data["payload"]
        ttl = TTL_SIN_DATO if payload.get("sin_dato") else TTL_SEGUNDOS
        if time.time() - data["guardado_en"] <= ttl:
            return payload
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _escribir_cache(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"guardado_en": time.time(), "payload": payload}, f, ensure_ascii=False)


def _parsear(payload: dict) -> dict:
    return {
        "equipos": {eq: [Ausente(**a) for a in lst]
                    for eq, lst in payload.get("equipos", {}).items()},
        "url": payload.get("url"),
        "scrapeado_en": payload.get("scrapeado_en"),
    }


def obtener_ausencias(home: str, away: str) -> dict | None:
    path = _cache_path(home, away)
    payload = _leer_cache(path)
    if payload is None:
        try:
            r = subprocess.run(
                [_PY_SCRAPLING, os.path.abspath(__file__), "scrape", home, away],
                capture_output=True, text=True, encoding="utf-8",
                timeout=SCRAPE_TIMEOUT,
            )
            if r.returncode == 0 and r.stdout.strip():
                payload = json.loads(r.stdout)
            else:
                payload = {"sin_dato": True, "motivo": f"scrape rc={r.returncode}"}
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
            payload = {"sin_dato": True, "motivo": type(e).__name__}
        _escribir_cache(path, payload)
    if payload.get("sin_dato"):
        return None
    return _parsear(payload)
```

- [ ] **Step 2.4: Verificar que pasan + gitignore**

Run: `python -m pytest tests/test_ausencias_sofascore.py -q` → Expected: 6 passed.

Añadir a `.gitignore` (junto a `fifa_ranking.csv`):
```
cache_ausencias/
.venv-scrapling/
```

- [ ] **Step 2.5: Suite completa + commit**

Run: `python -m pytest -q` → Expected: todos passed.

```bash
git add ausencias_sofascore.py tests/test_ausencias_sofascore.py .gitignore
git commit -m "feat(ausencias): runtime de fuente — cache TTL 6h/1h + scrape via subprocess

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: CLI scrape con Scrapling + venv (operacional + smoke live)

**Files:**
- Modify: `ausencias_sofascore.py` (añadir el bloque CLI al final)
- Create: `.venv-scrapling/` (local, gitignored — Step 3.1)

⚠ Esta task tiene una parte NO determinista (scrape live). El criterio de éxito del
smoke es: JSON válido por stdout (con `equipos` o con `sin_dato` — ambos son éxito
del MECANISMO; `sin_dato` solo significa que Sofascore no listaba ese partido/dato).

- [ ] **Step 3.1: Crear el venv de scraping**

```powershell
python -m venv .venv-scrapling
.venv-scrapling\Scripts\pip install "scrapling[fetchers]" rapidfuzz
.venv-scrapling\Scripts\python -m scrapling install
```

(el último paso baja el browser de patchright; si `-m scrapling install` no existe en
la versión instalada, el comando equivalente es `.venv-scrapling\Scripts\scrapling install`).
Verificar: `.venv-scrapling\Scripts\python -c "from scrapling.fetchers import StealthyFetcher; print('ok')"` → `ok`.

- [ ] **Step 3.2: Añadir el bloque CLI al final de `ausencias_sofascore.py`**

El código de referencia sigue el patrón VALIDADO del spike 2026-06-25 (memoria del
proyecto). La API exacta de scrapling 0.4.x puede variar en nombres de kwargs —
**ajustar contra la librería instalada**, manteniendo el patrón: fetch stealth →
esperar ~7s a que la app pueble el DOM → leer DOM. Nada de `api.sofascore.com` (murada).

```python
# ── CLI scrape (corre BAJO .venv-scrapling; el runtime nunca importa scrapling) ──

_DIAS_BUSQUEDA = 4          # hoy..+3: ventana donde vive un boleto real
_ESPERA_DOM_MS = 8000       # la app llama su API interna y renderiza (~7s en el spike)
_UMBRAL_LINK = 80


def _match_link(texto: str, home: str, away: str) -> bool:
    from rapidfuzz import fuzz
    t = (texto or "").lower()
    return (fuzz.token_set_ratio(home.lower(), t) >= _UMBRAL_LINK and
            fuzz.token_set_ratio(away.lower(), t) >= _UMBRAL_LINK)


def _clasificar_estado(texto: str) -> str:
    return "doubtful" if any(w in texto.lower() for w in ("doubt", "question")) else "out"


def _extraer_ausentes(texto_pagina: str, home: str, away: str) -> dict:
    """Parsea la sección de ausentes del inner_text del partido. Formato observado
    en el spike: bloques 'Missing players' por equipo con líneas
    'Nombre' / 'Injured - Muscle' (o 'Suspended', 'Doubtful'). Se parsea por
    ventanas de texto entre el nombre del equipo y la siguiente sección."""
    equipos: dict = {home: [], away: []}
    # Implementación por regex sobre líneas: un nombre propio seguido de una línea
    # de motivo conocida. Motivos vistos: Injured, Suspended, Doubtful, Personal.
    import re as _re
    lineas = [l.strip() for l in texto_pagina.splitlines() if l.strip()]
    motivo_re = _re.compile(r"^(Injur|Suspend|Doubt|Question|Personal|Illness)", _re.I)
    lado = None
    for i, linea in enumerate(lineas):
        if linea == home or linea.lower() == home.lower():
            lado = home
        elif linea == away or linea.lower() == away.lower():
            lado = away
        if lado and i + 1 < len(lineas) and motivo_re.match(lineas[i + 1]):
            equipos[lado].append({
                "nombre": linea, "estado": _clasificar_estado(lineas[i + 1]),
                "motivo": lineas[i + 1], "posicion": None,
            })
    return equipos


def _scrape(home: str, away: str) -> dict:
    from datetime import date, timedelta, datetime
    from scrapling.fetchers import StealthyFetcher

    def _esperar(page):
        page.wait_for_timeout(_ESPERA_DOM_MS)
        return page

    hoy = date.today()
    url_partido = None
    for d in range(_DIAS_BUSQUEDA):
        fecha = (hoy + timedelta(days=d)).isoformat()
        page = StealthyFetcher.fetch(
            f"https://www.sofascore.com/football/{fecha}",
            network_idle=False, load_dom=False, timeout=60000, page_action=_esperar,
        )
        for a in page.css("a[href*='/football/match/']"):
            href = a.attrib.get("href", "")
            if _match_link(a.text, home, away):
                url_partido = "https://www.sofascore.com" + href
                break
        if url_partido:
            break
    if not url_partido:
        return {"sin_dato": True, "motivo": f"partido no encontrado hoy..+{_DIAS_BUSQUEDA - 1}d"}

    page = StealthyFetcher.fetch(url_partido, network_idle=False, load_dom=False,
                                 timeout=60000, page_action=_esperar)
    texto = page.get_all_text() if hasattr(page, "get_all_text") else page.body
    equipos = _extraer_ausentes(texto, home, away)
    return {"equipos": equipos, "url": url_partido,
            "scrapeado_en": datetime.now().isoformat(timespec="seconds")}


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "scrape":
        try:
            print(json.dumps(_scrape(sys.argv[2], sys.argv[3]), ensure_ascii=False))
        except Exception as e:   # el runtime interpreta stdout-JSON, nunca traza
            print(json.dumps({"sin_dato": True, "motivo": f"{type(e).__name__}: {e}"}))
    else:
        print(json.dumps({"sin_dato": True, "motivo": "uso: scrape <home> <away>"}))
```

- [ ] **Step 3.3: Test unitario del parser (sin browser)**

Añadir a `tests/test_ausencias_sofascore.py`:

```python
def test_extraer_ausentes_parsea_bloques():
    texto = "\n".join([
        "Türkiye", "Hakan Calhanoglu", "Suspended",
        "USA", "Cristian Roldán", "Injured - Muscle",
        "Tim Weah", "Doubtful",
    ])
    r = mod._extraer_ausentes(texto, "Türkiye", "USA")
    assert r["Türkiye"][0]["estado"] == "out"          # Suspended -> out
    assert r["USA"][0]["motivo"] == "Injured - Muscle"
    assert r["USA"][1]["estado"] == "doubtful"
```

Run: `python -m pytest tests/test_ausencias_sofascore.py -q` → Expected: 7 passed.
(el import de scrapling es lazy dentro de `_scrape`: la suite NO lo necesita.)

- [ ] **Step 3.4: Smoke live (elegir un partido internacional REAL de hoy/mañana)**

Buscar en el calendario real un partido internacional próximo (el ejecutor lo elige
al momento). Run:

```powershell
.venv-scrapling\Scripts\python ausencias_sofascore.py scrape "<Home>" "<Away>"
```

Expected: una línea JSON válida con `equipos` (aunque las listas vengan vacías) o
`sin_dato` con motivo. Si el DOM cambió y `_extraer_ausentes` no matchea, ajustar el
parser contra `inner_text` real (guardarlo a un archivo del scratchpad para iterar)
— el patrón fetch/espera es el validado, el parser es la parte viva.

- [ ] **Step 3.5: Smoke del camino completo runtime→subprocess**

```powershell
python -c "from ausencias_sofascore import obtener_ausencias; print(obtener_ausencias('<Home>', '<Away>'))"
```

Expected: dict con `equipos` o `None`; segunda corrida instantánea (caché).

- [ ] **Step 3.6: Suite completa + commit**

Run: `python -m pytest -q` → Expected: todos passed.

```bash
git add ausencias_sofascore.py tests/test_ausencias_sofascore.py
git commit -m "feat(ausencias): CLI scrape Sofascore (Scrapling render+DOM) + parser de ausentes

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: `betbuilder.py` — cruce de patas de jugador + veredicto (TDD)

**Files:**
- Modify: `betbuilder.py` (`analyze_bet_builder`, ~193)
- Test: `tests/test_betbuilder_ausencias.py`

Reglas del spec: pata de jugador con ausente **out** → `prob_modelo = 0.0` (la lógica
existente de techo hace el resto: marginal 0 → ceiling 0 → SIN_VALOR) + razón visible.
**doubtful** → prob intacta + alerta + si el veredicto salía VALOR se degrada a
NO_CONCLUYENTE (sin Kelly).

- [ ] **Step 4.1: Tests que fallan**

Mirar `tests/test_betbuilder*.py` existentes para copiar el patrón de fixtures
(parlay fake con selecciones player). Tests mínimos:

```python
"""Cruce de ausencias en el bet builder (spec 2026-07-16)."""
import pytest
from ajuste_ausencias import Ausente
from betbuilder import analyze_bet_builder

# Reusar los helpers/fixtures de parlay fake del test de betbuilder existente
# (importarlos o copiarlos: _sel_player, _parlay, modelo player fake con Messi).


AUSENCIAS = {"equipos": {"Argentina": [Ausente(nombre="Lionel Messi", estado="out",
                                               motivo="Injured - Muscle")],
                         "France": []},
             "url": "http://x", "scrapeado_en": "2026-07-17T10:00:00"}


def test_pata_out_mata_el_boleto():
    # parlay: 1 pata player "Messi anota" + cuota_total 2.0, equipos cubiertos
    res = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=AUSENCIAS)
    pata = res.selecciones[0]
    assert pata.prob_modelo == 0.0
    assert res.veredicto == "SIN_VALOR"
    assert any("no juega" in a.lower() for a in pata.alertas)


def test_pata_doubtful_degrada_valor_a_no_concluyente():
    dudoso = {"equipos": {"Argentina": [Ausente(nombre="Lionel Messi",
                                                estado="doubtful", motivo="Knock")],
              "France": []}}
    res = analyze_bet_builder(parlay_valor, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=dudoso)
    assert res.veredicto == "NO_CONCLUYENTE"
    assert res.bet_builder_kelly is None
    assert any("duda" in a.lower() for a in res.selecciones[0].alertas)


def test_sin_ausencias_todo_igual():
    a = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                            player_model=player_model_fake)
    b = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                            player_model=player_model_fake, ausencias=None)
    assert a.veredicto == b.veredicto and a.prob_techo == b.prob_techo


def test_ausente_de_otro_jugador_no_toca_la_pata():
    otras = {"equipos": {"Argentina": [Ausente(nombre="Nicolas Otamendi", estado="out")],
                         "France": []}}
    res = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=otras)
    assert res.selecciones[0].prob_modelo not in (None, 0.0)
```

(El implementador completa los fixtures `parlay`/`parlay_valor`/`player_model_fake`
copiando el patrón del test de betbuilder existente — parlay con `cuota_total`,
selección `mercado="player"`, `metric="goal"`, `player="Messi"`, `local_match`/
`visitante_match` con `canonical`; `parlay_valor` con cuota baja para que sin
ausencias salga VALOR.)

- [ ] **Step 4.2: Verificar que fallan**

Run: `python -m pytest tests/test_betbuilder_ausencias.py -q`
Expected: FAIL — `analyze_bet_builder() got an unexpected keyword argument 'ausencias'`

- [ ] **Step 4.3: Implementación**

En `betbuilder.py`:

1. Firma: `def analyze_bet_builder(parlay, lh, la, rho, version_modelo, margin, counts_model=None, neutral=False, player_model=None, player_sot_model=None, ausencias=None):`
2. Import arriba del módulo: `from ajuste_ausencias import cruzar_pata`.
3. Antes del loop de selecciones:

```python
    todos_ausentes = []
    if ausencias:
        for lst in ausencias.get("equipos", {}).values():
            todos_ausentes.extend(lst)
    hay_doubtful_en_pata = False
```

4. Dentro del loop, DESPUÉS de calcular `player_p` (tras la línea ~241) y ANTES del
   ladder de `if is_goal and covered:` — el cruce pisa el cálculo normal:

```python
        hit = cruzar_pata(sel.player, todos_ausentes) if (is_player and sel.player and todos_ausentes) else None
        if hit is not None and hit.estado == "out":
            player_p = 0.0    # pata muerta: entra al techo como marginal 0 -> SIN_VALOR
        # el ladder de abajo maneja player_p normalmente; las alertas se ajustan después
```

   y tras el ladder (donde ya existen `prob_mod`/`alertas`), antes del
   `analyses.append(...)`:

```python
        if hit is not None and hit.estado == "out":
            alertas = [f"{sel.player} no juega ({hit.motivo or 'ausencia confirmada'}): pata muerta."]
            nivel_cov = "ALTA"   # certeza del dato, no del modelo
        elif hit is not None and hit.estado == "doubtful":
            alertas = alertas + [f"{sel.player} en duda ({hit.motivo or 'doubtful'}): el veredicto no puede afirmar valor."]
            hay_doubtful_en_pata = True
```

5. Tras `vered, kelly = verdict(...)` (~306):

```python
    if hay_doubtful_en_pata and vered == "VALOR":
        vered, kelly = "NO_CONCLUYENTE", None
        razones = razones + ["Jugador en duda por lesión: techo válido pero la pata puede caerse."]
```

   ⚠ Ojo al orden: `bb_confidence` se llama con el veredicto FINAL (mover la línea
   de `nivel_conf, razones = bb_confidence(...)` a después de esta degradación, y
   luego anexar la razón).

6. En el `ParlayAnalysis(...)` final añadir `ausencias=_ausencias_a_dict(ausencias),`
   con el helper (en `betbuilder.py`, junto a los otros helpers):

```python
def _ausencias_a_dict(ausencias):
    """Serializa el bloque para la respuesta JSON (None -> sin_dato explícito)."""
    if not ausencias:
        return None
    from dataclasses import asdict
    return {
        "equipos": {eq: [asdict(a) for a in lst]
                    for eq, lst in ausencias.get("equipos", {}).items()},
        "url": ausencias.get("url"), "scrapeado_en": ausencias.get("scrapeado_en"),
        "lambdas": ausencias.get("lambdas"),
    }
```

   (El campo `ausencias` del dataclass `ParlayAnalysis` se añade en Task 5 — Task 4
   y 5 se pueden implementar en este orden solo si el campo ya existe; por eso el
   **primer paso real de esta task es añadir el campo**: en `analyzer.py`, dataclass
   `ParlayAnalysis` (~111), añadir al FINAL de los campos: `ausencias: Optional[dict] = None`.)

- [ ] **Step 4.4: Verificar que pasan**

Run: `python -m pytest tests/test_betbuilder_ausencias.py -q` → Expected: 4 passed.

- [ ] **Step 4.5: Suite completa + commit**

Run: `python -m pytest -q` → Expected: todos passed (regresión: los tests existentes
de betbuilder no pasan `ausencias` y nada cambia para ellos).

```bash
git add betbuilder.py analyzer.py tests/test_betbuilder_ausencias.py
git commit -m "feat(ausencias): pata de jugador out mata el boleto; doubtful degrada el veredicto

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 5: `analyzer.py` — integración en serving (TDD)

**Files:**
- Modify: `analyzer.py` (`_prob_for_selection_intl` ~332, `_analyze_intl` ~736, `_analyze_bet_builder_route` ~848)
- Test: `tests/test_analyzer_ausencias.py`

- [ ] **Step 5.1: Tests que fallan**

```python
"""Integración de ausencias en el analyzer intl. obtener_ausencias SIEMPRE mockeado."""
import analyzer
from ajuste_ausencias import Ausente

# Fixtures: modelo intl fake via DixonColesIntl.from_params (patrón de
# tests/test_analyzer_intl.py — copiar el parlay 1X2 de ahí) con Argentina/France.

AUS = {"equipos": {"Argentina": [Ausente(nombre="Lionel Messi", estado="out",
                                          motivo="Injured")], "France": []},
       "url": "http://x", "scrapeado_en": "t"}


def test_analyze_intl_ajusta_lambdas(monkeypatch):
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: AUS)
    monkeypatch.setattr(analyzer, "_load_player_model", lambda liga: player_model_fake)
    res_con = analyzer._analyze_intl(parlay_1x2, model_fake)
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None)
    res_sin = analyzer._analyze_intl(parlay_1x2, model_fake)
    # Messi out -> ataque argentino mermado -> prob de "Argentina gana" BAJA
    assert res_con.selecciones[0].prob_modelo < res_sin.selecciones[0].prob_modelo
    assert res_con.ausencias["equipos"]["Argentina"][0]["nombre"] == "Lionel Messi"
    assert res_con.ausencias["lambdas"]["Argentina - France"]["antes"] != \
           res_con.ausencias["lambdas"]["Argentina - France"]["despues"]


def test_analyze_intl_sin_dato_no_ajusta_y_lo_dice(monkeypatch):
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None)
    res = analyzer._analyze_intl(parlay_1x2, model_fake)
    assert res.ausencias == {"sin_dato": True}


def test_route_betbuilder_intl_pasa_ausencias(monkeypatch):
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: AUS)
    # ... montar route con monkeypatch de _load_intl_predictor y modelos None
    res = analyzer._analyze_bet_builder_route(parlay_bb_intl, "internacional", 0.06)
    assert res.ausencias is not None and "equipos" in res.ausencias
```

(Fixtures: reusar el patrón de `tests/test_analyzer_intl.py` — ahí ya hay parlays
fake y `DixonColesIntl.from_params`; para el route, monkeypatch de
`analyzer._load_intl_predictor`, `_load_counts_model`, `_load_player_model`,
`_load_player_sot_model` como hacen los tests de route existentes.)

- [ ] **Step 5.2: Verificar que fallan**

Run: `python -m pytest tests/test_analyzer_ausencias.py -q`
Expected: FAIL — `AttributeError: module 'analyzer' has no attribute 'obtener_ausencias'`

- [ ] **Step 5.3: Implementación**

En `analyzer.py`:

1. Imports arriba (junto a los del motor): `from ausencias_sofascore import obtener_ausencias` y `from ajuste_ausencias import deltas_equipo, aplicar_ajuste`.

2. `_prob_for_selection_intl(model, sel, neutral, mults=None)`: tras
   `lh, la = model.lambdas(home, away, neutral)` (~352):

```python
    if mults is not None:
        lh, la = aplicar_ajuste(lh, la, mults[0], mults[1])
```

3. Helper nuevo (después de `_marcadores_intl`):

```python
def _ausencias_del_parlay(parlay) -> tuple[dict, dict | None]:
    """Consulta ausencias por partido distinto del parlay (normalmente 1).
    Devuelve (mults_por_partido, bloque_respuesta). Falla suave: sin dato ->
    ({}, {"sin_dato": True})."""
    player = _load_player_model("Internacional")
    mults: dict = {}
    bloque_eq: dict = {}
    bloque_lam: dict = {}
    urls = []
    vistos = set()
    for sel in parlay.selecciones:
        home = sel.local_match.canonical
        away = sel.visitante_match.canonical if sel.visitante_match else None
        if not away or (home, away) in vistos:
            continue
        vistos.add((home, away))
        aus = obtener_ausencias(home, away)
        if aus is None:
            continue
        d_home = deltas_equipo(aus["equipos"].get(home, []), home, player)
        d_away = deltas_equipo(aus["equipos"].get(away, []), away, player)
        mults[(home, away)] = (d_home, d_away, aus)
        from dataclasses import asdict
        for eq, lst in aus["equipos"].items():
            bloque_eq[eq] = [asdict(a) for a in lst]
        urls.append(aus.get("url"))
    if not mults:
        return {}, {"sin_dato": True}
    return mults, {"equipos": bloque_eq, "urls": urls, "lambdas": bloque_lam}
```

   (`bloque_lam` se llena en el punto 4, donde ya hay λ: clave `f"{home} - {away}"`,
   valor `{"antes": [lh, la], "despues": [lh2, la2]}`.)

4. `_analyze_intl`: al inicio (tras `margin`), `mults_map, bloque = _ausencias_del_parlay(parlay)`.
   En el loop, para cada sel: `entry = mults_map.get((home, away or ""))` —
   construir la clave con los mismos `home/away` del loop; si `entry`, pasar
   `mults=(entry[0], entry[1])` a `_prob_for_selection_intl`, y registrar en
   `bloque["lambdas"]` el antes/después (calcular `lh0, la0 = model.lambdas(...)` y
   `aplicar_ajuste` una vez por partido, no por sel). Al final:
   `return ParlayAnalysis(..., ausencias=bloque)`.
   ⚠ `_marcadores_intl` se queda SIN ajuste (marcador ilustrativo; YAGNI).

5. `_analyze_bet_builder_route`, rama `liga == "internacional"`, tras calcular
   `lh, la` (~868):

```python
            ausencias_match = None
            if lh is not None:
                mults_map, _ = _ausencias_del_parlay(parlay)
                entry = mults_map.get((home, away))
                if entry:
                    d_home, d_away, ausencias_match = entry
                    lh0, la0 = lh, la
                    lh, la = aplicar_ajuste(lh, la, d_home, d_away)
                    ausencias_match = dict(ausencias_match)
                    ausencias_match["lambdas"] = {"antes": [round(lh0, 4), round(la0, 4)],
                                                  "despues": [round(lh, 4), round(la, 4)]}
```

   y en el `return analyze_bet_builder(...)` añadir `ausencias=ausencias_match`.
   Si `_ausencias_del_parlay` devolvió `{}` (sin dato), `ausencias_match` queda
   `None` → betbuilder serializa `None` → el frontend muestra "sin dato" cuando el
   campo llegue `null` y la liga sea internacional.

6. Rama liga1 del route: sin cambios (spec: solo Internacional).

- [ ] **Step 5.4: Verificar que pasan + regresión**

Run: `python -m pytest tests/test_analyzer_ausencias.py -q` → Expected: 3 passed.
Run: `python -m pytest -q` → Expected: todos passed. ⚠ Los tests intl existentes NO
mockean `obtener_ausencias` — el import en analyzer hace que `_analyze_intl` la llame
de verdad: como no existe `.venv-scrapling` en CI de tests, `subprocess.run` fallará
→ `None` → sin ajuste → los tests viejos pasan igual PERO pagan el intento. Para que
la suite no toque disco/subprocess: en `tests/conftest.py` añadir un autouse fixture:

```python
import pytest

@pytest.fixture(autouse=True)
def _sin_scrape_real(monkeypatch):
    """Ningún test dispara el scrape real; los que prueban ausencias re-mockean."""
    import analyzer
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None, raising=False)
```

(los tests de Task 5 re-monkeypatchean encima — el suyo gana por orden de aplicación.)

- [ ] **Step 5.5: Verificar serialización en main.py**

Leer cómo `main.py` serializa `ParlayAnalysis` (busca `asdict`): si usa
`dataclasses.asdict`, el campo `ausencias` sale solo. Si construye el dict a mano,
añadir la clave. Verificar con:
`python -c "from dataclasses import asdict; from analyzer import ParlayAnalysis; ..."`
o revisando el endpoint. Ajustar si hace falta.

- [ ] **Step 5.6: Commit**

```bash
git add analyzer.py tests/test_analyzer_ausencias.py tests/conftest.py
git commit -m "feat(ausencias): analyzer intl ajusta lambdas por ausentes y expone el bloque

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 6: Frontend — etapa del loader + bloque de ausencias

**Files:**
- Modify: `frontend/src/components/Spinner.jsx`
- Create: `frontend/src/components/AusenciasBlock.jsx`
- Modify: `frontend/src/App.jsx` (render del bloque, junto a `MarcadorProbable`)

- [ ] **Step 6.1: Etapa en el loader**

En `Spinner.jsx`, `STAGES` (líneas 3-9), insertar entre "Identificando equipos…" y
"Corriendo modelo…":

```js
  { at: 13, label: 'Consultando ausencias en Sofascore… (puede tardar ~2 min)' },
```

y recorrer los `at` siguientes (`Corriendo modelo…` pasa a `at: 100`, `Cruzando
probabilidades…` a `at: 130`) — con caché el fetch responde antes y el loader
desaparece solo; sin caché la etapa acompaña la espera real.

- [ ] **Step 6.2: `AusenciasBlock.jsx`**

Copiar el patrón visual de `MarcadorProbable.jsx` (leerlo primero: estructura de
card, clases CSS del design system). Contrato de datos (`analysis.ausencias`):
`null` → no renderizar nada (liga1/legacy); `{sin_dato: true}` → línea discreta
"Sin dato de ausencias para este partido (Sofascore aún no publica)."; con
`equipos` → por equipo con ausentes, lista `nombre — motivo` (badge rojo "NO JUEGA"
para `estado === "out"`, ámbar "EN DUDA" para `doubtful`) y, si viene `lambdas`,
una línea pequeña "λ ajustado: 1.42 → 1.19".

```jsx
export default function AusenciasBlock({ ausencias }) {
  if (!ausencias) return null
  if (ausencias.sin_dato) {
    return (
      <div className="ausencias-block sin-dato">
        Sin dato de ausencias para este partido (Sofascore aún no publica).
      </div>
    )
  }
  const equipos = Object.entries(ausencias.equipos || {}).filter(([, l]) => l.length)
  return (
    <div className="ausencias-block">
      <h3>Ausencias detectadas</h3>
      {equipos.length === 0 && <p>Sin ausentes reportados en ninguno de los dos equipos.</p>}
      {equipos.map(([equipo, lista]) => (
        <div key={equipo}>
          <strong>{equipo}</strong>
          <ul>
            {lista.map(a => (
              <li key={a.nombre}>
                <span className={a.estado === 'out' ? 'badge-out' : 'badge-duda'}>
                  {a.estado === 'out' ? 'NO JUEGA' : 'EN DUDA'}
                </span>
                {a.nombre}{a.motivo ? ` — ${a.motivo}` : ''}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {ausencias.lambdas && Object.entries(ausencias.lambdas).map(([k, v]) => (
        <p className="lambda-ajuste" key={k}>
          λ {k}: {v.antes.join(' / ')} → {v.despues.join(' / ')}
        </p>
      ))}
    </div>
  )
}
```

Estilos: añadir `.ausencias-block`, `.badge-out` (fondo `var(--red)` suave),
`.badge-duda` (ámbar), `.lambda-ajuste` (texto `var(--sub)`, pequeño) en
`frontend/src/styles/index.css` siguiendo las vars existentes.

- [ ] **Step 6.3: Render en `App.jsx`**

Localizar dónde se renderiza `MarcadorProbable` y añadir debajo:
`<AusenciasBlock ausencias={analysis.ausencias} />` (con su import).

- [ ] **Step 6.4: Verificación visual mínima**

Levantar frontend (`npm run dev` en `frontend/`) y backend, usar `?demo` — el demo
no trae `ausencias` → el bloque no debe renderizar nada ni romper. La verificación
con datos reales es Task 7.

- [ ] **Step 6.5: Commit**

```bash
git add frontend/src/components/Spinner.jsx frontend/src/components/AusenciasBlock.jsx frontend/src/App.jsx frontend/src/styles/index.css
git commit -m "ui(ausencias): etapa Sofascore en loader + bloque de ausentes con badges

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 7: E2E real + docs + cierre (operacional)

- [ ] **Step 7.1: E2E backend con partido real**

Con un partido internacional real próximo (elegir al ejecutar): levantar
`python -m uvicorn main:app --port 8123` y analizar un boleto (o construir el
parlay por el endpoint que corresponda) de ese partido. Verificar en la respuesta:
`ausencias` presente (con equipos o `sin_dato`), λ ajustados si hubo ausentes, y en
la segunda corrida el caché evita el scrape (respuesta rápida).

- [ ] **Step 7.2: E2E del caso jugador (si la fecha lo permite)**

Si algún partido próximo tiene un lesionado conocido con props en el player model:
boleto con esa pata → veredicto SIN_VALOR + razón "no juega". Si no hay caso real
esta semana, validar con el caché editado a mano (inyectar un ausente en el JSON de
`cache_ausencias/` y correr el análisis) y ANOTARLO como validación sintética.

- [ ] **Step 7.3: Verificación visual de Angel**

Mostrar el bloque de ausencias y el veredicto en el frontend con el caso real (o
sintético). **Gate humano: Angel confirma antes de cerrar.**

- [ ] **Step 7.4: Docs + memoria + cierre de rama**

- `docs/COBERTURA.md`: sección nueva o nota en "Cómo leer el veredicto": la capa de
  ausencias ajusta λ intl y puede forzar SIN_VALOR/NO_CONCLUYENTE por jugador
  out/doubtful; fuente Sofascore on-demand con caché 6h.
- Suite completa verde + actualizar memoria (roadmap Fase 3.4, project nuevo).
- Cierre con superpowers:finishing-a-development-branch (merge a master + push con
  confirmación de Angel, borrar rama).

```bash
git add docs/COBERTURA.md
git commit -m "docs(ausencias): capa de ausencias en COBERTURA

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
