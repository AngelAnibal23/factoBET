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
import base64
from pathlib import Path

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Eres un extractor de datos de tickets de apuestas deportivas.
Tu única tarea: extraer las selecciones del parlay que aparece en la imagen y devolver JSON puro.

REGLAS ESTRICTAS:
1. Responde SOLO con JSON válido. Cero texto antes o después.
2. No inventes datos. Si un campo no está visible, usa null.
3. Para "mercado" usa exactamente uno de: 1X2, over_under, btts, handicap, exotic
4. Para "seleccion" en mercado 1X2 usa: home, draw, away
   Para over_under usa: over, under
   Para btts usa: yes, no
   Para handicap usa: home, away (el equipo con handicap)
   Para exotic usa el texto exacto visible (ej: "primer goleador Guerrero")
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
      "linea": null
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

    # Call Gemini — retry up to 3 times on transient 503 errors
    import time as _time
    last_err = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[SYSTEM_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=4096,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            last_err = None
            break
        except Exception as e:
            last_err = e
            if "503" in str(e) and attempt < 2:
                _time.sleep(10 * (attempt + 1))   # 10s, 20s
            else:
                break
    if last_err is not None:
        raise OcrExtractionError(f"Error llamando a Gemini: {last_err}") from last_err

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
