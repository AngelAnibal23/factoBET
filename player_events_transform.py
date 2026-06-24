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


def parse_titulares(blob: str) -> dict:
    """df_li_1: {player_id: fue_titular}. Titular si ST==1."""
    out = {}
    for c in _registros(blob):
        if "LP" not in c:
            continue
        out[c["LP"]] = c.get("ST", "0") == "1"
    return out
