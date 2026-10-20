"""Head-to-head experiment, implementing BACKTEST_SPEC.md Amendment 2 (pre-registered) exactly.

usage: python h2h_experiment.py selfcheck | dev | holdout
  dev      2024-25 only: R per match, dev RPS / log-loss per w_h2h, decision per pool (data/h2h_experiment.json)
  holdout  2025-26, once, only for pools accepted on dev (refuses to run twice)
"""
import sys, os, json
import numpy as np
import pandas as pd
from core import *
from dc import score_grids, lambdas
from backtest import mondays, TUNE, REPORT, POOLS, bootstrap_diff, SEED
import h2h as H

WEIGHTS = [0.0, 0.05, 0.1, 0.2]
HALF_DAYS = 3 * 365.25   # recency half-life of a meeting (fixed, not tuned)
SHRINK = 5.0             # pseudo-meetings with zero residual (fixed)
NMAX = 10
THRESH = 0.0005
OUT = os.path.join(DATA, "h2h_experiment.json")


def pool_index(pool=None):
    pool = H.load_pool() if pool is None else pool
    pool = pool[pool.how == "ft"]
    idx = {}
    for r in pool.sort_values("date").itertuples():
        idx.setdefault(frozenset((r.home, r.away)), []).append((pd.Timestamp(r.date), r.home, r.away, int(r.hg), int(r.ag)))
    return idx


def compute_R(fit, space, cut, test, pidx):
    """shrunk, recency-weighted mean goal-difference residual of the last <=10 meetings strictly before `cut`, from the home team's side."""
    h_t, a_t, c_t = test.home.values, test.away.values, space.idx(test)[2]
    ent, owner = [], []
    for i in range(len(test)):
        ms = [m for m in pidx.get(frozenset((h_t[i], a_t[i])), []) if m[0] < cut][-NMAX:]
        for m in ms:
            ent.append((space.tix[m[1]], space.tix[m[2]], c_t[i], 1.0 if m[1] == h_t[i] else -1.0, m[3] - m[4], (cut - m[0]).days))
            owner.append(i)
    n = len(test)
    num, den, cnt = np.zeros(n), np.zeros(n), np.zeros(n)
    if ent:
        e = np.array(ent, dtype=float); owner = np.array(owner)
        lam, mu = lambdas(fit, e[:, 0].astype(int), e[:, 1].astype(int), e[:, 2].astype(int))
        resid = e[:, 3] * (e[:, 4] - (lam - mu))
        v = 0.5 ** (e[:, 5] / HALF_DAYS)
        np.add.at(num, owner, v * resid); np.add.at(den, owner, v); np.add.at(cnt, owner, 1)
    return num / (den + SHRINK), cnt


def run_fold_period(df, space, period, sel, pidx, pool_override=None):
    rows, xprev = [], None
    for cut in mondays(*period):
        nxt = cut + pd.Timedelta(days=7)
        test = df[(df.dt >= max(cut, period[0])) & (df.dt < nxt) & (df.dt <= period[1])]
        if len(test) == 0:
            continue
        train = df[df.dt < cut]
        assert train.dt.max() < test.dt.min(), "LEAK: training data overlaps test window"
        el, (t0, t1, b), coef = elo_models(train)
        dE = np.array([el.get(h) - el.get(a) for h, a in zip(test.home, test.away)])
        x = (dE + el.H) / 400.0
        fit = fit_at(space, train, cut, sel["xi"], sel["reg"], x0=xprev)
        xprev = fit.x
        h, a, c = space.idx(test)
        lh, la = lambdas(fit, h, a, c)
        R, cnt = compute_R(fit, space, cut, test.reset_index(drop=True), pidx)
        rec = test[["comp", "season", "date", "home", "away", "hg", "ag"]].copy().reset_index(drop=True)
        rec["fold"] = cut; rec["lh"], rec["la"], rec["rho"] = lh, la, fit.rho
        rec["elo_sup"] = coef[0] + coef[1] * x
        rec["R"], rec["n_meet"] = R, cnt
        rows.append(rec)
    return pd.concat(rows, ignore_index=True)


def probs_for(rec, sel, wh):
    w = np.where(rec.comp.values == "ucl", sel.get("w_ucl", sel["w"]), sel["w"]).astype(float)
    lh, la, rho, sup, R = rec.lh.values, rec.la.values, rec.rho.values, rec.elo_sup.values, rec.R.values
    T = lh + la
    leh = np.maximum((T + sup) / 2, 0.2); lea = np.maximum((T - sup) / 2, 0.2)
    L1 = np.exp(w * np.log(lh) + (1 - w) * np.log(leh)) * np.exp(wh * R)
    L2 = np.exp(w * np.log(la) + (1 - w) * np.log(lea)) * np.exp(-wh * R)
    G = np.zeros((len(rec), 9, 9))
    for r in np.unique(rho):
        m = rho == r
        G[m] = score_grids(L1[m], L2[m], float(r))
    ii, jj = np.indices((9, 9))
    p = np.column_stack([(G * (ii > jj)).sum((1, 2)), (G * (ii == jj)).sum((1, 2)), (G * (ii < jj)).sum((1, 2))])
    return p, L1 - L2, L1 + L2


def metrics(rec, sel, wh, mask=None):
    p, gd, tot = probs_for(rec, sel, wh)
    y = outcome(rec.hg.values, rec.ag.values)
    r, l = rps(p, y), logloss(p, y)
    return r, l, gd, tot


def check_reproduces(pool, rec, sel):
    """w_h2h = 0 must equal the tuning-grid numbers of the main backtest (same fits, same folds)."""
    g = pd.DataFrame(json.load(open(os.path.join(DATA, f"backtest_{pool}.json")))["tuning_grid"])
    r, l, _, _ = metrics(rec, sel, 0.0)
    out = {}
    if pool == "eu":
        dom = (rec.comp != "ucl").values; ucl = ~dom
        for nm, m, key, w in [("rps_dom", dom, "rps_dom", sel["w"]), ("rps_ucl", ucl, "rps_ucl", sel["w_ucl"])]:
            ref = float(g[(g.xi == sel["xi"]) & (g.reg == sel["reg"]) & (g.w == w)][key].iloc[0])
            # the grid's rps_ucl is for the UCL rows at the UCL weight; our rows already use that weight
            got = float(r[m].mean())
            out[nm] = (got, ref)
            assert abs(got - ref) < 2e-5, f"does not reproduce main backtest: {nm} {got} vs {ref}"
    else:
        ref = float(g[(g.xi == sel["xi"]) & (g.reg == sel["reg"]) & (g.w == sel["w"])]["rps_all"].iloc[0])
        got = float(r.mean()); out["rps_all"] = (got, ref)
        assert abs(got - ref) < 2e-5, f"does not reproduce main backtest: {got} vs {ref}"
    return out


def by_weight(rec, sel, mask=None):
    res = {}
    base = None
    for wh in WEIGHTS:
        r, l, _, _ = metrics(rec, sel, wh)
        if mask is not None:
            r, l = r[mask], l[mask]
        res[str(wh)] = {"rps": float(r.mean()), "ll": float(l.mean())}
    return res


def decide(bw):
    r0, l0 = bw["0.0"]["rps"], bw["0.0"]["ll"]
    ok = [w for w in WEIGHTS[1:] if bw[str(w)]["rps"] <= r0 - THRESH and bw[str(w)]["ll"] <= l0]
    if not ok:
        return {"accepted": False, "w": 0.0, "reason": f"no weight lowers dev RPS by {THRESH} with log-loss not higher"}
    top = min(bw[str(w)]["rps"] for w in ok)
    tied = [w for w in ok if bw[str(w)]["rps"] <= top + THRESH]
    return {"accepted": True, "w": float(min(tied)), "reason": "meets the acceptance rule"}


def diagnostics(rec, sel):
    r, l, gd, tot = metrics(rec, sel, 0.0)
    resid = (rec.hg.values - rec.ag.values) - gd
    R = rec.R.values
    slope = float((R * resid).sum() / (R ** 2).sum()) if (R ** 2).sum() > 0 else float("nan")
    rng = np.random.RandomState(SEED); n = len(R)
    idx = rng.randint(0, n, size=(2000, n))
    bs = (R[idx] * resid[idx]).sum(1) / np.maximum((R[idx] ** 2).sum(1), 1e-12)
    mt = float(tot.mean())
    return {"share_ge1": float((rec.n_meet >= 1).mean()), "share_ge5": float((rec.n_meet >= 5).mean()), "share_10": float((rec.n_meet >= 10).mean()),
            "mean_abs_R": float(np.abs(R).mean()), "sd_R": float(R.std()),
            "slope_gd_per_R": slope, "slope_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
            "mean_total_goals": mt, "implied_w": slope / mt, "implied_w_ci95": [float(np.percentile(bs, 2.5)) / mt, float(np.percentile(bs, 97.5)) / mt]}


def setup(pool):
    cfg = POOLS[pool]
    sel = json.load(open(os.path.join(DATA, f"backtest_{pool}.json")))["selected"]
    m = load_matches()
    df = m[m.comp.isin(cfg["comps"])].copy().sort_values("dt").reset_index(drop=True)
    return sel, df, Space(df, cfg["comps"])


def load_out():
    return json.load(open(OUT)) if os.path.exists(OUT) else {}


def dev():
    pidx = pool_index()
    out = load_out()
    out.setdefault("spec", dict(half_life_years=3, shrink=SHRINK, n_max=NMAX, weights=WEIGHTS, threshold_rps=THRESH))
    for pool in ["eu", "spl"]:
        sel, df, space = setup(pool)
        print(f"[{pool}] selected {sel}; dev 2024-25 ...", flush=True)
        rec = run_fold_period(df, space, TUNE, sel, pidx)
        rec.to_csv(os.path.join(DATA, f"h2h_dev_{pool}_matches.csv"), index=False)
        rep = check_reproduces(pool, rec, sel)
        bw = by_weight(rec, sel)
        dec = decide(bw)
        sub = (rec.n_meet >= 5).values
        out.setdefault("dev", {})[pool] = {"n": int(len(rec)), "selected_settings": sel, "reproduces_main_backtest_w0": rep, "by_weight": bw,
                                         "by_weight_ge5_meetings": {"n": int(sub.sum()), **({"by_weight": by_weight(rec, sel, sub)} if sub.sum() else {})},
                                         "decision": dec, "diagnostics": diagnostics(rec, sel)}
        print(json.dumps({k: out["dev"][pool][k] for k in ("by_weight", "decision")}, indent=1), flush=True)
    json.dump(out, open(OUT, "w"), indent=1, default=float)


def holdout():
    out = load_out()
    assert "dev" in out, "run dev first"
    pidx = pool_index()
    out.setdefault("holdout", {})
    for pool in ["eu", "spl"]:
        d = out["dev"][pool]["decision"]
        if not d["accepted"]:
            print(f"[{pool}] not accepted on dev: holdout NOT run"); continue
        assert pool not in out["holdout"], f"[{pool}] holdout was already run once; the pre-registration forbids a second run"
        sel, df, space = setup(pool)
        wh = d["w"]
        rec = run_fold_period(df, space, REPORT, sel, pidx)
        rec.to_csv(os.path.join(DATA, f"h2h_holdout_{pool}_matches.csv"), index=False)
        r0, l0, _, _ = metrics(rec, sel, 0.0); r1, l1, _, _ = metrics(rec, sel, wh)
        out["holdout"][pool] = {"n": int(len(rec)), "w_h2h": wh, "rps_w0": float(r0.mean()), "rps_w": float(r1.mean()), "ll_w0": float(l0.mean()), "ll_w": float(l1.mean()),
                                "rps_diff_boot": bootstrap_diff(r1, r0), "ll_diff_boot": bootstrap_diff(l1, l0),
                                "no_worse_than_w0": bool(r1.mean() <= r0.mean()), "diagnostics": diagnostics(rec, sel)}
        print(pool, json.dumps(out["holdout"][pool], indent=1))
    json.dump(out, open(OUT, "w"), indent=1, default=float)


def selfcheck():
    """Leak test: scramble every pool result dated on/after the fold cutoff (and the whole test week); the features must not change."""
    pool_df = H.load_pool()
    for pool, cut in [("eu", pd.Timestamp("2025-11-03")), ("spl", pd.Timestamp("2025-11-03"))]:
        sel, df, space = setup(pool)
        per = (cut, cut + pd.Timedelta(days=6))
        a = run_fold_period(df, space, per, sel, pool_index(pool_df))
        p2 = pool_df.copy()
        late = p2.date >= cut.strftime("%Y-%m-%d")
        rng = np.random.RandomState(0)
        p2.loc[late, "hg"] = rng.randint(0, 6, late.sum()); p2.loc[late, "ag"] = rng.randint(0, 6, late.sum())
        b = run_fold_period(df, space, per, sel, pool_index(p2))
        d = float(np.max(np.abs(a.R.values - b.R.values)))
        print(f"[{pool}] selfcheck: {int(late.sum())} pool results dated on/after {cut.date()} scrambled; max |R| change = {d:.2e} over {len(a)} matches (mean |R| {np.abs(a.R).mean():.3f})")
        assert d < 1e-12, "LEAK DETECTED"
    print("h2h selfcheck PASSED")


if __name__ == "__main__":
    {"selfcheck": selfcheck, "dev": dev, "holdout": holdout}[sys.argv[1]]()
