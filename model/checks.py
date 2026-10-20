"""Data assertions (critic C.2 #2). Run by `make fetch` after every rebuild of data/matches.csv.
 * always: no duplicate domestic matches, every big-five league season has 18 or 20 clubs (no club under two names), the latest result date is shown
 * snapshot of 19 Oct 2026 (only while the data still ends on 18 Oct): each featured team's 2026-27 game counts and the five weekend results must be present exactly once
 * on later refreshes the featured teams' current counts are printed for a quick eyeball instead (they keep growing, so exact numbers would be meaningless)"""
import pandas as pd, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
m = pd.read_csv(os.path.join(ROOT, "data", "matches.csv")); s = m[m.season == 2026]
last = m.date.max()

dup = m[m.comp.isin(["epl", "laliga", "ligue1", "bundesliga", "seriea", "spl"])].duplicated(["comp", "season", "home", "away"]).sum()
assert dup == 0, f"{dup} duplicate domestic matches"
for (c, se), g in m[m.comp.isin(["epl", "laliga", "ligue1", "bundesliga", "seriea"])].groupby(["comp", "season"]):
    n = len(set(g.home) | set(g.away))
    assert n in (18, 20), f"{c} {se}: {n} clubs (a club probably appears under two names)"

FEAT = {"Barcelona": "laliga", "Paris Saint-Germain": "ligue1", "Bayern Munich": "bundesliga", "Arsenal": "epl", "Real Madrid": "laliga"}
if last <= "2026-10-18":
    EXPECT = {"Barcelona": (9, 2), "Paris Saint-Germain": (7, 2), "Bayern Munich": (6, 2), "Arsenal": (7, 2), "Real Madrid": (9, 2)}
    for t, (nl, nu) in EXPECT.items():
        d = s[(s.home == t) | (s.away == t)]
        assert (d.comp == FEAT[t]).sum() == nl and (d.comp == "ucl").sum() == nu, (t, (d.comp == FEAT[t]).sum(), (d.comp == "ucl").sum())
    RES = [("Real Betis", "Barcelona", 2, 5), ("Strasbourg", "Paris Saint-Germain", 1, 3), ("Bayern Munich", "RB Leipzig", 6, 1), ("Nottingham Forest", "Arsenal", 0, 1), ("Real Madrid", "Sevilla", 4, 1)]
    for h, a, hg, ag in RES:
        r = s[(s.home == h) & (s.away == a) & (s.date >= "2026-10-15")]
        assert len(r) == 1 and (r.hg.iloc[0], r.ag.iloc[0]) == (hg, ag), (h, a)
    print("snapshot checks passed: featured game counts and the 5 weekend results")
else:
    for t, lg in FEAT.items():
        d = s[(s.home == t) | (s.away == t)]
        print(f"  {t}: {(d.comp == lg).sum()} {lg} + {(d.comp == 'ucl').sum()} ucl results in 2026-27")
print(f"data checks passed: no duplicate domestic matches, 18/20 clubs per league season; latest result {last}")
