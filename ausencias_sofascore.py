"""Fuente de ausencias (Sofascore) para el serving: caché local JSON + scrape en
subprocess. El scrape (CLI `scrape`, Task 3) corre BAJO .venv-scrapling porque
scrapling/patchright es incompatible con el venv del runtime. Este módulo se
importa desde analyzer sin dependencias nuevas.

Contrato de obtener_ausencias: dict {"equipos": {equipo: [Ausente,...]},
"url", "scrapeado_en"} o None (sin dato — el análisis sigue SIN ajuste)."""
import json
import os
import re
import subprocess
import sys
import time

from ajuste_ausencias import Ausente

_REPO = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_REPO, "cache_ausencias")
TTL_SEGUNDOS = 6 * 3600      # spec: TTL_CACHE = 6h
TTL_SIN_DATO = 1 * 3600      # negativo se reintenta antes (extensión acordada en plan)
SCRAPE_TIMEOUT = 240         # s — el browser stealth tarda ~2 min
_PY_SCRAPLING = os.environ.get(
    "SCRAPLING_PYTHON",
    os.path.join(_REPO, ".venv-scrapling", "Scripts", "python.exe"),
)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _cache_path(home: str, away: str) -> str:
    return os.path.join(CACHE_DIR, f"{_slug(home)}__{_slug(away)}.json")


def _leer_cache(path: str) -> dict | None:
    """payload cacheado y vigente, o None. TTL corto para payloads sin_dato."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        payload = data["payload"]
        ttl = TTL_SIN_DATO if payload.get("sin_dato") else TTL_SEGUNDOS
        if time.time() - data["guardado_en"] <= ttl:
            return payload
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _escribir_cache(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"guardado_en": time.time(), "payload": payload}, f, ensure_ascii=False)


def _parsear(payload: dict) -> dict:
    return {
        "equipos": {eq: [Ausente(**a) for a in lst]
                    for eq, lst in payload.get("equipos", {}).items()},
        "url": payload.get("url"),
        "scrapeado_en": payload.get("scrapeado_en"),
    }


def obtener_ausencias(home: str, away: str) -> dict | None:
    path = _cache_path(home, away)
    payload = _leer_cache(path)
    if payload is None:
        try:
            r = subprocess.run(
                [_PY_SCRAPLING, os.path.abspath(__file__), "scrape", home, away],
                capture_output=True, text=True, encoding="utf-8",
                timeout=SCRAPE_TIMEOUT,
            )
            if r.returncode == 0 and r.stdout.strip():
                payload = json.loads(r.stdout)
            else:
                payload = {"sin_dato": True, "motivo": f"scrape rc={r.returncode}"}
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as e:
            payload = {"sin_dato": True, "motivo": type(e).__name__}
        _escribir_cache(path, payload)
    if payload.get("sin_dato"):
        return None
    return _parsear(payload)


# ── CLI scrape (corre BAJO .venv-scrapling; el runtime nunca importa scrapling) ──

_DIAS_BUSQUEDA = 4          # hoy..+3: ventana donde vive un boleto real
_ESPERA_DOM_MS = 8000       # la app llama su API interna y renderiza (~7s en el spike)
_UMBRAL_LINK = 80


def _sin_acentos(s: str) -> str:
    """El slug de Sofascore es ASCII ('turkiye'); los canonicals pueden traer
    acentos ('Türkiye'). Normaliza ambos lados para que el fuzzy no los penalice."""
    import unicodedata as _u
    return "".join(c for c in _u.normalize("NFKD", s or "") if not _u.combining(c))


def _slug_a_texto(href: str) -> str:
    """Los nombres de los equipos viven en el slug del href
    (…/football/match/coritiba-palmeiras/…), NO en el texto del ancla (viene vacío
    con disable_resources). Normaliza el slug a texto buscable."""
    import re as _re
    m = _re.search(r"/football/match/([^/?#]+)", href or "")
    slug = m.group(1) if m else (href or "")
    return _sin_acentos(_re.sub(r"[-_]+", " ", slug).lower())


def _match_link(href: str, home: str, away: str) -> bool:
    t = _slug_a_texto(href)
    from rapidfuzz import fuzz
    return (fuzz.token_set_ratio(_sin_acentos(home.lower()), t) >= _UMBRAL_LINK and
            fuzz.token_set_ratio(_sin_acentos(away.lower()), t) >= _UMBRAL_LINK)


def _clasificar_estado(texto: str) -> str:
    return "doubtful" if any(w in texto.lower() for w in ("doubt", "question")) else "out"


# Etiquetas de sección que Sofascore intercala en el bloque de ausentes y que NO
# son jugadores (verificado en vivo 2026-07-22: 'Coach' con motivo 'Injuries and
# suspensions' se colaba como un ausente fantasma).
_NO_JUGADOR = {"coach", "manager", "head coach", "missing players",
               "injuries and suspensions", "injuries", "suspensions"}


def _extraer_ausentes(texto_pagina: str, home: str, away: str) -> dict:
    """Parsea la sección de ausentes del inner_text del partido. Formato observado
    en vivo: bloques por equipo con líneas 'Nombre' / 'Injured - Muscle' (o
    'Suspended', 'Doubtful'). Se parsea por ventanas de texto entre el nombre del
    equipo y la siguiente sección; se descartan etiquetas de sección (_NO_JUGADOR)."""
    equipos: dict = {home: [], away: []}
    # Implementación por regex sobre líneas: un nombre propio seguido de una línea
    # de motivo conocida. Motivos vistos: Injured, Suspended, Doubtful, Personal.
    import re as _re
    lineas = [l.strip() for l in texto_pagina.splitlines() if l.strip()]
    motivo_re = _re.compile(r"^(Injur|Suspend|Doubt|Question|Personal|Illness)", _re.I)
    lado = None
    for i, linea in enumerate(lineas):
        if linea == home or linea.lower() == home.lower():
            lado = home
        elif linea == away or linea.lower() == away.lower():
            lado = away
        if (lado and linea.lower() not in _NO_JUGADOR
                and i + 1 < len(lineas) and motivo_re.match(lineas[i + 1])):
            equipos[lado].append({
                "nombre": linea, "estado": _clasificar_estado(lineas[i + 1]),
                "motivo": lineas[i + 1], "posicion": None,
            })
    return equipos


def _scrape(home: str, away: str) -> dict:
    from datetime import date, timedelta, datetime
    from scrapling.fetchers import StealthyFetcher

    def _esperar(page):
        page.wait_for_timeout(_ESPERA_DOM_MS)
        return page

    # disable_resources dropea imágenes/media/websockets/stylesheets: sin eso, la
    # página viva de Sofascore nunca completa "load" y goto revienta (Page crashed).
    _COMUN = dict(network_idle=False, load_dom=False, disable_resources=True,
                  block_webrtc=True, timeout=60000)

    hoy = date.today()
    url_partido = None
    for d in range(_DIAS_BUSQUEDA):
        fecha = (hoy + timedelta(days=d)).isoformat()
        page = StealthyFetcher.fetch(
            f"https://www.sofascore.com/football/{fecha}",
            wait_selector="a[href*='/football/match/']", page_action=_esperar, **_COMUN,
        )
        for a in page.css("a[href*='/football/match/']"):
            href = a.attrib.get("href", "")
            if _match_link(href, home, away):
                url_partido = "https://www.sofascore.com" + href
                break
        if url_partido:
            break
    if not url_partido:
        return {"sin_dato": True, "motivo": f"partido no encontrado hoy..+{_DIAS_BUSQUEDA - 1}d"}

    page = StealthyFetcher.fetch(url_partido, page_action=_esperar, **_COMUN)
    texto = page.get_all_text() if hasattr(page, "get_all_text") else page.body
    equipos = _extraer_ausentes(texto, home, away)
    return {"equipos": equipos, "url": url_partido,
            "scrapeado_en": datetime.now().isoformat(timespec="seconds")}


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "scrape":
        try:
            print(json.dumps(_scrape(sys.argv[2], sys.argv[3]), ensure_ascii=False))
        except Exception as e:   # el runtime interpreta stdout-JSON, nunca traza
            print(json.dumps({"sin_dato": True, "motivo": f"{type(e).__name__}: {e}"}))
    else:
        print(json.dumps({"sin_dato": True, "motivo": "uso: scrape <home> <away>"}))
