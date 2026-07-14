# Diseño: ELO como prior del motor Dixon-Coles internacional

**Fecha:** 2026-07-13
**Estado:** aprobado por Angel (brainstorming de esta fecha)
**Fase del roadmap:** Fase 3 — robustez del motor, punto (5)
**Rama sugerida:** `feat/elo-prior-intl`

## Problema

El Dixon-Coles internacional (`engine_intl_v01.py`) estima ataque (α) y defensa (β)
por selección, pero la muestra es dispareja:

1. **Selecciones con pocos partidos en el train**: su α/β se estima con ruido y la
   penalización L2 actual (`l2·Σ(α²+β²)`) los encoge hacia 0 — es decir, hacia
   "equipo promedio". Un prior de "todos los equipos son iguales".
2. **Selecciones fuera del modelo**: el fallback de `lambdas()` usa λ promedio puro
   (`exp(μ+γ)` / `exp(μ)`), así que un no-visto vs Brasil se predice como partido
   parejo.

ELO resuelve ambos con un solo mecanismo: anclar la fuerza de cada equipo a lo que
su historial largo dice que es, en vez de al promedio universal.

## A qué afecta (y a qué no)

**Afecta (gratis, sin tocar su código):** toda pata que salga de los λ del DC intl —
1X2, over/under, BTTS, hándicap, resultado exacto, doble oportunidad, marcador más
probable, y el modelo por-jugador anota/asiste (top-down: λ_jugador = λ_equipo × cuota).

**NO afecta (fuera de alcance):** conteos por-equipo (tiros/SoT, modelo NegBin propio
— ELO es señal de goles) y SoT por-jugador (cuelga de counts, no del DC). Liga 1 no
se toca (descartada como inversión 2026-07-12).

**Fuera de alcance explícito (decisión del brainstorming):** el ajuste por lesiones
(restar ataque si se lesiona un delantero, etc.) es el capítulo de Fase 3 punto (4)
— lesiones vía Sofascore. Se conecta ENCIMA de esto (ajustando α/β al servir), no se
mezcla en este capítulo.

## Decisiones del brainstorming

- **Propósito**: ambos problemas (pocos partidos + fuera del modelo), un mecanismo.
- **Enfoque A elegido** (prior en el fit). Descartados: B (solo fallback — no arregla
  el ruido de equipos con muestra chica) y C (blend post-hoc de probabilidades 1X2 —
  rompe la consistencia entre patas: over/under, marcador y jugador salen de λ, no
  del 1X2).
- **Fuente ELO**: lo calculamos nosotros (fórmula World Football Elo estándar) sobre
  el histórico martj42 ya en el stack. Cero scraping, misma identidad de nombres.
- **Blend FIFA**: Angel quiere probar `0.7·nuestro + 0.3·FIFA` (predominante el
  nuestro). Decisión honesta: el ranking FIFA post-2018 ya es una fórmula tipo Elo
  sobre los mismos resultados (señal no independiente, peor calibrada). **El gate
  decide empíricamente**: se corren ambas variantes y se publica la que gane. Si no
  hay fuente FIFA decente sin scraping frágil (se buscan CSVs históricos públicos),
  el blend se pospone y se anota — no bloquea el capítulo.

## Componentes

### 1. `elo_intl.py` (nuevo, puro, sin red)

Recorre el histórico martj42 partido a partido y produce `{selección: elo}` a una
fecha de corte.

- Rating inicial 1500 para todos; histórico desde ~1990 para que los ratings estén
  maduros en la era relevante (el CSV fuente llega a 1872; hoy `intl_results.csv`
  está filtrado a 2018+, así que el download se relaja de filtro — misma fuente).
- **K por importancia del torneo** (columna `tournament` del CSV): Mundial 60,
  continentales/Copa América 50, eliminatorias 40, Nations League 40, amistosos 20.
- **Multiplicador por diferencia de goles** (estándar World Football Elo: ×1.5 si
  gana por 2, ×1.75 por 3, +0.25 por gol extra a partir del 4º).
- **Ventaja local +100 puntos** solo cuando `neutral == False` (mismo flag que el DC).
- **Estandarización**: salida final como z-scores sobre los equipos presentes
  (`z = (elo − media)/desvío`), que es lo que consume el prior.
- **Blend FIFA opcional**: ambos rankings a z-scores → `z_final = 0.7·z_nuestro +
  0.3·z_fifa`. Equipos sin FIFA usan solo el nuestro.

### 2. Prior en `engine_intl_v01.fit`

Cambio mínimo a la penalización (y su gradiente):

```
α₀ᵢ = +c·zᵢ        β₀ᵢ = −c·zᵢ
penalty = l2·Σ[(αᵢ−α₀ᵢ)² + (βᵢ−β₀ᵢ)²]
grad    = ... + 2·l2·(α−α₀)   (antes 2·l2·α)
```

- ELO alto ⇒ ancla "ataca más, le anotan menos". Equipos con muchos partidos: la
  verosimilitud domina y el prior casi no pesa. Muestra chica: el prior manda.
- **La escala `c` no se inventa**: grid chico (ej. {0.1, 0.2, 0.3, 0.5}) contra el
  Brier del holdout. El dato decide.
- `fit(..., elo=None)` reproduce exactamente el comportamiento actual (α₀=β₀=0) —
  backward compatible, los tests existentes no cambian.

### 3. Serving: params y fallback

- **Publicación**: `parametros_modelo` (Supabase), versión `engine_intl_v0.2`
  (v0.1 queda de rollback — ritual conocido). El JSON de notas añade: tabla
  `{selección: z}`, escala `c`. `load_intl_to_supabase.py` se extiende.
- **Fallback en `lambdas()`/`from_params`**: si el equipo no está en `idx` pero SÍ
  tiene z en la tabla ELO ⇒ sintetizar `α = c·z`, `β = −c·z` (mismo mapeo del
  prior). Si tampoco tiene ELO ⇒ fallback actual (promedio). Degradación con
  gracia, cero regresión.
- **No se toca**: `betbuilder.py`, `marcador.py`, `counts_model`, `player_model`,
  frontend. `analyzer._load_intl_model` solo pasa los 2 campos nuevos a
  `from_params`.

### 4. Gate

Esto es un **refinamiento vs el modelo actual**, no una pata nueva vs baseline
ingenuo — el rival a vencer es el DC v0.1 tal cual:

- Split temporal igual que siempre: train ≤ 2024-12-31, test 2025+.
- **Condición dura (global)**: Brier 1X2 en TODO el test no empeora más de 0.5%
  relativo vs DC v0.1. Si el prior daña a los equipos bien muestreados, no se publica.
- **Condición de publicación (segmento objetivo)**: mejora **≥3% relativa** en el
  Brier del segmento sparse — partidos donde al menos un equipo tiene pocos
  partidos ponderados en el train (umbral inicial ~15; se fija mirando la
  distribución real antes de correr el gate, y queda documentado).
- El gate corre 3 variantes y elige: `v0.1 (sin prior)` vs `prior ELO nuestro` vs
  `prior blend FIFA` (si hay fuente). Se publica la ganadora; si ninguna variante
  ELO pasa, NO se publica nada y se guarda el diagnóstico.

### 5. Testing (TDD)

- `tests/test_elo_intl.py`: K por torneo, multiplicador de goles, ventaja local
  condicional a neutral, convergencia direccional en histórico sintético (el que
  siempre gana sube), estandarización, blend.
- `engine_intl`: gradiente del prior vs gradiente numérico (patrón existente);
  `elo=None` ⇒ fit idéntico al actual.
- `from_params`/`lambdas()`: round-trip con tabla ELO, fallback sintetizado,
  fallback sin-ELO intacto.
- Suite completa (249) sigue verde; e2e final con `?demo`.

## Flujo de implementación

`elo_intl.py` → prior en `fit` → gate extendido (main de `engine_intl_v01`) →
`load_intl_to_supabase.py` v0.2 → fallback en `from_params`/`lambdas()` →
e2e → COBERTURA/roadmap.

## Riesgos conocidos

- **Fuga temporal**: el ELO que ancla el prior del train debe calcularse con corte
  en la fecha de fin del train (2024-12-31), NO con resultados del test. El de
  serving sí puede ser el más fresco.
- **Nombres**: martj42 es la misma fuente del DC, así que la identidad ya está
  resuelta; el blend FIFA sí requiere casar nombres (alias ES/EN ya existentes
  ayudan) — si el casado es sucio, es un motivo más para que el gate lo descarte.
- **Doble conteo de la ventaja local**: el ELO usa +100 de local internamente para
  SUS updates; el DC tiene su propio γ. No interactúan (el prior solo ancla α/β),
  pero se anota para no "corregir" γ por error.
