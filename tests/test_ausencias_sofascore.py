"""Tests del runtime de ausencias: caché TTL + subprocess mockeado. Nunca scrapea."""
import json, subprocess, time
import ausencias_sofascore as mod


PAYLOAD = {
    "equipos": {"Argentina": [{"nombre": "Lionel Messi", "estado": "out",
                               "motivo": "Injured - Muscle", "posicion": None}],
                "France": []},
    "url": "https://www.sofascore.com/football/match/x", "scrapeado_en": "2026-07-17T10:00:00",
}


def _fake_run_ok(*args, **kwargs):
    class R:
        returncode, stdout, stderr = 0, json.dumps(PAYLOAD), ""
    return R()


def test_scrape_ok_parsea_y_cachea(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    r = mod.obtener_ausencias("Argentina", "France")
    assert r["equipos"]["Argentina"][0].nombre == "Lionel Messi"
    assert r["equipos"]["Argentina"][0].estado == "out"
    assert (tmp_path / "argentina__france.json").exists()


def test_cache_vigente_no_llama_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time(), "payload": PAYLOAD}), encoding="utf-8")
    def _boom(*a, **k): raise AssertionError("no debe scrapear con cache vigente")
    monkeypatch.setattr(subprocess, "run", _boom)
    r = mod.obtener_ausencias("Argentina", "France")
    assert r["equipos"]["Argentina"][0].nombre == "Lionel Messi"


def test_cache_vencida_rescrapea(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time() - mod.TTL_SEGUNDOS - 60,
                    "payload": PAYLOAD}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    assert mod.obtener_ausencias("Argentina", "France") is not None


def test_fallo_subprocess_devuelve_none_y_cachea_negativo(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    def _timeout(*a, **k): raise subprocess.TimeoutExpired(cmd="x", timeout=1)
    monkeypatch.setattr(subprocess, "run", _timeout)
    assert mod.obtener_ausencias("Argentina", "France") is None
    data = json.loads((tmp_path / "argentina__france.json").read_text(encoding="utf-8"))
    assert data["payload"]["sin_dato"] is True


def test_sin_dato_cacheado_respeta_ttl_corto(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text(
        json.dumps({"guardado_en": time.time() - mod.TTL_SIN_DATO - 60,
                    "payload": {"sin_dato": True}}), encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)   # vencido -> re-scrapea
    assert mod.obtener_ausencias("Argentina", "France") is not None


def test_cache_corrupto_se_ignora(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CACHE_DIR", str(tmp_path))
    (tmp_path / "argentina__france.json").write_text("{basura", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _fake_run_ok)
    assert mod.obtener_ausencias("Argentina", "France") is not None


def test_extraer_ausentes_parsea_bloques():
    texto = "\n".join([
        "Türkiye", "Hakan Calhanoglu", "Suspended",
        "USA", "Cristian Roldán", "Injured - Muscle",
        "Tim Weah", "Doubtful",
    ])
    r = mod._extraer_ausentes(texto, "Türkiye", "USA")
    assert r["Türkiye"][0]["estado"] == "out"          # Suspended -> out
    assert r["USA"][0]["motivo"] == "Injured - Muscle"
    assert r["USA"][1]["estado"] == "doubtful"


def test_extraer_ausentes_descarta_encabezado_coach():
    # Verificado en vivo (Palmeiras 2026-07-22): 'Coach' / 'Injuries and suspensions'
    # es un encabezado de sección, no un jugador -> debe descartarse.
    texto = "\n".join([
        "Palmeiras", "Coach", "Injuries and suspensions",
        "Vitor Roque", "Injured", "Paulinho", "Suspended",
    ])
    r = mod._extraer_ausentes(texto, "Coritiba", "Palmeiras")
    nombres = [a["nombre"] for a in r["Palmeiras"]]
    assert "Coach" not in nombres
    assert nombres == ["Vitor Roque", "Paulinho"]


def test_match_link_por_href():
    # Los nombres viven en el slug del href, no en a.text (vacío con disable_resources).
    href = "/football/match/coritiba-palmeiras/nOsHO#id:15237982"
    assert mod._match_link(href, "Coritiba", "Palmeiras") is True
    assert mod._match_link(href, "Coritiba", "Flamengo") is False   # away no está
    # nombre compuesto en slug con guiones
    href2 = "/football/match/united-states-turkiye/xYz"
    assert mod._match_link(href2, "United States", "Türkiye") is True
