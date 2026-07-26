"""Gate de goles (Dixon-Coles) para UNA liga de clubes.

Holdout temporal: se ordena por fecha, el último 30% es test. El baseline es
ingenuo: las frecuencias HOME/DRAW/AWAY del train (lo que sabe cualquiera que
mire la tabla). El modelo tiene que batirlo por >= 3% relativo de Brier.

NO publica nada: la ruta de clubes del analyzer reajusta el Dixon-Coles en
runtime desde `partidos`, así que este gate es un go/no-go antes de servir
boletos de esa liga.

    python gate_goles_liga.py --liga "Premier League"
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

GATE_MIN_MEJORA = 0.03
TEST_FRAC = 0.30
TEMPORADAS = ["2022", "2023", "2024"]
RESULTADOS = ("HOME", "DRAW", "AWAY")
PAGINA_SUPABASE = 1000   # PostgREST corta en 1000 filas si no se pagina con .range()


def baseline_tasas(train: list[dict]) -> tuple[float, float, float]:
    """Frecuencias (home, draw, away) del train. Sin partidos -> uniforme."""
    c = Counter(m["resultado"] for m in train if m["resultado"] in RESULTADOS)
    n = sum(c.values())
    if n == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (c["HOME"] / n, c["DRAW"] / n, c["AWAY"] / n)


def split_temporal(partidos: list[dict], test_frac: float = TEST_FRAC):
    """Ordena por fecha y parte: primeros (1-frac) train, últimos frac test."""
    ordenados = sorted(partidos, key=lambda m: m["fecha"])
    corte = int(len(ordenados) * (1 - test_frac))
    return ordenados[:corte], ordenados[corte:]


def brier(preds: list[tuple]) -> float:
    """preds: [(p_home, p_draw, p_away, resultado)]. Brier multiclase normalizado."""
    total = 0.0
    for ph, pd, pa, real in preds:
        obs = (1.0 if real == "HOME" else 0.0,
               1.0 if real == "DRAW" else 0.0,
               1.0 if real == "AWAY" else 0.0)
        total += sum((p - o) ** 2 for p, o in zip((ph, pd, pa), obs)) / 2
    return total / len(preds) if preds else 0.0


def decidir_gate(bs_modelo: float, bs_baseline: float,
                  minimo: float = GATE_MIN_MEJORA) -> tuple[float, bool]:
    """(mejora relativa, pasa el gate). Pasa si el modelo es mejor por >= `minimo`."""
    mejora = (bs_baseline - bs_modelo) / bs_baseline if bs_baseline > 0 else 0.0
    return mejora, bool(bs_modelo < bs_baseline and mejora >= minimo)


def cargar_partidos(sb, liga_nombre: str) -> list[dict]:
    liga = sb.table("ligas").select("id").eq("nombre", liga_nombre).execute().data
    if not liga:
        raise SystemExit(f"La liga '{liga_nombre}' no existe en `ligas`.")
    liga_id = liga[0]["id"]
    rows, desde = [], 0
    while True:
        # PostgREST tope 1000 filas por página; Premier trae 1140 FINISHED -> paginar.
        chunk = (sb.table("partidos")
                 .select("equipo_local_id, equipo_visitante_id, goles_local, "
                         "goles_visitante, resultado, temporada, fecha")
                 .eq("liga_id", liga_id).in_("temporada", TEMPORADAS)
                 .eq("estado", "FINISHED")
                 .range(desde, desde + PAGINA_SUPABASE - 1)
                 .execute().data)
        rows.extend(chunk)
        if len(chunk) < PAGINA_SUPABASE:
            break
        desde += PAGINA_SUPABASE
    return [r for r in rows if r["goles_local"] is not None]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("--liga", default="Premier League")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    load_dotenv()
    from analyzer import DixonColesModel   # import tardío: lee env al importar

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    partidos = cargar_partidos(sb, args.liga)
    train, test = split_temporal(partidos)
    print("=" * 60)
    print(f"GATE DE GOLES — {args.liga}")
    print("=" * 60)
    print(f"  partidos: {len(partidos)}  (train {len(train)} / test {len(test)})")
    if len(train) < 100 or len(test) < 30:
        raise SystemExit("  Muestra insuficiente para un gate honesto.")

    ref = datetime.fromisoformat(min(m["fecha"] for m in test).replace("Z", "+00:00"))
    modelo = DixonColesModel().fit(train, ref.astimezone(timezone.utc))

    ph_b, pd_b, pa_b = baseline_tasas(train)
    preds_m, preds_b, sin_cobertura = [], [], 0
    for m in test:
        if m["resultado"] not in RESULTADOS:
            continue
        if m["equipo_local_id"] not in modelo.idx or m["equipo_visitante_id"] not in modelo.idx:
            sin_cobertura += 1
            continue
        ph, pd, pa = modelo.predict_1x2(*modelo.lambdas(m["equipo_local_id"], m["equipo_visitante_id"]))
        preds_m.append((ph, pd, pa, m["resultado"]))
        preds_b.append((ph_b, pd_b, pa_b, m["resultado"]))

    bs_m, bs_b = brier(preds_m), brier(preds_b)
    mejora, ok = decidir_gate(bs_m, bs_b)
    print(f"  baseline tasas train: H={ph_b:.3f} D={pd_b:.3f} A={pa_b:.3f}")
    print(f"  test evaluado: {len(preds_m)} partidos "
          f"({sin_cobertura} sin cobertura de equipo)")
    print(f"  Brier modelo={bs_m:.4f}  baseline={bs_b:.4f}  "
          f"mejora={mejora * 100:+.1f}%  {'✅ PASA' if ok else '❌ no pasa'}")
    print("=" * 60)
    return bs_m, bs_b, ok


if __name__ == "__main__":
    main()
