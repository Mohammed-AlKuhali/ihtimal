"""Shared helpers for the prospective evaluation (lock_week.py, score.py).

Nothing here writes into site/, model/ or data/. Everything the prospective study writes lives in prospective/.
The baselines reuse the project's own code (model/core.py: Elo class, elo_models, ordered-logit mapping, rps/logloss/brier)
with the same parameters as the pre-registered backtest (K=20, home +65, neutral 1500 start, ordered logit fitted on pre-cutoff data only;
base rates per competition with +1/+3 smoothing, exactly as in model/backtest.py run_period).
"""
import os, sys, json, glob, hashlib, re, time, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROSP = os.path.join(ROOT, "prospective")
LOCKS = os.path.join(PROSP, "locks")
SITE_MATCHES = os.path.join(ROOT, "site", "data", "matches")
SITE_URL = "https://match-predictions.vercel.app"
sys.path.insert(0, os.path.join(ROOT, "model"))

import numpy as np
import pandas as pd


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s):
    """'2026-10-20T19:00:00Z' or '2026-10-19T19:00Z' -> aware datetime."""
    s = s.replace("Z", "")
    fmt = "%Y-%m-%dT%H:%M:%S" if s.count(":") == 2 else "%Y-%m-%dT%H:%M"
    return dt.datetime.strptime(s, fmt).replace(tzinfo=dt.timezone.utc)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def canon(o):
    """Stable JSON used only for the manifest self-hash (sorted keys, no whitespace, UTF-8)."""
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_hash(m):
    body = {k: v for k, v in m.items() if k != "manifest_sha256"}
    return sha256_bytes(canon(body).encode("utf-8"))


def base_match_id(mid):
    """A correction file `<id>_v2` is the same match; v1 (the earliest) is the one that counts."""
    return re.sub(r"_v\d+$", "", mid)


# ------------------------------------------------------------------ manifests
def manifest_paths():
    return sorted(glob.glob(os.path.join(LOCKS, "*_manifest*.json")))


def load_manifests(verify=True):
    """All manifests, oldest lock first. Raises if a manifest's self-hash no longer matches (tamper / edit check)."""
    out = []
    for p in manifest_paths():
        m = json.load(open(p, encoding="utf-8"))
        if verify and manifest_hash(m) != m.get("manifest_sha256"):
            raise SystemExit("MANIFEST CHANGED AFTER LOCK: %s (stored %s, now %s)" % (p, m.get("manifest_sha256"), manifest_hash(m)))
        out.append((p, m))
    out.sort(key=lambda pm: pm[1]["locked_at_utc"])
    return out


def locked_index(manifests):
    """match_id -> (manifest_path, manifest_id, entry). Earliest lock wins; a later duplicate is ignored."""
    idx = {}
    for p, m in manifests:
        for e in m["matches"]:
            if e["match_id"] not in idx:
                idx[e["match_id"]] = (p, m["manifest_id"], e)
    return idx


# ------------------------------------------------------------------ baselines (project's own Elo code + backtest base rates)
class Baselines:
    """Elo-only and league-base-rate probabilities at a data cutoff, using only results strictly before the cutoff.
    Pools exactly as in model/predict_live.py: Europe = EU_COMPS (incl. UCL) one closed-pool Elo; Saudi = its own pool."""

    def __init__(self):
        from core import load_matches, EU_COMPS
        self.EU_COMPS = EU_COMPS
        self.df = load_matches()
        self.cache = {}
        tm = json.load(open(os.path.join(ROOT, "data", "team_meta.json"), encoding="utf-8"))
        self.id2canon = {v["id"]: k for k, v in tm.items()}
        self.matches_csv_sha256 = sha256_file(os.path.join(ROOT, "data", "matches.csv"))

    def _pool(self, comp_key, cutoff):
        from core import elo_models
        pool = "spl" if comp_key == "spl" else "eu"
        key = (pool, cutoff)
        if key not in self.cache:
            comps = ["spl"] if pool == "spl" else self.EU_COMPS
            train = self.df[self.df.comp.isin(comps)].copy()
            train = train[train.dt < cutoff].sort_values("dt", kind="stable")
            assert train.dt.max() < cutoff
            el, (t0, t1, b), coef = elo_models(train)
            self.cache[key] = (train, el, (t0, t1, b))
        return self.cache[key]

    def predict(self, comp_key, home_id, away_id, cutoff):
        from core import ordered_logit_probs, outcome
        train, el, (t0, t1, b) = self._pool(comp_key, cutoff)
        h, a = self.id2canon[home_id], self.id2canon[away_id]
        rh, ra = el.get(h), el.get(a)
        x = np.array([(rh - ra + el.H) / 400.0])
        pe = ordered_logit_probs(t0, t1, b, x)[0]
        tr = train[train.comp == comp_key]
        o = outcome(tr.hg.values, tr.ag.values)
        fr = (np.bincount(o, minlength=3) + 1.0) / (len(o) + 3.0)
        return {
            "elo_only": {"p_home": round(float(pe[0]), 6), "p_draw": round(float(pe[1]), 6), "p_away": round(float(pe[2]), 6),
                         "elo_home": round(float(rh), 1), "elo_away": round(float(ra), 1), "home_advantage": el.H,
                         "ordered_logit": {"t0": round(float(t0), 6), "t1": round(float(t1), 6), "b": round(float(b), 6)},
                         "train_matches": int(len(train)), "pool": "spl" if comp_key == "spl" else "europe_incl_ucl"},
            "base_rates": {"p_home": round(float(fr[0]), 6), "p_draw": round(float(fr[1]), 6), "p_away": round(float(fr[2]), 6),
                           "competition": comp_key, "n_matches": int(len(o)), "smoothing": "(count+1)/(n+3)"},
        }


# ------------------------------------------------------------------ public copy
def public_check(file_name, retries=3, session=None):
    """One read-only GET of the public copy of site/data/matches/<file_name>. Returns evidence dict (never raises)."""
    import requests
    url = "%s/data/matches/%s" % (SITE_URL, file_name)
    out = {"url": url, "fetched_at_utc": None, "http_status": None, "public_sha256": None, "equals_local": None, "error": None}
    s = session or requests
    for k in range(retries):
        try:
            r = s.get(url, timeout=30, headers={"User-Agent": "ihtimal-prospective-lock/1.0 (read-only integrity check)"})
            out["fetched_at_utc"] = iso(utcnow())
            out["http_status"] = r.status_code
            if r.status_code == 200:
                out["public_sha256"] = sha256_bytes(r.content)
                out["bytes"] = len(r.content)
                out["headers"] = {h: r.headers.get(h) for h in ("date", "etag", "last-modified", "x-vercel-id", "x-vercel-cache") if r.headers.get(h)}
                try:
                    j = json.loads(r.content.decode("utf-8"))
                    out["public_headline"] = {x: j.get(x) for x in ("p_home", "p_draw", "p_away", "generated_at", "locked_at", "sha256")}
                except Exception:
                    out["public_headline"] = None
            out["error"] = None
            if r.status_code in (200, 404):
                return out
        except Exception as ex:  # network hiccup
            out["error"] = type(ex).__name__
        time.sleep(1.5 * (k + 1))
    return out
