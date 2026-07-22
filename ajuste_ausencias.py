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


def _sin_acentos(s: str) -> str:
    """Normaliza acentos para que el fuzzy no penalice 'Di María' vs 'Di Maria'."""
    import unicodedata as _u
    return "".join(c for c in _u.normalize("NFKD", s or "") if not _u.combining(c))


def _clamp(x: float) -> float:
    return max(CLAMP_MIN, min(CLAMP_MAX, x))


def _resolver_en_equipo(nombre: str, equipo: str, player_model) -> str | None:
    """Resuelve un ausente contra el roster, ACOTADO al equipo. No usa
    `player_model.resolver` (token_set_ratio) porque Sofascore da 'Nombre Apellido'
    y el modelo guarda 'Apellido I.': token_set falla en 'Lionel Messi'->'Messi L.'
    (76.9<80) mientras WRatio da 85.5, y al revés WRatio falla en 'Julian Alvarez'
    ->'Alvarez J.' (78.2) mientras token_set da 82.4 — por eso `max` de ambos. El
    guard de equipo (fuzzy sin acento) evita cruzar homónimos de otra selección."""
    eq_q = _sin_acentos(equipo.lower())
    n = _sin_acentos(nombre.lower())
    mejor_id, mejor = None, 0.0
    for pid, j in player_model.jugadores.items():
        eq = j.get("equipo") or ""
        if fuzz.token_set_ratio(_sin_acentos(eq.lower()), eq_q) < UMBRAL_NOMBRE:
            continue
        cand = _sin_acentos(j["nombre"].lower())
        s = max(fuzz.token_set_ratio(n, cand), fuzz.WRatio(n, cand))
        if s > mejor:
            mejor_id, mejor = pid, s
    return mejor_id if mejor >= UMBRAL_NOMBRE else None


def _cuota_ofensiva(nombre: str, equipo: str, player_model) -> float | None:
    """cuota_gol del ausente en el player model, con guard de equipo (un fuzzy
    global sin guard cruzaría homónimos de otra selección)."""
    if player_model is None:
        return None
    pid = _resolver_en_equipo(nombre, equipo, player_model)
    return player_model.jugadores[pid].get("cuota_gol") if pid else None


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
