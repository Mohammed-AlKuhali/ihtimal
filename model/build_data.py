"""Build the unified match table.
Sources (one source per match, dedupe by (comp, season, home, away)):
  1. openfootball football.json (public domain) for EPL/LaLiga/Ligue1/Bundesliga/SerieA when it holds a REAL full-time score
  2. ESPN public scoreboard JSON fills every match openfootball lacks (all of 2026-27 after ~20 Sep, a few 2024-25/2025-26 gaps),
     and is the sole source for the Saudi Pro League and the Champions League.
Odds are never read. Outputs: data/matches.csv (finished), data/fixtures_raw.json (scheduled), data/team_meta.json, data/build_report.json
"""
import json, glob, os, re, collections
import pandas as pd
from teams import OF_TO_CANON, strip_accents, team_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data")

OF_MAP = {"en.1": "epl", "es.1": "laliga", "fr.1": "ligue1", "de.1": "bundesliga", "it.1": "seriea"}
ESPN_COMP = {"eng.1": "epl", "esp.1": "laliga", "fra.1": "ligue1", "ger.1": "bundesliga", "ita.1": "seriea",
             "ksa.1": "spl", "uefa.champions": "ucl"}
MIN_DATE = "2023-08-01"


def season_of(date_str):
    y, m = int(date_str[:4]), int(date_str[5:7])
    return y if m >= 7 else y - 1


def norm_tokens(s):
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    stop = {"fc", "afc", "cf", "cd", "ud", "rc", "rcd", "sc", "ssc", "ac", "as", "us", "ss", "ca", "sv", "vfl", "vfb", "tsg", "de", "la",
            "club", "calcio", "balompie", "futbol", "real", "sporting"}
    return [t for t in s.split() if t not in stop and not t.isdigit()]


def load_espn():
    rows, fixtures, excluded = [], [], []
    teams = {}
    seen = set()
    for f in sorted(glob.glob(os.path.join(RAW, "espn", "*.json"))):
        d = json.load(open(f))
        lg = d["league"]
        for e in d["events"]:
            comp = e["competitions"][0]
            date = e["date"]  # UTC "2026-01-02T13:30Z"
            if date[:10] < MIN_DATE or (lg, e["id"]) in seen:
                continue
            seen.add((lg, e["id"]))
            cs = {c["homeAway"]: c for c in comp["competitors"]}
            if "home" not in cs or "away" not in cs:
                continue
            for c in cs.values():
                t = c["team"]
                teams[t["displayName"]] = (t.get("color"), t.get("alternateColor"), t.get("abbreviation"))
            st = comp["status"]["type"]["name"]
            ko = date if date.endswith(":00Z") or len(date) > 17 else date.replace("Z", ":00Z")
            rec = dict(comp=ESPN_COMP[lg], season=season_of(date[:10]), date=date[:10], kickoff_utc=ko,
                       home=cs["home"]["team"]["displayName"], away=cs["away"]["team"]["displayName"], espn_id=e["id"],
                       venue=(comp.get("venue") or {}).get("fullName"), status=st)
            if st == "STATUS_FULL_TIME":
                rec["hg"], rec["ag"] = int(cs["home"]["score"]), int(cs["away"]["score"])
                rows.append(rec)
            elif st == "STATUS_SCHEDULED":
                fixtures.append(rec)
            else:
                # AET / penalties / abandoned / postponed: not used for the regulation-time model
                excluded.append(rec)
    return rows, fixtures, excluded, teams


def load_openfootball(canon_pool):
    rows = []
    unmapped = set()
    cache = {}
    for f in sorted(glob.glob(os.path.join(RAW, "openfootball", "*_*.json"))):
        base = os.path.basename(f)
        if base.startswith("cl_"):
            continue
        season_s, lgcode = base[:-5].split("_")
        comp = OF_MAP[lgcode]
        d = json.load(open(f))
        for m in d["matches"]:
            sc = m.get("score")
            if not (isinstance(sc, dict) and sc.get("ft") and len(sc["ft"]) == 2):
                continue  # placeholder [] / [0,0] list or empty dict -> not a real result
            if m["date"] < MIN_DATE:
                continue
            out = []
            for n in (m["team1"], m["team2"]):
                if n in OF_TO_CANON:
                    out.append(OF_TO_CANON[n]); continue
                if (comp, n) not in cache:
                    nt = set(norm_tokens(n))
                    best, bs = None, 0
                    for e in canon_pool[comp]:
                        ne = set(norm_tokens(e))
                        if not ne or not nt:
                            continue
                        s = len(ne & nt) / len(ne | nt)
                        if s > bs:
                            best, bs = e, s
                    cache[(comp, n)] = (best, bs)
                best, bs = cache[(comp, n)]
                if bs < 0.99:
                    unmapped.add((comp, n, best, round(bs, 2)))
                out.append(best)
            rows.append(dict(comp=comp, season=season_of(m["date"]), date=m["date"], kickoff_utc=None, home=out[0], away=out[1],
                             hg=sc["ft"][0], ag=sc["ft"][1], espn_id=None, venue=None, status="FT"))
    return rows, unmapped


def main():
    espn_rows, espn_fix, excluded, teams = load_espn()
    pool = collections.defaultdict(set)
    for r in espn_rows + espn_fix + excluded:
        pool[r["comp"]].add(r["home"]); pool[r["comp"]].add(r["away"])
    of_rows, unmapped = load_openfootball(pool)
    assert not unmapped, f"unmapped openfootball names: {sorted(unmapped)}"
    for r in of_rows:
        r["source"] = "openfootball"
        assert r["home"] in pool[r["comp"]] and r["away"] in pool[r["comp"]], (r["comp"], r["home"], r["away"])
    for r in espn_rows:
        r["source"] = "espn"
    df_of = pd.DataFrame(of_rows)
    df_es = pd.DataFrame(espn_rows)
    key = ["comp", "season", "home", "away"]
    ov = df_of.merge(df_es, on=key, suffixes=("_of", "_es"))
    ov["date_diff"] = (pd.to_datetime(ov.date_es) - pd.to_datetime(ov.date_of)).dt.days
    bad = (ov.hg_of != ov.hg_es) | (ov.ag_of != ov.ag_es)
    report = {"overlap_matches": int(len(ov)), "overlap_score_mismatch": int(bad.sum()),
              "overlap_date_diff_gt1d": int((ov.date_diff.abs() > 1).sum()),
              "mismatch_examples": ov[bad][key + ["hg_of", "ag_of", "hg_es", "ag_es"]].head(10).to_dict("records"),
              "espn_excluded_aet_pen_abandoned": len(excluded)}
    es_only = df_es.merge(df_of[key].assign(_x=1), on=key, how="left")
    es_only = es_only[es_only._x.isna()].drop(columns="_x")
    allm = pd.concat([df_of, es_only], ignore_index=True)
    dom = allm[allm.comp.isin(["epl", "laliga", "ligue1", "bundesliga", "seriea", "spl"])]
    dups = dom[dom.duplicated(key, keep=False)]
    assert len(dups) == 0, f"duplicate domestic matches:\n{dups.head(10)}"
    allm = allm.sort_values(["date", "comp", "home"]).reset_index(drop=True)
    allm.to_csv(os.path.join(OUT, "matches.csv"), index=False)
    json.dump(espn_fix, open(os.path.join(OUT, "fixtures_raw.json"), "w"))
    tm = {}
    for k, v in teams.items():
        r = team_record(k, v[0], v[1]); r["abbr"] = v[2]; tm[k] = r
    json.dump(tm, open(os.path.join(OUT, "team_meta.json"), "w"), ensure_ascii=False, indent=1)
    cov = allm.groupby(["comp", "season"]).agg(n=("hg", "size"), last=("date", "max"),
                                                of=("source", lambda s: int((s == "openfootball").sum())),
                                                es=("source", lambda s: int((s == "espn").sum()))).reset_index()
    report["coverage"] = cov.to_dict("records")
    report["fixtures_scheduled_total"] = len(espn_fix)
    json.dump(report, open(os.path.join(OUT, "build_report.json"), "w"), indent=1, default=str)
    print(cov.to_string())
    print({k: v for k, v in report.items() if k != "coverage"})


if __name__ == "__main__":
    main()
