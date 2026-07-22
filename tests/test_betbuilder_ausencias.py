"""Cruce de ausencias en el bet builder (spec 2026-07-16, Task 4 del plan)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ajuste_ausencias import Ausente
from betbuilder import analyze_bet_builder
from player_model import PlayerModel
from validator import ValidatedParlay, ValidatedSelection, TeamMatch


def _tm(name):
    return TeamMatch(raw=name, canonical=name, equipo_id=name[:2].upper(),
                     score=1.0, status="MATCHED")


def _sel_messi():
    return ValidatedSelection(
        equipo_local_raw="Argentina", equipo_visitante_raw="France",
        mercado="player", seleccion="yes", cuota=None, linea=None,
        local_match=_tm("Argentina"), visitante_match=_tm("France"),
        prob_implicita=None, mercado_exotico=False,
        player="Messi", metric="goal", umbral=1, faltante=False)


player_model_fake = PlayerModel.from_params({
    "metricas": ["goal", "assist"],
    "jugadores": {"p1": {"nombre": "Lionel Messi", "equipo": "Argentina",
                         "cuota_gol": 0.30, "cuota_asist": 0.10}},
})

# parlay genérico de una pata (Messi anota) para los casos out / sin-dato / otro-jugador.
# El out fuerza player_p=0.0 -> SIN_VALOR sea cual sea la cuota, así que su veredicto
# base es indiferente a estos tests (a diferencia de parlay_valor, abajo).
parlay = ValidatedParlay(selecciones=[_sel_messi()], cuota_total=10.0,
                         casa_apuestas="Betano")

# cuota_total alta -> 1/cuota por debajo del techo (marginal Poisson de Messi:
# lam=1.4*0.30=0.42, prob(>=1)=1-exp(-0.42)=~0.343) -> VALOR sin ausencias
# (única pata, sin exóticas, techo exacto de una sola familia).
parlay_valor = ValidatedParlay(selecciones=[_sel_messi()], cuota_total=5.0,
                               casa_apuestas="Betano")

AUSENCIAS = {"equipos": {"Argentina": [Ausente(nombre="Lionel Messi", estado="out",
                                               motivo="Injured - Muscle")],
                         "France": []},
             "url": "http://x", "scrapeado_en": "2026-07-17T10:00:00"}

DUDOSO = {"equipos": {"Argentina": [Ausente(nombre="Lionel Messi", estado="doubtful",
                                            motivo="Knock")],
                      "France": []},
          "url": "http://x", "scrapeado_en": "2026-07-17T10:00:00"}

OTRO_AUSENTE = {"equipos": {"Argentina": [Ausente(nombre="Nicolas Otamendi", estado="out")],
                            "France": []}}


def _baseline_es_valor():
    """Confirma que parlay_valor SIN ausencias ya da VALOR (si no, el test de
    doubtful sería vacío)."""
    res = analyze_bet_builder(parlay_valor, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake)
    return res.veredicto


def test_baseline_parlay_valor_es_valor_sin_ausencias():
    assert _baseline_es_valor() == "VALOR"


def test_pata_out_mata_el_boleto():
    res = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=AUSENCIAS)
    pata = res.selecciones[0]
    assert pata.prob_modelo == 0.0
    assert res.veredicto == "SIN_VALOR"
    assert any("no juega" in a.lower() for a in pata.alertas)


def test_pata_doubtful_degrada_valor_a_no_concluyente():
    assert _baseline_es_valor() == "VALOR"   # confirma que hay algo que degradar
    res = analyze_bet_builder(parlay_valor, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=DUDOSO)
    assert res.veredicto == "NO_CONCLUYENTE"
    assert res.bet_builder_kelly is None
    assert any("duda" in a.lower() for a in res.selecciones[0].alertas)


def test_sin_ausencias_todo_igual():
    a = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                            player_model=player_model_fake)
    b = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                            player_model=player_model_fake, ausencias=None)
    assert a.veredicto == b.veredicto
    assert a.prob_techo == b.prob_techo


def test_ausente_de_otro_jugador_no_toca_la_pata():
    res = analyze_bet_builder(parlay, 1.4, 1.1, -0.08, "intl_v0.1", 0.06,
                              player_model=player_model_fake, ausencias=OTRO_AUSENTE)
    assert res.selecciones[0].prob_modelo not in (None, 0.0)
