"""Score the locked prospective forecasts (PROTOCOL.md).

  python prospective/score.py                 fetch ESPN results, score every locked match that has finished, write results.json,
                                              results_table.csv (per match) and results_by_league.csv
  python prospective/score.py --offline       use the cached ESPN files in prospective/raw_espn/ (no network)
  python prospective/score.py --end 2026-12-06 --grace 2026-12-20 --out-dir DIR --cache-dir DIR --now ISO   (testing / final run overrides)

Reads manifests (self-hash verified), never writes into locks/, site/, model/ or data/. The ESPN fetch is the project's own
`model/fetch_espn.fetch`, with its cache redirected to prospective/raw_espn/ so the project's raw data folder is untouched.
Counted forecast = the earliest locked version in the manifests; metrics as defined in PROTOCOL.md.
"""
import os, sys, json, glob, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from core import rps, logloss, brier, outcome

REGISTERED_MODEL_VERSION = "ihtimal-v1.0"
ESPN_SLUG = {"spl": "ksa.1", "epl": "eng.1", "laliga": "esp.1", "ligue1": "fra.1", "ucl": "uefa.champions"}
B_BOOT, SEED = 10000, 2026
BINS = [0.0, 0.15, 0.25, 0.35, 0.45, 0.55, 0.70, 1.0000001]
NOT_PLAYED = {"STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "cancelled", "STATUS_CANCELLED": "cancelled", "STATUS_ABANDONED": "abandoned",
              "STATUS_FORFEIT": "awarded", "STATUS_SUSPENDED": "suspended"}
EXTRA = {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}
FINAL = {"STATUS_FULL_TIME", "STATUS_FINAL"}


# ------------------------------------------------------------------ statistics
def wilson(k, n, z=1.96):
    if n == 0:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(float(max(c - h, 0)), 4), round(float(min(c + h, 1)), 4)]


def boot(d, weeks=None):
    """Paired percentile bootstrap of mean(d): over matches, or over calendar weeks when `weeks` is given. 95% and Bonferroni 97.5% intervals."""
    d = np.asarray(d, float)
    n = len(d)
    out = {"n": int(n), "mean": round(float(d.mean()), 6) if n else None, "ci95": None, "ci97_5": None}
    if n < 2:
        return out
    rng = np.random.RandomState(SEED)
    if weeks is None:
        means = d[rng.randint(0, n, size=(B_BOOT, n))].mean(axis=1)
    else:
        wk = pd.Series(weeks).astype(str).values
        u, inv = np.unique(wk, return_inverse=True)
        S = np.bincount(inv, weights=d); N = np.bincount(inv).astype(float)
        k = len(u)
        if k < 2:
            return out
        idx = rng.randint(0, k, size=(B_BOOT, k))
        means = S[idx].sum(axis=1) / N[idx].sum(axis=1)
        out["n_clusters"] = int(k)
    out["ci95"] = [round(float(np.percentile(means, 2.5)), 6), round(float(np.percentile(means, 97.5)), 6)]
    out["ci97_5"] = [round(float(np.percentile(means, 1.25)), 6), round(float(np.percentile(means, 98.75)), 6)]
    return out


def verdict(b):
    """Wording rule of PROTOCOL.md section 6 (negative = model better)."""
    if not b.get("ci97_5"):
        return "n too small"
    if b["ci97_5"][1] < 0:
        return "model better (97.5% interval below zero)"
    if b["ci97_5"][0] > 0:
        return "baseline better (97.5% interval above zero)"
    return "no evidence of a difference"


# ------------------------------------------------------------------ ESPN
def fetch_feeds(leagues, years, cache, offline, now):
    import fetch_espn
    os.makedirs(cache, exist_ok=True)
    fetch_espn.RAW = cache
    feeds, meta = {}, {}
    for lg in sorted(leagues):
        for y in sorted(years):
            slug = ESPN_SLUG[lg]
            p = os.path.join(cache, "%s_%s.json" % (slug, y))
            if not offline:
                p = fetch_espn.fetch(slug, y, force=True)
            if not p or not os.path.exists(p):
                meta["%s_%s" % (slug, y)] = {"error": "no data"}
                continue
            d = json.load(open(p, encoding="utf-8"))
            feeds[(slug, y)] = d
            meta["%s_%s" % (slug, y)] = {"events": len(d["events"]), "fetched_utc": d.get("fetched_utc"), "sha256": sha256_file(p)}
    return feeds, meta


def classify(e, ev, now, grace, manual):
    """-> (status, home_goals, away_goals, note). Statuses: scored, pending, in_progress, awaiting_result, postponed, cancelled, abandoned, awarded,
    suspended, manual_review, not_found."""
    ko = parse_utc(e["kickoff_utc"])
    if e["match_id"] in manual:
        m = manual[e["match_id"]]
        return "scored", int(m["home_goals"]), int(m["away_goals"]), "manual override: %s" % m.get("source", "")
    if ev is None:
        return ("not_found" if now > ko + dt.timedelta(days=3) else "pending"), None, None, "no ESPN event with the stored id"
    comp = ev["competitions"][0]
    st = comp["status"]["type"]["name"]
    cs = {c["homeAway"]: c for c in comp["competitors"]}
    note = ""
    if st in FINAL:
        hg, ag = int(cs["home"]["score"]), int(cs["away"]["score"])
        return "scored", hg, ag, ("wasSuspended" if comp.get("wasSuspended") else "")
    if st in EXTRA:
        return "manual_review", None, None, "extra time or penalties: enter the 90-minute score in manual_overrides.json"
    if st in NOT_PLAYED:
        return NOT_PLAYED[st], None, None, st
    if st in ("STATUS_SCHEDULED", "STATUS_DELAYED"):
        return ("pending" if now <= ko else "awaiting_result"), None, None, st
    return "in_progress", None, None, st


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default="2026-12-06")
    ap.add_argument("--grace", default="2026-12-20")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out-dir", default=PROSP)
    ap.add_argument("--cache-dir", default=os.path.join(PROSP, "raw_espn"))
    ap.add_argument("--now", default=None)
    a = ap.parse_args()
    now = parse_utc(a.now) if a.now else utcnow()
    end = parse_utc(a.end + "T23:59:59Z")
    grace = parse_utc(a.grace + "T23:59:59Z")
    os.makedirs(a.out_dir, exist_ok=True)
    warnings = []

    manifests = load_manifests()                       # verifies every self-hash
    idx = locked_index(manifests)
    reg_p = os.path.join(PROSP, "PROTOCOL_REGISTRATION.json")
    proto_sha = sha256_file(os.path.join(PROSP, "PROTOCOL.md"))
    reg = json.load(open(reg_p)) if os.path.exists(reg_p) else None
    if not reg or reg["protocol_sha256"] != proto_sha:
        warnings.append("PROTOCOL.md differs from the registered version (or no registration found): check the Amendments section")
    man_path = os.path.join(PROSP, "manual_overrides.json")
    manual = {k: v for k, v in (json.load(open(man_path)) if os.path.exists(man_path) else {}).items() if not k.startswith("_")}
    tm = json.load(open(os.path.join(ROOT, "data", "team_meta.json"), encoding="utf-8"))
    id2canon = {v["id"]: k for k, v in tm.items()}

    # attestations (public copy fetched after deploy)
    attested = {}
    for p in sorted(glob.glob(os.path.join(LOCKS, "*_attest_*.json"))):
        for r in json.load(open(p, encoding="utf-8"))["checks"]:
            if r["equals_local"] and r["file_sha256_locked"] == r["public_sha256"]:
                attested.setdefault(r["match_id"], r["fetched_at_utc"])
    # version log for sensitivity S4
    vlog = collections.defaultdict(list)
    vp = os.path.join(LOCKS, "versions_log.jsonl")
    if os.path.exists(vp):
        for line in open(vp, encoding="utf-8"):
            v = json.loads(line)
            vlog[base_match_id(v["match_id"])].append(v)

    entries = [(mid, v) for mid, v in idx.items()]
    elig = [(mid, v) for mid, v in entries if parse_utc(v[2]["kickoff_utc"]) <= end]
    after = [mid for mid, v in entries if parse_utc(v[2]["kickoff_utc"]) > end]
    leagues = {v[2]["league"] for _, v in elig}
    years = {parse_utc(v[2]["kickoff_utc"]).year for _, v in elig} | {now.year}
    feeds, feed_meta = fetch_feeds(leagues, years, a.cache_dir, a.offline, now) if elig else ({}, {})
    if not a.offline:
        for k, m in feed_meta.items():
            if "error" in m:
                warnings.append("ESPN feed %s unavailable" % k)
    by_id = {}
    for (slug, y), d in feeds.items():
        for ev in d["events"]:
            by_id[ev["id"]] = ev

    rows = []
    for mid, (mpath, manifest_id, e) in sorted(elig, key=lambda x: x[1][2]["kickoff_utc"]):
        ko = parse_utc(e["kickoff_utc"])
        ev = by_id.get(str(e["espn_id"])) if e.get("espn_id") else None
        status, hg, ag, note = classify(e, ev, now, grace, manual)
        espn_ko = None
        if ev is not None:
            espn_ko = ev["date"]
            cs = {c["homeAway"]: c for c in ev["competitions"][0]["competitors"]}
            if cs["home"]["team"]["displayName"] != id2canon[e["home"]["id"]] or cs["away"]["team"]["displayName"] != id2canon[e["away"]["id"]]:
                status, hg, ag, note = "manual_review", None, None, "ESPN home/away names differ from the locked fixture"
        resched = bool(espn_ko and abs((parse_utc(espn_ko) - ko).total_seconds()) > 3600)
        if status == "scored" and parse_utc(espn_ko or e["kickoff_utc"]) > grace:
            status, note = "unresolved_after_grace", "played after the grace date"
        if status in ("postponed", "awaiting_result", "pending", "suspended", "in_progress", "not_found", "cancelled", "abandoned", "awarded") and now > grace and status != "pending":
            note = (note + "; " if note else "") + "unresolved at the grace date: excluded"
        fm, bs = e["forecast"], e["baselines"]
        r = {"match_id": e["match_id"], "manifest_id": manifest_id, "league": e["league"], "kickoff_utc": e["kickoff_utc"], "home": e["home"]["en"], "away": e["away"]["en"],
             "featured": e["featured"], "headline": e["headline"], "model_version": e["model_version"], "espn_id": e["espn_id"], "status": status,
             "espn_kickoff_utc": espn_ko, "rescheduled": resched, "note": note,
             "home_goals": hg, "away_goals": ag, "result": None if hg is None else ("H" if hg > ag else ("D" if hg == ag else "A")),
             "pm": [fm["p_home"], fm["p_draw"], fm["p_away"]], "pe": [bs["elo_only"]["p_home"], bs["elo_only"]["p_draw"], bs["elo_only"]["p_away"]],
             "pb": [bs["base_rates"]["p_home"], bs["base_rates"]["p_draw"], bs["base_rates"]["p_away"]],
             "pbase_model": [e["base_forecast"]["p_home"], e["base_forecast"]["p_draw"], e["base_forecast"]["p_away"]],
             "pick": e["forecast"]["pick"], "top_scores": e["forecast"]["top_scores"], "grid": e["forecast"]["grid_6x6"],
             "week": "%d-W%02d" % parse_utc(e["kickoff_utc"]).isocalendar()[:2]}
        pc = e.get("public_check", {})
        t_pub = pc.get("fetched_at_utc") if pc.get("equals_local") else attested.get(e["match_id"])
        r["public_evidence"] = bool(t_pub and parse_utc(t_pub) < ko)
        # S4: latest forecast seen before kick-off
        vs = [v for v in vlog.get(e["match_id"], []) if v["seen_at_utc"] < e["kickoff_utc"]]
        r["pl"] = [vs[-1]["p_home"], vs[-1]["p_draw"], vs[-1]["p_away"]] if vs else r["pm"]
        rows.append(r)

    scored = [r for r in rows if r["status"] == "scored"]
    primary = [r for r in scored if r["model_version"] == REGISTERED_MODEL_VERSION]
    other_ver = [r for r in scored if r["model_version"] != REGISTERED_MODEL_VERSION]
    if other_ver:
        warnings.append("%d scored matches carry another model_version: analysed separately, not pooled" % len(other_ver))

    def arr(rs, key):
        return np.array([r[key] for r in rs], float).reshape(-1, 3)

    def per_match(rs):
        y = np.array([0 if r["result"] == "H" else (1 if r["result"] == "D" else 2) for r in rs], int)
        out = {"y": y}
        for nm, key in (("m", "pm"), ("e", "pe"), ("b", "pb"), ("bm", "pbase_model"), ("l", "pl")):
            p = arr(rs, key)
            out["rps_" + nm], out["ll_" + nm], out["br_" + nm] = rps(p, y), logloss(p, y), brier(p, y)
            out["acc_" + nm] = (p.argmax(1) == y).astype(float)
        return out

    def compare(rs, model="m", weeks=False, with_ll=True):
        if not rs:
            return {"n": 0}
        pm = per_match(rs)
        wk = [r["week"] for r in rs] if weeks else None
        res = {"n": len(rs), "mean_rps": {"model": round(float(pm["rps_" + model].mean()), 6), "elo_only": round(float(pm["rps_e"].mean()), 6), "base_rates": round(float(pm["rps_b"].mean()), 6)}}
        res["rps_diff_vs_elo_only"] = boot(pm["rps_" + model] - pm["rps_e"], wk)
        res["rps_diff_vs_base_rates"] = boot(pm["rps_" + model] - pm["rps_b"], wk)
        res["rps_diff_vs_elo_only"]["verdict"] = verdict(res["rps_diff_vs_elo_only"])
        res["rps_diff_vs_base_rates"]["verdict"] = verdict(res["rps_diff_vs_base_rates"])
        return res

    def secondary(rs):
        if not rs:
            return {"n": 0}
        pm = per_match(rs)
        n = len(rs)
        res = {"n": n}
        for nm, key in (("model", "m"), ("elo_only", "e"), ("base_rates", "b")):
            res[nm] = {"rps": round(float(pm["rps_" + key].mean()), 6), "log_loss": round(float(pm["ll_" + key].mean()), 6), "brier": round(float(pm["br_" + key].mean()), 6),
                       "accuracy": round(float(pm["acc_" + key].mean()), 4)}
        for base, key in (("elo_only", "e"), ("base_rates", "b")):
            res["log_loss_diff_vs_" + base] = boot(pm["ll_m"] - pm["ll_" + key])
            res["brier_diff_vs_" + base] = boot(pm["br_m"] - pm["br_" + key])
        k = int(pm["acc_m"].sum())
        res["accuracy_ci95"] = wilson(k, n)
        pmv = arr(rs, "pm")
        res["share_draw_is_top_outcome"] = round(float((pmv.argmax(1) == 1).mean()), 4)
        res["actual_draw_share"] = round(float((pm["y"] == 1).mean()), 4)
        hit = [r["pick"]["score"] == [r["home_goals"], r["away_goals"]] for r in rs]
        top5 = [[r["home_goals"], r["away_goals"]] in [t["score"] for t in r["top_scores"]] for r in rs]
        res["exact_score_hit"] = {"k": int(sum(hit)), "rate": round(sum(hit) / n, 4), "ci95": wilson(int(sum(hit)), n)}
        res["actual_score_in_top5"] = {"k": int(sum(top5)), "rate": round(sum(top5) / n, 4), "ci95": wilson(int(sum(top5)), n)}
        pa = [r["grid"][r["home_goals"]][r["away_goals"]] for r in rs if r["home_goals"] <= 5 and r["away_goals"] <= 5]
        res["mean_prob_of_actual_score"] = round(float(np.mean(pa)), 6) if pa else None
        return res

    def calibration(rs):
        if not rs:
            return {}
        p = arr(rs, "pm").ravel()
        y = np.array([[r["result"] == c for c in "HDA"] for r in rs], float).ravel()
        tab = []
        for lo, hi in zip(BINS[:-1], BINS[1:]):
            m = (p >= lo) & (p < hi)
            tab.append({"bin": "%.2f to %.2f" % (lo, min(hi, 1.0)), "n": int(m.sum()), "mean_predicted": round(float(p[m].mean()), 4) if m.any() else None,
                        "observed_frequency": round(float(y[m].mean()), 4) if m.any() else None})
        pv = arr(rs, "pm")
        itl = {c: {"mean_predicted": round(float(pv[:, i].mean()), 4), "observed": round(float(np.mean([r["result"] == c for r in rs])), 4)} for i, c in enumerate("HDA")}
        return {"bins": tab, "in_the_large": itl, "note": "pooled over the three outcome probabilities of every match; descriptive, no test"}

    res = {
        "generated_at_utc": iso(now), "protocol": "prospective/PROTOCOL.md", "protocol_sha256": proto_sha,
        "protocol_registered": reg, "registered_model_version": REGISTERED_MODEL_VERSION,
        "period": {"kickoff_from": min([v[2]["kickoff_utc"] for _, v in elig], default=None), "kickoff_to_end": a.end + "T23:59:59Z", "grace_until": a.grace + "T23:59:59Z"},
        "manifests": [{"id": m["manifest_id"], "locked_at_utc": m["locked_at_utc"], "manifest_sha256": m["manifest_sha256"], "locked": len(m["matches"]), "excluded_already_kicked_off": len(m["excluded"])} for _, m in manifests],
        "espn_feeds": feed_meta, "warnings": warnings,
        "counts": {"locked_total": len(entries), "in_period": len(elig), "after_period_not_analysed": len(after),
                   "status": dict(collections.Counter(r["status"] for r in rows)),
                   "by_league_locked": dict(collections.Counter(r["league"] for r in rows)),
                   "by_league_scored": dict(collections.Counter(r["league"] for r in scored)),
                   "rescheduled": sum(r["rescheduled"] for r in rows), "manual_overrides_used": sorted(m for m in manual if m in {r["match_id"] for r in rows}),
                   "excluded_already_kicked_off_at_lock": sum(len(m["excluded"]) for _, m in manifests),
                   "publicly_evidenced_before_kickoff": sum(r["public_evidence"] for r in rows)},
        "primary": compare(primary, weeks=False),
        "secondary": secondary(primary),
        "calibration": calibration(primary),
        "sensitivity": {
            "S1_cluster_bootstrap_by_week": compare(primary, weeks=True),
            "S2_excluding_featured": compare([r for r in primary if not r["featured"]]),
            "S3_featured_scored_with_base_forecast": None,
            "S4_latest_forecast_before_kickoff": None,
            "S5_publicly_evidenced_only": compare([r for r in primary if r["public_evidence"]]),
            "S6_europe": compare([r for r in primary if r["league"] != "spl"]),
            "S6_saudi": compare([r for r in primary if r["league"] == "spl"]),
        },
        "by_league": {lg: {"compare": compare([r for r in primary if r["league"] == lg]), "secondary": secondary([r for r in primary if r["league"] == lg])}
                      for lg in ("spl", "epl", "laliga", "ligue1", "ucl") if any(r["league"] == lg for r in primary)},
        "featured_matches": [{"match_id": r["match_id"], "status": r["status"], "result": r["result"], "score": None if r["home_goals"] is None else [r["home_goals"], r["away_goals"]],
                              "p_counted": r["pm"], "p_base_model": r["pbase_model"], "p_elo_only": r["pe"], "p_base_rates": r["pb"],
                              "pick": r["pick"]} for r in rows if r["featured"]],
        "other_model_versions": compare(other_ver) if other_ver else None,
    }
    if primary:
        # S3 / S4 reuse compare with substituted forecasts
        def sub(key_from, only=None):
            rs = [dict(r) for r in primary]
            for r in rs:
                if only is None or only(r):
                    r["pm"] = r[key_from]
            return compare(rs)
        res["sensitivity"]["S3_featured_scored_with_base_forecast"] = sub("pbase_model", only=lambda r: r["featured"])
        res["sensitivity"]["S4_latest_forecast_before_kickoff"] = sub("pl")
    # ---- per-match table + by-league table
    T = []
    for r in rows:
        d = {k: r[k] for k in ("match_id", "manifest_id", "league", "kickoff_utc", "home", "away", "featured", "headline", "status", "home_goals", "away_goals", "result", "rescheduled", "public_evidence", "espn_id", "note")}
        d.update({"p_home": r["pm"][0], "p_draw": r["pm"][1], "p_away": r["pm"][2], "elo_p_home": r["pe"][0], "elo_p_draw": r["pe"][1], "elo_p_away": r["pe"][2],
                  "base_p_home": r["pb"][0], "base_p_draw": r["pb"][1], "base_p_away": r["pb"][2], "pick_outcome": r["pick"]["outcome"], "pick_score": "%d-%d" % tuple(r["pick"]["score"])})
        if r["status"] == "scored":
            pm = per_match([r])
            for nm, key in (("model", "m"), ("elo", "e"), ("base", "b")):
                d["rps_" + nm], d["log_loss_" + nm], d["brier_" + nm] = round(float(pm["rps_" + key][0]), 6), round(float(pm["ll_" + key][0]), 6), round(float(pm["br_" + key][0]), 6)
            d["correct_outcome_model"] = bool(pm["acc_m"][0])
            d["exact_score_hit"] = r["pick"]["score"] == [r["home_goals"], r["away_goals"]]
        T.append(d)
    tab = pd.DataFrame(T)
    for c in ("home_goals", "away_goals"):
        tab[c] = tab[c].astype("Int64")
    tab.to_csv(os.path.join(a.out_dir, "results_table.csv"), index=False)
    L = []
    for lg in ["spl", "epl", "laliga", "ligue1", "ucl", "ALL"]:
        rl = [r for r in rows if lg == "ALL" or r["league"] == lg]
        rs = [r for r in primary if lg == "ALL" or r["league"] == lg]
        c = compare(rs) if rs else {"n": 0}
        s = secondary(rs) if rs else {"n": 0}
        L.append({"league": lg, "locked": len(rl), "scored": len(rs), "pending_or_unresolved": len(rl) - len(rs),
                  "rps_model": c.get("mean_rps", {}).get("model"), "rps_elo_only": c.get("mean_rps", {}).get("elo_only"), "rps_base_rates": c.get("mean_rps", {}).get("base_rates"),
                  "diff_vs_elo": c.get("rps_diff_vs_elo_only", {}).get("mean"), "diff_vs_elo_ci95_lo": (c.get("rps_diff_vs_elo_only", {}).get("ci95") or [None, None])[0], "diff_vs_elo_ci95_hi": (c.get("rps_diff_vs_elo_only", {}).get("ci95") or [None, None])[1],
                  "diff_vs_base": c.get("rps_diff_vs_base_rates", {}).get("mean"), "diff_vs_base_ci95_lo": (c.get("rps_diff_vs_base_rates", {}).get("ci95") or [None, None])[0], "diff_vs_base_ci95_hi": (c.get("rps_diff_vs_base_rates", {}).get("ci95") or [None, None])[1],
                  "log_loss_model": s.get("model", {}).get("log_loss"), "brier_model": s.get("model", {}).get("brier"), "accuracy_model": s.get("model", {}).get("accuracy"),
                  "exact_score_hit_rate": s.get("exact_score_hit", {}).get("rate")})
    pd.DataFrame(L).to_csv(os.path.join(a.out_dir, "results_by_league.csv"), index=False)
    with open(os.path.join(a.out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    # ---- console summary
    print("locked %d (in period %d, after period %d) | status: %s" % (len(entries), len(elig), len(after), res["counts"]["status"]))
    for w in warnings:
        print("WARNING:", w)
    if primary:
        p = res["primary"]
        print("scored %d | mean RPS model %.4f, Elo-only %.4f, base rates %.4f" % (p["n"], p["mean_rps"]["model"], p["mean_rps"]["elo_only"], p["mean_rps"]["base_rates"]))
        for k in ("rps_diff_vs_elo_only", "rps_diff_vs_base_rates"):
            print("  %s: %s  95%% CI %s  -> %s" % (k, p[k]["mean"], p[k]["ci95"], p[k]["verdict"]))
    else:
        print("no locked match has finished yet: results.json holds the status counts only")
    print("wrote", os.path.join(a.out_dir, "results.json"), "+ results_table.csv + results_by_league.csv")


if __name__ == "__main__":
    main()
