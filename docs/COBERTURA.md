# Cobertura de mercados (patas)

> Mapa vivo de **qué patas sabe analizar Helpbetor**. Aquí vamos anotando poco a poco
> las patas que se van cubriendo. La fuente de verdad del código es `betbuilder.py`
> (`GOAL_MARKETS` / `COUNT_MARKET` / `PLAYER_MARKET`); este archivo es el resumen humano.

Última actualización: 2026-07-10

## Familias modelables

| Familia | Patas que cubre | Ligas | Modelo | Estado |
|---|---|---|---|---|
| **Goles** | 1X2 (gana/empata), más/menos goles (over/under), ambos anotan (BTTS), hándicap, resultado exacto, **doble oportunidad** (1X/X2/12) | Liga 1 + Internacional | Dixon-Coles (matriz de marcadores) | ✅ Fase 1 + quick win 2026-07-10 |
| **Conteos (por equipo)** | tiros **por equipo**, tiros al arco **por equipo** | Mundial + Liga 1 | NegBin + shrinkage (`counts_v0.1`) | ✅ Sub-proyecto B |
| **Jugador** | **anota** (goal), **asiste** (assist), **anota o asiste** (goal_or_assist) | Internacional (732 jugadores, ≥10 partidos) | Poisson top-down + shrinkage (`player_v0.1`) | ✅ **calibrado 2026-06-24** |

## Pendiente (hoy se marca `FALTANTE` o `EXÓTICO`)

| Pata | Por qué falta | Camino |
|---|---|---|
| **Tiros al arco POR JUGADOR** (ej. "Messi 1+ tiros al arco") | El feed de Flashscore (`df_sui_1`) no trae tiros por jugador | Scraper nuevo a FBref (match logs por jugador) + modelo de conteos por-jugador — *capítulo futuro* |
| Jugador en **Liga 1** (anota/asiste) | Sin probar; sparsity peor que Internacional | Re-correr gate con datos de Liga 1 |
| Córners / faltas / tarjetas **por equipo** | Situacionales, no modelables per-equipo (verificado) | — (probablemente no se modela) |
| Patas de **otras familias exóticas** | El motor no las reconoce | Caso por caso |

## Cómo leer el veredicto

El motor de bet builder estima un **techo** (cota superior de la probabilidad real de la
conjunta) y lo compara con la cuota:

- **VALOR** — el techo supera la cuota, **y** se cumplen DOS condiciones: (1) ninguna
  pata faltante/exótica, y (2) **todas las patas son de la misma familia** (entonces el
  techo es la probabilidad *exacta*, no una cota). Único caso en que se afirma valor + Kelly.
- **SIN_VALOR** — ni el mejor caso (techo) supera la cuota → EV ≤ 0 garantizado.
- **NO_CONCLUYENTE** — el techo supera la cuota **pero** hay patas faltantes/exóticas
  **o** se mezclan familias (ej. goles + jugador). El techo es una cota superior, no la
  prob exacta, así que no se puede *garantizar* valor. Igual informa: da el techo y la
  prob de cada pata.
- **NO_EVALUABLE** — ninguna pata es modelable.

### Implicación práctica

Cubrir más patas reduce los `NO_CONCLUYENTE` causados **por falta de datos**. Pero un
boleto que **mezcla familias** (lo más común: "el equipo gana" + "el jugador anota")
seguirá siendo `NO_CONCLUYENTE` aunque todas sus patas estén cubiertas — porque el motor
no modela la dependencia entre familias y se mantiene conservador a propósito. El
veredicto `VALOR` categórico solo aparece en boletos de **una sola familia**.
