# Cobertura de mercados (patas)

> Mapa vivo de **qué patas sabe analizar Helpbetor**. Aquí vamos anotando poco a poco
> las patas que se van cubriendo. La fuente de verdad del código es `betbuilder.py`
> (`GOAL_MARKETS` / `COUNT_MARKET` / `PLAYER_MARKET`); este archivo es el resumen humano.

Última actualización: 2026-07-27

> **Foco de cobertura:** terminado el Mundial 2026, el foco pasó a la **Premier League**
> (2026-07-26). Antes (2026-07-12) la prioridad era el Mundial y después **CONMEBOL en
> conjunto** (Copa América + eliminatorias). **Liga 1 sigue descartada como inversión
> futura** ("ya fue"): lo ya construido se mantiene, pero no se le dedica trabajo nuevo.
>
> El motor rutea por liga (`analyzer._liga_de_parlay`): `liga1`, `premier`,
> `internacional`. Un boleto que **cruza ligas** se rechaza como `mixto` — cada liga
> tiene su propio modelo de goles, no se comparan equipos de ligas distintas.

## Familias modelables

| Familia | Patas que cubre | Ligas | Modelo | Estado |
|---|---|---|---|---|
| **Goles** | 1X2 (gana/empata), más/menos goles (over/under), ambos anotan (BTTS), hándicap, resultado exacto, **doble oportunidad** (1X/X2/12) | Liga 1 + Internacional + **Premier League** | Dixon-Coles (matriz de marcadores), un fit por liga | ✅ Fase 1 + quick win 2026-07-10. **Premier ✅ 2026-07-26**: gate **+8.7%** (Brier 0.2994 vs 0.3278, 342 partidos de test), 1.140 partidos de 2022/23–2024/25. **Prior ELO (Fase 3.5, 2026-07-16): NO pasó el gate** — mejor variante `blend_fifa l2_prior=2-4` mejora global (0.2478 vs 0.2487) y sparse **+1.7%** pero el gate pedía ≥3% en sparse → sigue `intl_v0.1`; el código del prior quedó mergeado como no-op (sin publicar, `elo_params` NULL) |
| **Conteos (por equipo)** | tiros **por equipo**, tiros al arco **por equipo** | Mundial + Liga 1 (**la Premier NO**, ver abajo) | NegBin + shrinkage (`counts_v0.1`) | ✅ Sub-proyecto B |
| **Jugador** | **anota** (goal), **asiste** (assist), **anota o asiste** (goal_or_assist) | Internacional (513 jug.) + **Premier League** (574 jug.) — ≥10 partidos como titular | Poisson top-down + shrinkage (`player_v0.2`, k=3), **fit separado por liga** | ✅ calibrado 2026-06-24, **cola elite afinada 2026-07-11**, **Premier ✅ 2026-07-27** (gate goal **+7.7%** / assist **+3.5%**; Internacional re-publicado con fit propio: **+9.6% / +4.7%**) |
| **Jugador — tiros al arco** (ej. "Messi 1+ tiros al arco") | **sot** (N+ tiros al arco, umbral) | Internacional (358 jugadores, ≥10 partidos; datos API-Football `/fixtures/players`) | Poisson top-down: λ_jugador = counts_model.λ_sot × cuota_sot (`player_sot_v0.1`) | ✅ **publicado 2026-07-13** — gate definitivo **+22.9%** (Brier 0.1566 vs 0.2033), e2e Messi OK. Boletos que la pedían: BET5 (Ronaldo), BET6 (Brahim Díaz). **Premier: backfill en curso** (177/1.140 fixtures al 2026-07-27, ~88/día por la cuota del plan Free) → hasta que termine, la pata sale `faltante` en boletos de Premier |

## Pendiente (hoy se marca `FALTANTE` o `EXÓTICO`)

| Pata | Por qué falta | Camino |
|---|---|---|
| **Conteos por equipo en la Premier** (tiros, tiros al arco) | **Gate NO pasa 2026-07-26** y no se publica: córners −1.7%, tarjetas +1.0%, tiros **−6.1%**, tiros al arco **−2.1%** (las cuatro por debajo del +3% exigido), pese a que tiros y tiros-al-arco SÍ pasan en Internacional y Liga 1. Descartada la dilución por ascendidos/descendidos (restringir a los 17 equipos fijos da lo mismo). Causa medida: la Premier es **demasiado homogénea en volumen** (`disp` tiros 1.43 vs 1.71 INT / 1.58 L1) y el baseline de promedio-liga ya es muy bueno; los goles dependen de la calidad, pero los tiros totales de un partido son mucho más simétricos | Los datos ya están cargados (2.280 filas, identidad 24/24). Si en el futuro cambia, `load_counts_to_supabase.LIGA_NOMBRE` ya incluye "Premier League" |
| Jugador en **Liga 1** (anota/asiste) | **DESCARTADA como inversión 2026-07-12** (Liga 1 "ya fue"). Al separar el fit por liga se midió igual, por completitud: **no pasa** (goal +0.4%, assist +0.7%, 209 elegibles) → se queda `faltante`, que es lo que ya era | — |
| Córners / faltas / tarjetas **por equipo** | Situacionales, no modelables per-equipo (verificado en las tres ligas; reaparecen en boletos: córners totales en BET6, faltas por equipo en realbet4) | — (probablemente no se modela) |
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

## Identidad de equipos (cómo se resuelven los nombres de los boletos)

Los nombres que llegan del OCR (y los de los scrapes) se resuelven contra `equipos`
(`nombre_oficial` + `aliases`) con fuzzy matching en `validator._best_match`, umbral
0.85 para auto-match. Dos reglas que **no** son obvias y existen por bugs reales:

- **`partial_ratio` solo cuenta si un nombre es el otro con palabras de más o abreviadas
  por prefijo** ("Alianza Atl." ⊂ "Alianza Atletico"). Sin esa guarda, un nombre corto se
  cuela **dentro de una palabra** del otro: "Mali" cae en "**Ali**anza" con 0.857 y
  "Alianza Huanuco" se cargaba como la selección de Mali.
- **A igual score gana el nombre entero más parecido.** Sin ese desempate decidía el orden
  en que Supabase devolvía las filas, y así Romania quedó bajo Oman y Nigeria bajo Niger.

Los alias de casa de apuestas se cargan con `set_intl_aliases.py` / `set_pl_aliases.py`
("Man City"→Manchester City, "Spurs"→Tottenham). Hay un test invariante que impide que un
alias nuevo colisione con otro equipo (`test_ningun_alias_colisiona_con_otro_equipo`) — se
añadió porque el alias "City" hacía que "Leicester City" empatara con Manchester City.

## Capa de ausencias (lesiones/suspensiones) — solo Internacional

Antes de calcular, el analyzer internacional consulta los ausentes del partido en
**Sofascore** (scrape on-demand con caché local de 6h; 1h para "sin dato"). Fuente
efímera, por-predicción: **no toca el fit ni Supabase**.

- **Ajuste de λ (familia goles/marcador):** un titular ofensivo `out` merma el ataque de
  su equipo en proporción a su cuota de gol del `player_v0.2` (`K=0.6`, tope acumulado
  ±30% por la geometría del clamp); un defensa/arquero `out` sube el λ que concede.
- **Patas de jugador:** si el jugador de la pata está `out` confirmado → su marginal es 0
  → el boleto cae a **SIN_VALOR** con razón visible ("no juega"). Si está **en duda**
  (`doubtful`) → no se ajusta, pero si el veredicto salía `VALOR` se **degrada a
  NO_CONCLUYENTE** (el techo es válido, pero la pata puede caerse).
- **Sin dato** (Sofascore no publica el partido, o el scrape falla) → se analiza **sin
  ajuste** y se dice explícitamente en la respuesta (`ausencias: {sin_dato: true}`).

El scrape corre en un venv aparte (`.venv-scrapling`, Scrapling/patchright) vía
subprocess — el runtime nunca importa scrapling. No hay gate estadístico (no existe
histórico de lesiones): la validación es TDD + e2e + verificación visual.
