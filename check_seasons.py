"""Investigates why some seasons return 0 matches."""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

headers = {"x-apisports-key": os.environ["API_FOOTBALL_KEY"]}

def get(endpoint, params):
    r = requests.get(f"https://v3.football.api-sports.io/{endpoint}",
                     headers=headers, params=params, timeout=15)
    data = r.json()
    remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
    return data, remaining

print("=== Checking available seasons for ID 281 ===\n")
data, rem = get("leagues", {"id": 281})
item = data["response"][0]
seasons = item.get("seasons", [])
print(f"All seasons in API for ID 281:")
for s in seasons:
    print(f"  {s['year']} | current={s['current']} | coverage={s.get('coverage', {})}")

print(f"\nRemaining: {rem}")

print("\n=== Testing season 2026 (current) ===")
data, rem = get("fixtures", {"league": 281, "season": 2026})
total = len(data.get("response", []))
finished = sum(1 for f in data.get("response", []) if f["fixture"]["status"]["short"] == "FT")
print(f"2026: {total} total, {finished} finished | Remaining: {rem}")

print("\n=== Testing season 2021 raw response ===")
data, rem = get("fixtures", {"league": 281, "season": 2021})
print(f"Response count: {len(data.get('response', []))}")
if data.get("errors"):
    print(f"Errors: {data['errors']}")
print(f"Remaining: {rem}")

print("\n=== Testing season 2019 ===")
data, rem = get("fixtures", {"league": 281, "season": 2019})
total = len(data.get("response", []))
finished = sum(1 for f in data.get("response", []) if f["fixture"]["status"]["short"] == "FT")
print(f"2019: {total} total, {finished} finished | Remaining: {rem}")
