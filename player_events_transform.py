"""Parsers puros del feed packed por-jugador de Flashscore (df_sui_1, df_li_1).

Sin red: reciben el string ya decodificado y devuelven dicts/listas. La descarga
vive en download_player_events.py (offline, .venv-fbref)."""

import re

REG_SEP = "~"
FLD_SEP = "¬"
KV_SEP = "÷"


def _registros(blob: str):
    for reg in blob.split(REG_SEP):
        if not reg.strip():
            continue
        campos = {}
        for kv in reg.split(FLD_SEP):
            if KV_SEP in kv:
                k, v = kv.split(KV_SEP, 1)
                campos[k] = v
        yield campos


SHOOTOUT = "Penalties"   # seccion de tanda de penales; sus penales NO son "el jugador anota"


def parse_eventos(blob: str) -> list[dict]:
    """Eventos del df_sui_1: tipo (IK), jugador (IF/IM), lado (IA), minuto (IB).

    La mitad/seccion viene en registros-cabecera (AC sin IK: 1st Half, 2nd Half,
    Extra Time, Penalties). Se rastrea el estado y se EXCLUYE la seccion "Penalties"
    (tanda): esos penales no cuentan en el marcador (sin INX) ni como gol del jugador."""
    evs = []
    seccion = ""
    for c in _registros(blob):
        if "AC" in c and "IK" not in c:   # cabecera de seccion
            seccion = c["AC"]
            continue
        if "IK" not in c or "IM" not in c:
            continue
        if seccion == SHOOTOUT:           # tanda de penales -> fuera
            continue
        evs.append({
            "tipo": c.get("IK", ""),
            "player_id": c.get("IM", ""),
            "nombre": c.get("IF", ""),
            "lado": int(c["IA"]) if c.get("IA", "").isdigit() else None,
            "minuto": c.get("IB", ""),
            "mitad": seccion,
        })
    return evs


def _jugadores(blob: str):
    """Itera (campos, es_titular, lado) por cada JUGADOR del df_li_1, sin técnicos.

    El feed se divide en secciones por header `LB` (Starting Lineups / Substitutes /
    Coaches) y, dentro de cada sección, en dos bloques por `LC` (1=local, 2=visitante).
    Los registros de jugador traen LP (player_id), LI (nombre) y LK (1=titular, 2=suplente).
    OJO: LQ NO sirve como equipo (en partidos de club es la NACIONALIDAD del jugador, no
    el club); el equipo se deriva del lado LC y se resuelve después contra es_local.
    Los técnicos (sección Coaches) también traen LP/LK, así que se filtran por sección."""
    seccion = ""
    lado = None
    for c in _registros(blob):
        if "LC" in c and c["LC"].isdigit():
            lado = int(c["LC"])
        if "LB" in c:
            seccion = c["LB"]
        if "LP" not in c or seccion == "Coaches":
            continue
        yield c, c.get("LK") == "1", lado


def parse_titulares(blob: str) -> dict:
    """df_li_1: {player_id: fue_titular}. Titular si LK==1; técnicos excluidos."""
    return {c["LP"]: titular for c, titular, _ in _jugadores(blob)}


def parse_lineup(blob: str) -> list[dict]:
    """df_li_1 enriquecido: una fila por jugador del once/banca con su lado y nombre.

    Devuelve [{player_id (LP), nombre (LI), lado (LC int: 1 local / 2 visitante),
    fue_titular (LK==1)}]. Necesario para incluir a los titulares que NO anotaron
    (denominador del reparto) y para resolver su equipo por (event_id, lado)."""
    return [{
        "player_id": c["LP"],
        "nombre": c.get("LI", ""),
        "lado": lado,
        "fue_titular": titular,
    } for c, titular, lado in _jugadores(blob)]


# Goleador del campo LIT: "MIN' Goleador" o "MIN' Goleador (Asistente)" (el minuto
# admite descuento "90+2'"). El goleador es el texto entre el minuto y el paréntesis.
_LIT_MIN = re.compile(r"^(\d+(?:\+\d+)?)'")
_LIT_SCORER = re.compile(r"^\d+(?:\+\d+)?'\s+(.+?)(?:\s+\(.*)?$")


def parse_lit_goles(blob: str) -> list[dict]:
    """Goleadores recuperados del campo LIT de df_li_1.

    POR QUÉ: df_sui_1 OMITE el registro `Goal` de todo gol con asistencia (deja solo
    el `Assistance`) y en muchas ligas no-top no trae goles; el goleador SÍ vive en el
    LIT. El goleador es el nombre TRAS EL MINUTO en el TEXTO del LIT, NO el dueño de la
    fila (un jugador con varios eventos —p.ej. gol + cambio— guarda solo uno en su LIT,
    así que el LIT del gol puede aparecer en la fila del asistente). Se resuelve el
    nombre del goleador contra el lineup para obtener player_id y lado.

    Devuelve [{player_id, nombre, lado, minuto}] dedup por (player_id, minuto). OJO: el
    LIT NO distingue gol de tarjeta ("90+2' Vrsaljko S. (Tripping)"); ese filtrado se
    hace en eventos_completos() cruzando con las Yellow/Red de df_sui_1."""
    name2id, name2lado, lits = {}, {}, set()
    for c, _titular, lado in _jugadores(blob):
        nombre = c.get("LI", "")
        if nombre:
            name2id[nombre] = c["LP"]
            name2lado[nombre] = lado
        if c.get("LIT"):
            lits.add(c["LIT"])

    goles = {}
    for lit in lits:
        m_min, m_sc = _LIT_MIN.match(lit), _LIT_SCORER.match(lit)
        if not m_min or not m_sc:
            continue
        scorer = m_sc.group(1).strip()
        if scorer not in name2id:        # debe ser un jugador del lineup
            continue
        minuto = m_min.group(1) + "'"
        goles[(name2id[scorer], minuto)] = {
            "player_id": name2id[scorer], "nombre": scorer,
            "lado": name2lado[scorer], "minuto": minuto,
        }
    return list(goles.values())


def eventos_completos(sui_blob: str, li_blob: str) -> list[dict]:
    """Eventos del df_sui_1 + goleadores recuperados del LIT del df_li_1 (la UNIÓN).

    Arregla el sub-conteo de goles: agrega un evento `Goal` por cada goleador del LIT
    que NO esté ya en df_sui_1 (como Goal/Penalty) y que NO sea una tarjeta ni un
    autogol a ese mismo (jugador, minuto). Dedup por (player_id, minuto); un doblete
    emite dos filas Goal (el load las agrega vía `cantidad`)."""
    eventos = parse_eventos(sui_blob)
    excl = {                              # (player_id, minuto) que NO deben re-agregarse
        (e["player_id"], e["minuto"])
        for e in eventos
        if e["tipo"] in ("Goal", "Penalty", "Yellow Card", "Red Card", "Own goal")
    }
    extras = [
        {"tipo": "Goal", "player_id": g["player_id"], "nombre": g["nombre"],
         "lado": g["lado"], "minuto": g["minuto"], "mitad": ""}
        for g in parse_lit_goles(li_blob)
        if (g["player_id"], g["minuto"]) not in excl
    ]
    return eventos + extras
