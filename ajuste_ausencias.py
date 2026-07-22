"""Lógica pura de la capa de ausencias: ausentes -> multiplicadores de λ y cruce
de patas de jugador. Sin I/O. Spec: docs/superpowers/specs/2026-07-16-ausencias-lesiones-design.md."""
from dataclasses import dataclass
from rapidfuzz import fuzz

K_AUSENCIA = 0.6          # fracción de la cuota del ausente que realmente se pierde
PENAL_DEF = 0.05          # +5% λ concedido por titular defensivo/arquero out
CLAMP_MIN, CLAMP_MAX = 0.70, 1.30
UMBRAL_NOMBRE = 80.0      # token_set_ratio, mismo que PlayerModel.RESOLVER_UMBRAL
POSICIONES_DEFENSIVAS = {"d", "g", "df", "gk", "defender", "goalkeeper", "defensa", "arquero"}


@dataclass
class Ausente:
    nombre: str
    estado: str                     # "out" | "doubtful"
    motivo: str = ""
    posicion: str | None = None


def _clamp(x: float) -> float:
    return max(CLAMP_MIN, min(CLAMP_MAX, x))


def _cuota_ofensiva(nombre: str, equipo: str, player_model) -> float | None:
    """cuota_gol del ausente en el player model, con guard de equipo (un fuzzy
    global sin guard cruzaría homónimos de otra selección)."""
    if player_model is None:
        return None
    pid = player_model.resolver(nombre)
    if pid is None:
        return None
    eq = player_model.equipo_de(pid)
    if not eq or fuzz.token_set_ratio(eq.lower(), equipo.lower()) < UMBRAL_NOMBRE:
        return None
    return player_model.jugadores[pid].get("cuota_gol")


def deltas_equipo(ausentes: list[Ausente], equipo: str, player_model) -> tuple[float, float]:
    """(mult_ataque, mult_defensa) del equipo. Solo estado 'out' ajusta.
    Defensivo/arquero por posición conocida; ofensivo por cuota del player model;
    sin cuota NI posición -> no se inventa ajuste (spec, tabla de errores)."""
    mult_atk, mult_def = 1.0, 1.0
    for a in ausentes:
        if a.estado != "out":
            continue
        if (a.posicion or "").strip().lower() in POSICIONES_DEFENSIVAS:
            mult_def *= (1.0 + PENAL_DEF)
            continue
        q = _cuota_ofensiva(a.nombre, equipo, player_model)
        if q:
            mult_atk *= (1.0 - K_AUSENCIA * q)
    return _clamp(mult_atk), _clamp(mult_def)


def aplicar_ajuste(lh: float, la: float,
                   deltas_home: tuple[float, float],
                   deltas_away: tuple[float, float]) -> tuple[float, float]:
    """lh = goles del local: lo merma su ataque y lo sube la defensa mermada
    del rival. Simétrico para la."""
    atk_h, def_h = deltas_home
    atk_a, def_a = deltas_away
    return lh * atk_h * def_a, la * atk_a * def_h


def cruzar_pata(nombre_pata: str, ausentes: list[Ausente]) -> Ausente | None:
    """Mejor match por nombre entre la pata de jugador y los ausentes (>=80).
    'out' gana sobre 'doubtful' si ambos matchean.

    Usa WRatio (no token_set_ratio ni partial_token_set_ratio): la pata de boleto
    suele venir abreviada ("L. Messi") frente al nombre completo de Sofascore
    ("Lionel Messi"). token_set_ratio penaliza el token corto "l." (76.9 < 80) y
    partial_token_set_ratio se pasa de laxo: da 100 a cualquier par que comparta
    un solo token, así que colisiones de apellido entre AMBOS equipos
    ("Bernardo Silva" vs un "Thiago Silva" lesionado) matarían patas de jugadores
    que sí juegan. WRatio da 90/85.5 a los pares legítimos y <70 a esas colisiones
    (ver test_cruzar_pata_no_colisiona_por_apellido)."""
    hits = [a for a in ausentes
            if fuzz.WRatio(nombre_pata.lower(), a.nombre.lower()) >= UMBRAL_NOMBRE]
    if not hits:
        return None
    return sorted(hits, key=lambda a: a.estado != "out")[0]
