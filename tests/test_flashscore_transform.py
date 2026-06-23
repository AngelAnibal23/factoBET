import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flashscore_transform import parse_stats_feed

SEP_F = "¬"   # ¬
SEP_KV = "÷"  # ÷


def _feed(rows):
    return SEP_F.join(f"{k}{SEP_KV}{v}" for k, v in rows)


def test_parse_stats_feed_basic():
    feed = _feed([
        ("SG", "Ball possession"), ("SH", "40%"), ("SI", "60%"),
        ("SG", "Corner kicks"), ("SH", "4"), ("SI", "2"),
        ("SG", "Yellow cards"), ("SH", "1"), ("SI", "3"),
    ])
    out = parse_stats_feed(feed)
    assert out["Ball possession"] == ("40%", "60%")
    assert out["Corner kicks"] == ("4", "2")
    assert out["Yellow cards"] == ("1", "3")


def test_parse_stats_feed_keeps_first_occurrence_per_period():
    # La misma métrica se repite por período; debe quedar la PRIMERA (full match).
    feed = _feed([
        ("SG", "Total shots"), ("SH", "12"), ("SI", "9"),   # full match
        ("SG", "Total shots"), ("SH", "5"), ("SI", "4"),    # 1er tiempo
    ])
    out = parse_stats_feed(feed)
    assert out["Total shots"] == ("12", "9")
