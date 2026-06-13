import os
import requests
from dotenv import load_dotenv

load_dotenv()

headers = {"x-apisports-key": os.environ["API_FOOTBALL_KEY"]}
r = requests.get("https://v3.football.api-sports.io/leagues",
                 headers=headers, params={"country": "Peru"})
data = r.json()
remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
print(f"Requests remaining: {remaining}")
print()
for item in data.get("response", []):
    league = item["league"]
    seasons = [s["year"] for s in item.get("seasons", [])]
    print(f"ID: {league['id']} | {league['name']} | Type: {league['type']}")
    print(f"   Seasons: {seasons}")
    print()
