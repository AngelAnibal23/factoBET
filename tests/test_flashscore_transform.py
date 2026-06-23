import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flashscore_transform import parse_stats_feed, parse_results

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


# snippet real recortado de la fila Argentina-Francia (WC2022 results)
_ROW_HTML = '''
<div id="g_1_rBfk6fO7" class="event__match event__match--withRowLink event__match--twoLine" data-event-row="true">
<a href="https://www.flashscore.com/match/football/argentina-f9OppQjp/france-QkGeVG1n/?mid=rBfk6fO7" class="eventRowLink"></a>
<div class="event__time">18.12.2022<div class="event__stage"><div class="event__stage--block">Pen</div></div></div>
<div class="wcl-participant_bctDY event__homeParticipant" data-testid="wcl-matchRow-participant">
<img data-testid="wcl-participantLogo" data-size="xxs" aria-hidden="true" class="wcl-logo_UrSpU" alt="Argentina" loading="lazy" src="https://x.png">
</div>
<div class="wcl-participant_bctDY event__awayParticipant" data-testid="wcl-matchRow-participant">
<img data-testid="wcl-participantLogo" data-size="xxs" aria-hidden="true" class="wcl-logo_UrSpU" alt="France" loading="lazy" src="https://y.png">
</div></div>
'''


def test_parse_results_extracts_match():
    out = parse_results(_ROW_HTML)
    assert len(out) == 1
    m = out[0]
    assert m["event_id"] == "rBfk6fO7"
    assert m["fecha"] == "2022-12-18"
    assert m["home"] == "Argentina"
    assert m["away"] == "France"


def test_parse_results_ignores_blocks_without_teams():
    # un id sin participantes no debe romper ni emitir fila
    html = '<div id="g_1_ABCD1234" class="event__match"></div>'
    assert parse_results(html) == []
