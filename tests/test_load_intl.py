"""Tests del loader internacional: solo parsear_args (el resto es gated e2e)."""
from load_intl_to_supabase import parsear_args


def test_parsear_args():
    # < 4 args -> modo clasico v0.1
    assert parsear_args(["load_intl_to_supabase.py"]) is None
    assert parsear_args(["load_intl_to_supabase.py", "0.5"]) is None
    assert parsear_args(["load_intl_to_supabase.py", "0.5", "25"]) is None
    # modo ELO -> tupla (float, float, str)
    res = parsear_args(["load_intl_to_supabase.py", "0.5", "25", "elo_propio"])
    assert res == (0.5, 25.0, "elo_propio")
    c, l2p, variante = res
    assert isinstance(c, float)
    assert isinstance(l2p, float)
    assert isinstance(variante, str)
