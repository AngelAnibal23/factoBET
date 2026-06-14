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

    razones_str = "\n- ".join(analysis.razones_confianza) if analysis.razones_confianza else "Sin razones registradas"

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
    try:
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
    except Exception as e:
        log.warning("Gemini error generating narrative: %s", e)
        return None
