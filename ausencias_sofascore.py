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
