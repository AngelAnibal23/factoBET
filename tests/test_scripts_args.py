"""Parseo de argumentos de los scripts de descarga/carga. Los scripts hacen red y
Supabase en main(); aquí solo se prueban las funciones puras de configuración."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


# ── download_fixtures.py ──────────────────────────────────────────────────────

def test_config_fixtures_default_es_liga1():
    from download_fixtures import parsear_args
    cfg = parsear_args([])
    assert cfg.liga_api_id == 281
    assert cfg.temporadas == [2022, 2023, 2024]
    assert cfg.nombre == "Liga 1 Peruana"
    assert cfg.pais == "Peru"


def test_config_fixtures_premier():
    from download_fixtures import parsear_args
    cfg = parsear_args(["--liga", "39", "--nombre", "Premier League",
                        "--pais", "England"])
    assert cfg.liga_api_id == 39
    assert cfg.nombre == "Premier League"
    assert cfg.pais == "England"
    assert cfg.temporadas == [2022, 2023, 2024]


def test_config_fixtures_temporadas_explicitas():
    from download_fixtures import parsear_args
    cfg = parsear_args(["--temporadas", "2023,2024"])
    assert cfg.temporadas == [2023, 2024]


def test_filas_equipos_deduplica_por_api_id():
    from download_fixtures import filas_equipos
    fixtures = [
        {"teams": {"home": {"id": 1, "name": "Alianza Lima"},
                    "away": {"id": 2, "name": "Universitario"}}},
        {"teams": {"home": {"id": 1, "name": "Alianza Lima"},
                    "away": {"id": 3, "name": "Sporting Cristal"}}},
    ]
    rows = filas_equipos(fixtures, liga_id="liga-uuid", pais="Peru")
    ids = [r["api_football_id"] for r in rows]
    assert sorted(ids) == [1, 2, 3]
    assert len(rows) == 3
    for r in rows:
        assert r["liga_id"] == "liga-uuid"
        assert r["pais"] == "Peru"
    by_id = {r["api_football_id"]: r for r in rows}
    assert by_id[1]["nombre_oficial"] == "Alianza Lima"
    assert by_id[2]["nombre_oficial"] == "Universitario"
    assert by_id[3]["nombre_oficial"] == "Sporting Cristal"


def _fixture(fid=100, home_id=1, away_id=2, status="FT", gh=2, ga=1,
             season=2023, round_="Regular Season - 10"):
    return {
        "fixture": {"id": fid, "date": "2023-05-01T20:00:00+00:00",
                    "status": {"short": status},
                    "venue": {"name": "Estadio X"}, "referee": "Juan Perez"},
        "teams": {"home": {"id": home_id, "name": "Home FC"},
                  "away": {"id": away_id, "name": "Away FC"}},
        "goals": {"home": gh, "away": ga},
        "score": {"halftime": {"home": 1, "away": 0}},
        "league": {"season": season, "round": round_},
    }


def test_filas_partidos_salta_equipos_no_resueltos():
    from download_fixtures import filas_partidos
    fixtures = [_fixture(home_id=1, away_id=999)]  # 999 no está en el mapa
    equipo_map = {1: "uuid-home"}
    filas, saltados = filas_partidos(fixtures, liga_id="liga-uuid", equipo_map=equipo_map)
    assert filas == []
    assert saltados == 1


def test_filas_partidos_mapea_estado_y_resultado():
    from download_fixtures import filas_partidos
    # ids DISTINTOS para home/away: si el código llegara a intercambiarlos,
    # la aserción de equipo_local_id/equipo_visitante_id de abajo debe fallar.
    equipo_map = {1: "uuid-home", 2: "uuid-away"}

    ft_fixture = _fixture(fid=1, home_id=1, away_id=2, status="FT", gh=2, ga=1)
    ns_fixture = _fixture(fid=2, home_id=1, away_id=2, status="NS", gh=None, ga=None)

    filas, saltados = filas_partidos([ft_fixture, ns_fixture],
                                      liga_id="liga-uuid", equipo_map=equipo_map)
    assert saltados == 0
    assert len(filas) == 2

    by_id = {f["api_football_id"]: f for f in filas}
    assert by_id[1]["estado"] == "FINISHED"
    assert by_id[1]["resultado"] == "HOME"
    assert by_id[1]["datos_completos"] is True
    assert by_id[1]["equipo_local_id"] == "uuid-home"
    assert by_id[1]["equipo_visitante_id"] == "uuid-away"

    assert by_id[2]["estado"] == "SCHEDULED"
    assert by_id[2]["resultado"] is None
    assert by_id[2]["datos_completos"] is False
    assert by_id[2]["equipo_local_id"] == "uuid-home"
    assert by_id[2]["equipo_visitante_id"] == "uuid-away"


def test_api_get_detecta_cuota_agotada(monkeypatch):
    import download_fixtures

    class FakeResp:
        headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"errors": {"plan": "Free plans do not have access to this "
                                        "season, try from 2022 to 2024."},
                     "response": []}

    def fake_get(url, headers=None, params=None, timeout=None):
        return FakeResp()

    monkeypatch.setattr(download_fixtures.requests, "get", fake_get)

    with pytest.raises(RuntimeError) as exc_info:
        download_fixtures.api_get("fixtures", {"league": 39, "season": 2025},
                                   api_key="fake-key")
    assert "plan" in str(exc_info.value)


# ── download_flashscore_stats.py ──────────────────────────────────────────────

def test_torneos_incluye_las_3_temporadas_de_premier():
    """Slugs verificados el 2026-07-26 (HTTP 200 en flashscore.com)."""
    import download_flashscore_stats as d
    pl = [t for t in d.TOURNAMENTS if t[0] == "Premier League"]
    assert [t[2] for t in pl] == ["2022", "2023", "2024"]
    assert pl[0][1] == ("https://www.flashscore.com/football/england/"
                        "premier-league-2022-2023/results/")


def test_filtrar_torneos_por_liga():
    import download_flashscore_stats as d
    solo_pl = d.filtrar_torneos(d.TOURNAMENTS, "Premier League")
    assert len(solo_pl) == 3
    assert all(t[0] == "Premier League" for t in solo_pl)


def test_filtrar_torneos_sin_filtro_devuelve_todo():
    import download_flashscore_stats as d
    assert d.filtrar_torneos(d.TOURNAMENTS, None) == d.TOURNAMENTS


def test_filtrar_torneos_liga_inexistente_da_vacio():
    import download_flashscore_stats as d
    assert d.filtrar_torneos(d.TOURNAMENTS, "Premier") == []


def test_descargar_con_lista_vacia_no_escribe_nada():
    import download_flashscore_stats as d
    with pytest.raises(SystemExit):
        d.descargar([])


def test_rendimiento_sospechoso_detecta_cero():
    import download_flashscore_stats as d
    assert d.rendimiento_sospechoso(0) is True


def test_rendimiento_sospechoso_detecta_pocos():
    import download_flashscore_stats as d
    assert d.rendimiento_sospechoso(3) is True


def test_rendimiento_normal_no_alarma():
    import download_flashscore_stats as d
    assert d.rendimiento_sospechoso(380) is False
    assert d.rendimiento_sospechoso(30) is False  # el umbral mismo NO alarma


def test_descargar_sin_filas_no_escribe_csv(monkeypatch, tmp_path):
    """Un torneo que enumera partidos pero para el que nunca se junta ninguna
    fila con stats (ej. bajar_stats siempre falla) no debe pisar un CSV bueno
    existente. Se evita abrir un browser real inyectando un módulo `seleniumbase`
    falso en sys.modules (el import es lazy dentro de descargar()) y
    monkeypatcheando enumerar_partidos para no depender del DOM."""
    import sys
    import types
    import download_flashscore_stats as d

    fake_module = types.ModuleType("seleniumbase")

    class FakeSB:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_module.SB = FakeSB
    monkeypatch.setitem(sys.modules, "seleniumbase", fake_module)
    monkeypatch.setattr(d, "enumerar_partidos", lambda sb, url: [])

    salida = tmp_path / "flashscore_stats.csv"
    with pytest.raises(SystemExit):
        d.descargar([("Liga X", "http://example.com", "2024")], salida=str(salida))
    assert not salida.exists()


# ── load_counts_to_supabase.py ────────────────────────────────────────────────

def test_mapa_de_ligas_de_conteos_incluye_premier():
    """fit_counts_model agrupa por la columna `liga` del scrape; el loader traduce
    esa etiqueta al nombre de la tabla `ligas`."""
    from load_counts_to_supabase import LIGA_NOMBRE
    assert LIGA_NOMBRE["Premier League"] == "Premier League"
    assert LIGA_NOMBRE["INT"] == "Internacional"
    assert LIGA_NOMBRE["Liga 1 Peru"] == "Liga 1 Peruana"


# ── download_player_events.py ─────────────────────────────────────────────────

def test_rutas_player_events_por_defecto():
    from download_player_events import parsear_args
    a = parsear_args([])
    assert a.entrada == "flashscore_stats.csv"
    assert a.salida == "player_events.csv"


def test_rutas_player_events_premier():
    from download_player_events import parsear_args
    a = parsear_args(["--entrada", "flashscore_stats_pl.csv",
                      "--salida", "player_events_pl.csv"])
    assert a.entrada == "flashscore_stats_pl.csv"
    assert a.salida == "player_events_pl.csv"


def test_event_ids_deduplica_y_preserva_orden(tmp_path):
    from download_player_events import _event_ids
    ruta = tmp_path / "flashscore_stats.csv"
    ruta.write_text(
        "event_id,otro\n"
        "b,1\n"
        "a,2\n"
        "b,3\n"
        "c,4\n"
        "a,5\n",
        encoding="utf-8",
    )
    assert _event_ids(str(ruta)) == ["b", "a", "c"]


# ── download_sot_jugador.py ───────────────────────────────────────────────────

def test_manifiesto_incluye_la_premier():
    from download_sot_jugador import MANIFIESTO
    pl = [t for t in MANIFIESTO if t[0] == 39]
    assert pl and pl[0][1] == [2022, 2023, 2024]


# ── load_flashscore_stats_to_supabase.py ──────────────────────────────────────

class _FakeQuery:
    def __init__(self, should_fail):
        self.should_fail = should_fail

    def select(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self.should_fail:
            raise RuntimeError("tabla no existe")
        return {"data": []}


class _FakeSb:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.tabla_consultada = None

    def table(self, nombre):
        self.tabla_consultada = nombre
        return _FakeQuery(self.should_fail)


def test_asegurar_tabla_corre_el_ddl_si_hay_token(monkeypatch):
    import load_flashscore_stats_to_supabase as mod

    llamadas = []
    monkeypatch.setattr(mod, "run_ddl", lambda ddl, token: llamadas.append((ddl, token)))

    sb = _FakeSb(should_fail=True)  # si se llegara a probar la tabla, fallaría
    mod.asegurar_tabla(sb, "fake-token")

    assert llamadas == [(mod.DDL, "fake-token")]
    assert sb.tabla_consultada is None  # el probe no hizo falta


def test_asegurar_tabla_sigue_si_el_ddl_falla_pero_la_tabla_existe(monkeypatch):
    import load_flashscore_stats_to_supabase as mod

    def fake_run_ddl(ddl, token):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(mod, "run_ddl", fake_run_ddl)

    sb = _FakeSb(should_fail=False)
    mod.asegurar_tabla(sb, "token-caducado")  # no debe lanzar


def test_asegurar_tabla_aborta_si_no_hay_ddl_ni_tabla(monkeypatch):
    import load_flashscore_stats_to_supabase as mod

    def fake_run_ddl(ddl, token):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(mod, "run_ddl", fake_run_ddl)

    sb = _FakeSb(should_fail=True)
    with pytest.raises(SystemExit):
        mod.asegurar_tabla(sb, "token-caducado")


def test_asegurar_tabla_sin_token_no_llama_al_ddl(monkeypatch):
    import load_flashscore_stats_to_supabase as mod

    llamadas = []
    monkeypatch.setattr(mod, "run_ddl", lambda ddl, token: llamadas.append((ddl, token)))

    sb = _FakeSb(should_fail=False)
    mod.asegurar_tabla(sb, None)  # no debe lanzar

    assert llamadas == []
