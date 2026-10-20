"""Shared plumbing: load matches, index teams, fit DC at a cutoff, Elo leg, outcome metrics."""
import os, json
import numpy as np
import pandas as pd
from dc import fit_dc, lambdas, score_grid, wdl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
EU_COMPS = ["epl", "laliga", "ligue1", "bundesliga", "seriea", "ucl"]
LEAGUES = ["epl", "laliga", "ligue1", "bundesliga", "seriea", "other"]


def load_matches():
    m = pd.read_csv(os.path.join(DATA, "matches.csv"))
    m["dt"] = pd.to_datetime(m["date"])
    return m


class Space:
    """Team / comp / league indexing for a set of matches (all teams that ever appear)."""

    def __init__(self, df, comps):
        self.comps = comps
        teams = sorted(set(df.home) | set(df.away))
        self.teams = teams
        self.tix = {t: i for i, t in enumerate(teams)}
        self.cix = {c: i for i, c in enumerate(comps)}
        dom = df[df.comp.isin([c for c in comps if c != "ucl"])].sort_values("dt")
        last_comp = {}
        for r in dom.itertuples():
            last_comp[r.home] = r.comp; last_comp[r.away] = r.comp
        # amendment 1 (BACKTEST_SPEC.md): Saudi rho is estimated with slow decay (xi 0.0019) and held fixed in the fast-decay fit
        self.rho_xi = 0.0019 if comps == ["spl"] else None
        if comps == ["spl"]:
            self.leagues = ["spl"]
            self.team_league = np.zeros(len(teams), dtype=int)
        else:
            self.leagues = LEAGUES
            self.team_league = np.array([LEAGUES.index(last_comp.get(t, "other")) for t in teams])

    def idx(self, df):
        return (df.home.map(self.tix).values.astype(int), df.away.map(self.tix).values.astype(int),
                df.comp.map(self.cix).values.astype(int))


def fit_at(space, train, cutoff, xi, reg_team, reg_league=0.2, x0=None):
    """Fit on matches strictly before `cutoff` (Timestamp), weights exp(-xi*days_ago)."""
    tr = train[train.dt < cutoff]
    h, a, c = space.idx(tr)
    days = (cutoff - tr.dt).dt.days.values.astype(float)
    w = np.exp(-xi * days)
    assert tr.dt.max() < cutoff
    rho_fixed = None
    rho_xi = getattr(space, "rho_xi", None)
    if rho_xi is not None:  # amendment 1 (Saudi only): rho from a slow-decay first pass on the same pre-cutoff data
        w_slow = np.exp(-rho_xi * days)
        f0 = fit_dc(h, a, c, tr.hg.values, tr.ag.values, w_slow, space.team_league, len(space.teams), len(space.leagues), len(space.comps),
                    reg_team=reg_team, reg_league=reg_league)
        rho_fixed = f0.rho
    fit = fit_dc(h, a, c, tr.hg.values, tr.ag.values, w, space.team_league, len(space.teams), len(space.leagues), len(space.comps),
                 reg_team=reg_team, reg_league=reg_league, x0=x0, rho_fixed=rho_fixed)
    fit.n_train = len(tr); fit.cutoff = cutoff; fit.max_train_date = tr.dt.max()
    return fit


# ---------------------------------------------------------------- Elo leg
class Elo:
    """Own Elo over a closed pool (neutral 1500 start, K=20, home +65), updated only AFTER each match."""

    def __init__(self, K=20.0, H=65.0):
        self.K, self.H, self.r = K, H, {}

    def get(self, t):
        return self.r.get(t, 1500.0)

    def update(self, h, a, hg, ag):
        rh, ra = self.get(h), self.get(a)
        e = 1.0 / (1.0 + 10 ** (-(rh + self.H - ra) / 400.0))
        s = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        # goal-difference multiplier (standard eloratings.net form)
        gd = abs(hg - ag)
        mult = 1.0 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8.0)
        self.r[h] = rh + self.K * mult * (s - e)
        self.r[a] = ra - self.K * mult * (s - e)


def elo_run(train, K=20.0, H=65.0):
    """Run Elo over `train` in date order; returns the Elo object and a per-match (dElo) array aligned with train.sort."""
    el = Elo(K, H)
    tr = train.sort_values("dt", kind="stable")
    diffs = np.zeros(len(tr))
    for i, r in enumerate(tr.itertuples()):
        diffs[i] = el.get(r.home) - el.get(r.away)
        el.update(r.home, r.away, r.hg, r.ag)
    return el, tr, diffs


def fit_ordered_logit(x, y):
    """P(y<=k) = sigmoid(t_k - b*x) with y in {0=away,1=draw,2=home}; x = Elo diff + H over 400. returns (t0,t1,b)."""
    from scipy.optimize import minimize

    def nll(p):
        t0, dt, b = p
        t1 = t0 + np.exp(dt)
        z = b * x
        c0 = 1 / (1 + np.exp(-(t0 - z))); c1 = 1 / (1 + np.exp(-(t1 - z)))
        pr = np.where(y == 0, c0, np.where(y == 1, c1 - c0, 1 - c1))
        return -np.sum(np.log(np.clip(pr, 1e-12, 1)))
    r = minimize(nll, [-0.5, 0.0, 1.0], method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 400})
    t0, dt, b = r.x
    return t0, t0 + np.exp(dt), b


def ordered_logit_probs(t0, t1, b, x):
    z = b * x
    c0 = 1 / (1 + np.exp(-(t0 - z))); c1 = 1 / (1 + np.exp(-(t1 - z)))
    return np.column_stack([1 - c1, c1 - c0, c0])  # H, D, A


def elo_models(train_before, pool_comps_for_mapping=None):
    """Fit Elo on `train_before` (all strictly before the cutoff). Returns (elo, outcome mapping, goal-diff mapping, total-goals mean).
    Everything (ratings, mapping a/b, thresholds) is fitted on pre-cutoff data only (critic C.2 #5)."""
    el, tr, diffs = elo_run(train_before)
    # skip the first 6 months of the run: ratings are still ~1500 and uninformative
    keep = (tr.dt >= tr.dt.min() + pd.Timedelta(days=150)).values
    x = (diffs[keep] + el.H) / 400.0
    y = np.where(tr.hg.values[keep] > tr.ag.values[keep], 2, np.where(tr.hg.values[keep] == tr.ag.values[keep], 1, 0))
    t0, t1, b = fit_ordered_logit(x, y)
    gd = (tr.hg.values[keep] - tr.ag.values[keep]).astype(float)
    A = np.column_stack([np.ones(len(x)), x])
    coef = np.linalg.lstsq(A, gd, rcond=None)[0]  # goal diff = a + b * x
    return el, (t0, t1, b), coef


# ---------------------------------------------------------------- metrics
def rps(p, y):
    """p: (n,3) H,D,A ; y: (n,) 0=H,1=D,2=A ; ranked probability score for ordered H>D>A"""
    cp = np.cumsum(p, axis=1)[:, :2]
    o = np.zeros((len(y), 3)); o[np.arange(len(y)), y] = 1
    co = np.cumsum(o, axis=1)[:, :2]
    return 0.5 * np.sum((cp - co) ** 2, axis=1)


def logloss(p, y):
    return -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1))


def brier(p, y):
    o = np.zeros_like(p); o[np.arange(len(y)), y] = 1
    return np.sum((p - o) ** 2, axis=1)


def outcome(hg, ag):
    return np.where(hg > ag, 0, np.where(hg == ag, 1, 2))


def pick_from_grid(G):
    """headline pick: most likely outcome (H/D/A), then most likely score within that outcome."""
    p = wdl(G)
    k = int(np.argmax(p))
    mask = np.zeros_like(G, dtype=bool)
    ii, jj = np.indices(G.shape)
    mask = (ii > jj) if k == 0 else ((ii == jj) if k == 1 else (ii < jj))
    Gm = np.where(mask, G, -1)
    i, j = np.unravel_index(np.argmax(Gm), G.shape)
    return k, (int(i), int(j)), float(G[i, j])
