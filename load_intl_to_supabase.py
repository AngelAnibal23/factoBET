"""
Carga GATED del modelo internacional (Mundial 2026) a Supabase.

Ejecutar SOLO tras un GREENLIGHT de engine_intl_v01.py. Este script vuelve a
correr el gate de Brier internamente como defensa: si el modelo no supera al
baseline por >= 3%, ABORTA sin tocar Supabase.

Arquitectura (decision Opcion B — congelar parametros):
  - Los parametros de PRODUCCION se ajustan sobre TODO el dataset (2018->2026),
    porque es lo mejor para predecir el Mundial. El gate (train <= 2024 /
    test 2025+) ya valido que el metodo generaliza; su Brier de holdout se
    guarda como `brier_score` y se documenta en `notas`.

Pasos:
  1. DDL via Management API: columna `neutral` en partidos + tabla parametros_modelo.
  2. Liga "Internacional" (idempotente).
  3. Selecciones nacionales -> equipos (idempotente).
  4. Partidos -> partidos (recarga limpia: borra los intl y reinserta).
  5. Modelo de produccion -> parametros_modelo (intl_v0.1, is_production=true).
  6. Verificacion + resumen.
"""

import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client

from engine_intl_v01 import (
    cargar_csv, DixonColesIntl, baseline_tasas, predecir_baseline,
    brier_score, TRAIN_HASTA, TEST_DESDE, XI,
)

load_dotenv()

SUPA_URL = os.environ["SUPABASE_URL"]
SUPA_KEY = os.environ["SUPABASE_KEY"]
PROJECT_REF = "aahaivisyghpgqarqpak"
MGMT_TOKEN = os.environ["SUPABASE_MANAGEMENT_TOKEN"]
MGMT_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"

GATE_MIN_MEJORA = 0.03   # mismo umbral que el gate del motor


# ── DDL via Management API ────────────────────────────────────────────────────

def run_ddl(sql):
    resp = requests.post(
        MGMT_URL,
        headers={"Authorization": f"Bearer {MGMT_TOKEN}", "Content-Type": "application/json"},
        json={"query": sql},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


DDL_PARAMETROS = """
CREATE TABLE IF NOT EXISTS parametros_modelo (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    liga_id         UUID REFERENCES ligas(id),
    version_modelo  TEXT NOT NULL,
    temporada_fit   TEXT,
    mu              NUMERIC(10,6),
    gamma           NUMERIC(10,6),
    rho             NUMERIC(10,6),
    xi              NUMERIC(10,6),
    attack_params   JSONB,
    defense_params  JSONB,
    brier_score     NUMERIC(10,6),
    log_loss        NUMERIC(10,6),
    n_matches_fit   INTEGER,
    n_matches_val   INTEGER,
    is_production   BOOLEAN DEFAULT false,
    fitted_at       TIMESTAMPTZ DEFAULT NOW(),
    notas           TEXT
);
ALTER TABLE parametros_modelo DISABLE ROW LEVEL SECURITY;
"""


# ── Gate de Brier (re-chequeo defensivo antes de cargar) ──────────────────────

def rechequear_gate(train, test):
    """Reajusta el modelo solo sobre train y lo evalua en test. Devuelve
    (brier_modelo, brier_baseline, mejora_rel). NO usa el modelo de produccion."""
    ref_date = datetime.fromisoformat(TEST_DESDE).replace(tzinfo=timezone.utc)
    modelo = DixonColesIntl().fit(train, ref_date)

    tasas = baseline_tasas(train)
    preds_m, preds_b = [], []
    for m in test:
        if m["resultado"] not in ("HOME", "DRAW", "AWAY"):
            continue
        preds_m.append((*modelo.predict(m["home"], m["away"], m["neutral"]), m["resultado"]))
        preds_b.append((*predecir_baseline(tasas, m["neutral"]), m["resultado"]))

    bs_m = brier_score(preds_m)
    bs_b = brier_score(preds_b)
    return bs_m, bs_b, (bs_b - bs_m) / bs_b


# ── Carga ─────────────────────────────────────────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n" + "=" * 60)
    print("HELPBETOR — CARGA INTERNACIONAL A SUPABASE (intl_v0.1)")
    print("=" * 60)

    partidos = cargar_csv()
    train = [m for m in partidos if m["fecha"] <= TRAIN_HASTA]
    test  = [m for m in partidos if m["fecha"] >= TEST_DESDE]

    # ── GATE defensivo: si no pasa, no se carga nada ──
    print(f"\n[gate] Re-chequeando Brier (train {len(train)} / test {len(test)})...")
    bs_m, bs_b, mejora = rechequear_gate(train, test)
    print(f"  Brier modelo={bs_m:.4f}  baseline={bs_b:.4f}  mejora={mejora*100:+.1f}%")
    if not (bs_m < bs_b and mejora >= GATE_MIN_MEJORA):
        print("  ❌ NO PASA el gate. ABORTANDO carga (Supabase intacto).")
        sys.exit(1)
    print("  ✅ GREENLIGHT — se procede a cargar.")

    sb = create_client(SUPA_URL, SUPA_KEY)

    # ── Paso 1: DDL ──
    print("\n[1/5] DDL: columna neutral + tabla parametros_modelo...")
    run_ddl("ALTER TABLE partidos ADD COLUMN IF NOT EXISTS neutral BOOLEAN DEFAULT false;")
    run_ddl(DDL_PARAMETROS)

    # ── Paso 2: liga Internacional (idempotente por nombre) ──
    print("[2/5] Liga 'Internacional'...")
    existing = sb.table("ligas").select("id").eq("nombre", "Internacional").execute().data
    if existing:
        liga_id = existing[0]["id"]
    else:
        liga_id = sb.table("ligas").insert({
            "nombre": "Internacional",
            "pais": None,
            "nivel_cobertura": "MEDIA",
            "modelo": "dixon_coles_intl_v0.1",
        }).execute().data[0]["id"]
    print(f"  liga_id = {liga_id}")

    # ── Paso 3: equipos (selecciones), idempotente por nombre_oficial ──
    print("[3/5] Selecciones -> equipos...")
    nombres = sorted(set([m["home"] for m in partidos] + [m["away"] for m in partidos]))
    ya = {e["nombre_oficial"]: e["id"]
          for e in sb.table("equipos").select("id, nombre_oficial").eq("liga_id", liga_id).execute().data}
    equipo_id = dict(ya)
    nuevos = [{"nombre_oficial": n, "liga_id": liga_id} for n in nombres if n not in ya]
    for i in range(0, len(nuevos), 100):
        for row in sb.table("equipos").insert(nuevos[i:i+100]).execute().data:
            equipo_id[row["nombre_oficial"]] = row["id"]
    print(f"  {len(nombres)} selecciones ({len(nuevos)} nuevas, {len(ya)} ya existian)")

    # ── Paso 4: partidos (recarga limpia) ──
    print("[4/5] Partidos -> partidos (borrando intl previos y reinsertando)...")
    sb.table("partidos").delete().eq("liga_id", liga_id).execute()
    filas = [{
        "liga_id":             liga_id,
        "equipo_local_id":     equipo_id[m["home"]],
        "equipo_visitante_id": equipo_id[m["away"]],
        "fecha":               m["fecha"],
        "temporada":           m["fecha"][:4],
        "estado":              "FINISHED",
        "goles_local":         m["gl"],
        "goles_visitante":     m["gv"],
        "resultado":           m["resultado"],
        "neutral":             m["neutral"],
        "fuente":              "martj42",
    } for m in partidos]
    for i in range(0, len(filas), 500):
        sb.table("partidos").insert(filas[i:i+500]).execute()
    print(f"  {len(filas)} partidos cargados")

    # ── Paso 5: parametros_modelo (produccion = fit sobre TODO el dataset) ──
    print("[5/5] Ajustando modelo de produccion (todo el dataset) y guardando params...")
    ref_prod = datetime.now(tz=timezone.utc)
    modelo = DixonColesIntl().fit(partidos, ref_prod)
    if not modelo.converged:
        print("  ⚠ ADVERTENCIA: el fit de produccion reporto Convergio=False.")

    attack  = {t: float(modelo.alphas[modelo.idx[t]]) for t in modelo.teams}
    defense = {t: float(modelo.betas[modelo.idx[t]])  for t in modelo.teams}
    anios = [m["fecha"][:4] for m in partidos]
    temporada_fit = f"{min(anios)}..{max(anios)}"

    # una sola fila is_production=true por liga
    sb.table("parametros_modelo").update({"is_production": False}).eq("liga_id", liga_id).execute()
    sb.table("parametros_modelo").insert({
        "liga_id":        liga_id,
        "version_modelo": "intl_v0.1",
        "temporada_fit":  temporada_fit,
        "mu":             float(modelo.mu),
        "gamma":          float(modelo.gamma),
        "rho":            float(modelo.rho),
        "xi":             XI,
        "attack_params":  attack,
        "defense_params": defense,
        "brier_score":    round(bs_m, 6),
        "n_matches_fit":  len(partidos),
        "n_matches_val":  len(test),
        "is_production":  True,
        "notas": (
            f"Dixon-Coles internacional (gamma condicional a neutral). "
            f"Produccion ajustada sobre todo el dataset ({temporada_fit}). "
            f"Brier validado en holdout temporal train<={TRAIN_HASTA[:4]}/test{TEST_DESDE[:4]}+ "
            f"= {bs_m:.4f} ({mejora*100:+.1f}% vs baseline {bs_b:.4f})."
        ),
    }).execute()
    print(f"  parametros_modelo: intl_v0.1 (is_production=true, {len(modelo.teams)} selecciones)")

    # ── Verificacion ──
    print("\n[verificacion]")
    n_eq = sb.table("equipos").select("id", count="exact").eq("liga_id", liga_id).execute().count
    n_pa = sb.table("partidos").select("id", count="exact").eq("liga_id", liga_id).execute().count
    n_neutral = sb.table("partidos").select("id", count="exact").eq("liga_id", liga_id).eq("neutral", True).execute().count
    print(f"  equipos liga Internacional : {n_eq}")
    print(f"  partidos liga Internacional: {n_pa}  (neutrales: {n_neutral})")
    print("\n✅ Carga completa. Listo para Sub-proyecto B.")
    print("=" * 60)


if __name__ == "__main__":
    main()
