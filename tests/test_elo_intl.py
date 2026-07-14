"""Tests de elo_intl: World Football Elo sobre el histórico martj42."""
from elo_intl import (
    ELO_INICIAL, K_DEFAULT, k_torneo, multiplicador_goles, calcular_elo,
    estandarizar, blend_z, cargar_partidos_elo, cargar_z_fifa,
)


def _p(home, away, gl, gv, fecha, neutral=False, tournament="Friendly"):
    return {"home": home, "away": away, "gl": gl, "gv": gv,
            "fecha": fecha, "neutral": neutral, "tournament": tournament}


def test_k_por_torneo():
    assert k_torneo("FIFA World Cup") == 60.0
    # 'qualification' contiene 'FIFA World Cup': el orden del match importa
    assert k_torneo("FIFA World Cup qualification") == 40.0
    assert k_torneo("Copa América") == 50.0
    assert k_torneo("UEFA Euro") == 50.0
    assert k_torneo("UEFA Euro qualification") == 40.0
    assert k_torneo("UEFA Nations League") == 40.0
    assert k_torneo("Friendly") == 20.0
    assert k_torneo("Torneo Inventado 1999") == K_DEFAULT


def test_multiplicador_goles():
    assert multiplicador_goles(0) == 1.0
    assert multiplicador_goles(1) == 1.0
    assert multiplicador_goles(-2) == 1.5   # valor absoluto
    assert multiplicador_goles(3) == 1.75
    assert multiplicador_goles(4) == 1.875  # 1.75 + (4-3)/8


def test_elo_ganador_sube_perdedor_baja_suma_cero():
    elos = calcular_elo([_p("A", "B", 2, 0, "2020-01-01", neutral=True)])
    assert elos["A"] > ELO_INICIAL > elos["B"]
    assert abs((elos["A"] - ELO_INICIAL) + (elos["B"] - ELO_INICIAL)) < 1e-9


def test_elo_ventaja_local_solo_si_no_neutral():
    # Empate con iguales: en casa el local partía favorito (+100) => pierde puntos.
    en_casa = calcular_elo([_p("A", "B", 1, 1, "2020-01-01", neutral=False)])
    neutral = calcular_elo([_p("A", "B", 1, 1, "2020-01-01", neutral=True)])
    assert en_casa["A"] < ELO_INICIAL
    assert abs(neutral["A"] - ELO_INICIAL) < 1e-9


def test_elo_converge_direccional():
    # El que siempre gana 2-0 durante 48 partidos termina MUY arriba del otro.
    partidos = [
        _p("Fuerte", "Debil", 2, 0, f"{2010 + i // 12}-{i % 12 + 1:02d}-01", neutral=True)
        for i in range(48)
    ]
    elos = calcular_elo(partidos)
    assert elos["Fuerte"] - elos["Debil"] > 300


def test_calcular_elo_respeta_corte():
    # 'hasta' es exclusivo: el partido del día de corte NO cuenta (anti-fuga).
    partidos = [_p("A", "B", 3, 0, "2020-01-01", neutral=True),
                _p("A", "B", 3, 0, "2021-01-01", neutral=True)]
    con_corte = calcular_elo(partidos, hasta="2021-01-01")
    sin_corte = calcular_elo(partidos)
    assert con_corte["A"] < sin_corte["A"]


def test_estandarizar_media_cero_y_orden():
    z = estandarizar({"A": 1600.0, "B": 1500.0, "C": 1400.0})
    assert abs(sum(z.values())) < 1e-9
    assert z["A"] > 0 > z["C"]


def test_estandarizar_vacio_y_sd_cero():
    assert estandarizar({}) == {}
    assert estandarizar({"A": 1500.0}) == {"A": 0.0}   # sd=0 -> guard 'or 1.0'


def test_blend_z_predominante_y_fallback():
    za = {"A": 1.0, "B": -1.0}
    zb = {"A": 0.0}
    out = blend_z(za, zb, w=0.7)
    assert abs(out["A"] - 0.7) < 1e-9   # 0.7*1.0 + 0.3*0.0
    assert out["B"] == -1.0             # sin señal FIFA -> solo la nuestra


def test_cargar_partidos_elo_normaliza_y_ordena(tmp_path):
    csv_content = (
        "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
        "2022-12-18,Argentina,France,3,3,FIFA World Cup,Lusail,Qatar,TRUE\n"
        "2019-06-01,France,Brazil,2,1,Friendly,Paris,France,FALSE\n"
    )
    p = tmp_path / "mini_elo.csv"
    p.write_text(csv_content, encoding="utf-8")
    partidos = cargar_partidos_elo(str(p))
    assert len(partidos) == 2
    assert partidos[0]["fecha"] == "2019-06-01"      # ordenado por fecha
    assert partidos[0]["tournament"] == "Friendly"
    assert partidos[1]["neutral"] is True
    assert partidos[1]["gl"] == 3


def test_cargar_z_fifa_none_sin_archivo_y_estandariza(tmp_path):
    assert cargar_z_fifa(str(tmp_path / "no_existe.csv")) is None
    p = tmp_path / "fifa.csv"
    p.write_text("team,points\nArgentina,1800\nPeru,1500\n", encoding="utf-8")
    z = cargar_z_fifa(str(p))
    assert z["Argentina"] > 0 > z["Peru"]
    assert abs(sum(z.values())) < 1e-9
