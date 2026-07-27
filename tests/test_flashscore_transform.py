import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flashscore_transform import parse_stats_feed, parse_results, tidy_match

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


# snippet REAL recortado de la Premier League (live, 2026-07-26): Flashscore
# renombró el contenedor de fecha, `event__time` ya no existe. Todo despues de
# `id="g_1_`.
_BLOQUE_NUEVO = (
    '44RKa9ke" data-sport="soccer" data-is-duel="true" data-is-doubles="false" '
    'class="event__match event__match--withRowLink event__match--twoLine" '
    'data-event-row="true"><a href="https://www.flashscore.com/match/football/'
    'bournemouth-OtpNdwrc/leicester-KrrdAMyI/?mid=44RKa9ke" target="_self" '
    'class="eventRowLink" title="Click for details!" aria-label="Click for '
    'details!" id="match-row-g_1_44RKa9ke"></a><div class="eventStarTouchZone">'
    '</div><span class="wcl-scores-simple-text-01_-OvnR wcl-scores_Na715 '
    'wcl-stageTime_TQm5m event__stageTime event__stageTime--date" '
    'data-testid="wcl-stageTime" data-live="false" data-blinking="false" '
    'data-highlighted="false" data-linethrough="false"><span '
    'class="wcl-scores-simple-text-01_-OvnR wcl-scores_Na715 '
    'wcl-dateContent_eEChT" data-testid="wcl-scores-simple-text-01">'
    '25.05.2025</span></span><div class="wcl-participant_bctDY '
    'event__homeParticipant" data-testid="wcl-matchRow-participant">'
    '<div class="wcl-participants_ASufu"><div class="wcl-item_DKWjj">'
    '<img crossorigin="anonymous" data-testid="wcl-participantLogo" '
    'data-size="xxs" aria-hidden="true" class="wcl-assetContainer_KJQf9 '
    'wcl-logo_UrSpU wcl-sizeXXS_CNb8a" alt="Bournemouth" loading="lazy" '
    'src="https://static.flashscore.com/res/image/data/C60HMWTH-2XyrBA7b.png">'
    '<span class="wcl-bold_NZXv6 wcl-scores-simple-text-01_-OvnR '
    'wcl-scores_Na715 wcl-name_jjfMf" data-testid="wcl-scores-simple-text-01">'
    'Bournemouth</span></div></div></div><div class="wcl-participant_bctDY '
    'event__awayParticipant" data-testid="wcl-matchRow-participant">'
    '<div class="wcl-participants_ASufu"><div class="wcl-item_DKWjj">'
    '<img crossorigin="anonymous" data-testid="wcl-participantLogo" '
    'data-size="xxs" aria-hidden="true" class="wcl-assetContainer_KJQf9 '
    'wcl-logo_UrSpU wcl-sizeXXS_CNb8a" alt="Leicester" loading="lazy" '
    'src="https://static.flashscore.com/res/image/data/CvL5rhhT-UNZg5BP0.png">'
    '<span class="wcl-scores-simple-text-01_-OvnR wcl-scores_Na715 '
    'wcl-name_jjfMf" data-testid="wcl-scores-simple-text-01">Leicester</span>'
    '</div></div>'
)


def test_parse_results_extracts_match_new_markup():
    # marcado nuevo (jul-2026): sin `event__time`, fecha en span anidado bajo
    # `event__stageTime--date`
    html = '<div id="g_1_' + _BLOQUE_NUEVO + '</div>'
    out = parse_results(html)
    assert len(out) == 1
    m = out[0]
    assert m["event_id"] == "44RKa9ke"
    assert m["fecha"] == "2025-05-25"
    assert m["home"] == "Bournemouth"
    assert m["away"] == "Leicester"


def test_parse_results_new_markup_two_matches():
    html = (
        '<div id="g_1_' + _BLOQUE_NUEVO + '</div>'
        '<div id="g_1_' + _BLOQUE_NUEVO + '</div>'
    )
    out = parse_results(html)
    assert len(out) == 2
    assert out[0]["home"] == "Bournemouth"
    assert out[1]["away"] == "Leicester"


def test_tidy_match_two_team_rows():
    meta = {"event_id": "rBfk6fO7", "fecha": "2022-12-18",
            "home": "Argentina", "away": "France"}
    stats = {
        "Corner kicks": ("4", "2"),
        "Yellow cards": ("1", "3"),
        "Total shots": ("12", "9"),
        "Shots on target": ("5", "4"),
        "Ball possession": ("54%", "46%"),
        "Expected goals (xG)": ("2.3", "1.1"),
    }
    rows = tidy_match(meta, stats, liga="INT-World Cup", season="2022")
    assert len(rows) == 2

    local = rows[0]
    assert local["equipo_flashscore"] == "Argentina"
    assert local["rival_flashscore"] == "France"
    assert local["es_local"] is True
    assert local["corners"] == 4
    assert local["crd_y"] == 1
    assert local["sot"] == 5
    assert local["possession"] == 54        # sin '%'
    assert local["xg"] == 2.3
    assert local["liga"] == "INT-World Cup"

    visit = rows[1]
    assert visit["equipo_flashscore"] == "France"
    assert visit["es_local"] is False
    assert visit["corners"] == 2
    assert visit["crd_y"] == 3


def test_tidy_match_missing_metric_is_none():
    meta = {"event_id": "x", "fecha": "2024-06-01", "home": "A", "away": "B"}
    rows = tidy_match(meta, {"Corner kicks": ("5", "1")}, liga="L", season="2024")
    assert rows[0]["corners"] == 5
    assert rows[0]["xg"] is None          # métrica ausente -> None
    assert rows[0]["sot"] is None
