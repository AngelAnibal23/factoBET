# Estado del proyecto — cierre v1 (2026-07-29)

Helpbetor analiza **bet builders** (apuestas combinadas de un mismo partido): lee el
boleto, estima la probabilidad de cada pata con modelos propios, calcula un **techo** para
la conjunta y lo compara con la cuota para dar un veredicto.

**Este documento existe para que el proyecto se pueda retomar en frío** — dentro de seis
meses, o nunca. Lo que cubre el motor está en [`COBERTURA.md`](COBERTURA.md); esto es el
estado operativo: qué corre, cómo se levanta y qué quedó a medias **a propósito**.

## Qué está terminado y en producción

Todo lo de abajo está mergeado en `master`, pusheado, y con sus parámetros publicados en
Supabase. No requiere ninguna acción para seguir funcionando.

| Capa | Ligas | Versión publicada |
|---|---|---|
| Goles (1X2, over/under, BTTS, hándicap, resultado exacto, doble oportunidad) | Liga 1, Internacional, Premier | Dixon-Coles, fit en runtime (no publica params) |
| Marcador más probable | Internacional | — |
| Conteos por equipo (tiros, tiros al arco) | Internacional, Liga 1 | `counts_v0.1` |
| Jugador: anota / asiste / anota-o-asiste | Internacional (513), Premier (574) | `player_v0.2` |
| Jugador: tiros al arco | Internacional (358), Premier (216) | `player_sot_v0.1` |
| Ausencias (lesiones/suspensiones, scrape on-demand) | Internacional | sin params (efímero) |

Suite: **382 tests verdes** (`python -m pytest -q`).

## Cómo levantarlo

Requiere `.env` en la raíz (⚠️ la variable se llama **`SUPABASE_KEY`**, no
`SUPABASE_SERVICE_KEY`) y una Supabase activa — el plan gratis **pausa el proyecto por
inactividad**, hay que despausarlo desde el dashboard antes de esperar que algo responda.

```bash
python -m uvicorn main:app --port 8000     # backend, desde la raíz. SIN --reload
cd frontend && npm run dev                 # frontend, Vite en :5173
```

- **`--reload` no**: en Windows deja un worker huérfano al matarlo.
- El backend **tarda ~3-5 min en abrir el puerto** (`warm_up` ajusta los modelos al
  arrancar). No está colgado.
- El proxy de Vite apunta fijo a `localhost:8000`, así que el backend no puede ir en otro
  puerto si se usa la UI.

**Casos de demo sin red ni Gemini** (útiles para verificar la UI de un tirón):
`?demo=` (internacional, con la pata de Messi) · `?demo=premier` · `?demo=ausencias` ·
`?demo=error:CODIGO`. Si algo se ve raro: **Ctrl+Shift+R** — una vez se perdió una tarde
depurando un "bug" que era caché del navegador.

## Lo que quedó fuera a propósito

1. **Backfill de tiros al arco de la Premier — parado al 16%.** El modelo se publicó con
   184 de 1.140 fixtures hidratados porque el gate ya pasaba holgado (**+24.2%**, Brier
   0.1538 vs 0.2028). Lo que falta no es precisión, es **cobertura**: el backfill avanza en
   orden cronológico, así que los 216 jugadores son casi todos de la temporada 2022/23 y un
   fichaje posterior sale `faltante`.

   Para reanudarlo (956 fixtures pendientes, ~88/día por la cuota del plan Free de
   API-Football, ~11 días):
   ```bash
   python download_sot_jugador.py hidratar 88   # un lote/día, DESPUÉS de las 19:00 Lima
   python fit_player_sot.py                     # solo lectura, se puede correr cuando sea
   python load_player_sot_to_supabase.py        # publica solo las ligas que pasan el gate
   ```
   La ventana de cuota resetea a las **00:00 UTC = 19:00 Lima**; un lote corrido antes de
   esa hora se come la ventana del día siguiente. El progreso se consulta en la tabla
   `sot_backfill_progreso` (no gasta cuota). **No** programar una tarea de Windows: ya se
   intentó y no se disparó.

2. **Conteos por equipo en la Premier — medido y descartado.** Gate negativo en las cuatro
   métricas; la causa está diagnosticada (la Premier es demasiado homogénea en volumen de
   tiros) en `COBERTURA.md`. Los datos están cargados por si algún día se revisa; no es una
   tarea pendiente, es una decisión.

3. **Revisión visual de `?demo=premier`** — el backend está verificado end-to-end (envelope,
   alias, veredicto, techo, confianza); nadie miró la pantalla. Riesgo cosmético.

4. **Prior ELO** — implementado y mergeado, pero **no publicado**: la mejor variante mejoraba
   +1.7% en equipos con pocos partidos y el gate pedía ≥3%. Queda como capacidad latente,
   re-gateable con más datos.

## La regla que explica casi todas las decisiones

**Un gate que no pasa → la pata sale `faltante`, nunca un número malo.** El motor prefiere
decir "no sé" antes que dar una probabilidad en la que no confía. Por eso hay patas
implementadas que no están publicadas, y por eso el veredicto `VALOR` solo aparece cuando
todas las patas son de la misma familia y ninguna falta.

## Deuda conocida (nada de esto bloquea)

- Los scrapers son one-shot: **los datos no se refrescan solos** y envejecen. Este es el
  primer punto que va a doler si el proyecto se retoma en serio.
- ~37 `.py` planos en la raíz (scripts de ingesta/fit/carga sin paquete).
- Las familias de conteos y jugador se renderizan con cards genéricas; no tienen visuales
  propios.
- Los boletos de referencia viven en `boletos/` (local, ignorado por git a propósito).
