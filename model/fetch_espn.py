"""Fetch ESPN public scoreboard JSON (calendar-year queries) for the leagues we model.
Scores and schedule times are facts. Odds fields (and anything betting-related) are DROPPED at ingestion.
Raw (stripped) responses are cached in data/raw/espn/ and are NOT published.
"""
import json, os, sys, time, gzip
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "espn")
os.makedirs(RAW, exist_ok=True)

LEAGUES = {"ksa.1": [2023, 2024, 2025, 2026, 2027],
           "eng.1": [2023, 2024, 2025, 2026],
           "esp.1": [2023, 2024, 2025, 2026],
           "fra.1": [2023, 2024, 2025, 2026],
           "ger.1": [2023, 2024, 2025, 2026],
           "ita.1": [2023, 2024, 2025, 2026],
           "uefa.champions": [2023, 2024, 2025, 2026]}

DROP_KEYS = {"odds", "pickcenter", "tickets", "links", "logo", "logos", "geoBroadcasts", "broadcasts", "broadcast", "headlines", "leaders", "statistics", "form", "records"}


def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items() if k not in DROP_KEYS}
    if isinstance(o, list):
        return [strip(x) for x in o]
    return o


def fetch(league, year, force=False):
    path = os.path.join(RAW, f"{league}_{year}.json")
    if os.path.exists(path) and not force:
        return path
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
    r = None
    for attempt in range(4):
        try:
            r = requests.get(url, params={"dates": str(year), "limit": 1000}, timeout=45)
        except requests.RequestException as ex:
            print("retry", league, year, type(ex).__name__)
            time.sleep(2 + attempt * 2)
            continue
        if r.status_code == 200:
            d = r.json()
            d = {"events": strip(d.get("events", [])), "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "league": league, "year": year}
            json.dump(d, open(path, "w"))
            return path
        time.sleep(2 + attempt * 2)
    print("FAILED", league, year, getattr(r, "status_code", None))
    return path if os.path.exists(path) else None


if __name__ == "__main__":
    force = "--force" in sys.argv
    for lg, years in LEAGUES.items():
        for y in years:
            p = fetch(lg, y, force)
            if p:
                n = len(json.load(open(p))["events"])
                print(lg, y, n)
            time.sleep(0.4)
