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
