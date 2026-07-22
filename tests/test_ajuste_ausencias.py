"""Tests de la lógica pura de ausencias (spec 2026-07-16)."""
import pytest
from ajuste_ausencias import (
    Ausente, deltas_equipo, aplicar_ajuste, cruzar_pata,
    K_AUSENCIA, PENAL_DEF, CLAMP_MIN, CLAMP_MAX,
)


class _FakePlayerModel:
    """Mismo contrato que PlayerModel: resolver/equipo_de/jugadores."""
    def __init__(self, jugadores):
        self.jugadores = jugadores          # pid -> {nombre, equipo, cuota_gol}
    def resolver(self, nombre):
        for pid, j in self.jugadores.items():
            if nombre.lower() in j["nombre"].lower():
                return pid
        return None
    def equipo_de(self, pid):
        j = self.jugadores.get(pid)
        return j["equipo"] if j else None


PM = _FakePlayerModel({
    "p1": {"nombre": "Lionel Messi", "equipo": "Argentina", "cuota_gol": 0.30},
    "p2": {"nombre": "Suplente Perez", "equipo": "Argentina", "cuota_gol": 0.01},
})


def test_deltas_ofensivo_por_cuota():
    aus = [Ausente(nombre="Lionel Messi", estado="out", motivo="Injured")]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert atk == pytest.approx(1.0 - K_AUSENCIA * 0.30)   # 0.82
    assert dfn == 1.0


def test_deltas_doubtful_no_ajusta():
    aus = [Ausente(nombre="Lionel Messi", estado="doubtful", motivo="Knock")]
    assert deltas_equipo(aus, "Argentina", PM) == (1.0, 1.0)


def test_deltas_defensivo_por_posicion():
    aus = [Ausente(nombre="Central Gomez", estado="out", posicion="D")]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert atk == 1.0 and dfn == pytest.approx(1.0 + PENAL_DEF)


def test_deltas_equipo_equivocado_no_cruza():
    # Messi está en Argentina; el ausente reportado es de Francia -> no ajusta.
    aus = [Ausente(nombre="Lionel Messi", estado="out")]
    assert deltas_equipo(aus, "France", PM) == (1.0, 1.0)


def test_deltas_desconocido_sin_cuota_ni_posicion_no_ajusta():
    aus = [Ausente(nombre="Fulano Nadie", estado="out")]
    assert deltas_equipo(aus, "Argentina", PM) == (1.0, 1.0)


def test_deltas_clamp_equipo_diezmado():
    aus = [Ausente(nombre=f"Central {i}", estado="out", posicion="D") for i in range(9)]
    atk, dfn = deltas_equipo(aus, "Argentina", PM)
    assert dfn == pytest.approx(CLAMP_MAX)   # 1.05^9 ≈ 1.55 -> clamp 1.30
    assert CLAMP_MIN <= atk <= CLAMP_MAX


def test_aplicar_ajuste_direcciones():
    # def del visitante debilitada (1.05) SUBE lh; ataque local mermado lo BAJA.
    lh, la = aplicar_ajuste(1.5, 1.0, deltas_home=(0.82, 1.0), deltas_away=(1.0, 1.05))
    assert lh == pytest.approx(1.5 * 0.82 * 1.05)
    assert la == pytest.approx(1.0)


def test_cruzar_pata_exacto_fuzzy_y_none():
    aus = [Ausente(nombre="Lionel Messi", estado="out", motivo="Injured - Muscle")]
    assert cruzar_pata("Messi", aus).estado == "out"
    assert cruzar_pata("L. Messi", aus).motivo == "Injured - Muscle"
    assert cruzar_pata("Julian Alvarez", aus) is None


def test_cruzar_pata_no_colisiona_por_apellido():
    # Un apellido compartido con un ausente del OTRO equipo no debe matar la pata:
    # partial_token_set_ratio daba 100 aquí; WRatio da <70. La pata de "Bernardo
    # Silva" (que sí juega) no debe cruzarse con un "Thiago Silva" lesionado.
    aus = [Ausente(nombre="Thiago Silva", estado="out", motivo="Injured"),
           Ausente(nombre="Marcos Acuna", estado="out", motivo="Suspended")]
    assert cruzar_pata("Bernardo Silva", aus) is None
    assert cruzar_pata("Marcos Rojo", aus) is None
    # y el match legítimo del mismo jugador sí cruza
    assert cruzar_pata("T. Silva", aus).nombre == "Thiago Silva"
