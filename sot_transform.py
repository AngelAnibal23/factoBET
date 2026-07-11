# sot_transform.py
"""Transforma la respuesta de API-Football /fixtures/players en filas por jugador.

Puro (no toca red ni DB). La resolución de equipo_nombre -> equipo_id se hace en el
loader (download_sot_jugador.py) contra la tabla equipos, no aquí.
"""


def parse_fixtures_players(response: list, event_id: int) -> list[dict]:
    """response: lista 'response' de /fixtures/players (una entrada por equipo).

    Devuelve una fila por jugador con statistics no vacío:
      {event_id, player_id(str), player_nombre, equipo_nombre, sot, fue_titular, minutos}.
    sot = statistics[0].shots.on (null -> 0). fue_titular = not games.substitute.
    Si el feed repite un player_id en el mismo fixture (quirk de API-Football),
    se conserva la entrada con más minutos (el duplicado suele venir vacío).
    """
    filas = []
    for equipo in response:
        nombre_eq = equipo["team"]["name"]
        for p in equipo.get("players", []):
            stats = p.get("statistics") or []
            if not stats:
                continue
            st = stats[0]
            shots = st.get("shots") or {}
            games = st.get("games") or {}
            filas.append({
                "event_id": event_id,
                "player_id": str(p["player"]["id"]),
                "player_nombre": p["player"]["name"],
                "equipo_nombre": nombre_eq,
                "sot": shots.get("on") or 0,
                "fue_titular": not bool(games.get("substitute")),
                "minutos": games.get("minutes"),
            })
    por_pid = {}
    for f in filas:
        previa = por_pid.get(f["player_id"])
        if previa is None or (f["minutos"] or 0) > (previa["minutos"] or 0):
            por_pid[f["player_id"]] = f
    return list(por_pid.values())
