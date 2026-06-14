# Diseño: Narrativa LLM — Phase 3

**Fecha:** 2026-06-14
**Estado:** Aprobado por Angel

---

## Contexto

El campo `narrativa` en el response de `POST /api/v1/parlay/analizar` devuelve `null` desde Phase 1. Este diseño implementa la generación de texto explicativo en español usando Gemini 2.5 Flash — el mismo modelo ya en uso para OCR.

---

## Arquitectura

**Archivo nuevo:** `narrator.py`

Sigue el patrón existente del proyecto: cada responsabilidad tiene su propio módulo (`ocr.py`, `validator.py`, `analyzer.py`, `storage.py`, `narrator.py`).

**Interfaz pública:**
```python
def generate_narrative(analysis: ParlayAnalysis) -> str | None
```

**Integración en `main.py`** — 3 cambios mínimos:
1. Importar `generate_narrative` desde `narrator`
2. Llamarla después de `analyze(parlay)` dentro de un try/except
3. Pasar el resultado a `_serialize_analysis()` como parámetro nuevo

```python
narrativa = None
try:
    narrativa = generate_narrative(result)
except Exception as e:
    log.error("Narrative error: %s", e)

data = _serialize_analysis(result, parlay.needs_confirmation, narrativa)
```

En `_serialize_analysis`, el parámetro `narrativa` reemplaza el `None` hardcodeado actual.

---

## Pre-procesamiento (Python, sin LLM)

Antes de llamar a Gemini, `narrator.py` traduce los números a lenguaje natural:

### Tabla de probabilidades
| Rango | Texto |
|---|---|
| < 35% | "Poco probable — menos de 1 de cada 3 veces" |
| 35–50% | "Bajo — menos probable que improbable" |
| 50–60% | "Ligeramente favorable — cara o cruz con leve ventaja" |
| 60–70% | "Moderado — ocurre 6 de cada 10 veces en el largo plazo" |
| 70–80% | "Alto — pero falla 2-3 de cada 10 veces" |
| > 80% | "Muy alto — pero nunca es certeza en fútbol" |

### Traducción de edge
| Condición | Texto |
|---|---|
| `edge > 0.05` | "Valor estadístico real — la cuota paga más de lo que el riesgo justifica" |
| `0 < edge <= 0.05` | "Valor marginal — dentro del margen de error del modelo" |
| `edge == 0` o `None` | "Sin valor estadístico" |
| `-0.05 <= edge < 0` | "Sin valor — la casa tiene ventaja estadística aquí" |
| `edge < -0.05` | "La casa tiene ventaja clara — esta selección perjudica el parlay" |

### Framing "1 de cada N"
```python
prob_base = prob_parlay_modelo or prob_parlay_impl  # fallback si todo es exótico
n = round(1 / prob_base) if prob_base else None
# 0.20 → "1 de cada 5 veces"
```
Si `prob_parlay_modelo` es `None` (todas las selecciones son exóticas), se usa `prob_parlay_impl` con nota explícita de que el modelo no cubre esos mercados.

### Selección más débil
La selección con menor `prob_modelo` entre las modeladas. Si hay empate, la de mayor edge negativo.

---

## Llamada a Gemini

```python
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=800,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    ),
)
```

**Diferencias respecto a `ocr.py`:**
- Solo texto — sin imagen adjunta
- `temperature=0.2` en lugar de `0.0` (narrativa puede variar levemente)
- `max_output_tokens=800` — suficiente para 5 selecciones + resumen + disclaimer
- Sin retry — fallo degrada a `None`
- Sin parsing JSON — el texto se usa directo

---

## Estructura del prompt

El prompt envía datos ya interpretados (no números crudos) e instrucciones de formato:

```
DATOS DEL ANÁLISIS:
- Confianza del parlay: MEDIA
- Razones: [...]
- Prob. combinada modelo: 20.3% → 1 de cada 5 veces
- Prob. combinada implícita: 18.1%

SELECCIONES:
1. Alianza Lima vs Sport Huancayo — over 2.5 (cuota 1.85)
   Probabilidad modelo: 54.2% → Ligeramente favorable
   Edge: +3.1% → Valor marginal
   ...

CORRELACIONES DETECTADAS: [si aplica]

KELLY: [solo si alguna selección tiene edge > 0]
  Sel 1: apostar el 2.4% del bankroll

INSTRUCCIONES:
- Redacta en español, tono directo y honesto
- Estructura: resumen → selecciones → selección más débil → kelly → disclaimer
- Nunca uses "seguro", "garantizado", "el modelo recomienda apostar"
- Termina siempre con el disclaimer obligatorio
```

---

## Contenido obligatorio del output (según HELPBETOR_AI_CONTEXT.md sección 11)

1. Probabilidad de cada selección (traducida a lenguaje natural)
2. Edge por selección (con veredicto)
3. Probabilidad combinada con framing "1 de cada N veces"
4. Selección más débil identificada
5. Alertas de correlación si existen
6. Nivel de confianza con razones
7. Kelly fraccionario (solo si edge > 0 en alguna selección)
8. Disclaimer obligatorio al final

---

## Error handling

La narrativa nunca bloquea el response principal:

- Fallo de Gemini → `narrativa: null`, análisis numérico se entrega igual
- Response vacío → `narrativa: null`
- Sin retry — texto raramente da 503, y la degradación es preferible a retrasar el response
- El frontend ya maneja `narrativa: null` desde Phase 1

---

## Lo que NO cambia

- Contrato de la API — `narrativa` ya existe en el schema, hoy es `null`
- `disclaimer` hardcodeado en `_serialize_analysis` — se mantiene igual (la narrativa tiene su propio disclaimer interno, pero el campo `disclaimer` del response no se toca)
- Ningún otro archivo cambia excepto `main.py` (3 líneas)
