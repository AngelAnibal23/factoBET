# ADR-0001 — Mercados de conteo: el valor apostable está por-jugador, no por-equipo

**Fecha:** 2026-06-23
**Estado:** Aceptado
**Decisores:** Angel (producto), Claude (implementación)
**Contexto previo:** [[project-capa2-subproyecto-b]], [[project-capa2-dudas-abiertas]] (duda #1),
[[reference-capa2-datasources]]
**Afecta a:** dirección de Capa 2 (mercados de conteo). NO toca Capa 1 (motor de goles),
que queda como está y es producción.

---

## Contexto

Capa 2 nació para des-exotizar las patas de conteo de un bet builder (córners,
tarjetas, tiros, tiros al arco) — hoy el motor solo modela goles (`GOAL_MARKETS`) y
todo lo demás cuenta como pata exótica, lo que arrastra la confianza del ticket a BAJA.

Se ejecutaron tres sub-proyectos:

- **Flashscore pipeline** (cerrado): 1336 filas en Supabase `estadisticas_flashscore`,
  córners 98%, identidad por equipo 99%.
- **Sub-proyecto A** (cerrado): tarjetas+tiros vía FBref a `estadisticas_partido`.
- **Sub-proyecto B** (implementado y funcional, 183 tests verdes, pusheado en
  `origin/master` `30b22f9`): familia `count` integrada al motor con NegBin + shrinkage
  empírico-Bayes, gate por Brier vs baseline de liga, keyeo por `equipo_id`.

**Resultado estadístico de Sub-proyecto B (honesto, con identidad correcta):**

- ✅ **Modelable per-equipo:** TIROS y TIROS AL ARCO, en INT/Mundial y Liga 1
  (params `counts_v0.1` en Supabase, 4 filas).
- ❌ **NO modelable per-equipo:** CÓRNERS y TARJETAS — son situacionales (dependen de
  rival/árbitro/contexto, no son rasgo estable del equipo). El +3.9% de córners-Liga1
  que apareció antes era artefacto de keyear por nombre; con `equipo_id` da −2.4%.

Quedaba abierta la **duda #1** del registro de dudas: *¿las casas siquiera ofrecen los
mercados que logramos modelar?* La decisión de invertir más o pivotar dependía de
verificarlo contra boletos reales, no contra hipótesis.

## Evidencia nueva: verificación contra boletos reales

Se revisaron 3 boletos reales de **Betano** para el **Mundial 2026**
(`ejemploBET3.jpeg`, `BET4.jpeg`, `BET5.jpeg`). Mercados de conteo que la casa ofrece
de verdad:

| Mercado en el boleto | Tipo | ¿Lo modela Sub-proyecto B? |
|---|---|---|
| Lionel Messi — Tiros al Arco 1+ | **por jugador** | ❌ (modelamos por equipo) |
| Cristiano Ronaldo — Tiros al Arco 2+ | **por jugador** | ❌ (modelamos por equipo) |
| Bruno Fernandes — anota o asiste | **por jugador** | ❌ |
| Portugal — Córners Más de 4.5 | por equipo, situacional | ❌ (no modelable) |
| Uzbekistán — Faltas Más de 10.5 | por equipo, situacional | ❌ (no modelable, ≈ tarjetas) |
| Goles 1er tiempo Más de 0.5 | split de mitad | ❌ |
| Resultado / Doble oport. / Goles totales | goles | ✅ (Capa 1) |

**Hallazgo central:** en NINGUNO de los tres boletos aparece un mercado de
**tiros o tiros al arco POR EQUIPO** — que es exactamente lo único que Sub-proyecto B
logró modelar con skill real. Lo que la casa ofrece como "tiros al arco" es
**por jugador** (Messi, Ronaldo). El resto del conteo apostable (córners, faltas) cae
justo en lo **no modelable per-equipo**.

La app lo confirmó en vivo (`resultadoBET3.png`): clasificó "Lionel Messi Tiros al
Arco" como **pata no modelada**, computó techo 42.1% vs casa 53.5% y dictó SIN VALOR.
El motor se comporta correctamente; el problema no es el motor sino el **alcance del
modelo de datos**.

## Decisión

1. **El esfuerzo de modelado de conteo se reorienta a mercados POR JUGADOR.** El valor
   práctico (lo que el usuario realmente apuesta en un bet builder) está en
   tiros-al-arco del jugador, jugador-que-anota y jugador-anota-o-asiste. La fuente ya
   sondeada y viable es el feed por-jugador de Flashscore `df_sui_1`
   (goleador/amonestado/asistencia/penal/splits-mitad — ver
   [[reference-capa2-datasources]]).

2. **El modelo por-equipo de tiros/tiros-al-arco (Sub-proyecto B) NO se descarta ni se
   borra.** Queda en producción como:
   - Cota superior (techo) válida para cualquier pata count por-equipo que sí llegue.
   - Base reutilizable: el patrón NegBin + shrinkage + gate y el ruteo de la familia
     `count` en el motor sirven igual para el modelo por-jugador.
   No se invierte MÁS en densificar/tunear el por-equipo mientras no haya demanda en los
   boletos.

3. **Córners y tarjetas/faltas se aceptan como NO modelables per-equipo** y permanecen
   exóticos (situacionales). No se sigue persiguiendo córners pese a haber sido la
   motivación original de elegir Flashscore. Si en el futuro se quiere un número, será a
   **nivel-liga** (baseline calibrado sin skill) o como **derivado** de volumen de
   tiros, nunca como tasa propia per-equipo — pero queda fuera de alcance ahora.

4. **Capa 1 (goles) no se toca.** Sigue siendo la única familia con veredicto VALOR
   exacto; el resto modula el techo hacia abajo.

## Consecuencias

**Positivas**
- Se deja de invertir en una rama (tiros por-equipo) sin demanda real comprobada.
- El próximo trabajo ataca lo que de verdad aparece en los boletos → más patas
  des-exotizadas por ticket → confianza ALTA/MEDIA alcanzable en casos reales.
- Reutilizamos toda la infraestructura de Sub-proyecto B (motor, NegBin, gate, OCR de
  familia `count`).

**Negativas / costos**
- El trabajo de densificación del Mundial (~280→~990 partidos) y los params
  `counts_v0.1` quedan con uso marginal (solo como techo), no como su propósito original.
- El modelado por-jugador es más difícil: muestras por jugador más chicas, minutos
  jugados/titularidad como covariable, anulación si no inicia (los boletos lo dicen:
  "si un jugador no inicia, se anularán sus selecciones"). El gate será más exigente.
- Hay que extender el OCR para reconocer patas por-jugador (nombre del jugador + métrica)
  y el motor para una sub-familia `count_player`.

**Riesgos abiertos que el ADR NO cierra** (siguen en [[project-capa2-dudas-abiertas]]):
refresh de datos (#11), consolidación de los dos pipelines FBref vs Flashscore (#12),
validación cruzada del gate (#4), params como JSON en `notas` (#13), integración a
frontend (#14). Se abordarán cuando toquen el camino del trabajo por-jugador.

## Alternativas consideradas

- **A) Seguir densificando el por-equipo** (más amistosos, tunear k, cross-validation).
  Rechazada: aunque mejore el skill estadístico, no hay demanda en los boletos. Optimizar
  algo que nadie apuesta.
- **B) Modelar córners a nivel-liga o como derivado de tiros.** Diferida: da un número
  calibrado sin skill (poco valor para detectar SIN_VALOR) y no es prioridad frente a
  por-jugador. Queda como nota para el futuro.
- **C) Pivote a por-jugador (df_sui_1).** **Elegida.** Es lo que aparece en los boletos
  reales y la fuente ya está sondeada como viable.

## Próximos pasos

1. Brainstorming + spec del modelo por-jugador (métrica objetivo: tiros al arco del
   jugador y anota/asiste; covariable de minutos/titularidad; manejo de anulación).
2. Confirmar la extracción del feed `df_sui_1` de Flashscore a tabla nueva
   (p.ej. `estadisticas_jugador_flashscore`).
3. Reusar el patrón de Sub-proyecto B: modelo puro → fit con gate → load params →
   ruteo en analyzer → OCR sub-familia `count_player` → veredicto por techo (sin tocar
   el contrato externo de la API).
