# Impacto medido del fix de contaminación en el modelo de goles de Liga 1

**Fecha:** 2026-07-26 · **Tarea 4b** del plan
`docs/superpowers/plans/2026-07-26-premier-league-cobertura.md`
**Commits del fix:** `48b2a82` (filtro por `liga_id`) + `d6c438c` + el de paginación.

## Qué estaba mal

`analyzer._load_and_fit()` ajustaba el Dixon-Coles de clubes leyendo `partidos`
filtrando por temporada y estado, **sin filtrar por liga**. Dos problemas encadenados:

1. **`partidos` no es solo de Liga 1.** Guarda también los partidos internacionales
   (selecciones). Para temporadas 2022-2024 con estado `FINISHED` hay **4.251 filas:
   3.255 internacionales y 996 de Liga 1**.
2. **La consulta no paginaba, y PostgREST corta en 1.000 filas.** Así que el fit ni
   siquiera veía las 4.251: recibía un tajo arbitrario de 1.000 = **654
   internacionales + 346 de Liga 1**.

Resultado neto: el modelo que servía los boletos de Liga 1 se ajustaba con **65% de
partidos de selecciones** y con **solo un tercio de la propia historia de la Liga 1**
(346 de 996). Los `alpha/beta` por equipo no se cruzan (van por `equipo_id`), pero
`mu`, `gamma` y `rho` —los parámetros globales— salían de otra población.

## Parámetros: antes vs. después

Ajuste sobre temporadas 2022-2024 (ANTES = la consulta tal cual la hacía producción).

| param | ANTES | DESPUÉS | delta |
|-------|-------|---------|-------|
| `mu` (tasa base de goles) | 0.0157 | -0.0119 | -0.0276 |
| `gamma` (ventaja de local) | 0.4312 | 0.4623 | **+0.0311** |
| `rho` (corrección marcadores bajos) | -0.0058 | -0.1498 | **-0.1440** |
| equipos en el fit | 237 | 24 | -213 |

Los 237 equipos del "antes" son la prueba visible del problema: la Liga 1 tiene 24.

Lectura: `gamma` **sube**, como se esperaba — la ventaja de local en clubes peruanos es
mayor que en un pool lleno de partidos de selecciones, muchos en cancha neutral. Y
`rho` se vuelve **fuertemente negativo**: en la Liga 1 los marcadores bajos y el empate
pesan mucho más de lo que dice un Poisson puro; mezclado con selecciones, esa corrección
quedaba casi anulada.

## Efecto práctico en probabilidades

Tres partidos reales de Liga 1, P(local) / P(empate) / P(visita):

| partido | ANTES | DESPUÉS |
|---------|-------|---------|
| Alianza Lima vs Atlético Grau | 0.650 / 0.236 / 0.114 | 0.526 / 0.324 / 0.149 |
| UTC Cajamarca vs Sport Boys | 0.706 / 0.166 / 0.128 | 0.512 / 0.305 / 0.183 |
| César Vallejo vs Cienciano | 0.527 / 0.239 / 0.234 | 0.347 / 0.298 / 0.355 |

El modelo viejo era sistemáticamente **demasiado confiado con el local** y subestimaba
el empate. No es un ajuste cosmético: son 10-20 puntos porcentuales.

## ¿Cambia, o mejora? — holdout temporal

Para no quedarnos en "los números se movieron": entrenar con 2022+2023 y evaluar sobre
los **mismos** partidos de Liga 1 de 2024 con los dos modelos, más el baseline ingenuo
(frecuencias H/D/A del train). Se evalúan los 156 partidos que ambos modelos cubren
(el modelo viejo no conoce a muchos equipos de Liga 1, justamente por el truncamiento).

| modelo | Brier | vs baseline |
|--------|-------|-------------|
| VIEJO (producción actual) | 0.2826 | +8.1% |
| **NUEVO (filtrado por liga)** | **0.2740** | **+10.9%** |
| baseline (tasas de liga) | 0.3075 | — |

**El fix mejora la Liga 1 un +3.1% relativo de Brier.** No es solo "distinto": es mejor,
medido en holdout temporal contra el mismo test set.

## Consecuencias

- Los boletos de Liga 1 van a dar probabilidades distintas (más empate, menos local).
  Es la corrección, no una regresión.
- La ruta Internacional **no cambia**: usa params congelados por otro camino
  (`_load_intl_predictor`), intacto.
- La paginación era obligatoria antes de la ingesta de la Premier: son **1.140 partidos
  > 1.000**, así que sin paginar se habrían perdido ~140 en silencio. La Liga 1 (996)
  se salvaba por 4 filas.
