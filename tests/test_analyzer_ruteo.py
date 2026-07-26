"""Ruteo N-ligas del analyzer: mapa equipo->liga, liga del parlay y aislamiento
del Dixon-Coles por liga. Nada toca Supabase (cliente falso)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import analyzer
from validator import ValidatedParlay, ValidatedSelection, TeamMatch


# ── Cliente Supabase falso ────────────────────────────────────────────────────

class _FakeTable:
    def __init__(self, filas, registro, nombre):
        self._filas, self._reg, self._nombre = list(filas), registro, nombre

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._reg.append((self._nombre, "eq", col, val))
        self._filas = [f for f in self._filas if f.get(col) == val]
        return self

    def in_(self, col, vals):
        self._reg.append((self._nombre, "in", col, list(vals)))
        self._filas = [f for f in self._filas if f.get(col) in vals]
        return self

    def execute(self):
        return SimpleNamespace(data=self._filas)


class _FakeClient:
    def __init__(self, tablas, registro):
        self._tablas, self._reg = tablas, registro

    def table(self, nombre):
        return _FakeTable(self._tablas.get(nombre, []), self._reg, nombre)


LIGAS = [
    {"id": "L-PE", "nombre": "Liga 1 Peruana"},
    {"id": "L-EN", "nombre": "Premier League"},
    {"id": analyzer.LIGA_INTERNACIONAL_ID, "nombre": "Internacional"},
    {"id": "L-XX", "nombre": "Liga Que No Modelamos"},
]

EQUIPOS = [
    {"id": "E-ALI", "liga_id": "L-PE"},
    {"id": "E-ARS", "liga_id": "L-EN"},
    {"id": "E-FRA", "liga_id": analyzer.LIGA_INTERNACIONAL_ID},
    {"id": "E-ZZZ", "liga_id": "L-XX"},
]


def _fake_sb(monkeypatch, tablas):
    registro = []
    monkeypatch.setenv("SUPABASE_URL", "http://fake")
    monkeypatch.setenv("SUPABASE_KEY", "fake")
    monkeypatch.setattr(analyzer, "create_client",
                        lambda *_a, **_k: _FakeClient(tablas, registro))
    return registro


# ── Mapa equipo -> liga ───────────────────────────────────────────────────────

def test_mapa_equipo_liga_usa_el_nombre_de_la_liga(monkeypatch):
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert mapa["E-ALI"] == "liga1"
    assert mapa["E-ARS"] == "premier"
    assert mapa["E-FRA"] == "internacional"


def test_equipo_de_liga_no_registrada_queda_fuera_del_mapa(monkeypatch):
    """El ruteo binario mandaba TODO lo no-internacional a Liga 1. Una liga que no
    modelamos no debe heredar el modelo de otra: mejor fuera del mapa."""
    _fake_sb(monkeypatch, {"ligas": LIGAS, "equipos": EQUIPOS})
    monkeypatch.setattr(analyzer, "_cached_team_liga", None)
    monkeypatch.setattr(analyzer, "_team_liga_ts", None)

    mapa = analyzer._load_team_liga_map()

    assert "E-ZZZ" not in mapa
