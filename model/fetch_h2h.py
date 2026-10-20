"""Fetch older / extra results from the ESPN public scoreboard JSON for head-to-head history (no odds, scores and dates only).
Cached compactly in data/raw/h2h/ (private, not deployed). Existing slugs (the five leagues, Saudi, Champions League) are only
fetched for the years the main pipeline does not hold; new slugs (second tiers, other UEFA cups, domestic cups) for every year.
usage: python fetch_h2h.py [--force]
"""
import json, os, sys, time
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "raw", "h2h")
os.makedirs(OUT, exist_ok=True)
FORCE = "--force" in sys.argv

OLD = list(range(2010, 2023))  # years not held by fetch_espn.py (2023+)
EXISTING = {"eng.1": OLD, "esp.1": OLD, "fra.1": OLD, "ger.1": OLD, "ita.1": OLD, "uefa.champions": OLD, "ksa.1": [2022]}
ALL = list(range(2010, 2027))
NEW = {s: ALL for s in ["eng.2", "esp.2", "fra.2", "ger.2", "ita.2", "uefa.europa", "uefa.super_cup", "eng.fa", "eng.league_cup", "eng.charity",
                        "esp.copa_del_rey", "esp.super_cup", "fra.coupe_de_france", "fra.coupe_de_la_ligue", "fra.super_cup",
                        "ger.dfb_pokal", "ita.coppa_italia", "fifa.cwc"]}
NEW["uefa.europa.conf"] = list(range(2021, 2027))
NEW["ksa.kings.cup"] = list(range(2022, 2027))
NEW["afc.champions"] = list(range(2022, 2027))
JOBS = [(s, y) for d in (EXISTING, NEW) for s, ys in d.items() for y in ys]


def compact(e):
    c = e["competitions"][0]
    cs = {x["homeAway"]: x for x in c["competitors"]}
    if "home" not in cs or "away" not in cs:
        return None
    return dict(id=e["id"], date=e["date"], status=c["status"]["type"]["name"], stage=(e.get("season") or {}).get("slug"),
                leg=(c.get("leg") or {}).get("value"), venue=(c.get("venue") or {}).get("fullName"),
                home=cs["home"]["team"]["displayName"], home_id=cs["home"]["team"]["id"], hs=cs["home"].get("score"), hp=cs["home"].get("shootoutScore"),
                away=cs["away"]["team"]["displayName"], away_id=cs["away"]["team"]["id"], as_=cs["away"].get("score"), ap=cs["away"].get("shootoutScore"))


def job(a):
    slug, year = a
    path = os.path.join(OUT, f"{slug}_{year}.json")
    if os.path.exists(path) and not FORCE and year < dt.date.today().year:  # the current year is always refreshed
        return slug, year, -1
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    for attempt in range(4):
        try:
            r = requests.get(url, params={"dates": str(year), "limit": 1000}, timeout=60)
            if r.status_code == 200:
                ev = [x for x in (compact(e) for e in r.json().get("events", [])) if x]
                json.dump({"slug": slug, "year": year, "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "events": ev}, open(path, "w"))
                time.sleep(0.2)
                return slug, year, len(ev)
        except requests.RequestException:
            pass
        time.sleep(2 + attempt * 2)
    return slug, year, None


if __name__ == "__main__":
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(job, JOBS))
    bad = [r for r in res if r[2] is None]
    print("jobs", len(res), "fetched", sum(1 for r in res if r[2] and r[2] > 0), "cached", sum(1 for r in res if r[2] == -1), "empty", sum(1 for r in res if r[2] == 0), "FAILED", bad)


def fetch_openfootball_old():
    """openfootball football.json (public domain), seasons 2010-11 .. 2022-23: used to cross-check ESPN and fill gaps."""
    seasons = [f"{y}-{str(y + 1)[2:]}" for y in range(2010, 2023)]
    todo = [(s, l) for s in seasons for l in ["en.1", "en.2", "es.1", "es.2", "fr.1", "fr.2", "de.1", "it.1", "it.2"]]

    def one(a):
        s, l = a
        p = os.path.join(OUT, "openfootball", f"{s}_{l}.json")
        if os.path.exists(p) and not FORCE:
            return 0
        r = requests.get(f"https://raw.githubusercontent.com/openfootball/football.json/master/{s}/{l}.json", timeout=60)
        if r.status_code == 200:
            open(p, "w").write(r.text)
            return 1
        return 0
    with ThreadPoolExecutor(6) as ex:
        n = sum(ex.map(one, todo))
    print("openfootball older files fetched:", n)


if __name__ == "__main__" and "--openfootball" in sys.argv:
    fetch_openfootball_old()
