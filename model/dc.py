"""Time-decayed Dixon-Coles (own numpy/scipy implementation; penaltyblog (MIT) is the reference design).

lambda_home = exp(c[comp] + eta + (s[L(h)] + a[h]) - (s[L(a)] + d[a]))
lambda_away = exp(c[comp]       + (s[L(a)] + a[a]) - (s[L(h)] + d[h]))
  a, d  : team attack / defence-strength deviations   (ridge-penalised: shrinks thin teams to their league mean)
  s     : league strength offset (cancels inside a league; identified only through Champions League games)
  c     : per-competition scoring level, eta: home advantage (neutral/ignored for the UCL final)
Dixon-Coles low-score correction tau(x, y; lambda, mu, rho). Weights w = exp(-xi * days_ago).
"""
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


class DCFit:
    pass


def _tau_terms(x, y, lam, mu, rho):
    """returns log tau, dlogtau/dloglam, dlogtau/dlogmu, dlogtau/drho (vectorised)."""
    n = len(x)
    logt = np.zeros(n); dl = np.zeros(n); dm = np.zeros(n); dr = np.zeros(n)
    m00 = (x == 0) & (y == 0); m01 = (x == 0) & (y == 1); m10 = (x == 1) & (y == 0); m11 = (x == 1) & (y == 1)
    t00 = 1 - lam * mu * rho; t01 = 1 + lam * rho; t10 = 1 + mu * rho; t11 = 1 - rho
    t00 = np.maximum(t00, 1e-9); t01 = np.maximum(t01, 1e-9); t10 = np.maximum(t10, 1e-9); t11 = max(t11, 1e-9) if np.isscalar(t11) else t11
    logt[m00] = np.log(t00[m00]); logt[m01] = np.log(t01[m01]); logt[m10] = np.log(t10[m10]); logt[m11] = np.log(t11)
    dl[m00] = (-lam * mu * rho / t00)[m00]; dm[m00] = dl[m00]
    dl[m01] = (lam * rho / t01)[m01]
    dm[m10] = (mu * rho / t10)[m10]
    dr[m00] = (-lam * mu / t00)[m00]; dr[m01] = (lam / t01)[m01]; dr[m10] = (mu / t10)[m10]; dr[m11] = -1.0 / t11
    return logt, dl, dm, dr


def fit_dc(home_idx, away_idx, comp_idx, hg, ag, w, team_league, n_teams, n_leagues, n_comps,
           reg_team=6.0, reg_league=0.2, x0=None, maxiter=400, check=False, rho_fixed=None):
    """Weighted DC fit. Returns DCFit with .a .d .s .c .eta .rho"""
    n = len(hg)
    nT, nL, nC = n_teams, n_leagues, n_comps
    # param layout: a[nT], d[nT], s[nL], c[nC], eta, rho
    ia = slice(0, nT); id_ = slice(nT, 2 * nT); isl = slice(2 * nT, 2 * nT + nL); ic = slice(2 * nT + nL, 2 * nT + nL + nC)
    ieta = 2 * nT + nL + nC; irho = ieta + 1
    npar = irho + 1
    Lh = team_league[home_idx]; La = team_league[away_idx]
    hgf = hg.astype(float); agf = ag.astype(float)
    const = -(gammaln(hgf + 1) + gammaln(agf + 1))

    def unpack(th):
        return th[ia], th[id_], th[isl], th[ic], th[ieta], th[irho]

    def fun(th):
        a, d, s, c, eta, rho = unpack(th)
        lh = c[comp_idx] + eta + (s[Lh] + a[home_idx]) - (s[La] + d[away_idx])
        la = c[comp_idx] + (s[La] + a[away_idx]) - (s[Lh] + d[home_idx])
        lam = np.exp(lh); mu = np.exp(la)
        logt, dl, dm, dr = _tau_terms(hg, ag, lam, mu, rho)
        ll = w * (const + hgf * lh - lam + agf * la - mu + logt)
        pen = reg_team * (np.sum(a ** 2) + np.sum(d ** 2)) + reg_league * np.sum(s ** 2)
        f = -np.sum(ll) + pen
        gh = w * (hgf - lam + dl)  # d ll / d lh
        ga = w * (agf - mu + dm)
        g = np.zeros(npar)
        g[ia] = -np.bincount(home_idx, gh, nT) - np.bincount(away_idx, ga, nT) + 2 * reg_team * a
        g[id_] = np.bincount(away_idx, gh, nT) + np.bincount(home_idx, ga, nT) + 2 * reg_team * d
        gs = -(np.bincount(Lh, gh, nL) + np.bincount(La, ga, nL)) + (np.bincount(La, gh, nL) + np.bincount(Lh, ga, nL))
        g[isl] = gs + 2 * reg_league * s
        g[ic] = -np.bincount(comp_idx, gh + ga, nC)
        g[ieta] = -np.sum(gh)
        g[irho] = -np.sum(w * dr)
        return f, g

    if x0 is None:
        x0 = np.zeros(npar); x0[ic] = 0.2; x0[ieta] = 0.25; x0[irho] = -0.05
    bounds = [(None, None)] * npar
    bounds[irho] = (-0.25, 0.25)
    if rho_fixed is not None:  # amendment 1 (Saudi): rho estimated in a separate slow-decay pass, held fixed here
        bounds[irho] = (rho_fixed, rho_fixed); x0 = x0.copy(); x0[irho] = rho_fixed
    if check:
        from scipy.optimize import check_grad
        rng = np.random.RandomState(0)
        th = rng.normal(0, 0.1, npar); th[irho] = -0.05
        f0, g0 = fun(th)
        gn = np.array([(fun(th + 1e-6 * np.eye(npar)[i])[0] - fun(th - 1e-6 * np.eye(npar)[i])[0]) / 2e-6 for i in range(npar)])
        return float(np.max(np.abs(g0 - gn))), float(np.max(np.abs(g0)))
    res = minimize(fun, x0, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": maxiter, "maxcor": 20, "ftol": 1e-10})
    a, d, s, c, eta, rho = unpack(res.x)
    out = DCFit()
    out.a, out.d, out.s, out.c, out.eta, out.rho = a.copy(), d.copy(), s.copy(), c.copy(), float(eta), float(rho)
    out.x = res.x; out.success = res.success; out.nit = res.nit; out.team_league = team_league
    return out


def lambdas(fit, h, a, comp, neutral=False):
    """expected goals (home, away) for team indices h, a (arrays or ints) in competition index comp."""
    tl = fit.team_league
    eta = 0.0 if neutral else fit.eta
    lh = fit.c[comp] + eta + (fit.s[tl[h]] + fit.a[h]) - (fit.s[tl[a]] + fit.d[a])
    la = fit.c[comp] + (fit.s[tl[a]] + fit.a[a]) - (fit.s[tl[h]] + fit.d[h])
    return np.exp(lh), np.exp(la)


def score_grid(lam, mu, rho, maxg=8):
    """DC joint scoreline grid, 0..maxg x 0..maxg, renormalised. lam, mu scalars."""
    from scipy.stats import poisson
    k = np.arange(maxg + 1)
    ph = poisson.pmf(k, lam); pa = poisson.pmf(k, mu)
    G = np.outer(ph, pa)
    G[0, 0] *= max(1 - lam * mu * rho, 1e-9)
    G[0, 1] *= max(1 + lam * rho, 1e-9)
    G[1, 0] *= max(1 + mu * rho, 1e-9)
    G[1, 1] *= max(1 - rho, 1e-9)
    return G / G.sum()


def wdl(G):
    h = np.tril(G, -1).sum()  # home goals (row) > away goals (col)
    d = np.trace(G)
    a = np.triu(G, 1).sum()
    return np.array([h, d, a])


def score_grids(lam, mu, rho, maxg=8):
    """vectorised DC grids: lam, mu arrays (n,), rho scalar -> (n, maxg+1, maxg+1), each renormalised."""
    k = np.arange(maxg + 1)
    lg = gammaln(k + 1)
    ph = np.exp(-lam[:, None] + k[None, :] * np.log(lam)[:, None] - lg[None, :])
    pa = np.exp(-mu[:, None] + k[None, :] * np.log(mu)[:, None] - lg[None, :])
    G = ph[:, :, None] * pa[:, None, :]
    G[:, 0, 0] *= np.maximum(1 - lam * mu * rho, 1e-9)
    G[:, 0, 1] *= np.maximum(1 + lam * rho, 1e-9)
    G[:, 1, 0] *= np.maximum(1 + mu * rho, 1e-9)
    G[:, 1, 1] *= max(1 - rho, 1e-9)
    return G / G.sum(axis=(1, 2), keepdims=True)
