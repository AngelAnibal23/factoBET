# Narrativa LLM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `narrator.py` que genera texto explicativo en español desde un `ParlayAnalysis` usando Gemini 2.5 Flash, e integrarlo en `main.py` para que el campo `narrativa` deje de ser `null`.

**Architecture:** Nuevo módulo `narrator.py` con funciones puras de pre-procesamiento (números → lenguaje natural) y una función pública `generate_narrative(analysis) -> str | None`. Se llama en `main.py` después de `analyze()`, dentro de un try/except que degrada a `None` si Gemini falla. El contrato de la API no cambia.

**Tech Stack:** Python 3.11+, `google-genai==2.8.0` (ya instalado), `pytest` (instalar), `python-dotenv` (ya instalado).

---

## Archivos involucrados

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `narrator.py` | Pre-procesamiento + llamada Gemini |
| Crear | `tests/test_narrator.py` | Tests de funciones puras |
| Modificar | `main.py` | Import + llamada + pasar narrativa a serializer |

---

## Task 1: Setup de tests e instalación de pytest

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_narrator.py` (vacío por ahora)

- [ ] **Step 1: Instalar pytest**

```bash
pip install pytest
```

Verificar:
```bash
pytest --version
```
Esperado: `pytest 8.x.x`

- [ ] **Step 2: Crear directorio y archivo init**

```bash
mkdir tests
```

Crear `tests/__init__.py` vacío.

- [ ] **Step 3: Crear test placeholder para verificar que pytest funciona**

Crear `tests/test_narrator.py`:

```python
def test_placeholder():
    assert True
```

- [ ] **Step 4: Ejecutar pytest para confirmar que funciona**

```bash
pytest tests/test_narrator.py -v
```

Esperado:
```
tests/test_narrator.py::test_placeholder PASSED
```

---

## Task 2: Funciones puras de pre-procesamiento

**Files:**
- Create: `narrator.py`
- Modify: `tests/test_narrator.py`

- [ ] **Step 1: Escribir tests de `_prob_to_text`**

Reemplazar contenido de `tests/test_narrator.py`:

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from narrator import _prob_to_text, _edge_to_text, _framing_n


def test_prob_to_text_muy_bajo():
    assert "Poco probable" in _prob_to_text(0.20)

def test_prob_to_text_bajo():
    assert "Bajo" in _prob_to_text(0.40)

def test_prob_to_text_ligero():
    assert "Ligeramente favorable" in _prob_to_text(0.55)

def test_prob_to_text_moderado():
    assert "Moderado" in _prob_to_text(0.65)

def test_prob_to_text_alto():
    assert "Alto" in _prob_to_text(0.75)

def test_prob_to_text_muy_alto():
    assert "Muy alto" in _prob_to_text(0.85)

def test_prob_to_text_boundary_35():
    # 0.35 cae en "Bajo"
    assert "Bajo" in _prob_to_text(0.35)

def test_prob_to_text_boundary_50():
    # 0.50 cae en "Ligeramente favorable"
    assert "Ligeramente favorable" in _prob_to_text(0.50)


def test_edge_to_text_valor_real():
    assert "Valor estadístico real" in _edge_to_text(0.06)

def test_edge_to_text_marginal():
    assert "marginal" in _edge_to_text(0.03)

def test_edge_to_text_sin_valor_neutro():
    assert "Sin valor" in _edge_to_text(0.0)

def test_edge_to_text_sin_valor_negativo_leve():
    assert "Sin valor" in _edge_to_text(-0.03)

def test_edge_to_text_ventaja_clara():
    assert "ventaja clara" in _edge_to_text(-0.08)

def test_edge_to_text_none():
    result = _edge_to_text(None)
    assert "Sin valor estadístico" in result


def test_framing_n_20_pct():
    result = _framing_n(0.20)
    assert result == "1 de cada 5 veces"

def test_framing_n_50_pct():
    result = _framing_n(0.50)
    assert result == "1 de cada 2 veces"

def test_framing_n_10_pct():
    result = _framing_n(0.10)
    assert result == "1 de cada 10 veces"

def test_framing_n_none():
    assert _framing_n(None) is None

def test_framing_n_zero():
    assert _framing_n(0.0) is None
```

- [ ] **Step 2: Ejecutar tests — verificar que fallan**

```bash
pytest tests/test_narrator.py -v
```

Esperado: `ModuleNotFoundError: No module named 'narrator'` — correcto, no existe aún.

- [ ] **Step 3: Crear `narrator.py` con las funciones puras**

```python
"""
Narrator — Phase 3
Generates a Spanish narrative from a ParlayAnalysis using Gemini 2.5 Flash.
Pre-processes numbers into natural language before sending to the LLM.
"""

import os
import logging
from google import genai
from google.genai import types
from dotenv import load_dotenv

from analyzer import ParlayAnalysis, SelectionAnalysis

load_dotenv()
log = logging.getLogger(__name__)


def _prob_to_text(prob: float) -> str:
    if prob < 0.35:
        return "Poco probable — menos de 1 de cada 3 veces"
    if prob < 0.50:
        return "Bajo — menos probable que improbable"
    if prob < 0.60:
        return "Ligeramente favorable — cara o cruz con leve ventaja"
    if prob < 0.70:
        return "Moderado — ocurre 6 de cada 10 veces en el largo plazo"
    if prob < 0.80:
        return "Alto — pero falla 2-3 de cada 10 veces"
    return "Muy alto — pero nunca es certeza en fútbol"


def _edge_to_text(edge: float | None) -> str:
    if edge is None:
        return "Sin valor estadístico (mercado no cubierto por el modelo)"
    if edge > 0.05:
        return "Valor estadístico real — la cuota paga más de lo que el riesgo justifica"
    if edge > 0:
        return "Valor marginal — dentro del margen de error del modelo"
    if edge >= -0.05:
        return "Sin valor — la casa tiene ventaja estadística aquí"
    return "La casa tiene ventaja clara — esta selección perjudica el parlay"


def _framing_n(prob: float | None) -> str | None:
    if not prob:
        return None
    n = round(1 / prob)
    return f"1 de cada {n} veces"


def _weakest_selection(sels: list[SelectionAnalysis]) -> SelectionAnalysis | None:
    modeladas = [s for s in sels if s.prob_modelo is not None]
    if not modeladas:
        return None
    return min(modeladas, key=lambda s: (s.prob_modelo, -(s.edge or 0)))


def _build_prompt(analysis: ParlayAnalysis) -> str:
    prob_base   = analysis.prob_parlay_modelo or analysis.prob_parlay_impl
    framing     = _framing_n(prob_base)
    prob_source = "modelo" if analysis.prob_parlay_modelo else "implícita (mercados exóticos sin modelo)"

    weakest = _weakest_selection(analysis.selecciones)
    weakest_desc = ""
    if weakest:
        vis = weakest.equipo_visitante or "rival"
        linea_str = f" {weakest.linea}" if weakest.linea is not None else ""
        weakest_desc = (
            f"{weakest.equipo_local} vs {vis} — "
            f"{weakest.mercado}{linea_str} ({weakest.seleccion})"
        )

    sels_block = ""
    for i, s in enumerate(analysis.selecciones, 1):
        vis       = s.equipo_visitante or "(sin visitante)"
        linea_str = f" {s.linea}" if s.linea is not None else ""
        prob_text = _prob_to_text(s.prob_modelo) if s.prob_modelo is not None else "Sin modelo (mercado exótico)"
        edge_text = _edge_to_text(s.edge)
        kelly_str = (
            f"\n   Kelly recomendado: {s.kelly_fraccion:.1%} del bankroll"
            if s.kelly_fraccion else ""
        )
        alertas_str = "".join(f"\n   ⚠ {a}" for a in s.alertas)

        sels_block += (
            f"\n{i}. {s.equipo_local} vs {vis} — {s.mercado}{linea_str} "
            f"({s.seleccion}, cuota {s.cuota})"
            f"\n   Prob. modelo: {f'{s.prob_modelo:.1%}' if s.prob_modelo else 'N/A'} → {prob_text}"
            f"\n   Edge: {f'{s.edge:+.1%}' if s.edge is not None else 'N/A'} → {edge_text}"
            f"{kelly_str}"
            f"{alertas_str}"
        )

    corr_block = ""
    if analysis.correlaciones:
        corr_block = "\nCORRELACIONES DETECTADAS:"
        for c in analysis.correlaciones:
            s1 = analysis.selecciones[c.sel_idx_1]
            s2 = analysis.selecciones[c.sel_idx_2]
            corr_block += (
                f"\n- Sel {c.sel_idx_1+1} ({s1.seleccion}) + "
                f"Sel {c.sel_idx_2+1} ({s2.seleccion}): {c.tipo}"
                f"\n  {c.nota}"
            )

    kelly_sels = [(i + 1, s) for i, s in enumerate(analysis.selecciones) if s.kelly_fraccion]
    kelly_block = ""
    if kelly_sels:
        kelly_block = "\nKELLY FRACCIONARIO (20%) — solo selecciones con edge positivo:"
        for idx, s in kelly_sels:
            kelly_block += f"\n- Sel {idx}: apostar el {s.kelly_fraccion:.1%} del bankroll"

    razones_str = "\n- ".join(analysis.razones_confianza)

    cuota_line = f"\nCuota total declarada: {analysis.cuota_total}" if analysis.cuota_total else ""

    return f"""DATOS DEL ANÁLISIS ESTADÍSTICO:

Confianza del parlay: {analysis.nivel_confianza}
Razones:
- {razones_str}

Probabilidad combinada ({prob_source}): {f'{prob_base:.1%}' if prob_base else 'N/A'}{f' → {framing}' if framing else ''}
Probabilidad combinada implícita ajustada: {f'{analysis.prob_parlay_impl:.1%}' if analysis.prob_parlay_impl else 'N/A'}
Casa de apuestas: {analysis.casa_apuestas or 'no detectada'}
Margen aplicado: {analysis.margen_aplicado:.1%}{cuota_line}

SELECCIONES ({len(analysis.selecciones)} en total):{sels_block}
{corr_block}
{f'SELECCIÓN MÁS DÉBIL: {weakest_desc}' if weakest_desc else ''}
{kelly_block}

INSTRUCCIONES DE REDACCIÓN:
- Redacta en español, tono directo y honesto, sin adornos
- Estructura: (1) resumen del parlay → (2) análisis por selección → (3) selección más débil → (4) kelly si aplica → (5) disclaimer
- Máximo 600 palabras
- Nunca uses "seguro", "garantizado", "el modelo recomienda apostar"
- Si hay correlaciones: explica el impacto en la probabilidad real
- Termina SIEMPRE con este disclaimer exacto:
  "⚠ Este análisis es estadístico, no predictivo. El fútbol tiene alta varianza irreducible — el equipo con 80% de probabilidad pierde el 20% de las veces. El valor estadístico solo se realiza en el largo plazo con disciplina de bankroll. Este sistema no garantiza resultados individuales."
"""


def generate_narrative(analysis: ParlayAnalysis) -> str | None:
    """
    Generates a Spanish narrative from a ParlayAnalysis using Gemini 2.5 Flash.
    Returns None if generation fails — caller handles fallback.
    """
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log.warning("GEMINI_API_KEY not set — skipping narrative")
        return None

    prompt = _build_prompt(analysis)

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=800,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    text = response.text.strip() if response.text else ""
    return text if text else None
```

- [ ] **Step 4: Ejecutar tests — verificar que pasan**

```bash
pytest tests/test_narrator.py -v
```

Esperado: todos los tests `PASSED`.

- [ ] **Step 5: Commit**

```bash
git add narrator.py tests/__init__.py tests/test_narrator.py
git commit -m "feat: add narrator.py with LLM narrative generation via Gemini"
```

---

## Task 3: Tests de `_weakest_selection` y `_build_prompt`

**Files:**
- Modify: `tests/test_narrator.py`

- [ ] **Step 1: Agregar tests de `_weakest_selection` y `_build_prompt` al archivo de tests**

Agregar al final de `tests/test_narrator.py`:

```python
from dataclasses import dataclass, field
from narrator import _weakest_selection, _build_prompt, generate_narrative
from analyzer import ParlayAnalysis, SelectionAnalysis, Correlacion


def _make_selection(
    prob_modelo=0.55,
    edge=0.03,
    kelly_fraccion=None,
    mercado="1X2",
    seleccion="home",
    cuota=1.80,
    nivel_cobertura="ALTA",
    mercado_exotico=False,
    equipo_local="Alianza Lima",
    equipo_visitante="Sport Huancayo",
    equipo_local_id="alianza",
    equipo_visitante_id="sport_huancayo",
    linea=None,
    lambda_home=1.5,
    lambda_away=1.1,
    prob_implicita=0.55,
    prob_implicita_adj=0.51,
    n_partidos_local=20,
    n_partidos_visitante=18,
    alertas=None,
):
    return SelectionAnalysis(
        equipo_local=equipo_local,
        equipo_visitante=equipo_visitante,
        equipo_local_id=equipo_local_id,
        equipo_visitante_id=equipo_visitante_id,
        mercado=mercado,
        seleccion=seleccion,
        cuota=cuota,
        linea=linea,
        prob_implicita=prob_implicita,
        prob_implicita_adj=prob_implicita_adj,
        prob_modelo=prob_modelo,
        lambda_home=lambda_home,
        lambda_away=lambda_away,
        edge=edge,
        kelly_fraccion=kelly_fraccion,
        nivel_cobertura=nivel_cobertura,
        mercado_exotico=mercado_exotico,
        n_partidos_local=n_partidos_local,
        n_partidos_visitante=n_partidos_visitante,
        alertas=alertas or [],
    )


def _make_analysis(sels=None, correlaciones=None, nivel_confianza="ALTA"):
    sels = sels or [_make_selection()]
    modeladas = [s for s in sels if s.prob_modelo is not None]
    prob_parlay = None
    if modeladas:
        import math
        prob_parlay = round(math.prod(s.prob_modelo for s in modeladas), 6)
    return ParlayAnalysis(
        selecciones=sels,
        prob_parlay_modelo=prob_parlay,
        prob_parlay_impl=0.45,
        cuota_total=2.20,
        casa_apuestas="Betano",
        nivel_confianza=nivel_confianza,
        razones_confianza=["Todos los equipos con datos suficientes."],
        correlaciones=correlaciones or [],
        version_modelo="v0.2",
        margen_aplicado=0.06,
    )


# ── _weakest_selection ────────────────────────────────────────────────────────

def test_weakest_selection_picks_lowest_prob():
    strong = _make_selection(prob_modelo=0.75, edge=0.05, equipo_local="Universitario")
    weak   = _make_selection(prob_modelo=0.35, edge=-0.03, equipo_local="Alianza Lima")
    result = _weakest_selection([strong, weak])
    assert result.equipo_local == "Alianza Lima"

def test_weakest_selection_all_exotic():
    s = _make_selection(prob_modelo=None, edge=None, mercado_exotico=True)
    assert _weakest_selection([s]) is None

def test_weakest_selection_single():
    s = _make_selection(prob_modelo=0.55)
    assert _weakest_selection([s]) is s


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_build_prompt_contains_confidence():
    analysis = _make_analysis(nivel_confianza="MEDIA")
    prompt = _build_prompt(analysis)
    assert "MEDIA" in prompt

def test_build_prompt_contains_framing():
    sels = [_make_selection(prob_modelo=0.50)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "1 de cada" in prompt

def test_build_prompt_contains_disclaimer_instruction():
    analysis = _make_analysis()
    prompt = _build_prompt(analysis)
    assert "estadístico, no predictivo" in prompt

def test_build_prompt_contains_selection_name():
    sels = [_make_selection(equipo_local="Sporting Cristal")]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "Sporting Cristal" in prompt

def test_build_prompt_shows_correlacion():
    sels = [
        _make_selection(equipo_local="Alianza Lima", seleccion="home"),
        _make_selection(equipo_local="Alianza Lima", seleccion="over", mercado="over_under", linea=2.5),
    ]
    corr = Correlacion(sel_idx_1=0, sel_idx_2=1, tipo="POSITIVA_ALTA", nota="Las victorias locales amplias elevan los goles totales.")
    analysis = _make_analysis(sels=sels, correlaciones=[corr])
    prompt = _build_prompt(analysis)
    assert "CORRELACIONES" in prompt
    assert "POSITIVA_ALTA" in prompt

def test_build_prompt_no_kelly_when_no_edge():
    sels = [_make_selection(kelly_fraccion=None)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "KELLY" not in prompt

def test_build_prompt_shows_kelly_when_present():
    sels = [_make_selection(kelly_fraccion=0.024)]
    analysis = _make_analysis(sels=sels)
    prompt = _build_prompt(analysis)
    assert "KELLY" in prompt
    assert "2.4%" in prompt


# ── generate_narrative sin API key ────────────────────────────────────────────

def test_generate_narrative_no_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    analysis = _make_analysis()
    result = generate_narrative(analysis)
    assert result is None
```

- [ ] **Step 2: Ejecutar tests — verificar que pasan**

```bash
pytest tests/test_narrator.py -v
```

Esperado: todos los tests `PASSED`. El test `test_generate_narrative_no_api_key` no llama a Gemini.

- [ ] **Step 3: Commit**

```bash
git add tests/test_narrator.py
git commit -m "test: add tests for narrator helpers and build_prompt"
```

---

## Task 4: Integración en `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Agregar import de `generate_narrative` en `main.py`**

En `main.py`, agregar al bloque de imports existentes (línea ~34, junto a los otros imports locales):

```python
from narrator import generate_narrative
```

- [ ] **Step 2: Actualizar firma de `_serialize_analysis` para recibir `narrativa`**

Buscar la función `_serialize_analysis` (línea ~104). Cambiar su firma de:

```python
def _serialize_analysis(result: ParlayAnalysis, needs_confirmation: list[str]) -> dict:
```

a:

```python
def _serialize_analysis(result: ParlayAnalysis, needs_confirmation: list[str], narrativa: str | None = None) -> dict:
```

Y dentro de la función, reemplazar:

```python
        "narrativa":           None,   # Phase 3 — Groq/Llama
```

por:

```python
        "narrativa":           narrativa,
```

- [ ] **Step 3: Llamar a `generate_narrative` en el endpoint**

En el endpoint `analizar_parlay`, después del bloque de `save_analysis` (línea ~257) y antes de `_serialize_analysis`, agregar:

```python
    # 6. Generate narrative (non-blocking: failure keeps narrativa=None)
    narrativa = None
    try:
        narrativa = generate_narrative(result)
    except Exception as e:
        log.error("Narrative generation failed: %s", e)
```

Y actualizar la llamada a `_serialize_analysis` de:

```python
    data = _serialize_analysis(result, parlay.needs_confirmation)
```

a:

```python
    data = _serialize_analysis(result, parlay.needs_confirmation, narrativa)
```

- [ ] **Step 4: Actualizar el endpoint de estado para reflejar Phase 3**

En `modelo_estado`, cambiar:

```python
        "fase":               "Phase 1 MVP — sin narrativa LLM",
```

a:

```python
        "fase":               "Phase 3 — narrativa LLM activa (Gemini 2.5 Flash)",
```

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "feat: integrate LLM narrative into /api/v1/parlay/analizar endpoint"
```

---

## Task 5: Prueba manual end-to-end

**Files:** ninguno — solo verificación

- [ ] **Step 1: Arrancar el servidor**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Esperar el warm_up (~30s). Confirmar que aparece:
```
INFO:     Application startup complete.
```

- [ ] **Step 2: Enviar un parlay real y verificar el campo `narrativa`**

En otra terminal (o Postman), enviar una imagen de parlay:

```bash
curl -s -X POST http://localhost:8000/api/v1/parlay/analizar \
  -F "imagen=@<ruta_a_imagen.png>" \
  | python -m json.tool | findstr /C:"narrativa" /C:"disclaimer"
```

Esperado en el response:
```json
"narrativa": "Este parlay tiene confianza... [texto en español]",
"disclaimer": "Este analisis es estadístico..."
```

El campo `narrativa` ya no debe ser `null`.

- [ ] **Step 3: Verificar degradación si Gemini falla**

Temporalmente cambiar `GEMINI_API_KEY` a un valor inválido en `.env`, reiniciar el servidor y repetir el request.

Esperado:
- `narrativa: null`
- Response llega igual con todos los datos numéricos
- Log muestra `ERROR: Narrative generation failed`

Restaurar el API key real.

- [ ] **Step 4: Commit final de verificación (si hay ajustes)**

Si se hicieron ajustes durante la prueba:

```bash
git add -p
git commit -m "fix: narrative integration adjustments from manual testing"
```

---

## Checklist de spec coverage

| Requisito | Task que lo implementa |
|---|---|
| Nuevo archivo `narrator.py` | Task 2 |
| Interfaz `generate_narrative(analysis) -> str \| None` | Task 2 |
| Pre-procesamiento: tabla de probabilidades | Task 2 (_prob_to_text) |
| Pre-procesamiento: traducción de edge | Task 2 (_edge_to_text) |
| Pre-procesamiento: framing "1 de cada N" | Task 2 (_framing_n) |
| Selección más débil identificada | Task 2 (_weakest_selection) |
| Correlaciones en el prompt | Task 2 (_build_prompt) |
| Kelly solo si edge > 0 | Task 2 (_build_prompt) |
| Disclaimer obligatorio al final | Task 2 (instrucción en prompt) |
| Gemini 2.5 Flash, text-only, temp=0.2, max_tokens=800 | Task 2 (generate_narrative) |
| Fallo degrada a `null` sin bloquear response | Task 4 (try/except en endpoint) |
| Sin cambio en contrato de API | Task 4 (_serialize_analysis) |
| Fallback `prob_parlay_impl` si todo es exótico | Task 2 (_build_prompt) |
