"""
OCR Module — Phase 1
Recibe imagen de parlay → llama Gemini 1.5 Flash → devuelve JSON estructurado.

Output schema:
{
  "selecciones": [
    {
      "equipo_local":    str,
      "equipo_visitante": str,
      "mercado":         "1X2" | "over_under" | "btts" | "handicap" | "exotic",
      "seleccion":       "home" | "draw" | "away" | "over" | "under" | "yes" | "no" | str,
      "cuota":           float,
      "linea":           float | None   # solo para over/under y handicap (ej: 2.5, -1.5)
    }
  ],
  "cuota_total":   float | None,   # cuota combinada si aparece en la imagen
  "casa_apuestas": str | None      # casa detectada o None
}

Errores lanzados:
  OcrExtractionError  — Gemini no pudo extraer datos estructurados
  OcrParseError       — respuesta de Gemini no es JSON válido
"""

import os
import json
import re
import time
import base64
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ── Retry / backoff ───────────────────────────────────────────────────────────
# Gemini falla de forma transitoria por sobrecarga (503/UNAVAILABLE) y por cuota
# del free tier (429/RESOURCE_EXHAUSTED, que trae un hint retryDelay). Reintentar
# con backoff exponencial, respetando el retryDelay de la API cuando viene.

RETRY_MAX_ATTEMPTS = 4
RETRY_BASE_DELAY   = 2.0    # segundos
RETRY_DELAY_CAP    = 30.0   # tope por intento

# Modelo OCR. Default = gemini-2.5-flash (decisión cerrada); override por env para
# escapar de la cuota diaria del free tier apuntando a otro modelo (bucket aparte).
OCR_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_RETRYABLE_MARKERS = ("503", "429", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "OVERLOADED")


def _is_daily_quota(err: Exception) -> bool:
    """True si el 429 es por la cuota DIARIA del free tier (no se resetea en horas)."""
    return "PERDAY" in str(err).upper().replace(" ", "")


def _is_retryable(err: Exception) -> bool:
    """True si el error de Gemini es transitorio (sobrecarga o cuota por minuto).

    La cuota diaria NO es retryable: reintentar en segundos no la libera.
    """
    if _is_daily_quota(err):
        return False
    s = str(err).upper()
    return any(m in s for m in _RETRYABLE_MARKERS)


def _parse_retry_delay(text: str) -> float | None:
    """Extrae el hint 'retryDelay: 26s' del cuerpo del error 429, si existe."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def _retry_delay(err: Exception, attempt: int) -> float:
    """Segundos a esperar: respeta el hint de la API; si no, backoff exponencial."""
    hint = _parse_retry_delay(str(err))
    if hint is not None:
        return min(hint, RETRY_DELAY_CAP)
    return min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_DELAY_CAP)


def _generate_with_retry(call, *, max_attempts: int = RETRY_MAX_ATTEMPTS, sleep=time.sleep):
    """Ejecuta `call()` reintentando solo errores transitorios con backoff.

    Errores no transitorios (p.ej. 400) se propagan en el primer intento.
    """
    for attempt in range(max_attempts):
        try:
            return call()
        except Exception as e:
            if _is_retryable(e) and attempt < max_attempts - 1:
                sleep(_retry_delay(e, attempt))
            else:
                raise

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un extractor de datos de tickets de apuestas deportivas.
Tu única tarea: extraer las selecciones del parlay que aparece en la imagen y devolver JSON puro.

REGLAS ESTRICTAS:
1. Responde SOLO con JSON válido. Cero texto antes o después.
2. No inventes datos. Si un campo no está visible, usa null.
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, resultado_exacto, double_chance, count, player, exotic
4. Para "seleccion":
   - 1X2: home, draw, away
   - double_chance (Doble oportunidad): home_draw, draw_away, home_away.
     "Empate o <equipo local>" -> home_draw ; "Empate o <equipo visitante>" -> draw_away ;
     "<local> o <visitante>" (gana cualquiera) -> home_away. "linea": null.
   - over_under: over, under  (SOLO goles de partido completo)
   - btts: yes, no
   - handicap: home, away (el equipo con handicap)
   - resultado_exacto: el marcador como "local-visitante", ej "1-3" (Marcador exacto)
   - count: over, under  (mercado de conteo con línea)
   - exotic: el texto exacto visible (ej: "primer goleador Guerrero")
4b. MERCADO "count" (conteos con línea over/under). Rellena además "metric" y "scope":
    - "metric": "corners" (córners/saques de esquina) | "cards" (tarjetas amarillas/total) |
                "shots" (remates/tiros totales) | "sot" (tiros/remates al arco/a puerta)
    - "scope": "total" (del partido) | "home" (equipo local) | "away" (equipo visitante)
    - "seleccion": over | under ; "linea": el número (ej 8.5)
    Ejemplos: "Más de 9.5 córners" -> count/corners/total/over/9.5 ;
              "Tarjetas local más de 2.5" -> count/cards/home/over/2.5 ;
              "Remates al arco +7.5" -> count/sot/total/over/7.5
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
5. "cuota" debe ser número decimal (ej: 1.85, 2.30). Si ves cuotas americanas (+150) conviértelas.
6. "linea" solo para over_under y handicap (ej: 2.5 para over 2.5, -1.5 para handicap -1.5).
7. "cuota_total" es la cuota combinada del parlay completo si aparece en la imagen.
8. "casa_apuestas": detecta si ves logos o textos de Betano, Inkabet, Codere, Betsafe, Apuesta Total, Bet365, etc.

FORMATO DE SALIDA (exactamente esto):
{
  "selecciones": [
    {
      "equipo_local": "Nombre del equipo local",
      "equipo_visitante": "Nombre del equipo visitante",
      "mercado": "1X2",
      "seleccion": "home",
      "cuota": 1.85,
      "linea": null,
      "metric": null,
      "scope": null,
      "player": null,
      "umbral": 1,
      "faltante": false
    }
  ],
  "cuota_total": 5.40,
  "casa_apuestas": "Betano"
}"""

# ── Exceptions ────────────────────────────────────────────────────────────────

class OcrExtractionError(Exception):
    pass

class OcrParseError(Exception):
    pass

# ── Core function ─────────────────────────────────────────────────────────────

def extract_parlay(image_source: str | bytes | Path, api_key: str | None = None) -> dict:
    """
    Extrae selecciones de parlay desde una imagen.

    Args:
        image_source: ruta al archivo (str/Path) o bytes de la imagen
        api_key: Gemini API key. Si None, lee de env var GEMINI_API_KEY.

    Returns:
        dict con "selecciones", "cuota_total", "casa_apuestas"

    Raises:
        OcrExtractionError: Gemini no devolvió datos útiles
        OcrParseError: respuesta no es JSON válido
        ValueError: API key no encontrada
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "GEMINI_API_KEY no encontrada. "
            "Pásala como argumento o setea la variable de entorno."
        )

    client = genai.Client(api_key=key)

    # Load image
    if isinstance(image_source, (str, Path)):
        path = Path(image_source)
        if not path.exists():
            raise FileNotFoundError(f"Imagen no encontrada: {path}")
        image_bytes = path.read_bytes()
        suffix = path.suffix.lower().lstrip(".")
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png",  "webp": "image/webp"}
        mime_type = mime_map.get(suffix, "image/jpeg")
    else:
        image_bytes = image_source
        mime_type = "image/jpeg"

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    # Call Gemini — reintenta errores transitorios (503 sobrecarga / 429 cuota)
    # con backoff que respeta el retryDelay de la API.
    def _call():
        return client.models.generate_content(
            model=OCR_MODEL,
            contents=[SYSTEM_PROMPT, image_part],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=4096,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )

    try:
        response = _generate_with_retry(_call)
    except Exception as e:
        if _is_daily_quota(e):
            raise OcrExtractionError(
                "Se agotó la cuota DIARIA de Gemini (free tier). Reintentar hoy no "
                "ayuda: espera al reset (medianoche hora del Pacífico) o setea "
                "GEMINI_MODEL a otro modelo / usa una API key con billing."
            ) from e
        raise OcrExtractionError(f"Error llamando a Gemini: {e}") from e

    raw = response.text.strip() if response.text else ""

    if not raw:
        raise OcrExtractionError("Gemini devolvió respuesta vacía.")

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise OcrParseError(
            f"Gemini devolvió texto no-JSON: {e}\nRespuesta raw:\n{raw[:300]}"
        ) from e

    # Minimal normalization
    if "selecciones" not in data:
        raise OcrExtractionError(
            f"JSON sin campo 'selecciones'. Respuesta:\n{raw[:300]}"
        )

    data.setdefault("cuota_total", None)
    data.setdefault("casa_apuestas", None)

    for s in data["selecciones"]:
        s.setdefault("linea", None)
        s.setdefault("metric", None)   # familia count
        s.setdefault("scope", None)
        # Ensure cuota is float
        if s.get("cuota") is not None:
            s["cuota"] = float(s["cuota"])

    return data


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) < 2:
        print("Uso: python ocr.py <ruta_imagen> [GEMINI_API_KEY]")
        print("     o setea env var GEMINI_API_KEY")
        sys.exit(1)

    image_path = sys.argv[1]
    api_key    = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"\nProcesando: {image_path}")
    print("-" * 50)

    try:
        result = extract_parlay(image_path, api_key)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\nOK: {len(result['selecciones'])} selecciones extraidas")
        if result["cuota_total"]:
            print(f"  Cuota total: {result['cuota_total']}")
        if result["casa_apuestas"]:
            print(f"  Casa: {result['casa_apuestas']}")
    except (OcrExtractionError, OcrParseError, ValueError, FileNotFoundError) as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
