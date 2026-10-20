"""Prospective lock: freeze the published forecasts of every upcoming match BEFORE kick-off.

  python prospective/lock_week.py                 lock all site/data/matches/*.json not yet locked and still in the future -> locks/<date>_manifest.json
  python prospective/lock_week.py --dry-run       show what would be locked, write nothing
  python prospective/lock_week.py --no-public     skip the public-copy GETs (e.g. when offline); they can be attested later
  python prospective/lock_week.py --attest        AFTER a deploy: GET the public copy of every locked, not-yet-public match and write
                                                  locks/<manifest>_attest_<UTC>.json (manifests themselves are never edited)

Rules (PROTOCOL.md section 4):
 * a match is locked if its kick-off is later than the lock time; matches that already kicked off are listed as excluded
 * EARLIEST LOCK WINS: a match already present in an earlier manifest is never re-locked; later refits are only logged (locks/versions_log.jsonl)
 * a `<id>_v2` correction file is the same match; v1 stays the counted forecast
 * the manifest stores the published headline probabilities (featured games: the adjusted headline), the full headline grid, the baselines
   (league base rates, Elo-only), the sha256 of the file bytes and, for featured games, the project's own content hash and original lock time
 * every manifest carries a self-hash (manifest_sha256); score.py and this script refuse to run if any manifest was edited afterwards
"""
import os, sys, json, glob, time, argparse, platform
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

LEAGUE_NAMES = {"spl": "Saudi Pro League", "epl": "Premier League", "laliga": "La Liga", "ligue1": "Ligue 1", "ucl": "UEFA Champions League"}


def load_site_files():
    out = {}
    for p in sorted(glob.glob(os.path.join(SITE_MATCHES, "*.json"))):
        b = open(p, "rb").read()
        out[os.path.basename(p)] = (p, b, json.loads(b.decode("utf-8")))
    return out


def espn_ids():
    fx = json.load(open(os.path.join(ROOT, "data", "fixtures_raw.json"), encoding="utf-8"))
    tm = json.load(open(os.path.join(ROOT, "data", "team_meta.json"), encoding="utf-8"))
    return {(x["date"], tm[x["home"]]["id"], tm[x["away"]]["id"]): x["espn_id"] for x in fx if x["home"] in tm and x["away"] in tm}


def featured_lock_info():
    p = os.path.join(ROOT, "site", "data", "locks.json")
    if not os.path.exists(p):
        return {}
    return {m["match_id"]: m for m in json.load(open(p, encoding="utf-8"))["matches"]}


def entry_for(fname, path, raw, o, now, bl, eid, flocks):
    from lockutil import sha256_of
    head = o[o["headline"]] if o.get("headline") in ("base", "adjusted") and o.get(o["headline"]) else None
    assert head is not None, "no headline block in " + fname
    for k in ("p_home", "p_draw", "p_away"):
        assert abs(o[k] - head[k]) < 1e-9, "top-level %s differs from the %s block in %s" % (k, o["headline"], fname)
    ko = parse_utc(o["kickoff_utc"])
    cutoff = pd.Timestamp(o["data_cutoff_utc"].replace("Z", "").split("T")[0])
    b = bl.predict(o["competition"]["key"], o["home"]["id"], o["away"]["id"], cutoff)
    # validation: our recomputed Elo ratings must equal the ones printed in the match file
    elo_ok = abs(b["elo_only"]["elo_home"] - o["elo"]["home"]) < 0.051 and abs(b["elo_only"]["elo_away"] - o["elo"]["away"]) < 0.051
    e = {
        "match_id": o["match_id"], "file": fname, "espn_id": eid,
        "league": o["competition"]["key"], "competition_en": o["competition"]["en"], "stage": o["competition"].get("stage") or None,
        "kickoff_utc": o["kickoff_utc"], "home": {k: o["home"][k] for k in ("id", "en", "ar")}, "away": {k: o["away"][k] for k in ("id", "en", "ar")},
        "featured": bool(o["featured"]), "headline": o["headline"], "model_version": o["model_version"],
        "data_cutoff_utc": o["data_cutoff_utc"], "generated_at": o["generated_at"], "lead_time_hours": round((ko - now).total_seconds() / 3600.0, 2),
        "forecast": {"p_home": o["p_home"], "p_draw": o["p_draw"], "p_away": o["p_away"], "pick": o["pick"], "top_scores": o["top_scores"],
                     "lambda_home": o["lambda_home"], "lambda_away": o["lambda_away"], "rho": o["rho"], "grid_6x6": o["grid_6x6"]},
        "base_forecast": {k: o["base"][k] for k in ("p_home", "p_draw", "p_away", "pick", "lambda_home", "lambda_away")},
        "baselines": b, "baseline_elo_matches_file": bool(elo_ok),
        "file_sha256": sha256_bytes(raw), "file_bytes": len(raw),
    }
    if o["featured"]:
        fl = flocks.get(o["match_id"])
        e["original_lock"] = {"locked_at_utc": o.get("locked_at"), "content_sha256": o.get("sha256"),
                              "content_sha256_recomputed": sha256_of(o), "content_hash_ok": sha256_of(o) == o.get("sha256"),
                              "in_locks_json": bool(fl and fl["sha256"] == o.get("sha256") and fl["locked_at_utc"] == o.get("locked_at"))}
    return e


def lock(args):
    now = utcnow()
    manifests = load_manifests()                     # verifies self-hashes
    already = locked_index(manifests)
    site = load_site_files()
    ids = espn_ids()
    bl = Baselines()
    flocks = featured_lock_info()
    entries, excluded, skipped, versions = [], [], [], []
    for fname, (path, raw, o) in site.items():
        mid = base_match_id(o["match_id"])
        ko = parse_utc(o["kickoff_utc"])
        fsha = sha256_bytes(raw)
        versions.append({"seen_at_utc": iso(now), "match_id": o["match_id"], "file": fname, "file_sha256": fsha, "generated_at": o["generated_at"],
                         "p_home": o["p_home"], "p_draw": o["p_draw"], "p_away": o["p_away"], "kickoff_utc": o["kickoff_utc"]})
        if mid in already or o["match_id"] in already:
            skipped.append({"match_id": o["match_id"], "locked_in": already.get(mid, already.get(o["match_id"]))[1],
                            "changed_since_lock": already.get(mid, already.get(o["match_id"]))[2]["file_sha256"] != fsha})
            continue
        if o["match_id"] != mid:                      # a _vN correction of a match that was never locked: not counted, just logged
            skipped.append({"match_id": o["match_id"], "reason": "correction_file_of_unlocked_match"})
            continue
        if ko <= now:
            excluded.append({"match_id": o["match_id"], "league": o["competition"]["key"], "kickoff_utc": o["kickoff_utc"],
                             "reason": "kicked off at or before the lock time; not counted", "file_sha256": fsha})
            continue
        eid = ids.get((o["kickoff_utc"][:10], o["home"]["id"], o["away"]["id"]))
        entries.append(entry_for(fname, path, raw, o, now, bl, eid, flocks))
    entries.sort(key=lambda e: (e["kickoff_utc"], e["match_id"]))
    by_league = {}
    for e in entries:
        by_league[e["league"]] = by_league.get(e["league"], 0) + 1
    if not args.dry_run:                              # append-only change log: one line per (file, content) the first time it is seen
        vp = os.path.join(LOCKS, "versions_log.jsonl")
        seen = set()
        if os.path.exists(vp):
            seen = {(v["file"], v["file_sha256"]) for v in map(json.loads, open(vp, encoding="utf-8"))}
        with open(vp, "a", encoding="utf-8") as f:
            for v in versions:
                if (v["file"], v["file_sha256"]) not in seen:
                    f.write(json.dumps(v, ensure_ascii=False) + "\n")
    print("to lock: %d | excluded (already kicked off): %d | already locked earlier: %d" % (len(entries), len(excluded), len(skipped)))
    print("by league:", by_league)
    bad = [e["match_id"] for e in entries if not e["baseline_elo_matches_file"]]
    if bad:
        print("WARNING recomputed Elo differs from the file's Elo for", bad)
    if entries:
        print("earliest kickoff", entries[0]["kickoff_utc"], "| latest", max(e["kickoff_utc"] for e in entries))
    if args.dry_run or not entries:
        if not entries:
            print("nothing new to lock")
        return
    # ---- public copies (read-only GETs, 1 per file, small pause)
    if not args.no_public:
        import requests
        sess = requests.Session()
        for i, e in enumerate(entries):
            pc = public_check(e["file"], session=sess)
            pc["equals_local"] = (pc["public_sha256"] == e["file_sha256"]) if pc["public_sha256"] else False
            e["public_check"] = pc
            time.sleep(0.4)
        n_eq = sum(1 for e in entries if e["public_check"]["equals_local"])
        print("public copy sha256 equals local: %d / %d" % (n_eq, len(entries)))
    else:
        for e in entries:
            e["public_check"] = {"skipped": True}
    stamp = now.strftime("%Y-%m-%d")
    mid_ = stamp
    path = os.path.join(LOCKS, "%s_manifest.json" % stamp)
    if os.path.exists(path):
        mid_ = now.strftime("%Y-%m-%dT%H%MZ")
        path = os.path.join(LOCKS, "%s_manifest.json" % now.strftime("%Y-%m-%d_%H%MZ"))
    code = {f: sha256_file(os.path.join(ROOT, f)) for f in ("prospective/lock_week.py", "prospective/common.py", "model/core.py", "model/dc.py", "model/lockutil.py")}
    man = {
        "manifest_version": 1, "manifest_id": mid_, "locked_at_utc": iso(now),
        "protocol": "prospective/PROTOCOL.md",
        "rule": "Earliest lock wins. Counted forecast = the published headline probabilities in this manifest (featured games: adjusted). Kick-off must be later than locked_at_utc.",
        "site_url": SITE_URL,
        "counts": {"locked": len(entries), "by_league": by_league, "excluded_already_kicked_off": len(excluded), "skipped_already_locked_earlier": len(skipped),
                   "earliest_kickoff_utc": entries[0]["kickoff_utc"], "latest_kickoff_utc": max(e["kickoff_utc"] for e in entries),
                   "public_copy_sha256_equals_local": (sum(1 for e in entries if e["public_check"].get("equals_local")) if not args.no_public else None)},
        "baseline_inputs": {"matches_csv_sha256": bl.matches_csv_sha256, "note": "Elo-only and base rates recomputed from results strictly before each match's data_cutoff_utc with the project's own code (model/core.py, parameters of the pre-registered backtest)."},
        "code_sha256": code, "environment": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "matches": entries, "excluded": excluded, "skipped_already_locked": skipped,
    }
    man["manifest_sha256"] = manifest_hash(man)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    os.chmod(path, 0o444)                              # read-only on disk (a convenience, the self-hash is the real check)
    print("WROTE", path)
    print("manifest_sha256", man["manifest_sha256"])


def attest(args):
    """After a deploy: fetch the public copy of every locked match that is not yet attested as public-and-equal. Appends a new file; edits nothing."""
    import requests
    now = utcnow()
    manifests = load_manifests()
    done = set()
    for p in glob.glob(os.path.join(LOCKS, "*_attest_*.json")):
        a = json.load(open(p, encoding="utf-8"))
        done |= {r["match_id"] for r in a["checks"] if r["equals_local"]}
    rows = []
    sess = requests.Session()
    for p, m in manifests:
        for e in m["matches"]:
            if parse_utc(e["kickoff_utc"]) <= now or e["match_id"] in done or e.get("public_check", {}).get("equals_local"):
                continue
            pc = public_check(e["file"], session=sess)
            pc["equals_local"] = (pc["public_sha256"] == e["file_sha256"]) if pc["public_sha256"] else False
            pc.update({"match_id": e["match_id"], "manifest_id": m["manifest_id"], "file_sha256_locked": e["file_sha256"]})
            rows.append(pc)
            time.sleep(0.4)
    if not rows:
        print("nothing to attest")
        return
    out = {"attested_at_utc": iso(now), "note": "Public copies fetched after deploy. Evidence only; manifests are not modified.", "checks": rows}
    out["attest_sha256"] = sha256_bytes(canon({k: v for k, v in out.items() if k != "attest_sha256"}).encode("utf-8"))
    path = os.path.join(LOCKS, "%s_attest_%s.json" % (load_manifests()[-1][1]["manifest_id"].replace(":", ""), now.strftime("%Y%m%dT%H%M%SZ")))
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("attested %d files, equal to the locked bytes: %d -> %s" % (len(rows), sum(r["equals_local"] for r in rows), path))
    print("NOT equal (refit or not yet deployed):", [r["match_id"] for r in rows if not r["equals_local"]][:20])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-public", action="store_true")
    ap.add_argument("--attest", action="store_true")
    a = ap.parse_args()
    attest(a) if a.attest else lock(a)
