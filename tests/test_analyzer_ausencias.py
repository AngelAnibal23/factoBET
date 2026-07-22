"""Tests del wiring analyzer <-> capa de ausencias (Task 5, Fase 3.4).
Sin red: obtener_ausencias y los loaders de modelo van monkeypateados."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine_intl_v01 import DixonColesIntl
from validator import ValidatedParlay, ValidatedSelection, TeamMatch
import analyzer
from analyzer import _analyze_intl, _analyze_bet_builder_route
from ajuste_ausencias import Ausente


def _tm(name, eid):
    return TeamMatch(raw=name, canonical=name, equipo_id=eid,
                     score=1.0, status="MATCHED")


def _sel(local, lid, mercado, seleccion, cuota, vis=None, vid=None, linea=None):
    return ValidatedSelection(
        equipo_local_raw=local,
        equipo_visitante_raw=vis,
        mercado=mercado,
        seleccion=seleccion,
        cuota=cuota,
        linea=linea,
        local_match=_tm(local, lid),
        visitante_match=_tm(vis, vid) if vis else None,
        prob_implicita=round(1 / cuota, 6),
        mercado_exotico=(mercado == "exotic"),
    )


def _parlay(*sels, es_bet_builder=False, cuota_total=None):
    return ValidatedParlay(selecciones=list(sels), cuota_total=cuota_total,
                           casa_apuestas=None, es_bet_builder=es_bet_builder)


def _intl_model():
    attack = {"Argentina": 0.55, "France": 0.6}
    defense = {"Argentina": -0.45, "France": -0.5}
    return DixonColesIntl.from_params(mu=0.2, gamma=0.35, rho=-0.05,
                                      attack=attack, defense=defense)


class _FakePlayerModel:
    """Mismo contrato que PlayerModel: resolver/equipo_de/jugadores."""
    def __init__(self, jugadores):
        self.jugadores = jugadores   # pid -> {nombre, equipo, cuota_gol}

    def resolver(self, nombre):
        from rapidfuzz import fuzz
        mejor_id, mejor_score = None, 0.0
        for pid, j in self.jugadores.items():
            score = fuzz.token_set_ratio(nombre.lower(), j["nombre"].lower())
            if score > mejor_score:
                mejor_id, mejor_score = pid, score
        return mejor_id if mejor_score >= 80.0 else None

    def equipo_de(self, pid):
        j = self.jugadores.get(pid)
        return j["equipo"] if j else None


PM = _FakePlayerModel({
    "p1": {"nombre": "Lionel Messi", "equipo": "Argentina", "cuota_gol": 0.30},
})


def _ausencias_messi_out():
    return {
        "equipos": {
            "Argentina": [Ausente(nombre="Lionel Messi", estado="out", motivo="Injured")],
            "France": [],
        },
        "url": "https://www.sofascore.com/football/match/x",
        "scrapeado_en": "2026-07-22T00:00:00",
    }


# ── _analyze_intl ─────────────────────────────────────────────────────────────

def test_analyze_intl_ajusta_lambdas(monkeypatch):
    model = _intl_model()
    p = _parlay(_sel("Argentina", "IA", "1X2", "home", 1.8, "France", "IF"))
    monkeypatch.setattr(analyzer, "_load_player_model", lambda liga: PM)

    # Baseline: sin dato de ausencias -> el conftest autouse ya devuelve None,
    # pero lo re-mockeamos explicito para que quede claro en este test.
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None)
    res_sin = _analyze_intl(p, model)
    assert res_sin.ausencias == {"sin_dato": True}
    p_sin = res_sin.selecciones[0].prob_modelo

    # Con Messi out.
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: _ausencias_messi_out())
    res_con = _analyze_intl(p, model)
    p_con = res_con.selecciones[0].prob_modelo

    assert p_con < p_sin
    assert res_con.ausencias["equipos"]["Argentina"][0]["nombre"] == "Lionel Messi"
    clave = "Argentina - France"
    assert clave in res_con.ausencias["lambdas"]
    assert res_con.ausencias["lambdas"][clave]["antes"] != res_con.ausencias["lambdas"][clave]["despues"]


def test_analyze_intl_sin_dato_no_ajusta_y_lo_dice(monkeypatch):
    model = _intl_model()
    p = _parlay(_sel("Argentina", "IA", "1X2", "home", 1.8, "France", "IF"))
    monkeypatch.setattr(analyzer, "_load_player_model", lambda liga: PM)
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: None)
    res = _analyze_intl(p, model)
    assert res.ausencias == {"sin_dato": True}


# ── _analyze_bet_builder_route ────────────────────────────────────────────────

def test_route_betbuilder_intl_pasa_ausencias(monkeypatch):
    model = _intl_model()
    p = _parlay(
        _sel("Argentina", "IA", "1X2", "home", 1.8, "France", "IF"),
        es_bet_builder=True, cuota_total=1.8,
    )
    monkeypatch.setattr(analyzer, "_load_intl_predictor", lambda: model)
    monkeypatch.setattr(analyzer, "_load_counts_model", lambda liga: None)
    monkeypatch.setattr(analyzer, "_load_player_model", lambda liga: PM)
    monkeypatch.setattr(analyzer, "_load_player_sot_model", lambda liga: None)
    monkeypatch.setattr(analyzer, "obtener_ausencias", lambda h, a: _ausencias_messi_out())

    res = _analyze_bet_builder_route(p, "internacional", 0.06)
    assert res.ausencias is not None and "equipos" in res.ausencias
