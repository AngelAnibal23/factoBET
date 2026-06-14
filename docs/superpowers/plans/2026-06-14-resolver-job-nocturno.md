# Resolver (Job Nocturno) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `resolver.py` + endpoint `POST /api/v1/admin/resolver-resultados` que marca `acierto` por selección consultando resultados reales en ESPN, y `resultado_parlay` por parlay.

**Architecture:** Módulo `resolver.py` con funciones puras (cálculo de acierto, mapeo de estado, resultado de parlay, parseo y matching de eventos) y un orquestador `resolver_resultados(league, dry_run)` que consulta Supabase, hace una sola request a ESPN por rango de fechas, y aplica updates. El endpoint en `main.py` lo expone. Sin cambios de schema.

**Tech Stack:** Python 3.12, `requests` 2.34.2 (ya usado en audit.py/download_fixtures.py), `rapidfuzz` (ya usado en validator.py), `supabase` (patrón de storage.py), `pytest`.

---

## Estructura de archivos

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `resolver.py` | Funciones puras + fetch ESPN + orquestador |
| Crear | `tests/test_resolver.py` | Tests de funciones puras |
| Modificar | `main.py` | Endpoint admin |

**Representación interna de un evento** (producida por `_parse_eventos`, consumida por `_match_evento` y el orquestador):
```python
{
    "local": str,              # displayName del equipo home en ESPN
    "visitante": str,          # displayName del equipo away en ESPN
    "goles_local": int | None,
    "goles_visitante": int | None,
    "status_name": str,        # ej. "STATUS_FULL_TIME"
    "fecha": str,              # ISO, ej. "2026-05-31T18:15Z"
}
```

---

## Task 1: `_calcular_acierto` — lógica de acierto por mercado

**Files:**
- Create: `resolver.py`
- Create: `tests/test_resolver.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_resolver.py`:

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from resolver import _calcular_acierto


def test_1x2_home_gana():
    assert _calcular_acierto("1X2", "home", None, 2, 1) is True

def test_1x2_home_pierde():
    assert _calcular_acierto("1X2", "home", None, 1, 1) is False

def test_1x2_draw_gana():
    assert _calcular_acierto("1X2", "draw", None, 1, 1) is True

def test_1x2_away_gana():
    assert _calcular_acierto("1X2", "away", None, 0, 2) is True

def test_over_gana():
    assert _calcular_acierto("over_under", "over", 2.5, 2, 1) is True

def test_over_pierde():
    assert _calcular_acierto("over_under", "over", 2.5, 1, 1) is False

def test_under_gana():
    assert _calcular_acierto("over_under", "under", 2.5, 1, 1) is True

def test_over_sin_linea_devuelve_none():
    assert _calcular_acierto("over_under", "over", None, 3, 0) is None

def test_btts_yes_gana():
    assert _calcular_acierto("btts", "yes", None, 1, 2) is True

def test_btts_yes_pierde():
    assert _calcular_acierto("btts", "yes", None, 1, 0) is False

def test_btts_no_gana():
    assert _calcular_acierto("btts", "no", None, 3, 0) is True

def test_handicap_home_con_linea_negativa_gana():
    # home -1.5: gana si gana por 2+. 3-1 → 3 + (-1.5) = 1.5 > 1 → True
    assert _calcular_acierto("handicap", "home", -1.5, 3, 1) is True

def test_handicap_home_con_linea_negativa_pierde():
    # home -1.5: 2-1 → 2 + (-1.5) = 0.5 > 1 → False
    assert _calcular_acierto("handicap", "home", -1.5, 2, 1) is False

def test_handicap_away_con_linea_positiva_gana():
    # linea=+1.5 es el handicap aplicado al HOME (home +1.5).
    # away gana el handicap si gv - linea > gl. Con 0-2: 2 - 1.5 = 0.5 > 0 → True
    assert _calcular_acierto("handicap", "away", 1.5, 0, 2) is True

def test_marcador_none_devuelve_none():
    assert _calcular_acierto("1X2", "home", None, None, 1) is None

def test_exotic_devuelve_none():
    assert _calcular_acierto("exotic", "lo que sea", None, 2, 1) is None
```

- [ ] **Step 2: Ejecutar el test — verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: `ModuleNotFoundError: No module named 'resolver'`

- [ ] **Step 3: Crear `resolver.py` con `_calcular_acierto`**

```python
"""
Resolver — Phase 4 (Job Nocturno)
Marca el resultado real de cada selección de parlay consultando ESPN.
Fuente: ESPN hidden API. Sin cambios de schema en Supabase.
"""

import os
import logging
from datetime import datetime, timezone

import requests
from rapidfuzz import fuzz
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
MATCH_UMBRAL = 0.80   # mismo umbral que validator.py


# ── Lógica de acierto por mercado ─────────────────────────────────────────────

def _calcular_acierto(mercado, seleccion, linea, gl, gv):
    """Retorna True/False si la selección acertó, o None si no es resoluble."""
    if gl is None or gv is None:
        return None

    if mercado == "1X2":
        if seleccion == "home": return gl > gv
        if seleccion == "draw": return gl == gv
        if seleccion == "away": return gl < gv

    elif mercado == "over_under":
        if linea is None:
            return None
        total = gl + gv
        if seleccion == "over":  return total > linea
        if seleccion == "under": return total < linea

    elif mercado == "btts":
        ambos = gl > 0 and gv > 0
        if seleccion == "yes": return ambos
        if seleccion == "no":  return not ambos

    elif mercado == "handicap":
        if linea is None:
            return None
        if seleccion == "home": return gl + linea > gv
        if seleccion == "away": return gv - linea > gl

    return None
```

- [ ] **Step 4: Ejecutar el test — verificar que pasa**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 16 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py tests/test_resolver.py && git commit -m "feat: add _calcular_acierto to resolver"
```

---

## Task 2: `_mapear_status` — clasificar estado del partido

**Files:**
- Modify: `resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Agregar tests al final de `tests/test_resolver.py`**

```python
from resolver import _mapear_status


def test_status_full_time_finalizado():
    assert _mapear_status("STATUS_FULL_TIME") == "FINALIZADO"

def test_status_final_finalizado():
    assert _mapear_status("STATUS_FINAL") == "FINALIZADO"

def test_status_scheduled_pendiente():
    assert _mapear_status("STATUS_SCHEDULED") == "PENDIENTE"

def test_status_first_half_pendiente():
    assert _mapear_status("STATUS_FIRST_HALF") == "PENDIENTE"

def test_status_postponed_especial():
    assert _mapear_status("STATUS_POSTPONED") == "ESPECIAL"

def test_status_canceled_especial():
    assert _mapear_status("STATUS_CANCELED") == "ESPECIAL"

def test_status_final_pen_especial():
    # penales → revisión manual, no liquidar automático
    assert _mapear_status("STATUS_FINAL_PEN") == "ESPECIAL"

def test_status_desconocido_pendiente():
    assert _mapear_status("STATUS_LO_QUE_SEA") == "PENDIENTE"
```

- [ ] **Step 2: Ejecutar — verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -k mapear_status -v`
Expected: `ImportError: cannot import name '_mapear_status'`

- [ ] **Step 3: Agregar `_mapear_status` a `resolver.py`** (después de `_calcular_acierto`)

```python
# ── Mapeo de estado ESPN ──────────────────────────────────────────────────────

_STATUS_FINALIZADO = {"STATUS_FULL_TIME", "STATUS_FINAL"}
_STATUS_ESPECIAL = {
    "STATUS_FINAL_PEN", "STATUS_POSTPONED", "STATUS_CANCELED",
    "STATUS_CANCELLED", "STATUS_ABANDONED", "STATUS_SUSPENDED",
}


def _mapear_status(status_name):
    """FINALIZADO (resoluble) | PENDIENTE (no jugado/en curso) | ESPECIAL (anulado/penales)."""
    if status_name in _STATUS_FINALIZADO:
        return "FINALIZADO"
    if status_name in _STATUS_ESPECIAL:
        return "ESPECIAL"
    return "PENDIENTE"
```

- [ ] **Step 4: Ejecutar — verificar que pasa**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 24 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py tests/test_resolver.py && git commit -m "feat: add _mapear_status to resolver"
```

---

## Task 3: `_resultado_parlay` — resultado del parlay por precedencia

**Files:**
- Modify: `resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Agregar tests al final de `tests/test_resolver.py`**

```python
from resolver import _resultado_parlay


def test_parlay_todas_ganadas():
    assert _resultado_parlay(["GANADA", "GANADA"]) == "GANADO"

def test_parlay_una_perdida():
    assert _resultado_parlay(["GANADA", "PERDIDA"]) == "PERDIDO"

def test_parlay_perdida_tiene_precedencia_sobre_pendiente():
    # un leg perdido mata el parlay aunque haya pendientes
    assert _resultado_parlay(["PERDIDA", "PENDIENTE"]) == "PERDIDO"

def test_parlay_pendiente_sin_perdidas():
    assert _resultado_parlay(["GANADA", "PENDIENTE"]) == "PENDIENTE"

def test_parlay_pendiente_precede_a_especial():
    assert _resultado_parlay(["PENDIENTE", "ESPECIAL"]) == "PENDIENTE"

def test_parlay_especial_sin_perdidas_ni_pendientes():
    assert _resultado_parlay(["GANADA", "ESPECIAL"]) == "ANULADO"

def test_parlay_vacio_es_pendiente():
    # parlay con solo exóticas (todas excluidas) → no concluir
    assert _resultado_parlay([]) == "PENDIENTE"
```

- [ ] **Step 2: Ejecutar — verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -k resultado_parlay -v`
Expected: `ImportError: cannot import name '_resultado_parlay'`

- [ ] **Step 3: Agregar `_resultado_parlay` a `resolver.py`** (después de `_mapear_status`)

```python
# ── Resultado del parlay (por precedencia) ────────────────────────────────────

def _resultado_parlay(estados):
    """
    estados: lista de estado por selección NO exótica, cada uno en
    {GANADA, PERDIDA, PENDIENTE, ESPECIAL}.
    Precedencia: PERDIDA > PENDIENTE > ESPECIAL > GANADA.
    """
    if not estados:
        return "PENDIENTE"
    if "PERDIDA" in estados:
        return "PERDIDO"
    if "PENDIENTE" in estados:
        return "PENDIENTE"
    if "ESPECIAL" in estados:
        return "ANULADO"
    return "GANADO"
```

- [ ] **Step 4: Ejecutar — verificar que pasa**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 31 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py tests/test_resolver.py && git commit -m "feat: add _resultado_parlay to resolver"
```

---

## Task 4: `_parse_eventos` — parsear JSON de ESPN a eventos normalizados

**Files:**
- Modify: `resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Agregar tests al final de `tests/test_resolver.py`**

```python
from resolver import _parse_eventos


_ESPN_SAMPLE = {
    "events": [
        {
            "date": "2026-05-31T18:15Z",
            "status": {"type": {"name": "STATUS_FULL_TIME", "completed": True}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "score": "1",
                     "team": {"displayName": "FC Cajamarca", "abbreviation": "CAJ"}},
                    {"homeAway": "away", "score": "2",
                     "team": {"displayName": "Alianza Lima", "abbreviation": "ALI"}},
                ]
            }],
        },
        {
            "date": "2026-06-01T20:00Z",
            "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "score": None,
                     "team": {"displayName": "Melgar", "abbreviation": "MEL"}},
                    {"homeAway": "away", "score": None,
                     "team": {"displayName": "Sporting Cristal", "abbreviation": "CRI"}},
                ]
            }],
        },
    ]
}


def test_parse_eventos_cantidad():
    evs = _parse_eventos(_ESPN_SAMPLE)
    assert len(evs) == 2

def test_parse_eventos_marcador_y_nombres():
    ev = _parse_eventos(_ESPN_SAMPLE)[0]
    assert ev["local"] == "FC Cajamarca"
    assert ev["visitante"] == "Alianza Lima"
    assert ev["goles_local"] == 1
    assert ev["goles_visitante"] == 2
    assert ev["status_name"] == "STATUS_FULL_TIME"

def test_parse_eventos_score_none_cuando_no_jugado():
    ev = _parse_eventos(_ESPN_SAMPLE)[1]
    assert ev["goles_local"] is None
    assert ev["goles_visitante"] is None

def test_parse_eventos_vacio():
    assert _parse_eventos({"events": []}) == []

def test_parse_eventos_sin_events_key():
    assert _parse_eventos({}) == []
```

- [ ] **Step 2: Ejecutar — verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -k parse_eventos -v`
Expected: `ImportError: cannot import name '_parse_eventos'`

- [ ] **Step 3: Agregar `_parse_eventos` a `resolver.py`** (después de `_resultado_parlay`)

```python
# ── Parseo de la respuesta ESPN ───────────────────────────────────────────────

def _score_int(competitor):
    s = competitor.get("score")
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _parse_eventos(espn_json):
    """Convierte el JSON del scoreboard ESPN en una lista de eventos normalizados."""
    eventos = []
    for e in espn_json.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        eventos.append({
            "local":            home["team"]["displayName"],
            "visitante":        away["team"]["displayName"],
            "goles_local":      _score_int(home),
            "goles_visitante":  _score_int(away),
            "status_name":      e.get("status", {}).get("type", {}).get("name", ""),
            "fecha":            e.get("date", ""),
        })
    return eventos
```

- [ ] **Step 4: Ejecutar — verificar que pasa**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 36 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py tests/test_resolver.py && git commit -m "feat: add _parse_eventos to resolver"
```

---

## Task 5: `_match_evento` — fuzzy match de selección a evento ESPN

**Files:**
- Modify: `resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Agregar tests al final de `tests/test_resolver.py`**

```python
from resolver import _match_evento


_EVENTOS = [
    {"local": "FC Cajamarca", "visitante": "Alianza Lima",
     "goles_local": 1, "goles_visitante": 2, "status_name": "STATUS_FULL_TIME", "fecha": ""},
    {"local": "Melgar", "visitante": "Sporting Cristal",
     "goles_local": 0, "goles_visitante": 0, "status_name": "STATUS_FULL_TIME", "fecha": ""},
]


def test_match_evento_exacto():
    ev = _match_evento("FC Cajamarca", "Alianza Lima", _EVENTOS)
    assert ev is not None
    assert ev["local"] == "FC Cajamarca"

def test_match_evento_nombre_canonico_diferente():
    # equipos.nombre_oficial "FBC Melgar" vs ESPN "Melgar" → fuzzy debe matchear
    ev = _match_evento("FBC Melgar", "Sporting Cristal", _EVENTOS)
    assert ev is not None
    assert ev["local"] == "Melgar"

def test_match_evento_sin_coincidencia():
    ev = _match_evento("Universitario", "ADT", _EVENTOS)
    assert ev is None

def test_match_evento_local_ok_visitante_no():
    # solo coincide el local → no es match (exige ambos)
    ev = _match_evento("FC Cajamarca", "Equipo Inexistente", _EVENTOS)
    assert ev is None

def test_match_evento_no_acepta_orientacion_invertida():
    # parlay con local/visitante invertidos respecto a ESPN → no match
    # (preserva semántica home/away para el cálculo de acierto)
    ev = _match_evento("Alianza Lima", "FC Cajamarca", _EVENTOS)
    assert ev is None
```

- [ ] **Step 2: Ejecutar — verificar que falla**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -k match_evento -v`
Expected: `ImportError: cannot import name '_match_evento'`

- [ ] **Step 3: Agregar `_match_evento` a `resolver.py`** (después de `_parse_eventos`)

```python
# ── Matching de selección a evento ────────────────────────────────────────────

def _fuzzy(a, b):
    a_norm, b_norm = a.strip().lower(), b.strip().lower()
    return max(
        fuzz.partial_ratio(a_norm, b_norm),
        fuzz.token_sort_ratio(a_norm, b_norm),
    ) / 100.0


def _match_evento(nombre_local, nombre_visitante, eventos, umbral=MATCH_UMBRAL):
    """
    Devuelve el evento cuyo local Y visitante coinciden (>= umbral) con los nombres
    dados, respetando la orientación home/away. None si ninguno cumple.
    """
    best = None
    best_score = 0.0
    for ev in eventos:
        sl = _fuzzy(nombre_local, ev["local"])
        sv = _fuzzy(nombre_visitante, ev["visitante"])
        if sl >= umbral and sv >= umbral and (sl + sv) > best_score:
            best_score = sl + sv
            best = ev
    return best
```

- [ ] **Step 4: Ejecutar — verificar que pasa**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 41 tests PASSED

- [ ] **Step 5: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py tests/test_resolver.py && git commit -m "feat: add _match_evento to resolver"
```

---

## Task 6: `_fetch_eventos` + orquestador `resolver_resultados`

**Files:**
- Modify: `resolver.py`

(Sin tests unitarios: el fetch ESPN y los updates a Supabase se prueban en la verificación manual de la Task 8. Las funciones puras que llaman ya están cubiertas.)

- [ ] **Step 1: Agregar `_client`, `_fetch_eventos`, `_actualizar_parlay` y `resolver_resultados` al final de `resolver.py`**

```python
# ── Cliente Supabase (lazy, igual que storage.py) ─────────────────────────────

_sb = None


def _client():
    global _sb
    if _sb is None:
        _sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _sb


# ── Fetch ESPN ────────────────────────────────────────────────────────────────

def _fetch_eventos(league, fecha_inicio, fecha_fin):
    """
    league: slug ESPN (ej. 'per.1'). fecha_inicio/fecha_fin: 'YYYYMMDD'.
    Una sola request cubre todo el rango. Lanza requests.HTTPError si falla.
    """
    url = f"{ESPN_BASE}/{league}/scoreboard"
    params = {"dates": f"{fecha_inicio}-{fecha_fin}", "limit": 1000}
    resp = requests.get(
        url, params=params, timeout=25,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    resp.raise_for_status()
    return _parse_eventos(resp.json())


# ── Actualización de parlay completo ──────────────────────────────────────────

def _actualizar_parlay(sb, parlay_id, ahora_iso, dry_run):
    """Recalcula resultado_parlay con las selecciones no exóticas. Retorna True si lo escribió."""
    sels = (
        sb.table("selecciones_parlay")
        .select("acierto, resultado_real, es_mercado_exotico")
        .eq("parlay_id", parlay_id)
        .execute().data
    )
    estados = []
    for s in sels:
        if s["es_mercado_exotico"]:
            continue
        if s["acierto"] is True:
            estados.append("GANADA")
        elif s["acierto"] is False:
            estados.append("PERDIDA")
        elif s["resultado_real"]:        # acierto NULL pero con resultado escrito → especial
            estados.append("ESPECIAL")
        else:
            estados.append("PENDIENTE")

    resultado = _resultado_parlay(estados)
    if resultado == "PENDIENTE":
        return False
    if not dry_run:
        (sb.table("analisis_parlays")
         .update({"resultado_parlay": resultado, "resolved_at": ahora_iso})
         .eq("id", parlay_id).execute())
    return True


# ── Orquestador público ───────────────────────────────────────────────────────

def resolver_resultados(league="per.1", dry_run=False):
    """
    Resuelve todas las selecciones pendientes (acierto IS NULL, no exóticas).
    Retorna resumen {resueltas, pendientes, sin_match, especiales, errores,
    parlays_completados, detalle}.
    """
    sb = _client()
    resumen = {
        "resueltas": 0, "pendientes": 0, "sin_match": 0, "especiales": 0,
        "errores": 0, "parlays_completados": 0, "detalle": [],
    }

    pend = (
        sb.table("selecciones_parlay")
        .select("id, parlay_id, mercado, seleccion, linea, features_snapshot, "
                "es_mercado_exotico, analisis_parlays(created_at)")
        .is_("acierto", "null")
        .eq("es_mercado_exotico", False)
        .execute().data
    )
    if not pend:
        return resumen

    # Ventana temporal: desde el parlay más antiguo pendiente hasta hoy
    fechas = [
        p["analisis_parlays"]["created_at"]
        for p in pend if p.get("analisis_parlays")
    ]
    ahora = datetime.now(tz=timezone.utc)
    if fechas:
        inicio_dt = min(
            datetime.fromisoformat(f.replace("Z", "+00:00")) for f in fechas
        )
    else:
        inicio_dt = ahora
    inicio = inicio_dt.strftime("%Y%m%d")
    fin = ahora.strftime("%Y%m%d")
    ahora_iso = ahora.isoformat()

    eventos = _fetch_eventos(league, inicio, fin)

    equipos = {
        e["id"]: e
        for e in sb.table("equipos").select("id, nombre_oficial, aliases").execute().data
    }

    parlays_afectados = set()

    for sel in pend:
        try:
            fs = sel.get("features_snapshot") or {}
            eq_local = equipos.get(fs.get("equipo_local_id"))
            eq_vis = equipos.get(fs.get("equipo_visitante_id"))
            if not eq_local or not eq_vis:
                resumen["sin_match"] += 1
                continue

            ev = _match_evento(eq_local["nombre_oficial"], eq_vis["nombre_oficial"], eventos)
            if not ev:
                resumen["sin_match"] += 1
                continue

            estado = _mapear_status(ev["status_name"])

            if estado == "PENDIENTE":
                resumen["pendientes"] += 1
                continue

            if estado == "ESPECIAL":
                resumen["especiales"] += 1
                if not dry_run:
                    (sb.table("selecciones_parlay")
                     .update({"resultado_real": ev["status_name"], "resolved_at": ahora_iso})
                     .eq("id", sel["id"]).execute())
                parlays_afectados.add(sel["parlay_id"])
                resumen["detalle"].append({
                    "seleccion_id": sel["id"],
                    "match": f"{ev['local']} vs {ev['visitante']}",
                    "resultado_real": ev["status_name"],
                    "acierto": None,
                })
                continue

            # FINALIZADO
            acierto = _calcular_acierto(
                sel["mercado"], sel["seleccion"], sel["linea"],
                ev["goles_local"], ev["goles_visitante"],
            )
            marcador = f"{ev['goles_local']}-{ev['goles_visitante']}"
            if not dry_run:
                (sb.table("selecciones_parlay")
                 .update({"resultado_real": marcador, "acierto": acierto, "resolved_at": ahora_iso})
                 .eq("id", sel["id"]).execute())
            resumen["resueltas"] += 1
            parlays_afectados.add(sel["parlay_id"])
            resumen["detalle"].append({
                "seleccion_id": sel["id"],
                "match": f"{ev['local']} vs {ev['visitante']}",
                "resultado_real": marcador,
                "acierto": acierto,
            })

        except Exception as e:
            resumen["errores"] += 1
            log.error("Error resolviendo seleccion %s: %s", sel.get("id"), e)

    for pid in parlays_afectados:
        try:
            if _actualizar_parlay(sb, pid, ahora_iso, dry_run):
                resumen["parlays_completados"] += 1
        except Exception as e:
            resumen["errores"] += 1
            log.error("Error actualizando parlay %s: %s", pid, e)

    return resumen
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python -c "import resolver; print('resolver OK')"`
Expected: `resolver OK`

- [ ] **Step 3: Ejecutar todos los tests (las funciones puras siguen pasando)**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && pytest tests/test_resolver.py -v`
Expected: 41 tests PASSED

- [ ] **Step 4: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add resolver.py && git commit -m "feat: add ESPN fetch and resolver_resultados orchestrator"
```

---

## Task 7: Endpoint en `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Agregar import de `resolver_resultados`**

En `main.py`, junto a los otros imports locales (después de `from narrator import generate_narrative`, línea ~34):

```python
from resolver import resolver_resultados
```

- [ ] **Step 2: Agregar el endpoint** (después de `modelo_estado`, antes de `root`, alrededor de la línea 280)

```python
@app.post("/api/v1/admin/resolver-resultados")
async def resolver_resultados_endpoint(league: str = "per.1", dry_run: bool = False):
    t0 = time.monotonic()
    try:
        resumen = resolver_resultados(league=league, dry_run=dry_run)
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=502,
            content=_err("RESOLVER_ERROR",
                         "Error resolviendo resultados desde ESPN.",
                         str(e), ms),
        )
    ms = int((time.monotonic() - t0) * 1000)
    return JSONResponse(content=_ok(resumen, ms))
```

- [ ] **Step 3: Verificar que la app importa sin errores**

Run: `cd C:\Users\WIN10\Desktop\helpBETOR && python -c "from main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add main.py && git commit -m "feat: add POST /api/v1/admin/resolver-resultados endpoint"
```

---

## Task 8: Verificación manual end-to-end

**Files:** ninguno — solo verificación

- [ ] **Step 1: Arrancar el servidor**

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && uvicorn main:app --host 0.0.0.0 --port 8000
```

Esperar `Application startup complete.` (~30s de warm_up).

- [ ] **Step 2: Probar en modo dry_run primero (no escribe en Supabase)**

En otra terminal:

```bash
curl -s -X POST "http://localhost:8000/api/v1/admin/resolver-resultados?dry_run=true" | python -m json.tool
```

Esperado: envelope `success: true` con `data` mostrando `resueltas`, `pendientes`, `sin_match`, `detalle`. Revisar que los `match` y `resultado_real` del detalle tengan sentido (los marcadores coinciden con partidos reales de Liga 1).

- [ ] **Step 3: Si el dry_run se ve correcto, ejecutar real**

```bash
curl -s -X POST "http://localhost:8000/api/v1/admin/resolver-resultados" | python -m json.tool
```

Esperado: mismos números, pero ahora persistidos. `parlays_completados` > 0 si algún parlay quedó totalmente resuelto.

- [ ] **Step 4: Verificar en Supabase que se escribió**

Repetir el request real una segunda vez:

```bash
curl -s -X POST "http://localhost:8000/api/v1/admin/resolver-resultados" | python -m json.tool
```

Esperado: la segunda corrida debe mostrar `resueltas: 0` para las que ya se resolvieron (porque `acierto` ya no es NULL) — confirma que la persistencia funcionó y que el job es idempotente.

- [ ] **Step 5: Commit de cualquier ajuste**

Si hubo ajustes durante la verificación:

```bash
cd C:\Users\WIN10\Desktop\helpBETOR && git add -p && git commit -m "fix: resolver adjustments from manual testing"
```

---

## Checklist de spec coverage

| Requisito del spec | Task |
|---|---|
| Fuente ESPN, slug per.1, query por rango de fechas | Task 6 (`_fetch_eventos`) |
| `_calcular_acierto` (tabla por mercado) | Task 1 |
| `_mapear_status` (FINALIZADO/PENDIENTE/ESPECIAL) | Task 2 |
| `_resultado_parlay` (precedencia PERDIDO>PENDIENTE>ANULADO>GANADO) | Task 3 |
| Parseo de eventos ESPN | Task 4 (`_parse_eventos`) |
| Matching fuzzy con nombre canónico, exige local Y visitante | Task 5 (`_match_evento`) |
| Orquestador con dry_run, ventana por created_at, sin schema change | Task 6 |
| Exóticas excluidas de pendientes y de completion | Task 6 (filtro + `_actualizar_parlay`) |
| Penales (FINAL_PEN) → ESPECIAL, revisión manual | Task 2 + Task 6 |
| Endpoint POST /api/v1/admin/resolver-resultados | Task 7 |
| Error ESPN → falla limpia sin escribir parcial | Task 7 (try/except 502) |
| Verificación end-to-end con dry_run | Task 8 |
