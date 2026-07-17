# Cobertura de mercados (patas)

> Mapa vivo de **qué patas sabe analizar Helpbetor**. Aquí vamos anotando poco a poco
> las patas que se van cubriendo. La fuente de verdad del código es `betbuilder.py`
> (`GOAL_MARKETS` / `COUNT_MARKET` / `PLAYER_MARKET`); este archivo es el resumen humano.

Última actualización: 2026-07-16

> **Foco de cobertura (decisión de Angel 2026-07-12):** la prioridad es el **Mundial**,
> y después las competiciones **CONMEBOL en conjunto** (Copa América + eliminatorias
> sudamericanas). **Liga 1 queda descartada como inversión futura** ("ya fue"): lo ya
> construido (goles, conteos) se mantiene tal cual, pero no se le dedica trabajo nuevo.

## Familias modelables

| Familia | Patas que cubre | Ligas | Modelo | Estado |
|---|---|---|---|---|
| **Goles** | 1X2 (gana/empata), más/menos goles (over/under), ambos anotan (BTTS), hándicap, resultado exacto, **doble oportunidad** (1X/X2/12) | Liga 1 + Internacional | Dixon-Coles (matriz de marcadores) | ✅ Fase 1 + quick win 2026-07-10. **Prior ELO (Fase 3.5, 2026-07-16): NO pasó el gate** — mejor variante `blend_fifa l2_prior=2-4` mejora global (0.2478 vs 0.2487) y sparse **+1.7%** pero el gate pedía ≥3% en sparse → sigue `intl_v0.1`; el código del prior quedó mergeado como no-op (sin publicar, `elo_params` NULL) |
| **Conteos (por equipo)** | tiros **por equipo**, tiros al arco **por equipo** | Mundial + Liga 1 | NegBin + shrinkage (`counts_v0.1`) | ✅ Sub-proyecto B |
| **Jugador** | **anota** (goal), **asiste** (assist), **anota o asiste** (goal_or_assist) | Internacional (732 jugadores, ≥10 partidos) | Poisson top-down + shrinkage (`player_v0.2`, k=3) | ✅ calibrado 2026-06-24, **cola elite afinada 2026-07-11** |
| **Jugador — tiros al arco** (ej. "Messi 1+ tiros al arco") | **sot** (N+ tiros al arco, umbral) | Internacional (358 jugadores, ≥10 partidos; datos API-Football `/fixtures/players`) | Poisson top-down: λ_jugador = counts_model.λ_sot × cuota_sot (`player_sot_v0.1`) | ✅ **publicado 2026-07-13** — gate definitivo **+22.9%** (Brier 0.1566 vs 0.2033), e2e Messi OK. Boletos que la pedían: BET5 (Ronaldo), BET6 (Brahim Díaz) |

## Pendiente (hoy se marca `FALTANTE` o `EXÓTICO`)

| Pata | Por qué falta | Camino |
|---|---|---|
| ~~Jugador en **Liga 1** (anota/asiste)~~ | **DESCARTADA 2026-07-12** — Liga 1 no interesa; foco Mundial + CONMEBOL | — |
| Córners / faltas / tarjetas **por equipo** | Situacionales, no modelables per-equipo (verificado; reaparecen en boletos: córners totales en BET6, faltas por equipo en realbet4) | — (probablemente no se modela) |
| **Acumulador multi-partido de bet builders** | Formato no soportado (composición multi-partido) | Diferido; 2ª aparición real en realbet4 (Doble con bet builder adentro) |
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
