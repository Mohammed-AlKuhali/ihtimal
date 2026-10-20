"""Full model evaluation of the Ihtimal match predictor (writes EVALUATION.md, results.json, figures/*.png).

usage (from the project root):
    .venv/bin/python evaluation/run_eval.py                 # compute everything, then write the report
    .venv/bin/python evaluation/run_eval.py --compute-only
    .venv/bin/python evaluation/run_eval.py --report-only   # re-render EVALUATION.md from evaluation/results.json
    EVAL_QUICK=1 .venv/bin/python evaluation/run_eval.py --compute-only   # smoke test: tiny bootstraps, not for reporting

Design rules
  * Nothing here changes a model, a locked file, locks.json or site/. The pre-registered shipped settings are read from
    data/backtest_eu.json and data/backtest_spl.json and the shipped predictions are regenerated with the SAME code path as
    model/backtest.py (weekly walk-forward refits on the 2025-26 holdout); the regenerated probabilities are asserted to match
    data/backtest_*_2025-26_matches.csv.  Refits are cheap (a whole season of weekly refits takes about a second), so every
    analysis below uses WEEKLY refits, not a cheaper schedule.
  * Bootstrap: match-level resampling, 2,000 replicates, seed 2026, the same resampled indices for every paired comparison.
  * Every number in EVALUATION.md is read from results.json, which this file computes.
"""
import os, sys, json, math, time, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIG = os.path.join(HERE, "figures")
sys.path.insert(0, os.path.join(ROOT, "model"))
from core import load_matches, Space, fit_at, elo_models, rps, logloss, brier, outcome, EU_COMPS, DATA  # noqa: E402
from dc import fit_dc, lambdas, score_grids  # noqa: E402
from backtest import run_period, blended_grids, eval_grids, REPORT, TUNE, mondays  # noqa: E402

warnings.filterwarnings("ignore")
QUICK = os.environ.get("EVAL_QUICK") == "1"
SEED = 2026
B = 200 if QUICK else 2000          # bootstrap replicates (match level)
B_FIT = 12 if QUICK else 400        # bootstrap refits for the parameter-stability analysis
N_NULL = 100 if QUICK else 1000     # simulations for the calibration null
os.makedirs(FIG, exist_ok=True)
RES_PATH = os.path.join(HERE, "results.json")

COMP_NAME = {"epl": "Premier League", "laliga": "La Liga", "ligue1": "Ligue 1", "bundesliga": "Bundesliga", "seriea": "Serie A",
             "ucl": "Champions League", "spl": "Saudi Pro League"}
SITE3 = ["epl", "laliga", "ligue1"]
OUT_LAB = ["H", "D", "A"]

# ----------------------------------------------------------------------------- colours (dataviz skill: validated categorical slots 1-4)
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6"


def style():
    plt.rcParams.update({"axes.facecolor": SURF, "figure.facecolor": SURF, "savefig.facecolor": SURF, "axes.edgecolor": GRID,
                         "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
                         "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
                         "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
                         "legend.frameon": False, "savefig.dpi": 150, "figure.dpi": 110})


def savefig(fig, name):
    fig.savefig(os.path.join(FIG, name), bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- bootstrap helpers
_IDX = {}


def bidx(n):
    """Resample indices, identical for every analysis with the same n (this is what makes comparisons paired)."""
    if n not in _IDX:
        _IDX[n] = np.random.RandomState(SEED).randint(0, n, size=(B, n)).astype(np.int32)
    return _IDX[n]


def boot_means(x):
    x = np.asarray(x, float)
    return x[bidx(len(x))].mean(axis=1)


def boot_mean(x):
    """(mean, lo, hi) with a 95% percentile interval."""
    x = np.asarray(x, float)
    m = boot_means(x)
    return [float(x.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def boot_p(m):
    """two-sided bootstrap p for 'difference = 0' from replicate means m (percentile inversion)."""
    if np.abs(m).max() < 1e-12:
        return 1.0
    p = 2 * min((m <= 0).mean(), (m >= 0).mean())
    return float(min(max(p, 1.0 / len(m)), 1.0))


def wilson(k, n, z=1.96):
    if n == 0:
        return [float("nan")] * 2
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [c - h, c + h]


def dm_test(d):
    """Diebold-Mariano test on per-match loss differences d (date ordered), Newey-West variance (Bartlett, lag n^(1/3)),
    Harvey-Leybourne-Newbold small-sample correction (h = 1) and a Student-t reference with n-1 df."""
    d = np.asarray(d, float)
    n = len(d)
    dbar = d.mean()
    e = d - dbar
    L = int(round(n ** (1 / 3)))
    var = e @ e / n
    for k in range(1, L + 1):
        var += 2 * (1 - k / (L + 1)) * (e[k:] @ e[:-k]) / n
    var = max(var, 1e-18)
    dm = dbar / math.sqrt(var / n) * math.sqrt((n - 1) / n)
    return float(dm), float(2 * stats.t.sf(abs(dm), n - 1))


def block_boot_ci(d, blocks):
    """Bootstrap over whole weekly folds (a check that the match-level interval is not too narrow because of within-week dependence)."""
    codes, _ = pd.factorize(blocks)
    nb = codes.max() + 1
    S = np.bincount(codes, weights=d, minlength=nb)
    C = np.bincount(codes, minlength=nb).astype(float)
    ix = np.random.RandomState(SEED).randint(0, nb, size=(B, nb))
    m = S[ix].sum(1) / C[ix].sum(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def compare(a, b, blocks=None):
    """paired comparison of per-match losses a (model) and b (other): mean difference a-b, bootstrap CI + p, DM test, block CI."""
    d = np.asarray(a, float) - np.asarray(b, float)
    m = boot_means(d)
    dm, dmp = dm_test(d)
    out = {"diff": float(d.mean()), "lo": float(np.percentile(m, 2.5)), "hi": float(np.percentile(m, 97.5)), "p_boot": boot_p(m), "dm": dm, "p_dm": dmp}
    if blocks is not None:
        out["block_ci"] = block_boot_ci(d, blocks)
    return out


# ----------------------------------------------------------------------------- grid helpers
II, JJ = np.indices((9, 9))
MH, MD, MA = II > JJ, II == JJ, II < JJ


def grid_wdl(G):
    return np.stack([(G * MH).sum((1, 2)), (G * MD).sum((1, 2)), (G * MA).sum((1, 2))], axis=1)


def grid_moments(G):
    eh = (G * II).sum((1, 2)); ea = (G * JJ).sum((1, 2))
    vh = (G * II ** 2).sum((1, 2)) - eh ** 2; va = (G * JJ ** 2).sum((1, 2)) - ea ** 2
    cv = (G * II * JJ).sum((1, 2)) - eh * ea
    return eh, ea, vh, va, cv


def losses(p, y):
    return {"rps": rps(p, y), "ll": logloss(p, y), "brier": brier(p, y), "acc": (p.argmax(1) == y).astype(float)}


def fci(v, d=4, pct=False, plus=False):
    """format [mean, lo, hi] -> 'mean [lo, hi]'"""
    if pct:
        return f"{100 * v[0]:.1f}% [{100 * v[1]:.1f}, {100 * v[2]:.1f}]"
    s = "+" if plus else ""
    return f"{v[0]:{s}.{d}f} [{v[1]:{s}.{d}f}, {v[2]:{s}.{d}f}]"


# ----------------------------------------------------------------------------- weekly refit machinery (same folds as model/backtest.py)
def fit_variant(space, train, cutoff, xi, reg, no_rho=False, x0=None):
    if not no_rho:
        return fit_at(space, train, cutoff, xi, reg, x0=x0)
    tr = train[train.dt < cutoff]
    assert tr.dt.max() < cutoff
    h, a, c = space.idx(tr)
    w = np.exp(-xi * (cutoff - tr.dt).dt.days.values.astype(float))
    fit = fit_dc(h, a, c, tr.hg.values, tr.ag.values, w, space.team_league, len(space.teams), len(space.leagues), len(space.comps),
                 reg_team=reg, reg_league=0.2, x0=x0, rho_fixed=0.0)
    fit.n_train = len(tr)
    return fit


def run_weekly(df, space, period, xi, reg, win=None, no_rho=False, drop_ucl=False, insample=False):
    """Weekly walk-forward refits of the Dixon-Coles leg only (same folds and test rows as backtest.run_period).
    win: keep only the last `win` days of history; drop_ucl: remove Champions League matches from the training data;
    insample: also return the decay-weighted in-sample RPS / log-loss of each fit on its own training matches."""
    rows, ins, xprev = [], [], None
    for cut in mondays(*period):
        nxt = cut + pd.Timedelta(days=7)
        test = df[(df.dt >= max(cut, period[0])) & (df.dt < nxt) & (df.dt <= period[1])]
        if len(test) == 0:
            continue
        train = df[df.dt < cut]
        if win:
            train = train[train.dt >= cut - pd.Timedelta(days=win)]
        if drop_ucl:
            train = train[train.comp != "ucl"]
        assert train.dt.max() < test.dt.min(), "LEAK"
        fit = fit_variant(space, train, cut, xi, reg, no_rho=no_rho, x0=xprev)
        xprev = fit.x
        h, a, c = space.idx(test)
        lh, la = lambdas(fit, h, a, c)
        r = test[["comp", "date", "home", "away", "hg", "ag"]].copy().reset_index(drop=True)
        r["fold"] = cut; r["lh"], r["la"], r["rho"] = lh, la, fit.rho
        ht_, at_, _ = space.idx(train[train.dt < cut])
        r["sd_a"] = float(np.std(fit.a[np.unique(np.r_[ht_, at_])]))   # spread of attack ratings over teams seen in training (shrinkage diagnostic)
        rows.append(r)
        if insample:
            tr = train[train.dt < cut]
            h2, a2, c2 = space.idx(tr)
            l1, l2 = lambdas(fit, h2, a2, c2)
            p = grid_wdl(score_grids(l1, l2, fit.rho))
            y = outcome(tr.hg.values, tr.ag.values)
            w = np.exp(-xi * (cut - tr.dt).dt.days.values.astype(float))
            ins.append((float((w * rps(p, y)).sum() / w.sum()), float((w * logloss(p, y)).sum() / w.sum()), len(tr)))
    out = pd.concat(rows, ignore_index=True)
    return (out, np.array(ins)) if insample else out


def dc_probs(rec, w=1.0, elo_sup=None):
    """W/D/L probabilities and grids from a frame with lh, la, rho (and elo_sup if w < 1) -- the same blend as backtest.blended_grids."""
    r = pd.DataFrame({"lh_v": rec.lh.values, "la_v": rec.la.values, "rho_v": rec.rho.values,
                      "elo_sup": np.zeros(len(rec)) if elo_sup is None else elo_sup})
    G = blended_grids(r, "v", w)
    return G, grid_wdl(G)


def mixed(rec, elo_sup, w_dom, w_ucl):
    G, _ = dc_probs(rec, w_dom, elo_sup)
    isu = (rec.comp == "ucl").values
    if isu.any() and w_ucl != w_dom:
        Gu, _ = dc_probs(rec, w_ucl, elo_sup)
        G[isu] = Gu[isu]
    return G, grid_wdl(G)


def aligned(rec_ref, rec):
    assert len(rec_ref) == len(rec) and (rec_ref.home.values == rec.home.values).all() and (rec_ref.date.values == rec.date.values).all()


# ============================================================================= STAGE 1: holdout master frame
def build_master():
    m = load_matches()
    out = {}
    sel_eu = json.load(open(os.path.join(DATA, "backtest_eu.json")))["selected"]
    sel_sp = json.load(open(os.path.join(DATA, "backtest_spl.json")))["selected"]
    pools = {"eu": (m[m.comp.isin(EU_COMPS)], EU_COMPS, sel_eu), "spl": (m[m.comp == "spl"], ["spl"], sel_sp)}
    frames, grids, ctx = [], [], {}
    for pool, (dfp, comps, sel) in pools.items():
        df = dfp.copy().sort_values("dt").reset_index(drop=True)
        space = Space(df, comps)
        t_fit = time.time()
        rec = run_period(pool, df, space, REPORT, [(sel["xi"], sel["reg"])], verbose=False)
        refit_seconds = time.time() - t_fit
        tag = f"{sel['xi']}_{sel['reg']}"
        G = blended_grids(rec, tag, sel["w"])
        if "w_ucl" in sel and sel["w_ucl"] != sel["w"]:
            Gu = blended_grids(rec, tag, sel["w_ucl"]); isu = (rec.comp == "ucl").values; G[isu] = Gu[isu]
        ev = eval_grids(rec, G)
        # reproducibility check against the stored backtest output
        old = pd.read_csv(os.path.join(DATA, f"backtest_{pool}_2025-26_matches.csv"))
        assert (old.home.values == rec.home.values).all() and (old.date.values == rec.date.values).all()
        dmax = float(np.abs(old[["ph", "pd", "pa"]].values - ev[["ph", "pd", "pa"]].values).max())
        assert dmax < 1e-9, f"regenerated holdout differs from stored backtest ({dmax})"
        stored = json.load(open(os.path.join(DATA, f"backtest_{pool}.json")))["report_2025_26"]["all"]["models"]["shipped"]
        ctx[pool] = {"sel": sel, "n": len(rec), "refit_seconds": refit_seconds, "n_folds": int(rec.fold.nunique()), "max_abs_prob_diff_vs_stored_csv": dmax,
                     "rps_regenerated": float(ev.rps.mean()), "rps_stored_json": stored["rps"],
                     "n_train_last_fold": int(len(df[df.dt < rec.fold.max()]))}
        y = outcome(rec.hg.values, rec.ag.values)
        A = rec[["comp", "date", "home", "away", "hg", "ag", "fold"]].copy()
        A["pool"] = pool; A["y"] = y
        for c in ["ph", "pd", "pa", "rps", "ll", "brier", "acc", "head_hit", "top_hit", "p_actual_score"]:
            A[c] = ev[c].values
        A = A.rename(columns={"p_actual_score": "pas"})
        eh, ea, vh, va, cv = grid_moments(G)
        A["eh"], A["ea"], A["vh"], A["va"], A["cv"] = eh, ea, vh, va, cv
        A["lam_h"] = rec[f"lh_{tag}"].values; A["lam_a"] = rec[f"la_{tag}"].values; A["rho"] = rec[f"rho_{tag}"].values
        A["elo_sup"] = rec.elo_sup.values
        # DC-only
        Gd = blended_grids(rec, tag, 1.0); pd_ = grid_wdl(Gd)
        for k, v in losses(pd_, y).items():
            A[f"dc_{k}"] = v
        A["dc_ph"], A["dc_pd"], A["dc_pa"] = pd_.T
        # baselines
        for nm, cols in [("elo", ["p_elo_h", "p_elo_d", "p_elo_a"]), ("base", ["p_base_h", "p_base_d", "p_base_a"])]:
            p = rec[cols].values
            for k, v in losses(p, y).items():
                A[f"{nm}_{k}"] = v
            A[f"{nm}_ph"], A[f"{nm}_pd"], A[f"{nm}_pa"] = p.T
        for k, v in losses(np.full((len(y), 3), 1 / 3), y).items():
            A[f"uni_{k}"] = v
        A["home_acc"] = (y == 0).astype(float)
        frames.append(A); grids.append(G)
        out[pool] = dict(df=df, space=space, rec=rec, sel=sel, tag=tag)
    A = pd.concat(frames, ignore_index=True)
    A["date"] = pd.to_datetime(A["date"]); A["fold"] = pd.to_datetime(A["fold"])
    G = np.concatenate(grids)
    return A, G, out, ctx, m


def games_before(df, pool_df, A):
    """number of earlier same-season matches of each team (cold-start measure) and matches in the prior 365 days (thin data)."""
    d = pool_df.sort_values("dt", kind="stable")
    cnt, prior = {}, {}
    key = {}
    for r in d.itertuples():
        key[(r.date, r.home, r.away, r.comp)] = (cnt.get((r.season, r.home), 0), cnt.get((r.season, r.away), 0))
        cnt[(r.season, r.home)] = cnt.get((r.season, r.home), 0) + 1
        cnt[(r.season, r.away)] = cnt.get((r.season, r.away), 0) + 1
    ph = np.zeros(len(A)); pa = np.zeros(len(A))
    for i, r in enumerate(A.itertuples()):
        ph[i], pa[i] = key[(r.date.strftime("%Y-%m-%d"), r.home, r.away, r.comp)]
    return ph, pa


def prior_year(pool_df, A):
    d = pool_df
    out = np.zeros((len(A), 2))
    for i, r in enumerate(A.itertuples()):
        lo = r.date - pd.Timedelta(days=365)
        w = d[(d.dt >= lo) & (d.dt < r.date)]
        out[i] = [((w.home == r.home) | (w.away == r.home)).sum(), ((w.home == r.away) | (w.away == r.away)).sum()]
    return out


# ============================================================================= SECTION 1-2: headline metrics, baselines, significance
def group_masks(A):
    g = {"Europe (big-5 + UCL)": (A.pool == "eu").values,
         "Site leagues (EPL + La Liga + Ligue 1)": A.comp.isin(SITE3).values,
         "Saudi Pro League": (A.pool == "spl").values}
    return g


def sec_headline(A):
    metrics = ["acc", "head_hit", "top_hit", "rps", "ll", "brier"]
    out = {"groups": {}, "competitions": {}}
    for gname, mk in group_masks(A).items():
        sub = A[mk]
        out["groups"][gname] = {"n": int(mk.sum()), **{k: boot_mean(sub[k].values) for k in metrics}, "pas": boot_mean(sub.pas.values)}
    for c in ["epl", "laliga", "ligue1", "bundesliga", "seriea", "ucl", "spl"]:
        sub = A[A.comp == c]
        out["competitions"][COMP_NAME[c]] = {"n": int(len(sub)), **{k: boot_mean(sub[k].values) for k in metrics}}
    return out


def sec_baselines(A):
    out = {}
    for gname, mk in group_masks(A).items():
        sub = A[mk]
        blocks = sub.fold.values
        n = len(sub)
        r = {"n": n, "models": {}, "tests": {}}
        for nm, lab in [("", "Shipped model"), ("dc_", "Dixon-Coles only (w=1)"), ("elo_", "Elo only"), ("base_", "League base rates"), ("uni_", "Uniform 1/3")]:
            r["models"][lab] = {k: boot_mean(sub[f"{nm}{k}"].values) for k in ["rps", "ll", "brier", "acc"]}
        r["models"]["Home win always"] = {"acc": boot_mean(sub.home_acc.values)}
        for nm, lab in [("base_", "League base rates"), ("elo_", "Elo only"), ("uni_", "Uniform 1/3"), ("dc_", "Dixon-Coles only (w=1)")]:
            t = {"rps": compare(sub.rps.values, sub[f"{nm}rps"].values, blocks), "ll": compare(sub.ll.values, sub[f"{nm}ll"].values, blocks)}
            r["tests"][lab] = t
        # accuracy vs home-always (paired)
        d = sub.acc.values - sub.home_acc.values
        m = boot_means(d)
        r["tests"]["Home win always"] = {"acc": {"diff": float(d.mean()), "lo": float(np.percentile(m, 2.5)), "hi": float(np.percentile(m, 97.5)), "p_boot": boot_p(m)}}
        out[gname] = r
    return out


# ============================================================================= SECTION 3: calibration
def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def logistic_ab(x, y, it=30):
    """y ~ sigmoid(a + b x) by Newton-Raphson. returns (a, b)."""
    X = np.column_stack([np.ones_like(x), x]); beta = np.array([0.0, 1.0])
    for _ in range(it):
        mu = 1 / (1 + np.exp(-(X @ beta))); W = mu * (1 - mu)
        H = (X * W[:, None]).T @ X + 1e-9 * np.eye(2)
        step = np.linalg.solve(H, X.T @ (y - mu)); beta = beta + step
        if np.abs(step).max() < 1e-9:
            break
    return float(beta[0]), float(beta[1])


def logistic_a(x, y, it=30):
    """calibration-in-the-large: y ~ sigmoid(a + x) (slope fixed at 1)."""
    a = 0.0
    for _ in range(it):
        mu = 1 / (1 + np.exp(-(a + x))); W = mu * (1 - mu)
        step = (y - mu).sum() / max(W.sum(), 1e-12); a += step
        if abs(step) < 1e-10:
            break
    return float(a)


def reliability(p, yb, nb=10):
    order = np.argsort(p, kind="stable")
    bins = np.array_split(order, nb)
    n = len(p)
    rows = []
    for b in bins:
        k = int(yb[b].sum()); lo, hi = wilson(k, len(b))
        rows.append({"n": len(b), "pred": float(p[b].mean()), "obs": float(yb[b].mean()), "lo": lo, "hi": hi, "pmin": float(p[b].min()), "pmax": float(p[b].max())})
    ece = float(sum(r["n"] / n * abs(r["pred"] - r["obs"]) for r in rows))
    return rows, ece, bins


def calib_class(p, yb):
    rows, ece, bins = reliability(p, yb)
    n = len(p)
    rng = np.random.RandomState(SEED + 7)
    null = np.zeros(N_NULL)
    for s in range(N_NULL):
        ys = (rng.rand(n) < p).astype(float)
        null[s] = sum(len(b) / n * abs(p[b].mean() - ys[b].mean()) for b in bins)
    ix = bidx(n)
    xl = logit(p)
    ab = np.array([logistic_ab(xl[ix[i]], yb[ix[i]]) for i in range(B)])
    ct = np.array([logistic_a(xl[ix[i]], yb[ix[i]]) for i in range(B)])
    a0, b0 = logistic_ab(xl, yb)
    c0 = logistic_a(xl, yb)
    pc = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    return {"bins": rows, "ece": ece, "ece_null_mean": float(null.mean()), "ece_null_p95": float(np.percentile(null, 95)),
            "ece_p": float((null >= ece).mean()), "slope": [b0, *pc(ab[:, 1])], "intercept": [a0, *pc(ab[:, 0])], "citl": [c0, *pc(ct)],
            "mean_pred": float(p.mean()), "obs_rate": float(yb.mean())}


def sec_calibration(A):
    out = {}
    for gname, mk in group_masks(A).items():
        sub = A[mk]
        o = {}
        for k, (col, lab) in enumerate([("ph", "Home win"), ("pd", "Draw"), ("pa", "Away win")]):
            o[lab] = calib_class(sub[col].values, (sub.y.values == k).astype(float))
        o["mean_ece"] = float(np.mean([o[l]["ece"] for l in ["Home win", "Draw", "Away win"]]))
        o["draw_5bins"] = reliability(sub.pd.values, (sub.y.values == 1).astype(float), nb=5)[0]
        out[gname] = o
    # draw-specific: by closeness |pH - pA|, by league
    eu = A[A.pool == "eu"]
    closeness = (eu.ph - eu.pa).abs().values
    edges = [0, 0.10, 0.20, 0.35, 0.50, 1.01]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (closeness >= lo) & (closeness < hi)
        s = eu[mk]; k = int((s.y == 1).sum())
        rows.append({"band": f"{lo:.2f}-{min(hi, 1):.2f}", "n": int(mk.sum()), "pred": float(s.pd.mean()), "obs": k / len(s), "ci": wilson(k, len(s))})
    out["draw_by_closeness_europe"] = rows
    out["draw_by_comp"] = {COMP_NAME[c]: {"n": int((A.comp == c).sum()), "pred": float(A[A.comp == c].pd.mean()), "obs": float((A[A.comp == c].y == 1).mean()),
                                         "diff": boot_mean(A[A.comp == c].pd.values - (A[A.comp == c].y.values == 1))} for c in ["epl", "laliga", "ligue1", "bundesliga", "seriea", "ucl", "spl"]}
    return out


# ============================================================================= SECTION 4: bias
def sec_bias(A, G):
    out = {}
    names = [("epl", "Premier League"), ("laliga", "La Liga"), ("ligue1", "Ligue 1"), ("bundesliga", "Bundesliga"), ("seriea", "Serie A"), ("ucl", "Champions League"), ("spl", "Saudi Pro League")]
    sets = [(COMP_NAME[c], (A.comp == c).values) for c, _ in names] + [("Europe (big-5 + UCL)", (A.pool == "eu").values), ("Site leagues (EPL + La Liga + Ligue 1)", A.comp.isin(SITE3).values)]
    goals, outs, ha = {}, {}, {}
    for lab, mk in sets:
        s = A[mk]
        goals[lab] = {"n": int(mk.sum()),
                      "home": {"pred": float(s.eh.mean()), "act": float(s.hg.mean()), "err": boot_mean(s.eh.values - s.hg.values)},
                      "away": {"pred": float(s.ea.mean()), "act": float(s.ag.mean()), "err": boot_mean(s.ea.values - s.ag.values)},
                      "total": {"pred": float((s.eh + s.ea).mean()), "act": float((s.hg + s.ag).mean()), "err": boot_mean(s.eh.values + s.ea.values - s.hg.values - s.ag.values)}}
        outs[lab] = {}
        for k, (col, nm) in enumerate([("ph", "H"), ("pd", "D"), ("pa", "A")]):
            yk = (s.y.values == k).astype(float)
            outs[lab][nm] = {"pred": float(s[col].mean()), "obs": float(yk.mean()), "err": boot_mean(s[col].values - yk)}
        ha[lab] = {"pred_gd": float((s.eh - s.ea).mean()), "act_gd": float((s.hg - s.ag).mean()), "err": boot_mean((s.eh - s.ea).values - (s.hg - s.ag).values),
                   "pred_home_share": float(s.eh.sum() / (s.eh.sum() + s.ea.sum())), "act_home_share": float(s.hg.sum() / (s.hg.sum() + s.ag.sum()))}
    out["goals"], out["outcomes"], out["home_adv"] = goals, outs, ha

    # favourite - longshot pattern
    eu = A[A.pool == "eu"]
    fav_home = (eu.ph >= eu.pa).values
    pf = np.where(fav_home, eu.ph, eu.pa); pl = np.where(fav_home, eu.pa, eu.ph)
    fw = np.where(fav_home, eu.y.values == 0, eu.y.values == 2).astype(float)
    lw = np.where(fav_home, eu.y.values == 2, eu.y.values == 0).astype(float)
    dr = (eu.y.values == 1).astype(float)
    edges = [0, 0.40, 0.50, 0.60, 0.70, 1.0]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (pf >= lo) & (pf < hi)
        n = int(mk.sum())
        rows.append({"band": f"{int(lo * 100)}-{int(hi * 100)}%", "n": n, "p_fav": float(pf[mk].mean()), "fav_win": float(fw[mk].mean()), "fav_ci": wilson(int(fw[mk].sum()), n),
                     "p_long": float(pl[mk].mean()), "long_win": float(lw[mk].mean()), "long_ci": wilson(int(lw[mk].sum()), n),
                     "p_draw": float(eu.pd.values[mk].mean()), "draw": float(dr[mk].mean()), "draw_ci": wilson(int(dr[mk].sum()), n)})
    out["fav_bands"] = rows
    # pooled team-side win probabilities (each match gives a home and an away observation)
    ps = np.r_[eu.ph.values, eu.pa.values]; ws = np.r_[(eu.y.values == 0), (eu.y.values == 2)].astype(float)
    edges = [0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 1.0]
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mk = (ps >= lo) & (ps < hi); n = int(mk.sum())
        if n == 0:
            continue
        rows.append({"band": f"{int(lo * 100)}-{int(hi * 100)}%", "n": n, "pred": float(ps[mk].mean()), "obs": float(ws[mk].mean()), "ci": wilson(int(ws[mk].sum()), n)})
    out["side_bands"] = rows
    n = len(eu); ix = bidx(n)
    sl = []
    for i in range(B):
        j = ix[i]
        sl.append(logistic_ab(np.r_[logit(eu.ph.values[j]), logit(eu.pa.values[j])], np.r_[(eu.y.values[j] == 0), (eu.y.values[j] == 2)].astype(float)))
    a0, b0 = logistic_ab(logit(ps), ws)
    sl = np.array(sl)
    out["side_slope"] = {"slope": [b0, float(np.percentile(sl[:, 1], 2.5)), float(np.percentile(sl[:, 1], 97.5))], "intercept": [a0, float(np.percentile(sl[:, 0], 2.5)), float(np.percentile(sl[:, 0], 97.5))]}
    # low-probability (<20%) and high-probability (>=60%) side observations
    for nm, mk in [("longshot_lt20", ps < 0.20), ("favourite_ge60", ps >= 0.60)]:
        out[nm] = {"n": int(mk.sum()), "pred": float(ps[mk].mean()), "obs": float(ws[mk].mean()), "ci": wilson(int(ws[mk].sum()), int(mk.sum())), "gap": boot_mean_sub(ps, ws, mk)}

    # scoreline distribution
    cells = [(0, 0), (1, 0), (0, 1), (1, 1), (2, 0), (0, 2), (2, 1), (1, 2), (2, 2), (3, 0), (0, 3), (3, 1), (1, 3), (3, 2), (2, 3)]
    sc = {}
    for lab, mk in [("Europe (big-5 + UCL)", (A.pool == "eu").values), ("Site leagues (EPL + La Liga + Ligue 1)", A.comp.isin(SITE3).values), ("Saudi Pro League", (A.pool == "spl").values)]:
        s = A[mk]; Gm = G[mk]; n = len(s); rows = []
        used_obs = np.zeros(n, bool); used_exp = np.zeros(n)
        for (i, j) in cells:
            o = ((s.hg.values == i) & (s.ag.values == j)).astype(float); pe = Gm[:, i, j]
            used_obs |= o.astype(bool); used_exp += pe
            z = (o.mean() - pe.mean()) / math.sqrt((pe * (1 - pe)).sum() / n ** 2)
            rows.append({"score": f"{i}-{j}", "obs": float(o.mean()), "obs_ci": wilson(int(o.sum()), n), "exp": float(pe.mean()), "z": float(z)})
        o = (~used_obs).astype(float); pe = 1 - used_exp
        z = (o.mean() - pe.mean()) / math.sqrt((pe * (1 - pe)).sum() / n ** 2)
        rows.append({"score": "other", "obs": float(o.mean()), "obs_ci": wilson(int(o.sum()), n), "exp": float(pe.mean()), "z": float(z)})
        # chi-square over the cells (+ other)
        chi = sum((r["obs"] - r["exp"]) ** 2 * n / r["exp"] for r in rows)
        sc[lab] = {"n": n, "rows": rows, "chi2": float(chi), "df": len(rows) - 1, "p_chi2": float(stats.chi2.sf(chi, len(rows) - 1))}
    out["scorelines"] = sc

    # goal-count dispersion (Pearson ratio against the model's own predictive variance) and marginal count distributions
    disp = {}
    for lab, mk in [("Europe (big-5 + UCL)", (A.pool == "eu").values), ("Site leagues (EPL + La Liga + Ligue 1)", A.comp.isin(SITE3).values), ("Saudi Pro League", (A.pool == "spl").values),
                    ("Premier League", (A.comp == "epl").values), ("La Liga", (A.comp == "laliga").values), ("Ligue 1", (A.comp == "ligue1").values),
                    ("Bundesliga", (A.comp == "bundesliga").values), ("Serie A", (A.comp == "seriea").values), ("Champions League", (A.comp == "ucl").values)]:
        s = A[mk]; n = len(s); ix = bidx(n)
        eh, ea = s.eh.values, s.ea.values
        sqh, sqa = (s.hg.values - eh) ** 2, (s.ag.values - ea) ** 2
        tot_var = s.vh.values + s.va.values + 2 * s.cv.values
        sqt = (s.hg.values + s.ag.values - eh - ea) ** 2
        def ratio(num, den):
            r = num[ix].sum(1) / den[ix].sum(1)
            return [float(num.sum() / den.sum()), float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))]
        za = (s.hg.values - eh) / np.sqrt(s.vh.values); zb = (s.ag.values - ea) / np.sqrt(s.va.values)
        mom = np.column_stack([za, zb, za * zb, za ** 2, zb ** 2])[ix].mean(1)
        cor = (mom[:, 2] - mom[:, 0] * mom[:, 1]) / np.sqrt((mom[:, 3] - mom[:, 0] ** 2) * (mom[:, 4] - mom[:, 1] ** 2))
        c0 = float(np.corrcoef(za, zb)[0, 1])
        disp[lab] = {"n": n, "home": ratio(sqh, s.vh.values), "away": ratio(sqa, s.va.values), "total": ratio(sqt, tot_var),
                     "resid_corr": [c0, float(np.percentile(cor, 2.5)), float(np.percentile(cor, 97.5))]}
    out["dispersion"] = disp
    gc = {}
    for lab, mk in [("Europe (big-5 + UCL)", (A.pool == "eu").values), ("Saudi Pro League", (A.pool == "spl").values)]:
        s = A[mk]; Gm = G[mk]; n = len(s)
        kmax = 5
        rowsT, rowsG = [], []
        side = np.r_[s.hg.values, s.ag.values]; marg = np.concatenate([Gm.sum(2), Gm.sum(1)])  # (2n, 9)
        for k in range(kmax + 1):
            ob = (side >= k) if k == kmax else (side == k)
            ex = marg[:, k:].sum(1) if k == kmax else marg[:, k]
            rowsG.append({"k": f"{k}+" if k == kmax else str(k), "obs": float(ob.mean()), "ci": wilson(int(ob.sum()), len(side)), "exp": float(ex.mean())})
        tot = s.hg.values + s.ag.values
        tm = np.zeros((n, 9))
        for i in range(9):
            for j in range(9):
                if i + j < 9:
                    tm[:, i + j] += Gm[:, i, j]
        for k in range(7):
            ob = (tot >= k) if k == 6 else (tot == k)
            ex = tm[:, k:].sum(1) if k == 6 else tm[:, k]
            rowsT.append({"k": f"{k}+" if k == 6 else str(k), "obs": float(ob.mean()), "ci": wilson(int(ob.sum()), n), "exp": float(ex.mean())})
        gc[lab] = {"team_goals": rowsG, "total_goals": rowsT}
    out["goal_counts"] = gc
    return out


def boot_mean_sub(p, w, mk):
    return boot_mean(w[mk] - p[mk])


# ============================================================================= SECTION 5: variance / bias-variance
RIDGE_GRID = [0.01, 0.1, 0.3, 1, 3, 8, 20, 50, 150, 500]
XI_GRID = [0.0231, 0.0116, 0.0077, 0.0039, 0.0019, 0.00095, 0.00048, 0.0]
WIN_GRID = [182, 365, 730, 1095]


def val_metrics(rec, y=None):
    G, p = dc_probs(rec, 1.0)
    y = outcome(rec.hg.values, rec.ag.values)
    return losses(p, y)


def sec_variance(eu):
    df, space, sel = eu["df"], eu["space"], eu["sel"]
    xi0, reg0 = sel["xi"], sel["reg"]
    out = {"shipped": {"xi": xi0, "reg": reg0}}
    # (a) ridge sweep, 2024-25 tuning season (selection season) and 2025-26 (report only)
    sweep = []
    for lam in RIDGE_GRID:
        row = {"reg": lam}
        for per_name, per in [("tune", TUNE), ("hold", REPORT)]:
            rec, ins = run_weekly(df, space, per, xi0, lam, insample=True)
            L = val_metrics(rec)
            row[per_name] = {"val_rps": boot_mean(L["rps"]), "val_ll": boot_mean(L["ll"]), "train_rps": float(ins[:, 0].mean()), "train_ll": float(ins[:, 1].mean()),
                             "sd_attack": float(rec.groupby("fold").sd_a.first().mean())}
        sweep.append(row)
    out["ridge_sweep"] = sweep
    # (b) learning curves: history length (shipped decay and no decay), 2025-26 holdout
    hist = []
    for win in WIN_GRID:
        row = {"window_days": win}
        for nm, xi in [("decay", xi0), ("nodecay", 0.0)]:
            rec, ins = run_weekly(df, space, REPORT, xi, reg0, win=win, insample=True)
            L = val_metrics(rec)
            ntr = [len(df[(df.dt < c) & (df.dt >= c - pd.Timedelta(days=win))]) for c in rec.fold.unique()]
            row[nm] = {"val_rps": boot_mean(L["rps"]), "val_ll": boot_mean(L["ll"]), "train_rps": float(ins[:, 0].mean()), "n_train_mean": float(np.mean(ntr))}
        hist.append(row)
    out["history_length"] = hist
    hl = []
    for xi in XI_GRID:
        row = {"xi": xi, "half_life_days": (math.log(2) / xi if xi > 0 else None)}
        for per_name, per in [("tune", TUNE), ("hold", REPORT)]:
            rec, ins = run_weekly(df, space, per, xi, reg0, insample=True)
            L = val_metrics(rec)
            row[per_name] = {"val_rps": boot_mean(L["rps"]), "val_ll": boot_mean(L["ll"]), "train_rps": float(ins[:, 0].mean())}
        hl.append(row)
    out["half_life"] = hl
    return out


def sec_stability(eu, m, locks):
    """Bootstrap refits at the live snapshot (cutoff 2026-10-19, the fit behind the three featured predictions)."""
    df, space, sel = eu["df"], eu["space"], eu["sel"]
    cutoff = pd.Timestamp("2026-10-19")
    train = df[df.dt < cutoff]
    fit0 = fit_at(space, train, cutoff, sel["xi"], sel["reg"])
    el, (t0, t1, bb), gcoef = elo_models(train)
    feats = json.load(open(os.path.join(ROOT, "inputs", "fixtures_featured.json")))
    comp_ix = space.cix
    def predict(fit, home, away, comp, w):
        hi, ai, ci = space.tix[home], space.tix[away], comp_ix[comp]
        lh, la = lambdas(fit, np.array([hi]), np.array([ai]), ci); lh, la = float(lh[0]), float(la[0])
        if w < 1:
            x = (el.get(home) - el.get(away) + el.H) / 400.0
            sup = gcoef[0] + gcoef[1] * x; T = lh + la
            leh, lea = max((T + sup) / 2, 0.2), max((T - sup) / 2, 0.2)
            lh = math.exp(w * math.log(lh) + (1 - w) * math.log(leh)); la = math.exp(w * math.log(la) + (1 - w) * math.log(lea))
        G = score_grids(np.array([lh]), np.array([la]), fit.rho)
        return grid_wdl(G)[0]
    games = []
    for f in feats:
        w_ship = sel["w_ucl"] if f["comp"] == "ucl" else sel["w"]
        games.append({"id": f["match_id"], "home": f["home"], "away": f["away"], "comp": f["comp"], "w_ship": w_ship})
    lk = {x["match_id"]: x for x in locks["matches"]}
    for g in games:
        g["point_dc"] = predict(fit0, g["home"], g["away"], g["comp"], 1.0).tolist()
        g["point_base"] = predict(fit0, g["home"], g["away"], g["comp"], g["w_ship"]).tolist()
        lb = lk[g["id"]]["base"]
        g["locked_base"] = [lb["p_home"], lb["p_draw"], lb["p_away"]]
        g["locked_adjusted"] = [lk[g["id"]]["headline"]["p_home"], lk[g["id"]]["headline"]["p_draw"], lk[g["id"]]["headline"]["p_away"]]
        g["repro_max_abs_diff"] = float(np.abs(np.array(g["point_base"]) - np.array(g["locked_base"])).max())
    # bootstrap refits: resample training matches with replacement, keep each match's date (so its time-decay weight)
    rng = np.random.RandomState(SEED)
    nT = len(space.teams)
    A_, D_, S_, preds_dc, preds_base, rhos, etas = [], [], [], [], [], [], []
    t = time.time()
    for b in range(B_FIT):
        tb = train.iloc[rng.randint(0, len(train), len(train))]
        fb = fit_at(space, tb, cutoff, sel["xi"], sel["reg"], x0=fit0.x)
        A_.append(fb.a); D_.append(fb.d); S_.append(fb.s[space.team_league]); rhos.append(fb.rho); etas.append(fb.eta)
        preds_dc.append([predict(fb, g["home"], g["away"], g["comp"], 1.0) for g in games])
        preds_base.append([predict(fb, g["home"], g["away"], g["comp"], g["w_ship"]) for g in games])
    A_, D_, S_ = np.array(A_), np.array(D_), np.array(S_)
    preds_dc, preds_base = np.array(preds_dc), np.array(preds_base)
    for gi, g in enumerate(games):
        for key, arr in [("boot_dc", preds_dc), ("boot_base", preds_base)]:
            g[key] = {o: {"median": float(np.median(arr[:, gi, k])), "lo": float(np.percentile(arr[:, gi, k], 2.5)), "hi": float(np.percentile(arr[:, gi, k], 97.5)),
                          "sd": float(arr[:, gi, k].std(ddof=1))} for k, o in enumerate(OUT_LAB)}
    # ratings
    recent = pd.concat([train[train.dt >= cutoff - pd.Timedelta(days=365)].home, train[train.dt >= cutoff - pd.Timedelta(days=365)].away]).value_counts()
    a0, d0, s0 = fit0.a, fit0.d, fit0.s[space.team_league]
    net0 = a0 + d0 + s0
    net_b = A_ + D_ + S_
    rows = []
    for t_, i in space.tix.items():
        nrec = int(recent.get(t_, 0))
        if nrec < 10:
            continue
        rows.append({"team": t_, "n_recent": nrec, "attack": float(a0[i]), "attack_sd": float(A_[:, i].std(ddof=1)), "attack_lo": float(np.percentile(A_[:, i], 2.5)), "attack_hi": float(np.percentile(A_[:, i], 97.5)),
                     "defence": float(d0[i]), "defence_sd": float(D_[:, i].std(ddof=1)), "defence_lo": float(np.percentile(D_[:, i], 2.5)), "defence_hi": float(np.percentile(D_[:, i], 97.5)),
                     "net": float(net0[i]), "net_sd": float(net_b[:, i].std(ddof=1)), "net_lo": float(np.percentile(net_b[:, i], 2.5)), "net_hi": float(np.percentile(net_b[:, i], 97.5))})
    T = pd.DataFrame(rows).sort_values("net", ascending=False).reset_index(drop=True)
    T["rank"] = np.arange(1, len(T) + 1)
    rank_b = (-net_b[:, [space.tix[t_] for t_ in T.team]]).argsort(1).argsort(1) + 1
    T["rank_lo"] = np.percentile(rank_b, 2.5, axis=0); T["rank_hi"] = np.percentile(rank_b, 97.5, axis=0)
    summ = {"n_teams": int(len(T)), "bootstrap_fits": B_FIT, "n_train": int(len(train)),
            "median_sd_attack": float(T.attack_sd.median()), "median_sd_defence": float(T.defence_sd.median()), "median_sd_net": float(T.net_sd.median()),
            "between_team_sd_attack": float(T.attack.std()), "between_team_sd_defence": float(T.defence.std()), "between_team_sd_net": float(T.net.std()),
            "reliability_attack": float(1 - (T.attack_sd ** 2).mean() / T.attack.var()), "reliability_defence": float(1 - (T.defence_sd ** 2).mean() / T.defence.var()),
            "reliability_net": float(1 - (T.net_sd ** 2).mean() / T.net.var()),
            "corr_logn_sd_attack": float(np.corrcoef(np.log(T.n_recent), T.attack_sd)[0, 1]),
            "sd_attack_few_matches": float(T[T.n_recent < 25].attack_sd.median()) if (T.n_recent < 25).any() else None,
            "sd_attack_many_matches": float(T[T.n_recent >= 40].attack_sd.median()) if (T.n_recent >= 40).any() else None,
            "n_few": int((T.n_recent < 25).sum()), "n_many": int((T.n_recent >= 40).sum()),
            "rho_point": float(fit0.rho), "rho_boot": [float(np.mean(rhos)), float(np.percentile(rhos, 2.5)), float(np.percentile(rhos, 97.5))],
            "eta_point": float(fit0.eta), "eta_boot": [float(np.mean(etas)), float(np.percentile(etas, 2.5)), float(np.percentile(etas, 97.5))],
            "seconds": float(time.time() - t)}
    names = ["Paris Saint-Germain", "Barcelona", "Bayern Munich", "Arsenal", "Real Madrid"]
    featured_teams = T[T.team.isin(names)].to_dict("records")
    return {"games": games, "summary": summ, "featured_teams": featured_teams, "table": T.round(5).to_dict("records")}


# ============================================================================= SECTION 6: ablations
def sec_ablations(A, G, eu, spl):
    rec_eu, df_eu, space_eu, sel = eu["rec"], eu["df"], eu["space"], eu["sel"]
    xi, reg = sel["xi"], sel["reg"]
    ae = A[A.pool == "eu"].reset_index(drop=True)
    y = ae.y.values
    elo_sup = ae.elo_sup.values
    shipped = {k: ae[k].values for k in ["rps", "ll"]}
    isu = (ae.comp == "ucl").values
    variants = {}   # name -> (desc, per-match rps, per-match ll, mask-of-matches-it-applies-to)

    def add(name, desc, p, mask=None):
        L = losses(p, y)
        variants[name] = {"desc": desc, "rps": L["rps"], "ll": L["ll"], "mask": np.ones(len(y), bool) if mask is None else mask}

    # -- refit variants (weekly)
    r = run_weekly(df_eu, space_eu, REPORT, 0.0, reg); aligned(rec_eu, r)
    add("No time decay", "xi = 0 (every match weighted equally); other settings as shipped", mixed(r, elo_sup, 1.0, sel["w_ucl"])[1])
    r = run_weekly(df_eu, space_eu, REPORT, xi, reg, no_rho=True); aligned(rec_eu, r)
    add("No Dixon-Coles rho correction", "rho fixed at 0 in the fit and in the score grid", mixed(r, elo_sup, 1.0, sel["w_ucl"])[1])
    r = run_weekly(df_eu, space_eu, REPORT, xi, 0.01); aligned(rec_eu, r)
    add("No ridge", "team ridge 0.01 instead of 3 (exactly 0 is not identified: attack and defence are only fixed relative to each other)", mixed(r, elo_sup, 1.0, sel["w_ucl"])[1])
    # -- Elo-leg variants (no refit: the shipped DC fit, different blend)
    rs = pd.DataFrame({"lh": ae.lam_h.values, "la": ae.lam_a.values, "rho": ae.rho.values, "comp": ae.comp.values})
    add("No Elo leg (Dixon-Coles only everywhere)", "w = 1 in the Champions League too (shipped: w = 0.3 there)", mixed(rs, elo_sup, 1.0, 1.0)[1])
    add("+ Elo leg in domestic matches, w = 0.8", "the best blend on 2024-25, which missed the pre-registered 0.0005 RPS bar", mixed(rs, elo_sup, 0.8, sel["w_ucl"])[1])
    add("+ Elo leg in domestic matches, w = 0.3", "the Champions League weight applied to every match", mixed(rs, elo_sup, 0.3, sel["w_ucl"])[1])
    # -- no UCL link, joint fit without UCL matches in training; evaluated on domestic AND ucl (ucl: pure DC)
    r = run_weekly(df_eu, space_eu, REPORT, xi, reg, drop_ucl=True); aligned(rec_eu, r)
    add("Joint fit without Champions League results (no cross-league link)", "same weights as shipped (w = 1 domestic, w = 0.3 in the Champions League); only the Champions League results are withheld from the Dixon-Coles fit", mixed(r, elo_sup, 1.0, sel["w_ucl"])[1])
    nolink_pure = mixed(r, elo_sup, 1.0, 1.0)[1]
    # -- per-league fits without the UCL link (domestic only)
    parts = []
    for c in ["epl", "laliga", "ligue1", "bundesliga", "seriea"]:
        dl = df_eu[df_eu.comp == c].reset_index(drop=True)
        rr = run_weekly(dl, Space(dl, [c]), REPORT, xi, reg)
        parts.append(rr)
    pl = pd.concat(parts, ignore_index=True)
    key = ae[["comp", "date", "home", "away"]].copy(); key["date"] = key["date"].dt.strftime("%Y-%m-%d"); key["i"] = np.arange(len(key))
    pl["date"] = pd.to_datetime(pl["date"]).dt.strftime("%Y-%m-%d")
    mg = key.merge(pl[["comp", "date", "home", "away", "lh", "la", "rho"]], on=["comp", "date", "home", "away"], how="left")
    dom = ~isu
    assert mg.lh[dom].notna().all() and len(mg) == len(key)
    mgf = mg.copy()
    for c_, v_ in [("lh", 1.3), ("la", 1.1), ("rho", 0.0)]:
        mgf.loc[isu, c_] = v_   # placeholders: the UCL rows are masked out of this variant
    G2, p2 = dc_probs(mgf.assign(comp="x"), 1.0)
    add("Per-league fits (no link, own rho and home advantage)", "five separate Dixon-Coles fits (one per league), no Champions League data; evaluated on the 1,751 domestic matches only", p2, mask=dom)

    # results
    res = {"europe": {}, "shipped_rps": float(shipped["rps"].mean()), "shipped_ll": float(shipped["ll"].mean())}
    for nm, v in variants.items():
        mk = v["mask"]
        ref_r, ref_l = shipped["rps"][mk], shipped["ll"][mk]
        res["europe"][nm] = {"desc": v["desc"], "n": int(mk.sum()), "rps": float(v["rps"][mk].mean()), "ref_rps": float(ref_r.mean()),
                             "d_rps": compare(v["rps"][mk], ref_r), "d_ll": compare(v["ll"][mk], ref_l)}
    # ucl-only comparison of the link (pure Dixon-Coles, w = 1, where the link matters most, and as shipped, w = 0.3)
    mk = isu
    Lp = losses(nolink_pure, y)
    dc_link = variants["No Elo leg (Dixon-Coles only everywhere)"]
    res["ucl_link"] = {"n": int(mk.sum()),
                       "shipped_blend_with_link": float(shipped["rps"][mk].mean()),
                       "blend_no_link": float(variants["Joint fit without Champions League results (no cross-league link)"]["rps"][mk].mean()),
                       "d_blend_no_link_vs_link": compare(variants["Joint fit without Champions League results (no cross-league link)"]["rps"][mk], shipped["rps"][mk]),
                       "dc_with_link": float(dc_link["rps"][mk].mean()), "dc_no_link": float(Lp["rps"][mk].mean()),
                       "d_dc_no_link_vs_link": compare(Lp["rps"][mk], dc_link["rps"][mk])}
    # domestic-only comparison for the 'no link' joint fit vs shipped
    dm_ = ~isu
    res["domestic_n"] = int(dm_.sum())
    res["domestic"] = {}
    for nm in ["Joint fit without Champions League results (no cross-league link)"]:
        v = variants[nm]
        res["domestic"][nm] = {"rps": float(v["rps"][dm_].mean()), "ref_rps": float(shipped["rps"][dm_].mean()), "d_rps": compare(v["rps"][dm_], shipped["rps"][dm_]), "d_ll": compare(v["ll"][dm_], shipped["ll"][dm_])}

    # --- Saudi
    asp = A[A.pool == "spl"].reset_index(drop=True)
    rec_s, df_s, space_s, sel_s = spl["rec"], spl["df"], spl["space"], spl["sel"]
    ys = asp.y.values; es = asp.elo_sup.values
    rs_ship = {k: asp[k].values for k in ["rps", "ll"]}
    sp = {}
    def adds(name, desc, p):
        L = losses(p, ys)
        sp[name] = {"desc": desc, "n": len(ys), "rps": float(L["rps"].mean()), "ref_rps": float(rs_ship["rps"].mean()), "d_rps": compare(L["rps"], rs_ship["rps"]), "d_ll": compare(L["ll"], rs_ship["ll"])}
    xs, rg = sel_s["xi"], sel_s["reg"]
    r = run_weekly(df_s, space_s, REPORT, 0.0, rg); aligned(rec_s, r)
    adds("No time decay", "xi = 0 (the slow-decay pass that fixes rho is unchanged)", mixed(r.assign(comp="spl"), es, sel_s["w"], sel_s["w"])[1])
    r = run_weekly(df_s, space_s, REPORT, xs, rg, no_rho=True); aligned(rec_s, r)
    adds("No Dixon-Coles rho correction", "rho = 0", mixed(r.assign(comp="spl"), es, sel_s["w"], sel_s["w"])[1])
    r = run_weekly(df_s, space_s, REPORT, xs, 0.01); aligned(rec_s, r)
    adds("No ridge", "team ridge 0.01 instead of 8", mixed(r.assign(comp="spl"), es, sel_s["w"], sel_s["w"])[1])
    rss = pd.DataFrame({"lh": asp.lam_h.values, "la": asp.lam_a.values, "rho": asp.rho.values, "comp": "spl"})
    adds("No Elo leg (Dixon-Coles only)", "w = 1 (shipped: w = 0.3)", mixed(rss, es, 1.0, 1.0)[1])
    adds("Elo leg weight 0.6", "w = 0.6", mixed(rss, es, 0.6, 0.6)[1])
    res["saudi"] = sp
    res["saudi_shipped_rps"] = float(rs_ship["rps"].mean())
    return res


def sec_recal(A, eu, spl):
    """Diagnostic only (nothing is shipped from it): would a one-parameter sharpening p' ~ p^T, with T fitted on the 2024-25 tuning
    season, have helped on the 2025-26 holdout?"""
    from scipy.optimize import minimize_scalar
    out = {}
    for pool, P, lab in [("eu", eu, "Europe (big-5 + UCL)"), ("spl", spl, "Saudi Pro League")]:
        sel = P["sel"]
        rec_t = run_period(pool, P["df"], P["space"], TUNE, [(sel["xi"], sel["reg"])], verbose=False)
        tag = f"{sel['xi']}_{sel['reg']}"
        G_t = blended_grids(rec_t, tag, sel["w"])
        if "w_ucl" in sel and sel["w_ucl"] != sel["w"]:
            Gu = blended_grids(rec_t, tag, sel["w_ucl"]); isu = (rec_t.comp == "ucl").values; G_t[isu] = Gu[isu]
        p_t = grid_wdl(G_t); y_t = outcome(rec_t.hg.values, rec_t.ag.values)
        sharpen = lambda p, t: (p ** t) / (p ** t).sum(1, keepdims=True)
        T = float(minimize_scalar(lambda t: logloss(sharpen(p_t, t), y_t).mean(), bounds=(0.5, 2.0), method="bounded").x)
        s = A[A.pool == pool]
        p_h = s[["ph", "pd", "pa"]].values; y = s.y.values
        L0, L1 = losses(p_h, y), losses(sharpen(p_h, T), y)
        out[lab] = {"T": T, "n_tune": int(len(y_t)), "n": int(len(y)), "rps_before": float(L0["rps"].mean()), "rps_after": float(L1["rps"].mean()),
                    "d_rps": compare(L1["rps"], L0["rps"]), "d_ll": compare(L1["ll"], L0["ll"]), "acc_before": float(L0["acc"].mean()), "acc_after": float(L1["acc"].mean())}
    return out


# ============================================================================= SECTION 7: error analysis
def sec_errors(A, G, eu, spl, m):
    out = {}
    names = ["Home win", "Draw", "Away win"]
    # confusion matrices
    for lab, mk in [("Europe (big-5 + UCL)", (A.pool == "eu").values), ("Saudi Pro League", (A.pool == "spl").values)]:
        s = A[mk]; pred = s[["ph", "pd", "pa"]].values.argmax(1); y = s.y.values
        cm = np.zeros((3, 3), int)
        for a_, b_ in zip(y, pred):
            cm[a_, b_] += 1
        out.setdefault("confusion", {})[lab] = {"matrix": cm.tolist(), "n": int(len(s)),
                                                  "recall": [float(cm[i, i] / cm[i].sum()) if cm[i].sum() else None for i in range(3)],
                                                  "precision": [float(cm[i, i] / cm[:, i].sum()) if cm[:, i].sum() else None for i in range(3)],
                                                  "pred_share": [float((pred == i).mean()) for i in range(3)], "actual_share": [float((y == i).mean()) for i in range(3)],
                                                  "recall_ci": [wilson(int(cm[i, i]), int(cm[i].sum())) if cm[i].sum() else None for i in range(3)]}
    eu_mk = (A.pool == "eu").values
    ae = A[eu_mk].reset_index(drop=True)
    sp_mk = (A.pool == "spl").values
    # by month
    ae["month"] = ae.date.dt.strftime("%Y-%m")
    rows = []
    for mo, s in ae.groupby("month"):
        k = int(s.acc.sum()); rows.append({"month": mo, "n": int(len(s)), "acc": k / len(s), "acc_ci": wilson(k, len(s)), "rps": boot_mean(s.rps.values), "ll": float(s.ll.mean())})
    out["by_month"] = rows
    early = ae.date.dt.month.isin([8, 9, 10]).values
    out["early_vs_rest"] = {"early_months": "Aug-Oct", "n_early": int(early.sum()), "n_rest": int((~early).sum()),
                            "rps_early": float(ae.rps[early].mean()), "rps_rest": float(ae.rps[~early].mean()),
                            "diff": boot_diff_two(ae.rps.values[early], ae.rps.values[~early]),
                            "acc_early": float(ae.acc[early].mean()), "acc_rest": float(ae.acc[~early].mean()),
                            "ll_diff": boot_diff_two(ae.ll.values[early], ae.ll.values[~early])}
    mon = ae.date.dt.month.values
    for nm, mk in [("may", mon == 5), ("apr_may", np.isin(mon, [4, 5]))]:
        out[f"{nm}_vs_rest"] = {"n": int(mk.sum()), "rps": float(ae.rps[mk].mean()), "rps_rest": float(ae.rps[~mk].mean()), "diff": boot_diff_two(ae.rps.values[mk], ae.rps.values[~mk]),
                                "acc": float(ae.acc[mk].mean()), "acc_rest": float(ae.acc[~mk].mean())}
    # cold start measured by the number of same-season matches already played by the less-experienced team
    pdf = eu["df"]
    gh, ga = games_before(pdf, pdf, ae)
    ae["min_prior"] = np.minimum(gh, ga)
    edges = [(0, 2), (3, 5), (6, 9), (10, 19), (20, 99)]
    rows = []
    for lo, hi in edges:
        mk = ((ae.min_prior >= lo) & (ae.min_prior <= hi)).values
        s = ae[mk]; k = int(s.acc.sum())
        rows.append({"band": f"{lo}-{hi}" if hi < 99 else f"{lo}+", "n": int(mk.sum()), "acc": k / len(s), "acc_ci": wilson(k, len(s)), "rps": boot_mean(s.rps.values), "ll": float(s.ll.mean())})
    out["by_games_played"] = rows
    # favourite strength
    pf = np.maximum(ae.ph.values, ae.pa.values)
    rows = []
    for lo, hi in [(0, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]:
        mk = (pf >= lo) & (pf < hi); s = ae[mk]; k = int(s.acc.sum())
        rows.append({"band": f"{int(lo * 100)}-{min(int(hi * 100), 100)}%", "n": int(mk.sum()), "acc": k / len(s), "acc_ci": wilson(k, len(s)), "rps": boot_mean(s.rps.values), "ll": float(s.ll.mean()),
                     "draw_rate": float((s.y == 1).mean()), "p_draw": float(s.pd.mean())})
    out["by_fav_band"] = rows
    # by goal difference
    gd = (ae.hg - ae.ag).values
    rows = []
    for g in range(-3, 4):
        mk = (gd <= -3) if g == -3 else ((gd >= 3) if g == 3 else (gd == g))
        s = ae[mk]; k = int(s.acc.sum())
        pa_ = np.where(s.y.values == 0, s.ph.values, np.where(s.y.values == 1, s.pd.values, s.pa.values))
        rows.append({"gd": ("<= -3" if g == -3 else (">= +3" if g == 3 else f"{g:+d}")), "n": int(mk.sum()), "acc": k / len(s), "acc_ci": wilson(k, len(s)), "p_actual_outcome": float(pa_.mean()), "rps": float(s.rps.mean())})
    out["by_gd"] = rows
    # worst predicted
    def worst(Ax, df_pool, k):
        p_act = np.where(Ax.y.values == 0, Ax.ph.values, np.where(Ax.y.values == 1, Ax.pd.values, Ax.pa.values))
        order = np.argsort(p_act)[:k]
        gh_, ga_ = games_before(df_pool, df_pool, Ax)
        py = prior_year(df_pool, Ax.iloc[order])
        rows = []
        for rank_, i in enumerate(order):
            r = Ax.iloc[i]
            fav_home = r.ph >= r.pa; pf_ = max(r.ph, r.pa); fav = r.home if fav_home else r.away
            parts = []
            if r.y == 1:
                parts.append(f"{fav} favoured ({pf_:.0%}) but it was a draw")
            else:
                win = r.home if r.y == 0 else r.away
                lose = r.away if r.y == 0 else r.home
                parts.append(f"longshot {win} ({p_act[i]:.0%}) beat {lose} ({(r.pa if r.y == 0 else r.ph):.0%})" if (r.y == 0) == (not fav_home) else f"{win} won at {p_act[i]:.0%}")
            if abs(r.hg - r.ag) >= 3:
                parts.append(f"{int(abs(r.hg - r.ag))}-goal margin")
            mp = min(gh_[i], ga_[i])
            if mp <= 5:
                parts.append("early season (" + ("a team's first game of the season" if mp == 0 else f"a team had played only {int(mp)} earlier game" + ("s" if mp > 1 else "")) + ")")
            thin = [t for t, nn in zip([r.home, r.away], py[rank_]) if nn < 20]
            if thin:
                parts.append(f"thin history for {', '.join(thin)} (<20 pool matches in the prior year)")
            if r.comp == "ucl":
                parts.append("Champions League (Elo-blended)")
            rows.append({"rank": rank_ + 1, "date": r.date.strftime("%Y-%m-%d"), "comp": COMP_NAME[r.comp], "match": f"{r.home} {int(r.hg)}-{int(r.ag)} {r.away}",
                         "probs": f"{r.ph:.0%}/{r.pd:.0%}/{r.pa:.0%}", "p_actual": float(p_act[i]), "reason": "; ".join(parts),
                         "kind": "draw" if r.y == 1 else "longshot", "margin": int(abs(r.hg - r.ag)), "min_prior": int(mp), "thin": bool(thin), "ucl": bool(r.comp == "ucl"), "comp_key": r.comp,
                         "fav_p": float(pf_), "away_win": bool(r.y == 2)})
        return rows
    w15 = worst(ae, pdf, 15)
    out["worst15_europe"] = w15
    out["worst15_summary"] = {"n_draw": sum(r["kind"] == "draw" for r in w15), "n_longshot": sum(r["kind"] == "longshot" for r in w15),
                              "n_margin3": sum(r["margin"] >= 3 for r in w15), "n_margin2": sum(r["margin"] >= 2 for r in w15), "n_early": sum(r["min_prior"] <= 5 for r in w15),
                              "n_thin": sum(r["thin"] for r in w15), "n_ucl": sum(r["ucl"] for r in w15), "n_away_win": sum(r["away_win"] for r in w15),
                              "mean_fav_p": float(np.mean([r["fav_p"] for r in w15])), "p_actual_max": float(max(r["p_actual"] for r in w15)),
                              "share_early_all": float((ae.min_prior <= 5).mean()), "share_ucl_all": float((ae.comp == "ucl").mean()),
                              "comp_counts": pd.Series([r["comp_key"] for r in w15]).value_counts().to_dict(), "n_leagues_in_top15_unique": int(pd.Series([r["comp_key"] for r in w15]).nunique()),
                              "mean_margin": float(np.mean([r["margin"] for r in w15])), "mean_margin_all": float((ae.hg - ae.ag).abs().mean())}
    # tail check: how many realised outcomes had a predicted probability below t, against the number the probabilities themselves imply
    P3 = ae[["ph", "pd", "pa"]].values; pact = P3[np.arange(len(ae)), ae.y.values]
    out["tail_check"] = [{"t": t, "observed": int((pact < t).sum()), "expected": float(P3[P3 < t].sum())} for t in (0.12, 0.20, 0.30)]
    asp = A[sp_mk].reset_index(drop=True)
    out["worst5_saudi"] = worst(asp, spl["df"], 5)
    # goal-difference error distribution
    err = (ae.hg - ae.ag).values - (ae.eh - ae.ea).values
    q = np.percentile(err, [5, 25, 50, 75, 95])
    ix = bidx(len(err))
    # model-implied SD of the GD error: sqrt(mean variance of (H - A)) from the grids
    Ge = G[eu_mk]
    exp_sd = float(np.sqrt((ae.vh + ae.va - 2 * ae.cv).mean()))
    gdpmf = np.zeros((len(Ge), 17))
    for i in range(9):
        for j in range(9):
            gdpmf[:, i - j + 8] += Ge[:, i, j]
    gdobs = np.array([(gd == g).mean() for g in range(-5, 6)])
    gdexp = gdpmf.mean(0)[3:14]
    out["gd_error"] = {"n": int(len(err)), "mean": boot_mean(err), "sd": float(err.std(ddof=1)), "mae": boot_mean(np.abs(err)), "rmse": float(math.sqrt((err ** 2).mean())),
                       "skew": float(stats.skew(err)), "excess_kurtosis": float(stats.kurtosis(err)), "q": q.tolist(), "model_implied_sd": exp_sd,
                       "gd_values": list(range(-5, 6)), "gd_obs": gdobs.tolist(), "gd_exp": gdexp.tolist(), "err_hist_vals": err.tolist()}
    return out


def boot_diff_two(x, y):
    rng = np.random.RandomState(SEED)
    bx = rng.randint(0, len(x), size=(B, len(x))); by = rng.randint(0, len(y), size=(B, len(y)))
    d = x[bx].mean(1) - y[by].mean(1)
    return [float(x.mean() - y.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


# ============================================================================= FIGURES
def fig_headline(R):
    style()
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw={"width_ratios": [1.15, 1]})
    groups = list(R["baselines"].keys())
    models = [("Shipped model", C1), ("Elo only", C3), ("League base rates", C2), ("Uniform 1/3", "#8a8985")]
    off = np.linspace(-0.27, 0.27, len(models))
    for gi, g in enumerate(groups):
        for mi, (mn, col) in enumerate(models):
            v = R["baselines"][g]["models"][mn]["rps"]
            ax[0].errorbar(v[0], gi + off[mi], xerr=[[v[0] - v[1]], [v[2] - v[0]]], fmt="o", ms=5, color=col, lw=1.2, capsize=2, label=mn if gi == 0 else None)
    ax[0].set_yticks(range(len(groups))); ax[0].set_yticklabels([f"{g}\nn={R['baselines'][g]['n']}" for g in groups]); ax[0].invert_yaxis()
    ax[0].set_xlabel("RPS on 2025-26 holdout (lower is better), 95% bootstrap CI"); ax[0].set_title("Ranked probability score by model")
    ax[0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=4, fontsize=8)
    rows = []
    for g in groups:
        for b in ["League base rates", "Elo only", "Dixon-Coles only (w=1)"]:
            rows.append((g, b, R["baselines"][g]["tests"][b]["rps"]))
    cols = {"League base rates": C2, "Elo only": C3, "Dixon-Coles only (w=1)": C4}
    ypos = 0; ticks = []; labs = []
    for g in groups:
        for b in ["League base rates", "Elo only", "Dixon-Coles only (w=1)"]:
            t = R["baselines"][g]["tests"][b]["rps"]
            ax[1].errorbar(t["diff"], ypos, xerr=[[t["diff"] - t["lo"]], [t["hi"] - t["diff"]]], fmt="o", ms=5, color=cols[b], lw=1.2, capsize=2, label=b if g == groups[0] else None)
            ypos += 1
        ticks.append(ypos - 2); labs.append(g.split(" (")[0]); ypos += 0.7
    ax[1].axvline(0, color=INK2, lw=0.8)
    ax[1].set_yticks(ticks); ax[1].set_yticklabels(labs); ax[1].invert_yaxis()
    ax[1].set_xlabel("RPS difference, shipped minus comparison (negative = shipped better)"); ax[1].set_title("Paired bootstrap on per-match RPS")
    ax[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3, fontsize=8)
    fig.tight_layout(); savefig(fig, "fig01_headline_and_baselines.png")


def fig_reliability(R):
    style()
    fig, axs = plt.subplots(2, 3, figsize=(11, 7))
    for ri, g in enumerate(["Europe (big-5 + UCL)", "Saudi Pro League"]):
        for ci, lab in enumerate(["Home win", "Draw", "Away win"]):
            ax = axs[ri, ci]; c = R["calibration"][g][lab]
            pr = np.array([b["pred"] for b in c["bins"]]); ob = np.array([b["obs"] for b in c["bins"]])
            lo = np.array([b["lo"] for b in c["bins"]]); hi = np.array([b["hi"] for b in c["bins"]])
            lim = (max(0.0, min(pr.min(), lo.min()) - 0.03), max(pr.max(), hi.max()) + 0.03)
            ax.plot(lim, lim, color=INK2, lw=0.8, ls="--")
            ax.errorbar(pr, ob, yerr=[ob - lo, hi - ob], fmt="o-", color=C1, ms=4.5, lw=1.2, capsize=2)
            ax.set_xlim(lim); ax.set_ylim(lim)
            ax.set_xlabel("mean predicted probability (decile bin)"); ax.set_ylabel("observed frequency")
            ax.set_title(f"{lab}: {g.split(' (')[0]}")
            ax.text(0.04, 0.95, f"ECE {c['ece']:.3f} (null mean {c['ece_null_mean']:.3f})\nslope {c['slope'][0]:.2f} [{c['slope'][1]:.2f}, {c['slope'][2]:.2f}]\nn = {R['baselines'][g]['n']}",
                    transform=ax.transAxes, va="top", fontsize=8, color=INK)
    fig.suptitle("Reliability diagrams (10 equal-count bins, Wilson 95% intervals on the observed frequency)", x=0.01, ha="left", fontsize=10, color=INK2)
    fig.tight_layout(); savefig(fig, "fig03_reliability.png")


def fig_draw(R):
    style()
    fig, ax = plt.subplots(1, 2, figsize=(10.5, 3.8))
    for g, col, dx in [("Europe (big-5 + UCL)", C1, -0.004), ("Site leagues (EPL + La Liga + Ligue 1)", C3, 0.0), ("Saudi Pro League", C2, 0.004)]:
        bins = R["calibration"][g]["draw_5bins"]
        pr = np.array([b["pred"] for b in bins]) + dx; ob = np.array([b["obs"] for b in bins]); lo_ = np.array([b["lo"] for b in bins]); hi_ = np.array([b["hi"] for b in bins])
        ax[0].errorbar(pr, ob, yerr=[ob - lo_, hi_ - ob], fmt="o-", color=col, ms=4, lw=1.1, capsize=2, label=g.split(" (")[0])
    lo = 0.05; hi = 0.45
    ax[0].plot([lo, hi], [lo, hi], color=INK2, lw=0.8, ls="--"); ax[0].set_xlim(lo, hi); ax[0].set_ylim(lo, hi)
    ax[0].set_xlabel("mean predicted P(draw), 5 equal-count bins"); ax[0].set_ylabel("observed draw frequency"); ax[0].set_title("Draw probability: reliability"); ax[0].legend(fontsize=8)
    rows = R["calibration"]["draw_by_closeness_europe"]
    x = np.arange(len(rows)); w = 0.36
    ax[1].bar(x - w / 2, [r["pred"] for r in rows], w, color=C1, label="predicted P(draw)")
    ob = np.array([r["obs"] for r in rows]); ci = np.array([r["ci"] for r in rows])
    ax[1].bar(x + w / 2, ob, w, color=C2, label="observed draw rate")
    ax[1].errorbar(x + w / 2, ob, yerr=[ob - ci[:, 0], ci[:, 1] - ob], fmt="none", color=INK, lw=1, capsize=2)
    ax[1].set_xticks(x); ax[1].set_xticklabels([f"{r['band']}\nn={r['n']}" for r in rows], fontsize=8)
    ax[1].set_xlabel("closeness |P(home) - P(away)|"); ax[1].set_ylabel("draw rate"); ax[1].set_title("Draws by how close the match is (Europe)"); ax[1].legend(fontsize=8)
    fig.tight_layout(); savefig(fig, "fig04_draw_calibration.png")


def fig_bias(R):
    style()
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.2, 1]})
    labs = list(R["bias"]["goals"].keys())
    off = {"home": -0.25, "away": 0.0, "total": 0.25}; col = {"home": C1, "away": C3, "total": C2}
    for k in ["home", "away", "total"]:
        for i, l in enumerate(labs):
            e = R["bias"]["goals"][l][k]["err"]
            ax[0].errorbar(e[0], i + off[k], xerr=[[e[0] - e[1]], [e[2] - e[0]]], fmt="o", ms=4, color=col[k], lw=1, capsize=2, label=f"{k} goals" if i == 0 else None)
    ax[0].axvline(0, color=INK2, lw=0.8)
    ax[0].set_yticks(range(len(labs))); ax[0].set_yticklabels([l.split(" (")[0] for l in labs], fontsize=8); ax[0].invert_yaxis()
    ax[0].set_xlabel("predicted minus actual mean goals per match, 95% CI"); ax[0].set_title("Goal-level bias by league"); ax[0].legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    rows = R["bias"]["side_bands"]
    x = np.arange(len(rows)); pr = np.array([r["pred"] for r in rows]); ob = np.array([r["obs"] for r in rows]); ci = np.array([r["ci"] for r in rows])
    ax[1].axhline(0, color=INK2, lw=0.8)
    ax[1].errorbar(x, ob - pr, yerr=[ob - ci[:, 0], ci[:, 1] - ob], fmt="o", ms=5, color=C1, lw=1.2, capsize=2)
    ax[1].set_xticks(x); ax[1].set_xticklabels([f"{r['band']}\nn={r['n']}" for r in rows], fontsize=7)
    ax[1].set_xlabel("predicted win probability of a team (each match counts twice)"); ax[1].set_ylabel("observed minus predicted win rate")
    ax[1].set_title("Favourite-longshot pattern (Europe)")
    fig.tight_layout(); savefig(fig, "fig05_bias.png")


def fig_scorelines(R):
    style()
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8), gridspec_kw={"width_ratios": [1.15, 1.15, 0.8]})
    for a, g in zip(ax[:2], ["Europe (big-5 + UCL)", "Saudi Pro League"]):
        rows = R["bias"]["scorelines"][g]["rows"]
        x = np.arange(len(rows)); ob = np.array([r["obs"] for r in rows]); ci = np.array([r["obs_ci"] for r in rows]); ex = np.array([r["exp"] for r in rows])
        a.errorbar(x, ob, yerr=[ob - ci[:, 0], ci[:, 1] - ob], fmt="o", color=C2, ms=4, lw=1, capsize=2, label="observed (95% CI)")
        a.scatter(x, ex, marker="_", s=180, color=C1, lw=2, label="model expected", zorder=3)
        a.set_xticks(x); a.set_xticklabels([r["score"] for r in rows], rotation=60, fontsize=8)
        a.set_ylabel("share of matches"); a.set_title(f"Scorelines: {g.split(' (')[0]}"); a.legend(fontsize=8)
    rows = R["bias"]["goal_counts"]["Europe (big-5 + UCL)"]["total_goals"]
    x = np.arange(len(rows)); ob = np.array([r["obs"] for r in rows]); ci = np.array([r["ci"] for r in rows]); ex = np.array([r["exp"] for r in rows])
    ax[2].errorbar(x, ob, yerr=[ob - ci[:, 0], ci[:, 1] - ob], fmt="o", color=C2, ms=4, lw=1, capsize=2, label="observed")
    ax[2].scatter(x, ex, marker="_", s=180, color=C1, lw=2, label="model expected", zorder=3)
    ax[2].set_xticks(x); ax[2].set_xticklabels([r["k"] for r in rows]); ax[2].set_xlabel("total goals in the match"); ax[2].set_title("Total goals (Europe)"); ax[2].legend(fontsize=8, loc="upper right")
    fig.tight_layout(); savefig(fig, "fig06_scorelines.png")


def fig_ridge(R):
    style()
    sw = R["variance"]["ridge_sweep"]
    x = [r["reg"] for r in sw]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.9))
    for a, key, ttl in [(ax[0], "val_rps", "RPS"), (ax[1], "val_ll", "log-loss")]:
        tr = [r["tune"]["train_rps" if key == "val_rps" else "train_ll"] for r in sw]
        vt = np.array([r["tune"][key] for r in sw]); vh = np.array([r["hold"][key] for r in sw])
        a.plot(x, tr, "o-", color=C3, ms=4, lw=1.3, label="train (in-sample, decay-weighted)")
        a.plot(x, vt[:, 0], "o-", color=C1, ms=4, lw=1.3, label="validation 2024-25 (tuning season)")
        a.fill_between(x, vt[:, 1], vt[:, 2], color=C1, alpha=0.15, lw=0)
        a.plot(x, vh[:, 0], "o--", color=C2, ms=4, lw=1.3, label="2025-26 holdout (report only)")
        a.fill_between(x, vh[:, 1], vh[:, 2], color=C2, alpha=0.15, lw=0)
        a.axvline(3, color=INK2, lw=0.8, ls=":"); a.text(3.1, a.get_ylim()[0], " shipped (3)", fontsize=8, color=INK2, va="bottom")
        a.set_xscale("log"); a.set_xlabel("ridge lambda (log scale; left = flexible, right = rigid)"); a.set_ylabel(ttl)
        a.set_title(f"Regularisation sweep: {ttl}"); a.legend(fontsize=7.5, loc="best")
    fig.tight_layout(); savefig(fig, "fig07_ridge_sweep.png")


def fig_learning(R):
    style()
    v = R["variance"]
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.9))
    h = v["history_length"]; x = [r["window_days"] / 365 for r in h]
    for nm, col, lab in [("decay", C1, "shipped decay (half-life 1 yr)"), ("nodecay", C2, "no decay")]:
        vv = np.array([r[nm]["val_rps"] for r in h])
        ax[0].plot(x, vv[:, 0], "o-", color=col, ms=4, lw=1.3, label=f"validation, {lab}")
        ax[0].fill_between(x, vv[:, 1], vv[:, 2], color=col, alpha=0.15, lw=0)
        ax[0].plot(x, [r[nm]["train_rps"] for r in h], "o--", color=col, ms=3, lw=1, alpha=0.7, label=f"train, {lab}")
    ax[0].set_xlabel("training history (years before each weekly cutoff; 3 = all data since Aug 2023)"); ax[0].set_ylabel("RPS (2025-26 holdout)"); ax[0].set_title("Learning curve: history length"); ax[0].legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2)
    hl = v["half_life"]
    xs = [r["half_life_days"] if r["half_life_days"] else 3200 for r in hl]
    for per, col, lab in [("tune", C1, "validation 2024-25 (tuning)"), ("hold", C2, "validation 2025-26 (holdout)")]:
        vv = np.array([r[per]["val_rps"] for r in hl])
        ax[1].plot(xs, vv[:, 0], "o-", color=col, ms=4, lw=1.3, label=lab); ax[1].fill_between(xs, vv[:, 1], vv[:, 2], color=col, alpha=0.15, lw=0)
    ax[1].plot(xs, [r["hold"]["train_rps"] for r in hl], "o--", color=C3, ms=3, lw=1, label="train (2025-26 folds)")
    ax[1].set_xscale("log"); ax[1].set_xticks(xs); ax[1].set_xticklabels([f"{int(round(r['half_life_days']))}d" if r["half_life_days"] else "none" for r in hl], fontsize=7.5)
    ax[1].minorticks_off(); ax[1].axvline(365, color=INK2, lw=0.8, ls=":")
    ax[1].set_xlabel("time-decay half-life (shipped: 365 days)"); ax[1].set_ylabel("RPS"); ax[1].set_title("Learning curve: time-decay half-life"); ax[1].legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
    fig.tight_layout(); savefig(fig, "fig08_learning_curves.png")


def fig_stability(R):
    style()
    st = R["stability"]
    fig, ax = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": [1, 1.1]})
    T = pd.DataFrame(st["table"]).head(25)
    feat = {"Paris Saint-Germain", "Barcelona", "Bayern Munich", "Arsenal", "Real Madrid"}
    y = np.arange(len(T))
    for i, r in T.iterrows():
        col = C2 if r.team in feat else C1
        ax[0].errorbar(r.net, i, xerr=[[r.net - r.net_lo], [r.net_hi - r.net]], fmt="o", ms=4, color=col, lw=1.1, capsize=2)
    ax[0].set_yticks(y); ax[0].set_yticklabels(T.team, fontsize=7.5); ax[0].invert_yaxis()
    ax[0].set_xlabel("overall strength (attack + defence + league offset, log-goal scale), 95% bootstrap band"); ax[0].set_title(f"Top 25 team ratings, {st['summary']['bootstrap_fits']} bootstrap refits (orange = featured clubs)")
    games = st["games"]; col = {"H": C1, "D": C4, "A": C3}; names = {"H": "home win", "D": "draw", "A": "away win"}
    short = {"Paris Saint-Germain": "PSG", "Bayern Munich": "Bayern"}
    ticks, labs = [], []
    for gi, g in enumerate(games):
        for vi, (key, lab) in enumerate([("boot_base", "shipped base"), ("boot_dc", "Dixon-Coles only")]):
            y0 = gi * 3.2 + vi * 1.15
            for k, o in enumerate(OUT_LAB):
                b_ = g[key][o]
                ax[1].errorbar(b_["median"], y0 + (k - 1) * 0.28, xerr=[[b_["median"] - b_["lo"]], [b_["hi"] - b_["median"]]], fmt="o", ms=4.5, color=col[o], lw=1.2, capsize=2,
                               label=names[o] if (gi == 0 and vi == 0) else None)
            ticks.append(y0); labs.append(f"{short.get(g['home'], g['home'])} v {short.get(g['away'], g['away'])}\n{lab}")
    ax[1].set_yticks(ticks); ax[1].set_yticklabels(labs, fontsize=7.5); ax[1].invert_yaxis()
    ax[1].set_xlabel("predicted probability: bootstrap median and 95% band (Elo leg held fixed in the shipped base)")
    ax[1].set_title("Prediction bands, three featured games (base, not adjusted)")
    ax[1].legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3)
    fig.tight_layout(); savefig(fig, "fig09_parameter_stability.png")


def fig_ablations(R):
    style()
    ab = R["ablations"]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1.5, 1]})
    items = [(k, v["d_rps"], v["n"]) for k, v in ab["europe"].items()]
    for i, (k, d, n) in enumerate(items):
        ax[0].errorbar(d["diff"], i, xerr=[[d["diff"] - d["lo"]], [d["hi"] - d["diff"]]], fmt="o", ms=5, color=C1, lw=1.2, capsize=2)
    ax[0].axvline(0, color=INK2, lw=0.8); ax[0].set_yticks(range(len(items))); ax[0].set_yticklabels([f"{k} (n={n})" for k, d, n in items], fontsize=7.5); ax[0].invert_yaxis()
    ax[0].set_xlabel("RPS difference vs shipped (positive = worse than shipped), 95% CI"); ax[0].set_title("Ablations: Europe, 2025-26 holdout")
    ax[0].xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(6))
    items = [(k, v["d_rps"]) for k, v in ab["saudi"].items()]
    for i, (k, d) in enumerate(items):
        ax[1].errorbar(d["diff"], i, xerr=[[d["diff"] - d["lo"]], [d["hi"] - d["diff"]]], fmt="o", ms=5, color=C3, lw=1.2, capsize=2)
    ax[1].axvline(0, color=INK2, lw=0.8); ax[1].set_yticks(range(len(items))); ax[1].set_yticklabels([k for k, _ in items], fontsize=7.5); ax[1].invert_yaxis()
    ax[1].set_xlabel("RPS difference vs shipped, 95% CI"); ax[1].set_title("Ablations: Saudi Pro League (n=306)")
    fig.tight_layout(); savefig(fig, "fig10_ablations.png")


def fig_errors(R):
    style()
    e = R["errors"]
    fig, ax = plt.subplots(1, 3, figsize=(13.5, 3.9), gridspec_kw={"width_ratios": [0.9, 1.3, 1.1]})
    cm = np.array(e["confusion"]["Europe (big-5 + UCL)"]["matrix"]); rp = cm / cm.sum(1, keepdims=True)
    ax[0].imshow(rp, cmap="Blues", vmin=0, vmax=0.8); ax[0].grid(False)
    for i in range(3):
        for j in range(3):
            ax[0].text(j, i, f"{cm[i, j]}\n{rp[i, j]:.0%}", ha="center", va="center", color="white" if rp[i, j] > 0.45 else INK, fontsize=9)
    ax[0].set_xticks(range(3)); ax[0].set_xticklabels(["pred H", "pred D", "pred A"]); ax[0].set_yticks(range(3)); ax[0].set_yticklabels(["actual H", "actual D", "actual A"])
    ax[0].set_title("Confusion matrix (Europe)")
    mo = e["by_month"]; x = np.arange(len(mo)); acc = np.array([r["acc"] for r in mo]); ci = np.array([r["acc_ci"] for r in mo])
    ax[1].errorbar(x, acc, yerr=[acc - ci[:, 0], ci[:, 1] - acc], fmt="o-", color=C1, ms=4, lw=1.2, capsize=2)
    ax[1].set_xticks(x); ax[1].set_xticklabels([r["month"][2:] + f"\nn={r['n']}" for r in mo], fontsize=7); ax[1].set_ylabel("W/D/L accuracy (95% Wilson CI)"); ax[1].set_title("Accuracy by calendar month (Europe)")
    g = e["gd_error"]; xv = g["gd_values"]
    ax[2].bar(xv, g["gd_exp"], 0.7, color=C1, alpha=0.55, label="model expected"); ax[2].scatter(xv, g["gd_obs"], color=C2, s=22, zorder=3, label="observed")
    ax[2].set_xlabel("home goals minus away goals"); ax[2].set_ylabel("share of matches"); ax[2].set_title("Goal-difference distribution (Europe)"); ax[2].legend(fontsize=8)
    fig.tight_layout(); savefig(fig, "fig11_error_analysis.png")


# ============================================================================= MAIN
def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (isinstance(o, float) and (math.isnan(o) or math.isinf(o))) or (isinstance(o, np.floating) and not np.isfinite(o)) else float(o)
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def compute():
    t0 = time.time()
    def tick(msg):
        print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)
    A, G, pools, ctx, m = build_master()
    eu, spl = pools["eu"], pools["spl"]
    tick(f"holdout regenerated: EU n={ctx['eu']['n']} (max |dp| vs stored csv {ctx['eu']['max_abs_prob_diff_vs_stored_csv']:.1e}), Saudi n={ctx['spl']['n']} ({ctx['spl']['max_abs_prob_diff_vs_stored_csv']:.1e})")
    R = {"meta": {"quick": QUICK, "bootstrap_reps": B, "seed": SEED, "bootstrap_refits": B_FIT, "null_sims": N_NULL, "context": ctx,
                  "selected": {"eu": eu["sel"], "spl": spl["sel"]}, "data_last_result": str(m.date.max()), "n_matches_total": int(len(m))}}
    locks = json.load(open(os.path.join(ROOT, "site", "data", "locks.json")))   # read only
    R["headline"] = sec_headline(A); tick("1 headline")
    R["baselines"] = sec_baselines(A); tick("2 baselines + significance")
    R["calibration"] = sec_calibration(A); tick("3 calibration")
    R["bias"] = sec_bias(A, G); tick("4 bias")
    R["variance"] = sec_variance(eu); tick("5a/b ridge sweep, learning curves")
    R["stability"] = sec_stability(eu, m, locks); tick("5c parameter stability")
    R["ablations"] = sec_ablations(A, G, eu, spl); tick("6 ablations")
    R["recalibration"] = sec_recal(A, eu, spl); tick("3b recalibration diagnostic")
    R["errors"] = sec_errors(A, G, eu, spl, m); tick("7 error analysis")
    R = clean(R)
    for f in [fig_headline, fig_reliability, fig_draw, fig_bias, fig_scorelines, fig_ridge, fig_learning, fig_stability, fig_ablations, fig_errors]:
        f(R)
    tick("figures")
    R["meta"]["compute_seconds"] = time.time() - t0
    if not QUICK:
        json.dump(R, open(RES_PATH, "w"), indent=1)
        keep = ["pool", "comp", "date", "home", "away", "hg", "ag", "ph", "pd", "pa", "eh", "ea", "rps", "ll", "head_hit", "elo_ph", "elo_pd", "elo_pa", "base_ph", "base_pd", "base_pa"]
        A[keep].round(5).to_csv(os.path.join(HERE, "holdout_predictions_2025-26.csv"), index=False)
    else:
        json.dump(R, open(os.path.join(HERE, "results_quick.json"), "w"), indent=1)
    tick("done")
    return R


OUT_LAB = ["H", "D", "A"]

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--report-only" in args:
        R = json.load(open(RES_PATH))
    else:
        R = compute()
    if "--compute-only" not in args:
        from write_report import write_report  # noqa: E402
        write_report(R)
