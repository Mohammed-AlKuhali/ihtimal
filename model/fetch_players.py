"""One-off helper for the featured-match adjustments: ESPN public roster + season stats (appearances, minutes, goals, assists)
for the five featured clubs, domestic league and Champions League 2026-27. Used only for the availability rule (regular = >=50% of minutes)."""
import json, os, requests, concurrent.futures as cf
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "raw", "espn", "players_featured.json")
TEAMS = {"bayern": ("ger.1", 132), "psg": ("fra.1", 160), "barcelona": ("esp.1", 83), "real-madrid": ("esp.1", 86), "arsenal": ("eng.1", 359)}


def stats(league, aid):
    out = {}
    u = f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/{league}/seasons/2026/types/1/athletes/{aid}/statistics/0"
    r = requests.get(u, timeout=30)
    if r.status_code != 200:
        return None
    for c in r.json().get("splits", {}).get("categories", []):
        for s in c["stats"]:
            out[s["name"]] = s["value"]
    return out


def main():
    res = {}
    for key, (lg, tid) in TEAMS.items():
        ro = requests.get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/teams/{tid}/roster", timeout=30).json()["athletes"]
        players = [(a["id"], a["displayName"], (a.get("position") or {}).get("abbreviation")) for a in ro]
        def job(p):
            return p, stats(lg, p[0]), stats("uefa.champions", p[0])
        with cf.ThreadPoolExecutor(8) as ex:
            rows = list(ex.map(job, players))
        res[key] = [dict(id=p[0], name=p[1], pos=p[2], league=l, ucl=u) for p, l, u in rows]
        print(key, len(rows))
    json.dump(res, open(OUT, "w"))


if __name__ == "__main__":
    main()
