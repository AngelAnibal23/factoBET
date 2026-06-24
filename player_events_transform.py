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


def parse_eventos(blob: str) -> list[dict]:
    """Eventos del df_sui_1: tipo (IK), jugador (IF/IM), lado (IA), minuto (IB)."""
    evs = []
    for c in _registros(blob):
        if "IK" not in c or "IM" not in c:
            continue
        evs.append({
            "tipo": c.get("IK", ""),
            "player_id": c.get("IM", ""),
            "nombre": c.get("IF", ""),
            "lado": int(c["IA"]) if c.get("IA", "").isdigit() else None,
            "minuto": c.get("IB", ""),
            "mitad": c.get("AC", ""),
        })
    return evs


def _jugadores(blob: str):
    """Itera (campos, es_titular) por cada JUGADOR del df_li_1, ya excluyendo técnicos.

    El feed se divide en secciones por un header `LB` (Starting Lineups / Substitutes /
    Coaches). Los registros de jugador traen LP (player_id), LI (nombre), LQ (equipo) y
    LK (1=titular, 2=suplente). Los técnicos (sección Coaches) también traen LP/LK, así
    que se filtran por sección, no por presencia de claves."""
    seccion = ""
    for c in _registros(blob):
        if "LB" in c:
            seccion = c["LB"]
            continue
        if "LP" not in c or seccion == "Coaches":
            continue
        yield c, c.get("LK") == "1"


def parse_titulares(blob: str) -> dict:
    """df_li_1: {player_id: fue_titular}. Titular si LK==1; técnicos excluidos."""
    return {c["LP"]: titular for c, titular in _jugadores(blob)}


def parse_lineup(blob: str) -> list[dict]:
    """df_li_1 enriquecido: una fila por jugador del once/banca con su equipo y nombre.

    Devuelve [{player_id (LP), nombre (LI), equipo (LQ), fue_titular (LK==1)}].
    Necesario para incluir a los titulares que NO anotaron (denominador del reparto)
    y para resolver su equipo por nombre contra estadisticas_flashscore.equipo_flashscore."""
    return [{
        "player_id": c["LP"],
        "nombre": c.get("LI", ""),
        "equipo": c.get("LQ", ""),
        "fue_titular": titular,
    } for c, titular in _jugadores(blob)]
