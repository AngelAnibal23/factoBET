# Afinar cola elite del modelo por-jugador — diseño

Fecha: 2026-07-11 · Rama: `feat/cola-elite` (desde master `c56d75e`) · Estado: aprobado por Angel

## Problema

Los jugadores elite (decil 9-10 de `cuota_gol`) sub-predicen: en el holdout temporal
70/30, D10 predice 24.3% y observa 28.1% (gap +3.8 puntos), D9 +1.9; los deciles
medios sobre-predicen (~-2.3). Diagnóstico del 2026-07-11 (307 jugadores elegibles,
1207 registros de test).

**Sospechoso principal: el λ plano del gate, no el shrinkage.** `_gate` y el
diagnóstico usan `LAMBDA_PROXY=1.0` para todos los equipos, pero los elite juegan en
selecciones que anotan más de 1.0/partido (Argentina, Francia ~1.5-2.0) y los deciles
medios incluyen equipos débiles. El patrón observado (elite sub-, medios sobre-) es
exactamente el que ese sesgo produce. El serving NO tiene este problema: usa el λ
real del partido (modelo DC). Parte de la "cola elite" puede ser artefacto de
medición.

Secundario: k=5 del shrinkage fue elegido a mano, nunca tuneado; aplasta a elites con
pocos partidos (Sesko 0.354 shrunk vs 0.500 pooled con n=14).

## Objetivo (criterio de éxito)

Calibración elite HONESTA: que la probabilidad servida a los killers coincida con su
tasa real, medida correctamente (λ por-equipo, no proxy). No es "subir los números
de Messi": si tras arreglar la medición el gap desaparece, el entregable es el gate
honesto y la evidencia de que el serving ya estaba bien.

Alcance: métricas `goal`/`assist` solamente. El modelo SoT hereda los aprendizajes en
su propia iteración. El serving (`player_model.PlayerModel.prob`, betbuilder,
analyzer) no se toca en el Paso A.

## Enfoque aprobado: incremental A→B→C

### Paso A — λ por-equipo en la medición (`fit_player_model.py`)

- Función pura nueva `lambdas_por_equipo(train, k)` → media de `goles_equipo` por
  partido de cada selección, con shrinkage hacia la media global del train (mismo
  patrón `_shrink_share`, k pequeño) para equipos con pocos partidos.
- `_gate` usa `λ_eq = lambdas[r["equipo"]]` en el modelo Y en el baseline
  (`1-exp(-λ_eq/n_titulares)`): ambos lados mejoran su λ, comparación justa.
- El diagnóstico de deciles se re-corre con el mismo λ por-equipo.
- **Criterio de decisión:** si el gap D9-D10 queda dentro de ±1.5 puntos, el problema
  era artefacto de medición → cerrar (sin republicar modelo, params publicados no
  cambian). Si persiste → Paso B.

### Paso B — tunear k (condicional)

Grid k ∈ {1, 2, 3, 5, 8, 12} sobre el mismo split temporal, eligiendo por Brier de
elegibles con λ por-equipo; reportar calibración D9-D10 por k. Regla anti-sobreajuste:
solo cambiar k=5 si la mejora es consistente en goal Y assist (un solo k para ambas;
test de ~1200 registros no da para elegir por-métrica).

### Paso C — estimador ponderado (condicional)

Solo si B no cierra el gap: `estimar_cuotas` pasa a shares ponderados por
`goles_equipo` (pooled con shrinkage). Se especifica en detalle solo si llegamos.

## Cierre y publicación

- Si el modelo cambió (B o C): re-correr gate completo; con ≥3% sobre baseline,
  publicar `player_v0.2` (`load_player_model_to_supabase.py`) y verificar e2e un
  boleto con pata elite (Messi/Kane).
- Si solo cambió la medición (A): commitear gate honesto + este doc actualizado con
  los números finales.

## Testing

TDD. Unitarios para `lambdas_por_equipo`: equipo con muchos partidos ≈ su media
observada; equipo con 1 partido ≈ tirado hacia la media global; train vacío → caso
borde sin crash. Para `_gate` con λ por-equipo: caso sintético donde un equipo fuerte
y uno débil producen probabilidades distintas para jugadores de igual cuota. Suite
completa verde antes de cada commit.
