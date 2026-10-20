"""Record keeper.
  python score.py --init     build site/data/record.json (all pending) from the match files
  python score.py            re-pull ESPN results for the current year, score every finished match, rewrite record.json
Rules (pre-registered): the headline tally counts the `adjusted` prediction of the three LOCKED featured games (v1 only);
`base` is scored alongside; every other fixture is tracked (not locked, not in the headline tally). Misses stay on the record.
Result correct = predicted outcome (H/D/A of the headline pick) equals the actual 90-minute result. Score correct = headline pick score equals the final score."""
import sys, os, json, glob, datetime as dt
from fetch_espn import fetch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site", "data")
LEAGUE_OF = {"spl": "ksa.1", "epl": "eng.1", "laliga": "esp.1", "ligue1": "fra.1", "ucl": "uefa.champions"}
NOW = lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def outcome(h, a):
    return "H" if h > a else ("D" if h == a else "A")


def load_matches():
    return {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob(os.path.join(SITE, "matches", "*.json"))}


def row_from(o):
    base = o["base"]
    return {"match_id": o["match_id"], "competition": o["competition"]["key"], "kickoff_utc": o["kickoff_utc"],
            "home": {k: o["home"][k] for k in ("id", "ar", "en")}, "away": {k: o["away"][k] for k in ("id", "ar", "en")},
            "featured": bool(o["featured"]), "locked": bool(o["locked_at"]), "counts_in_tally": bool(o["featured"] and o["locked_at"]),
            "generated_at": o["generated_at"], "locked_at": o["locked_at"], "sha256": o["sha256"],
            "prediction": {"p_home": o["p_home"], "p_draw": o["p_draw"], "p_away": o["p_away"], "pick": o["pick"], "headline": o["headline"]},
            "base_prediction": {"p_home": base["p_home"], "p_draw": base["p_draw"], "p_away": base["p_away"], "pick": base["pick"]},
            "status": "pending", "result": None, "result_correct": None, "score_correct": None, "base_result_correct": None, "base_score_correct": None}


def main(init):
    ms = load_matches()
    path = os.path.join(SITE, "record.json")
    if init or not os.path.exists(path):
        rows = sorted((row_from(o) for o in ms.values()), key=lambda r: (not r["counts_in_tally"], r["kickoff_utc"]))
        rec = {"updated_at": None, "model_version": "ihtimal-v1.0", "rules": __doc__.strip().split("Rules (pre-registered): ")[1], "rows": rows}
    else:
        rec = json.load(open(path))
    if not init:
        # new fixtures since the last run get a row; pending, un-locked rows follow the latest pre-match file. Results and locked rows are never touched.
        have = {r["match_id"]: r for r in rec["rows"]}
        for mid, o in ms.items():
            fresh = row_from(o)
            if mid not in have:
                rec["rows"].append(fresh)
            elif have[mid]["status"] == "pending" and not have[mid]["locked"]:
                for k in ("kickoff_utc", "generated_at", "prediction", "base_prediction"):
                    have[mid][k] = fresh[k]
        # results from ESPN: map (home en/ar via match file) -> espn event by canonical names stored in data/fixtures_raw.json
        fx = json.load(open(os.path.join(ROOT, "data", "fixtures_raw.json")))
        tm = json.load(open(os.path.join(ROOT, "data", "team_meta.json")))
        id2canon = {v["id"]: k for k, v in tm.items()}
        finished = {}
        for lg in set(LEAGUE_OF.values()):
            p = fetch(lg, 2026, force=True)
            for e in json.load(open(p))["events"]:
                comp = e["competitions"][0]
                if comp["status"]["type"]["name"] != "STATUS_FULL_TIME":
                    continue
                cs = {c["homeAway"]: c for c in comp["competitors"]}
                finished[(cs["home"]["team"]["displayName"], cs["away"]["team"]["displayName"], e["date"][:10])] = (int(cs["home"]["score"]), int(cs["away"]["score"]))
        for r in rec["rows"]:
            if r["status"] == "final":
                continue
            h, a = id2canon[r["home"]["id"]], id2canon[r["away"]["id"]]
            key = (h, a, r["kickoff_utc"][:10])
            if key in finished:
                hg, ag = finished[key]
                r["result"] = {"home_goals": hg, "away_goals": ag, "outcome": outcome(hg, ag)}
                r["status"] = "final"
                r["result_correct"] = r["prediction"]["pick"]["outcome"] == outcome(hg, ag)
                r["score_correct"] = r["prediction"]["pick"]["score"] == [hg, ag]
                r["base_result_correct"] = r["base_prediction"]["pick"]["outcome"] == outcome(hg, ag)
                r["base_score_correct"] = r["base_prediction"]["pick"]["score"] == [hg, ag]
                r["scored_at"] = NOW()
        rec["updated_at"] = NOW()
    tally = [r for r in rec["rows"] if r["counts_in_tally"]]
    done = [r for r in tally if r["status"] == "final"]
    rec["tally"] = {"featured_total": len(tally), "scored": len(done), "result_correct": sum(bool(r["result_correct"]) for r in done),
                    "score_correct": sum(bool(r["score_correct"]) for r in done), "base_result_correct": sum(bool(r["base_result_correct"]) for r in done),
                    "base_score_correct": sum(bool(r["base_score_correct"]) for r in done), "counts": "adjusted headline of the locked featured games (v1 only)"}
    tr = [r for r in rec["rows"] if not r["counts_in_tally"] and r["status"] == "final"]
    rec["tracked_summary"] = {"scored": len(tr), "result_correct": sum(bool(r["result_correct"]) for r in tr), "score_correct": sum(bool(r["score_correct"]) for r in tr),
                              "note": "All other published fixtures: base model, the latest version generated before kick-off (`generated_at` on each row), not hash-locked. Shown for completeness; they are not part of the headline tally."}
    json.dump(rec, open(path, "w"), ensure_ascii=False, indent=1)
    print("record rows", len(rec["rows"]), "tally", rec["tally"])


if __name__ == "__main__":
    main("--init" in sys.argv)
