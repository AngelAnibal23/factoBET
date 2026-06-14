"""
Resolver — Phase 4 (Job Nocturno)
Marca el resultado real de cada selección de parlay consultando ESPN.
Fuente: ESPN hidden API. Sin cambios de schema en Supabase.
"""

import os
import logging
from datetime import datetime, timezone

import requests
from rapidfuzz import fuzz
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
MATCH_UMBRAL = 0.80   # mismo umbral que validator.py


# ── Lógica de acierto por mercado ─────────────────────────────────────────────

def _calcular_acierto(mercado, seleccion, linea, gl, gv):
    """Retorna True/False si la selección acertó, o None si no es resoluble."""
    if gl is None or gv is None:
        return None

    if mercado == "1X2":
        if seleccion == "home": return gl > gv
        if seleccion == "draw": return gl == gv
        if seleccion == "away": return gl < gv

    elif mercado == "over_under":
        if linea is None:
            return None
        total = gl + gv
        if seleccion == "over":  return total > linea
        if seleccion == "under": return total < linea

    elif mercado == "btts":
        ambos = gl > 0 and gv > 0
        if seleccion == "yes": return ambos
        if seleccion == "no":  return not ambos

    elif mercado == "handicap":
        if linea is None:
            return None
        if seleccion == "home": return gl + linea > gv
        if seleccion == "away": return gv - linea > gl

    return None


# ── Mapeo de estado ESPN ──────────────────────────────────────────────────────

_STATUS_FINALIZADO = {"STATUS_FULL_TIME", "STATUS_FINAL"}
_STATUS_ESPECIAL = {
    "STATUS_FINAL_PEN", "STATUS_POSTPONED", "STATUS_CANCELED",
    "STATUS_CANCELLED", "STATUS_ABANDONED", "STATUS_SUSPENDED",
}


def _mapear_status(status_name):
    """FINALIZADO (resoluble) | PENDIENTE (no jugado/en curso) | ESPECIAL (anulado/penales)."""
    if status_name in _STATUS_FINALIZADO:
        return "FINALIZADO"
    if status_name in _STATUS_ESPECIAL:
        return "ESPECIAL"
    return "PENDIENTE"


# ── Resultado del parlay (por precedencia) ────────────────────────────────────

def _resultado_parlay(estados):
    """
    estados: lista de estado por selección NO exótica, cada uno en
    {GANADA, PERDIDA, PENDIENTE, ESPECIAL}.
    Precedencia: PERDIDA > PENDIENTE > ESPECIAL > GANADA.
    """
    if not estados:
        return "PENDIENTE"
    if "PERDIDA" in estados:
        return "PERDIDO"
    if "PENDIENTE" in estados:
        return "PENDIENTE"
    if "ESPECIAL" in estados:
        return "ANULADO"
    return "GANADO"


# ── Parseo de la respuesta ESPN ───────────────────────────────────────────────

def _score_int(competitor):
    s = competitor.get("score")
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _parse_eventos(espn_json):
    """Convierte el JSON del scoreboard ESPN en una lista de eventos normalizados."""
    eventos = []
    for e in espn_json.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        home_name = home.get("team", {}).get("displayName", "")
        away_name = away.get("team", {}).get("displayName", "")
        if not home_name or not away_name:
            continue
        eventos.append({
            "local":            home_name,
            "visitante":        away_name,
            "goles_local":      _score_int(home),
            "goles_visitante":  _score_int(away),
            "status_name":      e.get("status", {}).get("type", {}).get("name", ""),
            "fecha":            e.get("date", ""),
        })
    return eventos


# ── Matching de selección a evento ────────────────────────────────────────────

def _fuzzy(a, b):
    # token_set_ratio: matchea subsets legítimos (FBC Melgar -> Melgar = 1.00) pero
    # rechaza clubes distintos con prefijo compartido (Alianza Lima vs Alianza
    # Atlético = 0.74). partial_ratio daría 0.86 aquí — falso positivo. No usar partial
    # en el resolver: aquí matcheamos nombres canónicos limpios, no OCR crudo.
    a_norm, b_norm = a.strip().lower(), b.strip().lower()
    return fuzz.token_set_ratio(a_norm, b_norm) / 100.0


def _match_evento(nombre_local, nombre_visitante, eventos, umbral=MATCH_UMBRAL):
    """
    Devuelve el evento cuyo local Y visitante coinciden (>= umbral) con los nombres
    dados, respetando la orientación home/away. None si ninguno cumple.
    """
    best = None
    best_score = 0.0
    for ev in eventos:
        sl = _fuzzy(nombre_local, ev["local"])
        sv = _fuzzy(nombre_visitante, ev["visitante"])
        if sl >= umbral and sv >= umbral and (sl + sv) > best_score:
            best_score = sl + sv
            best = ev
    return best


# ── Cliente Supabase (lazy, igual que storage.py) ─────────────────────────────

_sb = None


def _client():
    global _sb
    if _sb is None:
        _sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    return _sb


# ── Fetch ESPN ────────────────────────────────────────────────────────────────

def _fetch_eventos(league, fecha_inicio, fecha_fin):
    """
    league: slug ESPN (ej. 'per.1'). fecha_inicio/fecha_fin: 'YYYYMMDD'.
    Una sola request cubre todo el rango. Lanza requests.HTTPError si falla.
    """
    url = f"{ESPN_BASE}/{league}/scoreboard"
    params = {"dates": f"{fecha_inicio}-{fecha_fin}", "limit": 1000}
    resp = requests.get(
        url, params=params, timeout=25,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
    )
    resp.raise_for_status()
    return _parse_eventos(resp.json())


# ── Actualización de parlay completo ──────────────────────────────────────────

def _actualizar_parlay(sb, parlay_id, ahora_iso, dry_run):
    """Recalcula resultado_parlay con las selecciones no exóticas. Retorna True si lo escribió."""
    sels = (
        sb.table("selecciones_parlay")
        .select("acierto, resultado_real, es_mercado_exotico")
        .eq("parlay_id", parlay_id)
        .execute().data
    )
    estados = []
    for s in sels:
        if s["es_mercado_exotico"]:
            continue
        if s["acierto"] is True:
            estados.append("GANADA")
        elif s["acierto"] is False:
            estados.append("PERDIDA")
        elif s["resultado_real"]:        # acierto NULL pero con resultado escrito → especial
            estados.append("ESPECIAL")
        else:
            estados.append("PENDIENTE")

    resultado = _resultado_parlay(estados)
    if resultado == "PENDIENTE":
        return False
    if not dry_run:
        (sb.table("analisis_parlays")
         .update({"resultado_parlay": resultado, "resolved_at": ahora_iso})
         .eq("id", parlay_id).execute())
    return True


# ── Orquestador público ───────────────────────────────────────────────────────

def resolver_resultados(league="per.1", dry_run=False):
    """
    Resuelve todas las selecciones pendientes (acierto IS NULL, no exóticas).
    Retorna resumen {resueltas, pendientes, sin_match, especiales, errores,
    parlays_completados, detalle}.

    Nota: en dry_run=True las selecciones no se escriben, por lo que
    _actualizar_parlay re-lee el estado original de la DB y parlays_completados
    será 0. El dry_run sirve para previsualizar `detalle` y los conteos por
    selección, no el cierre de parlays.
    """
    sb = _client()
    resumen = {
        "resueltas": 0, "pendientes": 0, "sin_match": 0, "especiales": 0,
        "errores": 0, "parlays_completados": 0, "detalle": [],
    }

    pend = (
        sb.table("selecciones_parlay")
        .select("id, parlay_id, mercado, seleccion, linea, features_snapshot, "
                "es_mercado_exotico, analisis_parlays(created_at)")
        .is_("acierto", "null")
        .eq("es_mercado_exotico", False)
        .execute().data
    )
    if not pend:
        return resumen

    # Ventana temporal: desde el parlay más antiguo pendiente hasta hoy
    fechas = []
    for p in pend:
        ap = p.get("analisis_parlays")
        if isinstance(ap, list):
            ap = ap[0] if ap else None
        if ap and ap.get("created_at"):
            fechas.append(ap["created_at"])
    ahora = datetime.now(tz=timezone.utc)
    if fechas:
        inicio_dt = min(
            datetime.fromisoformat(f.replace("Z", "+00:00")) for f in fechas
        )
    else:
        inicio_dt = ahora
    inicio = inicio_dt.strftime("%Y%m%d")
    fin = ahora.strftime("%Y%m%d")
    ahora_iso = ahora.isoformat()

    eventos = _fetch_eventos(league, inicio, fin)

    equipos = {
        e["id"]: e
        for e in sb.table("equipos").select("id, nombre_oficial, aliases").execute().data
    }

    parlays_afectados = set()

    for sel in pend:
        try:
            fs = sel.get("features_snapshot") or {}
            eq_local = equipos.get(fs.get("equipo_local_id"))
            eq_vis = equipos.get(fs.get("equipo_visitante_id"))
            if not eq_local or not eq_vis:
                resumen["sin_match"] += 1
                continue

            ev = _match_evento(eq_local["nombre_oficial"], eq_vis["nombre_oficial"], eventos)
            if not ev:
                resumen["sin_match"] += 1
                continue

            estado = _mapear_status(ev["status_name"])

            if estado == "PENDIENTE":
                resumen["pendientes"] += 1
                continue

            if estado == "ESPECIAL":
                resumen["especiales"] += 1
                if not dry_run:
                    (sb.table("selecciones_parlay")
                     .update({"resultado_real": ev["status_name"], "resolved_at": ahora_iso})
                     .eq("id", sel["id"]).execute())
                parlays_afectados.add(sel["parlay_id"])
                resumen["detalle"].append({
                    "seleccion_id": sel["id"],
                    "match": f"{ev['local']} vs {ev['visitante']}",
                    "resultado_real": ev["status_name"],
                    "acierto": None,
                })
                continue

            # FINALIZADO
            acierto = _calcular_acierto(
                sel["mercado"], sel["seleccion"], sel["linea"],
                ev["goles_local"], ev["goles_visitante"],
            )
            marcador = f"{ev['goles_local']}-{ev['goles_visitante']}"
            if acierto is None:
                # Partido finalizado pero no resoluble (linea/goles faltantes).
                # Fail loudly: registrar y contar como error, no liquidar la selección.
                resumen["errores"] += 1
                log.error(
                    "Seleccion %s FINALIZADA pero acierto no calculable "
                    "(mercado=%s, seleccion=%s, linea=%s, marcador=%s)",
                    sel.get("id"), sel["mercado"], sel["seleccion"], sel["linea"], marcador,
                )
                continue
            if not dry_run:
                (sb.table("selecciones_parlay")
                 .update({"resultado_real": marcador, "acierto": acierto, "resolved_at": ahora_iso})
                 .eq("id", sel["id"]).execute())
            resumen["resueltas"] += 1
            parlays_afectados.add(sel["parlay_id"])
            resumen["detalle"].append({
                "seleccion_id": sel["id"],
                "match": f"{ev['local']} vs {ev['visitante']}",
                "resultado_real": marcador,
                "acierto": acierto,
            })

        except Exception as e:
            resumen["errores"] += 1
            log.error("Error resolviendo seleccion %s: %s", sel.get("id"), e)

    for pid in parlays_afectados:
        try:
            if _actualizar_parlay(sb, pid, ahora_iso, dry_run):
                resumen["parlays_completados"] += 1
        except Exception as e:
            resumen["errores"] += 1
            log.error("Error actualizando parlay %s: %s", pid, e)

    return resumen
