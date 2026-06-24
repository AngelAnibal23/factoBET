"""Parsers puros del feed packed por-jugador de Flashscore (df_sui_1, df_li_1).

Sin red: reciben el string ya decodificado y devuelven dicts/listas. La descarga
vive en download_player_events.py (offline, .venv-fbref)."""

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
