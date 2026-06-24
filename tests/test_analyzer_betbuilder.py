import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from analyzer import ParlayAnalysis, SelectionAnalysis


def test_parlay_analysis_has_bet_builder_fields():
    pa = ParlayAnalysis(
        selecciones=[], prob_parlay_modelo=None, prob_parlay_impl=None,
        cuota_total=4.0, casa_apuestas="Betano", nivel_confianza="MEDIA",
        razones_confianza=[], correlaciones=[],
    )
    assert pa.es_bet_builder is False
    assert pa.veredicto is None
    assert pa.prob_techo is None
    assert pa.n_modelables == 0
    assert pa.exoticas_desc == []


def test_selection_cuota_can_be_none():
    sa = SelectionAnalysis(
        equipo_local="A", equipo_visitante="B", equipo_local_id="1",
        equipo_visitante_id="2", mercado="over_under", seleccion="over",
        cuota=None, linea=1.5, prob_implicita=None, prob_implicita_adj=None,
        prob_modelo=0.7, lambda_home=1.5, lambda_away=1.2, edge=None,
        kelly_fraccion=None, nivel_cobertura="ALTA", mercado_exotico=False,
        n_partidos_local=0, n_partidos_visitante=0,
    )
    assert sa.cuota is None and sa.prob_implicita is None


from validator import ValidatedParlay, ValidatedSelection, TeamMatch
from engine_intl_v01 import DixonColesIntl
import analyzer
import betbuilder


def _tm(name, eid):
    return TeamMatch(raw=name, canonical=name, equipo_id=eid, score=1.0, status="MATCHED")


def _bb_sel(local, lid, vis, vid, mercado, seleccion, linea=None):
    return ValidatedSelection(
        equipo_local_raw=local, equipo_visitante_raw=vis, mercado=mercado,
        seleccion=seleccion, cuota=None, linea=linea,
        local_match=_tm(local, lid), visitante_match=_tm(vis, vid),
        prob_implicita=None, mercado_exotico=(mercado == "exotic"),
    )


def _intl_model():
    attack = {"Uzbekistan": -0.2, "Colombia": 0.5}
    defense = {"Uzbekistan": 0.2, "Colombia": -0.4}
    return DixonColesIntl.from_params(mu=0.2, gamma=0.35, rho=-0.05, attack=attack, defense=defense)


def test_analyze_bet_builder_no_concluyente():
    parlay = ValidatedParlay(
        selecciones=[
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "resultado_exacto", "1-3"),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5),
            _bb_sel("Uzbekistan", "U1", "Colombia", "C1", "exotic", "Más 7.5 córners"),
        ],
        cuota_total=4.45, casa_apuestas="Betano", es_bet_builder=True,
    )
    m = _intl_model()
    lh, la = m.lambdas("Uzbekistan", "Colombia", neutral=True)
    res = betbuilder.analyze_bet_builder(parlay, lh, la, m.rho, "intl_v0.1", 0.06)
    assert res.es_bet_builder is True
    assert res.veredicto in {"SIN_VALOR", "NO_CONCLUYENTE", "VALOR"}
    assert res.n_modelables == 2 and res.n_exoticas == 1
    assert res.prob_techo is not None
    assert res.exoticas_desc == ["Más 7.5 córners"]


def test_analyze_bet_builder_intl_pobla_marcador():
    # Bet builder de selecciones (estilo ejemploBET3: Argentina vs Austria).
    parlay = ValidatedParlay(
        selecciones=[
            _bb_sel("Colombia", "C1", "Uzbekistan", "U1", "1X2", "home"),
            _bb_sel("Colombia", "C1", "Uzbekistan", "U1", "over_under", "over", 1.5),
        ],
        cuota_total=2.5, casa_apuestas="Betano", es_bet_builder=True,
    )
    m = _intl_model()
    lh, la = m.lambdas("Colombia", "Uzbekistan", neutral=True)
    res = betbuilder.analyze_bet_builder(parlay, lh, la, m.rho, "intl_v0.1", 0.06)
    assert len(res.marcadores_partido) == 1
    mar = res.marcadores_partido[0]
    assert mar["equipo_local"] == "Colombia"
    assert mar["equipo_visitante"] == "Uzbekistan"
    assert 0.0 < mar["probabilidad"] < 1.0
    assert len(mar["detalle"]["top"]) == 5


def test_analyze_bet_builder_liga1_sin_marcador():
    # Liga 1 (v0.2): alcance es solo selecciones por ahora -> sin marcador.
    parlay = ValidatedParlay(
        selecciones=[_bb_sel("Colombia", "C1", "Uzbekistan", "U1", "1X2", "home")],
        cuota_total=2.0, casa_apuestas="Betano", es_bet_builder=True,
    )
    m = _intl_model()
    lh, la = m.lambdas("Colombia", "Uzbekistan", neutral=True)
    res = betbuilder.analyze_bet_builder(parlay, lh, la, m.rho, "v0.2", 0.07)
    assert res.marcadores_partido == []


def test_analyze_bet_builder_sin_cobertura_sin_marcador():
    # Equipos fuera de los params (lh None) -> sin matriz -> sin marcador.
    parlay = ValidatedParlay(
        selecciones=[_bb_sel("Colombia", "C1", "Uzbekistan", "U1", "exotic", "corners")],
        cuota_total=2.0, casa_apuestas="Betano", es_bet_builder=True,
    )
    res = betbuilder.analyze_bet_builder(parlay, None, None, -0.05, "intl_v0.1", 0.06)
    assert res.marcadores_partido == []


def test_analyze_bet_builder_sin_cuota_raises():
    parlay = ValidatedParlay(
        selecciones=[_bb_sel("Uzbekistan", "U1", "Colombia", "C1", "over_under", "over", 1.5)],
        cuota_total=None, casa_apuestas="Betano", es_bet_builder=True,
    )
    import pytest
    with pytest.raises(betbuilder.BetBuilderSinCuotaError):
        analyzer._analyze_bet_builder_route(parlay, "internacional", 0.06)


# ── Familia COUNT (Sub-proyecto B) ──────────────────────────────────────────
from counts_model import CountsModel


def _count_sel(local, lid, vis, vid, metric, scope, seleccion, linea):
    s = _bb_sel(local, lid, vis, vid, "count", seleccion, linea)
    s.metric = metric
    s.scope = scope
    return s


_COUNTS = CountsModel.from_params({
    "shots": {"base_home": 13.0, "base_away": 11.0, "factor_neutral": 1.0,
              "disp": 1.6, "atk": {}, "def": {}},
})


def test_count_leg_baja_n_exoticas():
    parlay = ValidatedParlay(
        selecciones=[
            _bb_sel("Colombia", "C1", "Uzbekistan", "U1", "1X2", "home"),
            _count_sel("Colombia", "C1", "Uzbekistan", "U1", "shots", "total", "over", 22.5),
        ],
        cuota_total=5.0, casa_apuestas="bet365", es_bet_builder=True,
    )
    res = betbuilder.analyze_bet_builder(parlay, 1.6, 1.1, -0.05, "intl_v0.1", 0.05,
                                         counts_model=_COUNTS, neutral=True)
    # la pata de tiros es modelable -> 0 exóticas, 2 modelables
    assert res.n_exoticas == 0
    assert res.n_modelables == 2
    assert res.prob_estimada is not None


def test_count_sin_modelo_cuenta_exotica():
    parlay = ValidatedParlay(
        selecciones=[
            _count_sel("Colombia", "C1", "Uzbekistan", "U1", "cards", "total", "over", 3.5),
        ],
        cuota_total=5.0, casa_apuestas="bet365", es_bet_builder=True,
    )
    # _COUNTS no tiene 'cards' -> esa métrica no está gateada -> exótica
    res = betbuilder.analyze_bet_builder(parlay, 1.6, 1.1, -0.05, "intl_v0.1", 0.05,
                                         counts_model=_COUNTS, neutral=True)
    assert res.n_exoticas == 1
    assert res.n_modelables == 0


def test_load_player_model_cache_hit_devuelve_none():
    # Contrato de cache (sin red): una liga ya cacheada como None se devuelve tal cual,
    # igual que _load_counts_model. El path real a Supabase se ejerce en e2e.
    import analyzer
    analyzer._cached_player_model["LigaInexistenteXYZ"] = None
    assert analyzer._load_player_model("LigaInexistenteXYZ") is None
