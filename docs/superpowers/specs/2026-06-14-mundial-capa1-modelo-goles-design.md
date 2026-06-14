# Diseño: Phase 5 — Mundial, Capa 1 (Modelo de Goles)

**Fecha:** 2026-06-14
**Estado:** En revisión por Angel

---

## Contexto

Helpbetor hoy solo analiza Liga 1 Peruana (Dixon-Coles v0.2 entrenado con 996 partidos de clubes peruanos). Phase 5 habilita el análisis de parlays del Mundial 2026.

Phase 5 se construye **en capas por viabilidad** (decisión 2026-06-14):
- **Capa 1 (este spec):** modelo de **goles** para selecciones → mercados 1X2, over/under, BTTS, hándicap.
- **Capa 2 (futura):** córners, tarjetas, tiros por equipo (ESPN tiene la data; un modelo Poisson por mercado).
- **Fuera de alcance:** props de jugador individual (data gratuita no confiable).

Este spec cubre **solo Sub-proyecto A = Capa 1**: datos + modelo + validación Brier + carga a Supabase. **No** toca validator, analyzer ni frontend (eso es Sub-proyecto B, condicionado a que el modelo calibre).

---

## Principio rector

El orden refleja "validar primero": el modelo se ajusta y se mide **antes** de invertir en cargar Supabase. Si el Brier no supera el baseline ingenuo, el proyecto se detiene en seco y no se carga nada.

---

## Fuente de datos

Dataset abierto `martj42/international_results`:
- URL: `https://raw.githubusercontent.com/martj42/international_results/master/results.csv`
- 49,477 partidos internacionales (1872 → presente), verificado 2026-06-14
- Columnas: `date, home_team, away_team, home_score, away_score, tournament, city, country, neutral`
- La columna `neutral` (bool) indica si el partido fue en cancha neutral — clave para la ventaja de local

**Filtro:** partidos desde **2018-01-01** con marcador no nulo. Se incluyen **todos** los partidos internacionales (no solo de selecciones del Mundial 2026, no solo Mundiales): los rivales informan la fuerza relativa de cada selección en el sistema de ratings.

---

## Arquitectura

| Acción | Archivo | Responsabilidad |
|---|---|---|
| Crear | `download_intl_results.py` | Descarga CSV, filtra 2018+, guarda copia local limpia |
| Crear | `engine_intl_v01.py` | Ajusta Dixon-Coles con cancha neutral desde el CSV, mide Brier |
| Crear | `load_intl_to_supabase.py` | (Solo si pasa el gate) carga equipos + partidos a Supabase |
| Crear | `tests/test_engine_intl.py` | Tests de las funciones puras del modelo (acierto de probabilidades, tau, neutral) |
| Modificar | Supabase (DDL vía Management API) | Agregar columna `neutral` a `partidos`; crear liga "Internacional" |

**Sin tocar:** `engine_v02.py`, `analyzer.py`, `validator.py`, `main.py`, `resolver.py`, frontend. El motor de Liga 1 sigue intacto.

---

## El modelo: Dixon-Coles con cancha neutral

`engine_intl_v01.py` reusa la matemática de `engine_v02.py` con **una diferencia estructural**:

### Ventaja de local condicional
En Liga 1, todo partido tiene local, así que la tasa de goles del local es:
```
lambda_home = exp(mu + alpha_home + beta_away + gamma)
lambda_away = exp(mu + alpha_away + beta_home)
```
En internacionales, la ventaja `gamma` **solo aplica si `neutral == False`**:
```
g = gamma if not neutral else 0.0
lambda_home = exp(mu + alpha_home + beta_away + g)
lambda_away = exp(mu + alpha_away + beta_home)
```
Esto vale tanto al **ajustar** (en la log-verosimilitud, cada partido usa su propio `neutral`) como al **predecir** (un partido de Mundial en cancha neutral predice sin ventaja; un anfitrión 2026 en casa sí la recibe).

### Resto igual que v0.2
- Time-weighting exponencial: `peso = exp(-xi * dias_desde_partido)`, normalizado.
- Corrección Dixon-Coles `tau` para marcadores bajos (rho).
- Optimización L-BFGS-B con regularización L2 sobre alphas/betas.
- `MAX_GOALS = 10` para las sumas de Poisson.

### Sin ponderación por torneo (v1)
Se arranca tratando todos los partidos igual (solo time-weighting), igual que Liga 1. Ponderar competitivos > amistosos queda como **primera palanca de ajuste** si el Brier es pobre — no se implementa en v1 (YAGNI).

---

## Validación y gate de Brier

### Metodología (idéntica a Liga 1)
- **Holdout temporal:** entrenar con partidos **2018-01-01 a 2024-12-31**, testear con **2025-01-01 en adelante**.
- Para cada partido de test, el modelo predice P(home)/P(draw)/P(away) vía Dixon-Coles.
- **Brier score multiclase** sobre esas predicciones 1X2.

### Baseline ingenuo (el bar a superar)
Predecir SIEMPRE con las tasas base históricas del set de entrenamiento — es decir, las frecuencias globales de home/draw/away (respetando `neutral`: una tasa para partidos con local, otra para neutrales). Se calcula su Brier sobre el mismo test.

### Criterio de greenlight (concreto)
Greenlight si se cumplen **ambas**:
1. `brier_modelo < brier_baseline` (el modelo es estrictamente mejor), y
2. mejora relativa `(brier_baseline - brier_modelo) / brier_baseline >= 0.03` (al menos 3% mejor).

Razón del 3%: en internacionales la brecha de nivel entre selecciones es grande, así que un modelo de goles sano debería superar cómodamente a un baseline de tasas globales (típicamente >10% relativo). Si la mejora es <3%, el modelo casi no aporta señal sobre "adivinar con la tasa promedio" — señal de que algo está mal. Referencia: Liga 1 v0.2 dio Brier 0.2797.

- ✅ **Pasa** → proceder a cargar Supabase (siguiente sección) y luego Sub-proyecto B.
- ❌ **No pasa** → detenerse. Documentar el resultado, no cargar nada, reconsiderar (ej. ponderación por torneo, otra ventana temporal) antes de seguir.

El script imprime: Brier del modelo, Brier del baseline, margen, n_partidos_fit, n_partidos_val, y el veredicto.

---

## Carga a Supabase (solo si pasa el gate)

`load_intl_to_supabase.py`, ejecutado manualmente tras confirmar el Brier:

1. **DDL previo (vía Management API):**
   - Agregar columna `neutral BOOLEAN DEFAULT false` a `partidos`.
   - Insertar fila en `ligas`: nombre "Internacional", país NULL, `nivel_cobertura` según el Brier obtenido.
2. **Selecciones nacionales → `equipos`:** una fila por selección distinta presente en los partidos filtrados. `nombre_oficial` = nombre del dataset (inglés, ej. "France"). `liga_id` = la liga internacional. (Los alias español→inglés son trabajo de Sub-proyecto B / validator — aquí no.)
3. **Partidos → `partidos`:** una fila por partido del CSV filtrado. Mapear `home_team`/`away_team` → `equipo_id`. Guardar `goles_local`, `goles_visitante`, `fecha`, `resultado` (HOME/DRAW/AWAY), `neutral`, `estado="FINISHED"`, `fuente="martj42"`, `temporada` = año.
4. **Modelo ajustado → `parametros_modelo`:** una fila con `version_modelo="intl_v0.1"`, `liga_id` internacional, `mu/gamma/rho/xi`, `attack_params`/`defense_params` (JSONB por selección), `brier_score`, `n_matches_fit`, `n_matches_val`, `is_production=true`.

`api_football_id` queda NULL para estos partidos y equipos (no vienen de API-Football). Esto es válido (la columna permite NULL salvo el UNIQUE, que NULL no viola).

---

## Testing

`tests/test_engine_intl.py` cubre las funciones puras (sin red ni DB), con parámetros de modelo fijos/sintéticos:

- `_tau`: los 4 casos de corrección Dixon-Coles (0-0, 1-0, 0-1, 1-1) y el caso neutro (devuelve 1.0).
- Predicción 1X2: con lambdas conocidas, P(home)+P(draw)+P(away) ≈ 1.0.
- **Ventaja neutral:** con los mismos equipos, un partido `neutral=True` da `lambda_home` menor que el mismo con `neutral=False` (la ventaja desaparece). Test explícito de esta diferencia.
- Brier de un caso trivial: predicción perfecta → Brier 0; predicción 1/3-1/3-1/3 → Brier conocido.

El ajuste completo (optimización sobre 4,640 partidos) y la carga a Supabase se validan ejecutando los scripts manualmente, no en unit tests.

---

## Criterios de éxito de Sub-proyecto A

1. `download_intl_results.py` deja un CSV local filtrado (2018+, marcador no nulo).
2. `engine_intl_v01.py` ajusta el modelo, imprime Brier del modelo vs baseline y un veredicto claro.
3. Tests del motor en verde.
4. **Gate:** si el modelo supera el baseline → `load_intl_to_supabase.py` carga equipos, partidos y parámetros; queda listo para Sub-proyecto B.
5. Si no supera el baseline → resultado documentado, nada cargado, decisión consciente de cómo seguir.

---

## Fuera de alcance (explícito)

- Validator: reconocer nombres de selecciones + alias español→inglés → **Sub-proyecto B**.
- Analyzer: ruteo Liga 1 vs Internacional según el parlay → **Sub-proyecto B**.
- Frontend, narrativa, resolver para Mundial → **Sub-proyecto B** (el resolver ya soporta `fifa.world`, falta que los equipos estén en `equipos`).
- Córners, tarjetas, tiros, props de jugador → **Capa 2** y siguientes.
- Ponderación por torneo (competitivo vs amistoso) → palanca de ajuste solo si el Brier lo exige.
