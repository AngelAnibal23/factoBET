"""Ruteo N-ligas del analyzer: mapa equipo->liga, liga del parlay y aislamiento
del Dixon-Coles por liga. Nada toca Supabase (cliente falso)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import analyzer
from validator import ValidatedParlay, ValidatedSelection, TeamMatch


# ── Cliente Supabase falso ────────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, filas, registro, nombre):
        self._filas, self._reg, self._nombre = list(filas), registro, nombre

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._reg.append((self._nombre, "eq", col, val))
        self._filas = [f for f in self._filas if f.get(col) == val]
        return self

    def in_(self, col, vals):
        self._reg.append((self._nombre, "in", col, list(vals)))
        self._filas = [f for f in self._filas if f.get(col) in vals]
        return self

    def execute(self):
        return SimpleNamespace(data=self._filas)


class _FakeClient:
    def __init__(self, tablas, registro):
        self._tablas, self._reg = tablas, registro

    def table(self, nombre):
        return _FakeTable(self._tablas.get(nombre, []), self._reg, nombre)


LIGAS = [
    {"id": "L-PE", "nombre": "Liga 1 Peruana"},
    {"id": "L-EN", "nombre": "Premier League"},
    {"id": analyzer.LIGA_INTERNACIONAL_ID, "nombre": "Internacional"},
    {"id": "L-XX", "nombre": "Liga Que No Modelamos"},
]

EQUIPOS = [
    {"id": "E-ALI", "liga_id": "L-PE"},
    {"id": "E-ARS", "liga_id": "L-EN"},
    {"id": "E-FRA", "liga_id": analyzer.LIGA_INTERNACIONAL_ID},
    {"id": "E-ZZZ", "liga_id": "L-XX"},
]


def _fake_sb(monkeypatch, tablas):
    registro = []
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    monkeypatch.setenv("SUPABASE_KEY", "fake")
    monkeypatch.setattr(analyzer, "create_client",
                        lambda *_a, **_k: _FakeClient(tablas, registro))
    return registro


# ── Mapa equipo -> liga ───────────────────────────────────────────────────────

def test_mapa_equipo_liga_usa_el_nombre_de_la_liga(monkeypatch):
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert mapa["E-ALI"] == "liga1"
    assert mapa["E-ARS"] == "premier"
    assert mapa["E-FRA"] == "internacional"


def test_equipo_de_liga_no_registrada_queda_fuera_del_mapa(monkeypatch):
    """El ruteo binario mandaba TODO lo no-internacional a Liga 1. Una liga que no
    modelamos no debe heredar el modelo de otra: mejor fuera del mapa."""
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert "E-ZZZ" not in mapa


# ── Liga del parlay ───────────────────────────────────────────────────────────

def _tm(nombre, eid):
    return TeamMatch(raw=nombre, canonical=nombre, equipo_id=eid,
                     score=1.0, status="MATCHED")


def _sel(local, lid, vis, vid, cuota=2.0):
    return ValidatedSelection(
        equipo_local_raw=local, equipo_visitante_raw=vis,
        mercado="1X2", seleccion="home", cuota=cuota, linea=None,
        local_match=_tm(local, lid), visitante_match=_tm(vis, vid),
        prob_implicita=round(1 / cuota, 6), mercado_exotico=False,
    )


def _parlay(*sels, cuota_total=2.10, es_bet_builder=False):
    return ValidatedParlay(selecciones=list(sels), cuota_total=cuota_total,
                           casa_apuestas="betano", es_bet_builder=es_bet_builder)


def test_ruteo_premier():
    p = _parlay(_sel("Arsenal", "E-ARS", "Chelsea", "E-CHE"))
    m = {"E-ARS": "premier", "E-CHE": "premier"}
    assert analyzer._liga_de_parlay(p, m) == "premier"


def test_ruteo_premier_mas_liga1_es_mixto():
    p = _parlay(_sel("Arsenal", "E-ARS", "Alianza Lima", "E-ALI"))
    m = {"E-ARS": "premier", "E-ALI": "liga1"}
    assert analyzer._liga_de_parlay(p, m) == "mixto"


def test_ruteo_premier_mas_internacional_es_mixto():
    p = _parlay(_sel("Arsenal", "E-ARS", "France", "E-FRA"))
    m = {"E-ARS": "premier", "E-FRA": "internacional"}
    assert analyzer._liga_de_parlay(p, m) == "mixto"


def test_ruteo_sin_equipos_reconocidos_cae_a_liga1():
    """Comportamiento histórico del fallback: sin match, ruta de clubes por defecto."""
    p = _parlay(_sel("Equipo X", "E-???", "Equipo Y", "E-!!!"))
    assert analyzer._liga_de_parlay(p, {}) == "liga1"


def test_ruteo_con_equipo_no_reconocido_usa_los_que_si():
    """El ruteo se decide con los equipos que SÍ resolvieron: los no reconocidos
    no arrastran el parlay a otra liga."""
    p = _parlay(_sel("Arsenal", "E-ARS", "Unknown FC", "E-???"))
    m = {"E-ARS": "premier"}
    assert analyzer._liga_de_parlay(p, m) == "premier"


def test_ruteo_seleccion_sin_visitante():
    """Mercado de un solo equipo (visitante_match=None): no debe reventar y debe
    rutear por el local."""
    sel = ValidatedSelection(
        equipo_local_raw="Arsenal", equipo_visitante_raw=None,
        mercado="1X2", seleccion="home", cuota=2.0, linea=None,
        local_match=_tm("Arsenal", "E-ARS"), visitante_match=None,
        prob_implicita=0.5, mercado_exotico=False,
    )
    p = _parlay(sel)
    m = {"E-ARS": "premier"}
    assert analyzer._liga_de_parlay(p, m) == "premier"


# ── Un DC por liga de clubes ──────────────────────────────────────────────────

PARTIDOS = [
    # Liga 1 (liga_id L-PE)
    {"liga_id": "L-PE", "equipo_local_id": "E-ALI", "equipo_visitante_id": "E-UNI",
     "goles_local": 1, "goles_visitante": 0, "resultado": "HOME",
     "temporada": "2023", "fecha": "2023-05-01T00:00:00+00:00", "estado": "FINISHED"},
    # Premier (liga_id L-EN)
    {"liga_id": "L-EN", "equipo_local_id": "E-ARS", "equipo_visitante_id": "E-CHE",
     "goles_local": 2, "goles_visitante": 1, "resultado": "HOME",
     "temporada": "2023", "fecha": "2023-05-02T00:00:00+00:00", "estado": "FINISHED"},
    # Internacional: vive en la MISMA tabla y no debe entrar a ningún fit de clubes
    {"liga_id": analyzer.LIGA_INTERNACIONAL_ID, "equipo_local_id": "E-FRA",
     "equipo_visitante_id": "E-BRA", "goles_local": 1, "goles_visitante": 1,
     "resultado": "DRAW", "temporada": "2023", "fecha": "2023-05-03T00:00:00+00:00",
     "estado": "FINISHED"},
]


class _FakeDC:
    """Sustituye a DixonColesModel: registra con qué partidos se ajustó.

    `lambdas`/`predict_1x2` son necesarias porque `_prob_for_selection` las llama
    sin comprobar `idx` (analyzer.py:298)."""
    def __init__(self):
        self.matches = None
        self.rho = -0.05
        self.idx = {}

    def fit(self, matches, _ref_date):
        self.matches = list(matches)
        self.idx = {m["equipo_local_id"]: 0 for m in matches}
        return self

    def lambdas(self, _home_id, _away_id):
        return 1.3, 1.1

    def predict_1x2(self, _lh, _la):
        return 0.45, 0.28, 0.27


def _preparar_fit(monkeypatch):
    registro = _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS,
                                      "partidos": PARTIDOS})
    monkeypatch.setattr(analyzer, "DixonColesModel", _FakeDC)
    monkeypatch.setattr(analyzer, "_cached_clubes", {})
    monkeypatch.setattr(analyzer, "_cache_ts_clubes", {})
    monkeypatch.setattr(analyzer, "_cached_liga_ids", {})
    return registro


def test_load_and_fit_solo_usa_partidos_de_su_liga(monkeypatch):
    """El bug latente: sin filtro por liga_id, el DC de Liga 1 se comía los ~3.2k
    partidos internacionales que viven en la misma tabla `partidos`."""
    _preparar_fit(monkeypatch)

    model, matches, counts = analyzer._load_and_fit("liga1")

    assert [m["equipo_local_id"] for m in matches] == ["E-ALI"]
    assert set(counts) == {"E-ALI", "E-UNI"}


def test_load_and_fit_premier_usa_sus_propios_partidos(monkeypatch):
    _preparar_fit(monkeypatch)

    _, matches, counts = analyzer._load_and_fit("premier")

    assert [m["equipo_local_id"] for m in matches] == ["E-ARS"]
    assert set(counts) == {"E-ARS", "E-CHE"}


def test_load_and_fit_cachea_por_liga(monkeypatch):
    _preparar_fit(monkeypatch)

    m_l1, _, _ = analyzer._load_and_fit("liga1")
    m_pl, _, _ = analyzer._load_and_fit("premier")
    m_l1_otra_vez, _, _ = analyzer._load_and_fit("liga1")

    assert m_l1 is not m_pl                 # un modelo por liga
    assert m_l1 is m_l1_otra_vez            # y se cachea, no se reajusta


def test_load_and_fit_liga_inexistente_falla_claro(monkeypatch):
    _preparar_fit(monkeypatch)
    monkeypatch.setitem(analyzer.SLUG_A_NOMBRE, "fantasma", "Liga Fantasma")

    with pytest.raises(RuntimeError, match="Liga Fantasma"):
        analyzer._load_and_fit("fantasma")


def test_liga_ingestada_despues_se_resuelve_sin_reiniciar(monkeypatch):
    """warm_up() corre al arrancar el servidor y llama _load_and_fit("premier")
    ANTES de que la Premier esté ingestada (su ingesta es una tarea posterior).
    Ese primer fallo no debe envenenar el proceso: cuando la liga se ingesta de
    verdad, debe resolverse sola sin reiniciar el servidor."""
    ligas_sin_premier = [l for l in LIGAS if l["nombre"] != "Premier League"]
    _fake_sb(monkeypatch, {"ligas": ligas_sin_premier, "equipos": EQUIPOS,
                          "partidos": PARTIDOS})
    monkeypatch.setattr(analyzer, "DixonColesModel", _FakeDC)
    monkeypatch.setattr(analyzer, "_cached_clubes", {})
    monkeypatch.setattr(analyzer, "_cache_ts_clubes", {})
    monkeypatch.setattr(analyzer, "_cached_liga_ids", {})

    with pytest.raises(RuntimeError, match="Premier League"):
        analyzer._load_and_fit("premier")

    # La liga se ingesta "de verdad": nuevo cliente falso cuyo `ligas` SÍ la trae.
    # OJO: no se limpia _cached_liga_ids — así se prueba el auto-sane del proceso.
    monkeypatch.setattr(analyzer, "create_client",
                        lambda *_a, **_k: _FakeClient(
                            {"ligas": LIGAS, "equipos": EQUIPOS, "partidos": PARTIDOS}, []))

    _, matches, _ = analyzer._load_and_fit("premier")

    assert [m["equipo_local_id"] for m in matches] == ["E-ARS"]
