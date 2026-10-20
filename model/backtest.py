"""Walk-forward backtest, implementing BACKTEST_SPEC.md (pre-registered) exactly.

usage: python backtest.py eu|spl|selfcheck
Writes data/backtest_<pool>.json (+ per-match parquet-ish csv) consumed by write_backtest_md.py and the live pipeline.
"""
import sys, json, itertools, time
import numpy as np
import pandas as pd
from core import *
from dc import score_grids, wdl

SEED = 2026
W_GRID = [1.0, 0.8, 0.6, 0.3]
POOLS = {
    "eu": dict(comps=EU_COMPS, xi=[0.0010, 0.0019, 0.0030], reg=[3.0, 8.0]),
    "spl": dict(comps=["spl"], xi=[0.0030, 0.0046, 0.0077, 0.0120], reg=[3.0, 8.0]),
}
TUNE = (pd.Timestamp("2024-08-01"), pd.Timestamp("2025-07-31"))
REPORT = (pd.Timestamp("2025-08-01"), pd.Timestamp("2026-07-31"))
CURRENT = (pd.Timestamp("2026-08-01"), pd.Timestamp("2026-10-18"))


def mondays(start, end):
    d = start - pd.Timedelta(days=start.weekday())
    while d <= end:
        yield d
        d += pd.Timedelta(days=7)


def run_period(pool, df, space, period, configs, verbose=True):
    """For each weekly fold in `period`, fit every (xi, reg) config + Elo leg + base rates on data strictly before the fold.
    Returns per-match DataFrame with columns for each config's lambdas and the baselines."""
    rows = []
    xprev = {}
    t0 = time.time()
    for cut in mondays(*period):
        nxt = cut + pd.Timedelta(days=7)
        test = df[(df.dt >= max(cut, period[0])) & (df.dt < nxt) & (df.dt <= period[1])]
        if len(test) == 0:
            continue
        train = df[df.dt < cut]
        assert train.dt.max() < test.dt.min(), "LEAK: training data overlaps test window"
        # --- Elo leg (everything fitted on `train` only)
        el, (t0_, t1_, b), coef = elo_models(train)
        dE = np.array([el.get(h) - el.get(a) for h, a in zip(test.home, test.away)])
        x = (dE + el.H) / 400.0
        p_elo = ordered_logit_probs(t0_, t1_, b, x)
        sup = coef[0] + coef[1] * x
        # --- base rates per competition from `train`
        base = np.zeros((len(test), 3))
        for comp in test.comp.unique():
            tr = train[train.comp == comp]
            o = outcome(tr.hg.values, tr.ag.values)
            fr = (np.bincount(o, minlength=3) + 1.0) / (len(o) + 3.0)
            base[(test.comp == comp).values] = fr
        rec = test[["comp", "season", "date", "home", "away", "hg", "ag"]].copy().reset_index(drop=True)
        rec["fold"] = cut
        rec["p_elo_h"], rec["p_elo_d"], rec["p_elo_a"] = p_elo.T
        rec["p_base_h"], rec["p_base_d"], rec["p_base_a"] = base.T
        rec["elo_sup"] = sup
        h, a, c = space.idx(test)
        for (xi, reg) in configs:
            # leakage guard: DC fit receives the same `train` frame
            fit = fit_at(space, train, cut, xi, reg, x0=xprev.get((xi, reg)))
            assert fit.max_train_date < test.dt.min()
            xprev[(xi, reg)] = fit.x
            lh, la = lambdas(fit, h, a, c)
            tag = f"{xi}_{reg}"
            rec[f"lh_{tag}"], rec[f"la_{tag}"], rec[f"rho_{tag}"] = lh, la, fit.rho
        rows.append(rec)
        if verbose and len(rows) % 10 == 0:
            print(f"  fold {cut.date()} done ({len(rows)} folds, {time.time() - t0:.0f}s)", flush=True)
    return pd.concat(rows, ignore_index=True)


def blended_grids(rec, tag, w):
    lh, la, rho = rec[f"lh_{tag}"].values, rec[f"la_{tag}"].values, rec[f"rho_{tag}"].values
    T = lh + la
    sup = rec["elo_sup"].values
    leh = np.maximum((T + sup) / 2, 0.2); lea = np.maximum((T - sup) / 2, 0.2)
    L1 = np.exp(w * np.log(lh) + (1 - w) * np.log(leh))
    L2 = np.exp(w * np.log(la) + (1 - w) * np.log(lea))
    # rho differs per fold; group by rho value
    G = np.zeros((len(rec), 9, 9))
    for r in np.unique(rho):
        m = rho == r
        G[m] = score_grids(L1[m], L2[m], float(r))
    return G


def eval_grids(rec, G):
    """metrics from grids; returns DataFrame of per-match metrics."""
    n = len(rec)
    p = np.stack([np.array([np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()]) for g in G])
    y = outcome(rec.hg.values, rec.ag.values)
    out = pd.DataFrame({"rps": rps(p, y), "ll": logloss(p, y), "brier": brier(p, y)})
    out["acc"] = (p.argmax(1) == y).astype(float)
    hit_head = np.zeros(n); hit_top = np.zeros(n); pact = np.zeros(n)
    for i in range(n):
        k, sc, ps = pick_from_grid(G[i])
        hg, ag = int(rec.hg.values[i]), int(rec.ag.values[i])
        hit_head[i] = float(sc == (hg, ag))
        ij = np.unravel_index(np.argmax(G[i]), G[i].shape)
        hit_top[i] = float((int(ij[0]), int(ij[1])) == (hg, ag))
        pact[i] = G[i][min(hg, 8), min(ag, 8)]
    out["head_hit"], out["top_hit"], out["p_actual_score"] = hit_head, hit_top, pact
    out["ph"], out["pd"], out["pa"] = p.T
    return out


def eval_probs(p, y):
    out = pd.DataFrame({"rps": rps(p, y), "ll": logloss(p, y), "brier": brier(p, y)})
    out["acc"] = (p.argmax(1) == y).astype(float)
    return out


def tune(pool, rec, cfg):
    """select (xi, reg, w_dom[, w_ucl]) on the tuning-period record."""
    res = []
    dom_mask = (rec.comp != "ucl").values
    ucl_mask = (rec.comp == "ucl").values
    for xi, reg in itertools.product(cfg["xi"], cfg["reg"]):
        tag = f"{xi}_{reg}"
        for w in W_GRID:
            G = blended_grids(rec, tag, w)
            p = np.stack([np.array([np.tril(g, -1).sum(), np.trace(g), np.triu(g, 1).sum()]) for g in G])
            y = outcome(rec.hg.values, rec.ag.values)
            r = rps(p, y); l = logloss(p, y)
            res.append(dict(xi=xi, reg=reg, w=w, rps_dom=r[dom_mask].mean() if dom_mask.any() else np.nan,
                            ll_dom=l[dom_mask].mean() if dom_mask.any() else np.nan,
                            rps_ucl=r[ucl_mask].mean() if ucl_mask.any() else np.nan,
                            ll_ucl=l[ucl_mask].mean() if ucl_mask.any() else np.nan,
                            rps_all=r.mean(), ll_all=l.mean(), n_dom=int(dom_mask.sum()), n_ucl=int(ucl_mask.sum())))
    R = pd.DataFrame(res)
    key = "rps_dom" if pool == "eu" else "rps_all"
    llk = "ll_dom" if pool == "eu" else "ll_all"

    def best_in(sub):
        top = sub[key].min()
        ties = sub[sub[key] <= top + 0.0005]
        # ties within 0.0005 RPS: lowest log-loss, then simplest (larger w, smaller xi, larger reg)
        return ties.sort_values([llk, "w", "xi", "reg"], ascending=[True, False, True, False]).iloc[0]
    best_dc = best_in(R[R.w == 1.0])
    best_bl = best_in(R[R.w < 1.0])
    use_blend = (best_dc[key] - best_bl[key]) >= 0.0005
    chosen = best_bl if use_blend else best_dc
    sel = dict(xi=float(chosen.xi), reg=float(chosen.reg), w=float(chosen.w))
    if pool == "eu":
        sub = R[(R.xi == sel["xi"]) & (R.reg == sel["reg"])]
        bu_dc = sub[sub.w == 1.0].iloc[0]
        bu_bl = sub[sub.w < 1.0].sort_values("rps_ucl").iloc[0]
        sel["w_ucl"] = float(bu_bl.w) if (bu_dc.rps_ucl - bu_bl.rps_ucl) >= 0.0005 else 1.0
    return sel, R, dict(best_dc=best_dc.to_dict(), best_blend=best_bl.to_dict(), use_blend=bool(use_blend))


def bootstrap_diff(a, b, B=2000, seed=SEED):
    rng = np.random.RandomState(seed)
    d = np.asarray(a) - np.asarray(b)
    n = len(d)
    idx = rng.randint(0, n, size=(B, n))
    means = d[idx].mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarise(rec, sel, label):
    """report metrics for the shipped config + DC-only + baselines on record `rec`."""
    out = {}
    y = outcome(rec.hg.values, rec.ag.values)
    tag = f"{sel['xi']}_{sel['reg']}"
    is_ucl = (rec.comp == "ucl").values
    # shipped: per-row w (dom vs ucl)
    Gd = blended_grids(rec, tag, sel["w"])
    if "w_ucl" in sel and sel["w_ucl"] != sel["w"]:
        Gu = blended_grids(rec, tag, sel["w_ucl"])
        Gd[is_ucl] = Gu[is_ucl]
    ship = eval_grids(rec, Gd)
    dc_only = eval_grids(rec, blended_grids(rec, tag, 1.0))
    pe = rec[["p_elo_h", "p_elo_d", "p_elo_a"]].values
    pb = rec[["p_base_h", "p_base_d", "p_base_a"]].values
    elo = eval_probs(pe, y); base = eval_probs(pb, y); uni = eval_probs(np.full((len(y), 3), 1 / 3), y)
    home_always = float((y == 0).mean())
    out["n"] = int(len(rec))
    out["models"] = {}
    for name, df_ in [("shipped", ship), ("dc_only", dc_only), ("elo_only", elo), ("base_rates", base), ("uniform", uni)]:
        out["models"][name] = {k: float(df_[k].mean()) for k in df_.columns if k in ("rps", "ll", "brier", "acc", "head_hit", "top_hit", "p_actual_score")}
    out["home_win_always_acc"] = home_always
    out["bootstrap"] = {}
    for nm, other in [("base_rates", base), ("elo_only", elo), ("uniform", uni), ("dc_only", dc_only)]:
        out["bootstrap"][f"shipped_minus_{nm}"] = {
            "rps": bootstrap_diff(ship.rps, other.rps), "ll": bootstrap_diff(ship.ll, other.ll)}
    out["shipped_frame"] = ship
    return out


def split_report(rec, sel, label):
    subs = {"all": np.ones(len(rec), bool),
            "site_leagues_epl_laliga_ligue1": rec.comp.isin(["epl", "laliga", "ligue1"]).values,
            "big5_domestic": rec.comp.isin(["epl", "laliga", "ligue1", "bundesliga", "seriea"]).values,
            "ucl": (rec.comp == "ucl").values}
    if (rec.comp == "spl").any():
        subs = {"all": np.ones(len(rec), bool)}
    res = {}
    for k, m in subs.items():
        if m.sum() < 30:
            continue
        s = summarise(rec[m].reset_index(drop=True), sel, f"{label}:{k}")
        s.pop("shipped_frame")
        res[k] = s
    return res


def main(pool):
    cfg = POOLS[pool]
    m = load_matches()
    df = m[m.comp.isin(cfg["comps"])].copy()
    df = df.sort_values("dt").reset_index(drop=True)
    space = Space(df, cfg["comps"])
    configs = list(itertools.product(cfg["xi"], cfg["reg"]))
    print(f"[{pool}] matches {len(df)} teams {len(space.teams)} configs {len(configs)}", flush=True)
    print("tuning period 2024-25 ...", flush=True)
    rec_t = run_period(pool, df, space, TUNE, configs)
    sel, R, info = tune(pool, rec_t, cfg)
    print("selected:", sel, info["use_blend"], flush=True)
    print(R.sort_values("rps_all").head(8).to_string(), flush=True)
    sel_cfg = [(sel["xi"], sel["reg"])]
    print("report period 2025-26 ...", flush=True)
    rec_r = run_period(pool, df, space, REPORT, sel_cfg)
    print("current season to date ...", flush=True)
    rec_c = run_period(pool, df, space, CURRENT, sel_cfg)
    out = {"pool": pool, "selected": sel, "tuning_grid": R.round(5).to_dict("records"), "tuning_decision": info,
           "tuning_n": int(len(rec_t)), "report_2025_26": split_report(rec_r, sel, "2025-26"),
           "current_2026_27": split_report(rec_c, sel, "2026-27")}
    json.dump(out, open(f"{DATA}/backtest_{pool}.json", "w"), indent=1, default=float)
    # save per-match shipped predictions for the record page / audits
    for nm, rec in [("2025-26", rec_r), ("2026-27", rec_c)]:
        tag = f"{sel['xi']}_{sel['reg']}"
        G = blended_grids(rec, tag, sel["w"])
        if "w_ucl" in sel:
            Gu = blended_grids(rec, tag, sel["w_ucl"]); isu = (rec.comp == "ucl").values; G[isu] = Gu[isu]
        ev = eval_grids(rec, G)
        keep = rec[["comp", "date", "home", "away", "hg", "ag"]].join(ev[["ph", "pd", "pa", "rps", "ll", "head_hit"]])
        keep.to_csv(f"{DATA}/backtest_{pool}_{nm}_matches.csv", index=False)
    print("done", flush=True)


def selfcheck():
    """Leakage perturbation test: scrambling every result inside a test week must not change that week's predictions."""
    m = load_matches()
    df = m[m.comp.isin(EU_COMPS)].copy().sort_values("dt").reset_index(drop=True)
    space = Space(df, EU_COMPS)
    cut = pd.Timestamp("2025-11-03")
    per = (cut, cut + pd.Timedelta(days=6))
    a = run_period("eu", df, space, per, [(0.0019, 6.0)], verbose=False)
    df2 = df.copy()
    inwin = (df2.dt >= cut) & (df2.dt <= per[1])
    rng = np.random.RandomState(0)
    df2.loc[inwin, "hg"] = rng.randint(0, 6, inwin.sum()); df2.loc[inwin, "ag"] = rng.randint(0, 6, inwin.sum())
    b = run_period("eu", df2, space, per, [(0.0019, 6.0)], verbose=False)
    cols = [c for c in a.columns if c.startswith(("lh_", "la_", "p_elo", "p_base", "elo_sup"))]
    diff = max(float(np.max(np.abs(a[c].values - b[c].values))) for c in cols)
    print(f"selfcheck: {inwin.sum()} matches' results scrambled in test week; max prediction change = {diff:.2e}")
    assert diff < 1e-9, "LEAK DETECTED"
    print("selfcheck PASSED (no fitted object saw the test week's results)")


if __name__ == "__main__":
    if sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        main(sys.argv[1])
