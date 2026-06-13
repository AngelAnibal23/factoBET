"""
Phase 0 — Data Audit
Queries API-Football for Liga 1 Peruana (ID 268) seasons 2021-2026.
Answers: matches available, field completeness, data quality.
Output: prints report + saves data_audit_report.md
"""

import os
import requests
import json
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["API_FOOTBALL_KEY"]
BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}
LIGA1_ID = 281  # 268 = Uruguay; 281 = Peru Primera Division (corrected)
SEASONS = [2022, 2023, 2024]  # free plan only covers 2022-2024


def get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
    print(f"  [API] GET /{endpoint} | params={params} | remaining={remaining} req")
    return data, int(remaining) if remaining != "?" else 999


def check_field(value):
    return value is not None and value != "" and value != []


# ── 1. Verify connection ──────────────────────────────────────────────────────
print("\n" + "="*60)
print("HELPBETOR — PHASE 0 DATA AUDIT")
print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("="*60)

print("\n[1/5] Testing API connection...")
data, remaining = get("status")
account = data.get("response", {}).get("account", {})
sub = data.get("response", {}).get("subscription", {})
print(f"  Account  : {account.get('email', 'N/A')}")
print(f"  Plan     : {sub.get('plan', 'N/A')}")
print(f"  Active   : {sub.get('active', False)}")
print(f"  Requests remaining today: {remaining}")

if remaining < 20:
    print("\n  WARNING: Less than 20 requests remaining. Audit may be incomplete.")

# ── 2. League info ────────────────────────────────────────────────────────────
print("\n[2/5] Getting Liga 1 Peruana info...")
data, remaining = get("leagues", {"id": LIGA1_ID, "current": "true"})
leagues = data.get("response", [])

if not leagues:
    print("  ERROR: Liga 1 not found. Check league ID.")
else:
    league = leagues[0]
    print(f"  Name    : {league['league']['name']}")
    print(f"  Country : {league['country']['name']}")
    print(f"  Type    : {league['league']['type']}")
    seasons_available = [s["year"] for s in league.get("seasons", [])]
    print(f"  Seasons in API: {seasons_available}")

# ── 3. Matches per season ─────────────────────────────────────────────────────
print("\n[3/5] Counting matches per season...")

season_summary = {}
all_fixtures = {}

for season in SEASONS:
    if remaining < 5:
        print(f"  SKIPPING {season} — not enough API requests left ({remaining})")
        continue

    data, remaining = get("fixtures", {"league": LIGA1_ID, "season": season})
    fixtures = data.get("response", [])
    total = len(fixtures)

    finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
    n_finished = len(finished)

    season_summary[season] = {
        "total": total,
        "finished": n_finished,
        "scheduled": total - n_finished,
    }
    all_fixtures[season] = fixtures
    print(f"  {season}: {total} total  |  {n_finished} finished  |  {total-n_finished} pending")
    time.sleep(0.3)

# ── 4. Field completeness on finished matches ─────────────────────────────────
print("\n[4/5] Checking field completeness (finished matches)...")

completeness = {}

for season, fixtures in all_fixtures.items():
    finished = [f for f in fixtures if f["fixture"]["status"]["short"] == "FT"]
    if not finished:
        continue

    n = len(finished)
    counts = {
        "goals_home":       0,
        "goals_away":       0,
        "date":             0,
        "venue":            0,
        "referee":          0,
        "halftime_score":   0,
        "score_fulltime":   0,
    }

    for f in finished:
        fix = f["fixture"]
        goals = f.get("goals", {})
        score = f.get("score", {})

        if check_field(goals.get("home")):            counts["goals_home"] += 1
        if check_field(goals.get("away")):            counts["goals_away"] += 1
        if check_field(fix.get("date")):              counts["date"] += 1
        if check_field(fix.get("venue", {}).get("name")): counts["venue"] += 1
        if check_field(fix.get("referee")):           counts["referee"] += 1
        ht = score.get("halftime", {})
        if check_field(ht.get("home")) and check_field(ht.get("away")):
            counts["halftime_score"] += 1
        ft = score.get("fulltime", {})
        if check_field(ft.get("home")) and check_field(ft.get("away")):
            counts["score_fulltime"] += 1

    completeness[season] = {
        field: f"{(count/n*100):.1f}%" for field, count in counts.items()
    }
    completeness[season]["_total_finished"] = n
    print(f"\n  Season {season} ({n} finished matches):")
    for field, pct in completeness[season].items():
        if not field.startswith("_"):
            print(f"    {field:<20}: {pct}")

# ── 5. Sample 5 recent matches — check stats availability ────────────────────
print("\n[5/5] Sampling 5 recent matches for detailed stats...")

sample_results = []
sample_fixtures = []

for season in [2025, 2024]:
    if season in all_fixtures:
        finished = [f for f in all_fixtures[season]
                    if f["fixture"]["status"]["short"] == "FT"]
        sample_fixtures.extend(finished[:3])
    if len(sample_fixtures) >= 5:
        break

sample_fixtures = sample_fixtures[:5]

for f in sample_fixtures:
    fid = f["fixture"]["id"]
    home = f["teams"]["home"]["name"]
    away = f["teams"]["away"]["name"]
    gh = f["goals"]["home"]
    ga = f["goals"]["away"]

    if remaining < 3:
        print(f"  Skipping stats for {home} vs {away} — API limit")
        sample_results.append({"fixture_id": fid, "match": f"{home} vs {away}",
                                "score": f"{gh}-{ga}", "stats": "SKIPPED"})
        continue

    data, remaining = get("fixtures/statistics", {"fixture": fid})
    stats = data.get("response", [])
    has_stats = len(stats) > 0

    stats_fields = {}
    if has_stats:
        for team_stats in stats:
            team_name = team_stats["team"]["name"]
            for stat in team_stats.get("statistics", []):
                stats_fields[stat["type"]] = stat["value"]

    sample_results.append({
        "fixture_id": fid,
        "match": f"{home} vs {away}",
        "score": f"{gh}-{ga}",
        "has_stats": has_stats,
        "n_stat_types": len(stats_fields) // 2 if has_stats else 0,
        "shots_on_goal": stats_fields.get("Shots on Goal"),
        "total_shots": stats_fields.get("Total Shots"),
        "possession": stats_fields.get("Ball Possession"),
        "xG": stats_fields.get("expected_goals"),
    })

    flag_xg = "YES" if stats_fields.get("expected_goals") else "NO"
    print(f"  {home} vs {away}  [{gh}-{ga}]")
    print(f"    Has stats: {has_stats} | xG available: {flag_xg}")
    if has_stats:
        print(f"    Shots on goal: {stats_fields.get('Shots on Goal')} | "
              f"Possession: {stats_fields.get('Ball Possession')}")
    time.sleep(0.3)

# ── Build report ──────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("GENERATING data_audit_report.md ...")
print("="*60)

lines = []
lines.append(f"# HELPBETOR — DATA AUDIT REPORT")
lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
lines.append(f"**League:** Liga 1 Peruana (API-Football ID: {LIGA1_ID})")
lines.append(f"**API requests remaining after audit:** {remaining}")
lines.append("")

lines.append("## 1. Matches Available Per Season")
lines.append("")
lines.append("| Season | Total | Finished | Pending |")
lines.append("|--------|-------|----------|---------|")
for season, s in season_summary.items():
    lines.append(f"| {season} | {s['total']} | {s['finished']} | {s['scheduled']} |")
total_finished = sum(s["finished"] for s in season_summary.values())
lines.append(f"| **TOTAL** | | **{total_finished}** | |")
lines.append("")

lines.append("## 2. Field Completeness (Finished Matches)")
lines.append("")
for season, fields in completeness.items():
    n = fields.get("_total_finished", 0)
    lines.append(f"### Season {season} ({n} matches)")
    lines.append("| Field | Completeness |")
    lines.append("|-------|-------------|")
    for field, pct in fields.items():
        if not field.startswith("_"):
            lines.append(f"| {field} | {pct} |")
    lines.append("")

lines.append("## 3. Stats Availability (Sample Matches)")
lines.append("")
lines.append("| Match | Score | Has Stats | xG Available | Shots on Goal | Possession |")
lines.append("|-------|-------|-----------|--------------|---------------|------------|")
for r in sample_results:
    xg = "YES" if r.get("xG") else "NO"
    stats_flag = "YES" if r.get("has_stats") else "NO"
    lines.append(f"| {r['match']} | {r['score']} | {stats_flag} | {xg} | "
                 f"{r.get('shots_on_goal','N/A')} | {r.get('possession','N/A')} |")
lines.append("")

lines.append("## 4. Key Findings & Feasibility")
lines.append("")

total = sum(s["finished"] for s in season_summary.values())
if total >= 1000:
    lines.append(f"- **Data volume:** {total} finished matches across {len(season_summary)} seasons. SUFFICIENT for Dixon-Coles.")
elif total >= 500:
    lines.append(f"- **Data volume:** {total} finished matches. MARGINAL — proceed with v0.1 Poisson first.")
else:
    lines.append(f"- **Data volume:** {total} finished matches. INSUFFICIENT — expand data sources before modeling.")

xg_available = any(r.get("xG") for r in sample_results)
if xg_available:
    lines.append("- **xG data:** AVAILABLE in API-Football for Liga 1. Can use in v1.0.")
else:
    lines.append("- **xG data:** NOT AVAILABLE in API-Football for Liga 1. Confirmed: use raw goals for v1.0 lambdas.")

has_stats_count = sum(1 for r in sample_results if r.get("has_stats"))
if has_stats_count >= 3:
    lines.append(f"- **Match stats:** Available in {has_stats_count}/{len(sample_results)} sampled matches. Shots/possession data present.")
else:
    lines.append(f"- **Match stats:** Only {has_stats_count}/{len(sample_results)} sampled matches have stats. May affect model features.")

lines.append("")
lines.append("## 5. Next Steps")
lines.append("")
lines.append("- [ ] Phase 1: Build OCR module (Gemini Vision → JSON)")
lines.append("- [ ] Phase 1: Implement validation layer")
lines.append("- [ ] Phase 1: Statistical engine v0.1 (Plain Poisson baseline)")
lines.append("- [ ] Phase 1: Supabase schema setup")
lines.append("- [ ] Phase 2: Dixon-Coles v0.2 once v0.1 Brier Score is established")

report_text = "\n".join(lines)

with open("C:/Users/WIN10/Desktop/helpBETOR/data_audit_report.md", "w", encoding="utf-8") as f:
    f.write(report_text)

print("\nDone. Report saved to data_audit_report.md")
print(f"API requests remaining: {remaining}")
