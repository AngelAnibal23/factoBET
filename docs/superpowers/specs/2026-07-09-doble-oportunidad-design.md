# Diseño — Mercado "Doble oportunidad" (double chance)

**Fecha:** 2026-07-09
**Fase:** Roadmap Fase 2, quick win 1.5 (completar cobertura — añadir una pata que las casas ofrecen).
**Origen:** boleto real BET6 (DoradoBet, Países Bajos vs Marruecos: "Doble oportunidad —
Empate o Marruecos"). Hoy cae a `exotic` pese a ser trivialmente derivable de la matriz
Dixon-Coles ya calculada.

## Objetivo

Convertir la pata "doble oportunidad" en mercado **servible de la familia goles**
(`double_chance` en `GOAL_MARKETS`), para todas las ligas cubiertas por el motor DC
(Liga 1 + Internacional). Al ser familia goles, entra a la conjunta exacta y puede
participar en veredictos `VALOR`.

## Decisiones tomadas (brainstorming)

1. **Encoding de selecciones: `home_draw` / `draw_away` / `home_away`** — sigue el
   estilo verbal existente (`home`/`draw`/`away`, `over`/`under`, `yes`). Descartada la
   notación de casa `1X`/`X2`/`12` por críptica e inconsistente con el resto.
2. **Enfoque A — mercado nativo en `goal_leg_mask`** (recomendado y aprobado): rama
   nueva con 3 máscaras booleanas. La pata opera sobre la matriz de marcadores igual
   que cualquier pata de goles; cero cambios al motor de conjunta/techo/veredicto.
   Descartado B (azúcar sintáctico en validator traduciendo a pseudo-patas 1X2): el
   motor no tiene unión de patas y habría que inventar mecánica nueva para algo que la
   máscara resuelve en 3 líneas.

## Cambios (4 puntos de toque)

### 1. `betbuilder.py`

- `GOAL_MARKETS` += `"double_chance"`.
- Rama en `goal_leg_mask` (tras la de `1X2`):

```python
elif mercado == "double_chance":
    if seleccion == "home_draw": return I >= J
    if seleccion == "draw_away": return I <= J
    if seleccion == "home_away": return I != J
```

Selección desconocida cae al `ValueError` final ya existente ("Pata no modelable…").

### 2. `validator.py`

- `VALID_MARKETS` += `"double_chance"`.
- `VALID_SEL_DC = {"home_draw", "draw_away", "home_away"}` + chequeo con el mismo
  patrón que 1X2 (`RangeError` si la selección no es válida).
- `VALID_ODDS["double_chance"] = (1.01, 8.0)` — cuotas bajas por cubrir 2 de 3
  resultados; techo 8.0 para dobles oportunidades muy improbables.

### 3. `ocr.py` (prompt)

- Añadir `double_chance` a la lista de mercados válidos (punto 3 del prompt).
- Regla de traducción (misma mecánica equipo→lado que 1X2):
  - "Empate o [equipo local]" / "[equipo local] o Empate" → `home_draw`
  - "Empate o [equipo visitante]" / "[equipo visitante] o Empate" → `draw_away`
  - "[local] o [visitante]" (sin empate) → `home_away`
- `linea: null`, `faltante: false`.

### 4. Tests (TDD — se escriben ANTES de cada cambio)

- **`goal_leg_mask`**: las 3 selecciones marcan las celdas correctas; identidades sobre
  una matriz real: `P(home_draw) = P(1X2:home) + P(1X2:draw)`;
  complementariedad `P(home_draw) = 1 − P(1X2:away)` (y análogas).
- **Validator**: `double_chance` con selección inválida → `RangeError`; cuota fuera de
  `[1.01, 8.0]` → `RangeError`; boleto válido pasa.
- **Conjunta**: boleto `double_chance` + `over_under` del mismo partido produce techo
  y (siendo una sola familia, sin faltantes) puede dar veredicto `VALOR`.

## Fuera de alcance (YAGNI)

- Frontend: la card genérica de pata de goles ya renderiza el mercado; nada nuevo.
- Sinónimos exóticos del OCR más allá del patrón estándar ("doble oportunidad",
  "double chance", "1X/X2/12" impresos en el boleto se resuelven en el prompt).
- Docs: actualizar la fila correspondiente de `docs/COBERTURA.md` al cerrar (mover de
  Pendiente a familia Goles).

## Error handling

Sin mecanismos nuevos: selección desconocida → `ValueError` de `goal_leg_mask` /
`RangeError` del validator; mercado ausente del prompt → el OCR lo emite como `exotic`
y el motor lo trata como hoy (degradación conocida).
