"""Writes site/data/meta.json from the build report, backtest files and the league files."""
import json, os, glob
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data"); S = os.path.join(ROOT, "site", "data")
eu = json.load(open(f"{D}/backtest_eu.json")); spl = json.load(open(f"{D}/backtest_spl.json"))
lk = json.load(open(f"{S}/locks.json"))
m = pd.read_csv(f"{D}/matches.csv")
NAMES = {"epl": "Premier League", "laliga": "La Liga", "ligue1": "Ligue 1", "spl": "Saudi Pro League", "bundesliga": "Bundesliga (internal)", "seriea": "Serie A (internal)", "ucl": "Champions League (internal)"}
SRC = {"epl": "openfootball + ESPN", "laliga": "openfootball + ESPN", "ligue1": "openfootball + ESPN", "bundesliga": "openfootball + ESPN", "seriea": "openfootball + ESPN", "spl": "ESPN", "ucl": "ESPN"}
cov = {}
for c, g in m.groupby("comp"):
    seasons = {f"{int(s)}-{str(int(s) + 1)[2:]}": int(n) for s, n in g.groupby("season").size().items()}
    cov[c] = {"name": NAMES[c], "source": SRC[c], "matches_per_season": seasons, "last_result_date": g.date.max(), "total_matches": int(len(g))}
for lg in ["spl", "epl", "laliga", "ligue1"]:
    cov[lg]["fixtures_predicted_next_14_days"] = json.load(open(f"{S}/leagues/{lg}.json"))["n_matches"]
fetched = sorted({json.load(open(f))["fetched_utc"] for f in glob.glob(f"{D}/raw/espn/*_2026.json")})


def pack(b):
    s = b["models"]["shipped"]
    return {"n": b["n"], "wdl_accuracy": round(s["acc"], 4), "headline_score_hit": round(s["head_hit"], 4), "one_exact_score_in": round(1 / s["head_hit"], 1),
            "rps": round(s["rps"], 4), "rps_base_rates": round(b["models"]["base_rates"]["rps"], 4), "rps_elo_only": round(b["models"]["elo_only"]["rps"], 4),
            "rps_uniform": round(b["models"]["uniform"]["rps"], 4), "log_loss": round(s["ll"], 4), "log_loss_base_rates": round(b["models"]["base_rates"]["ll"], 4),
            "home_win_always_accuracy": round(b["home_win_always_acc"], 4),
            "rps_diff_vs_base_rates_ci95": [round(x, 4) for x in b["bootstrap"]["shipped_minus_base_rates"]["rps"]],
            "rps_diff_vs_elo_only_ci95": [round(x, 4) for x in b["bootstrap"]["shipped_minus_elo_only"]["rps"]]}


_LG = {"Barcelona": ("laliga", "La Liga"), "Paris Saint-Germain": ("ligue1", "Ligue 1"), "Bayern Munich": ("bundesliga", "Bundesliga"), "Arsenal": ("epl", "Premier League"), "Real Madrid": ("laliga", "La Liga")}
_s = m[m.season == 2026]
FEAT_COUNTS = {t: f"{int((((_s.home == t) | (_s.away == t)) & (_s.comp == lg)).sum())} {nm} + {int((((_s.home == t) | (_s.away == t)) & (_s.comp == 'ucl')).sum())} UCL" for t, (lg, nm) in _LG.items()}
R = eu["report_2025_26"]; C = eu["current_2026_27"]
meta = {
    "generated_at": json.load(open(f"{S}/leagues/epl.json"))["generated_at"],
    "data_cutoff_utc": json.load(open(f"{S}/leagues/epl.json"))["data_cutoff_utc"], "model_version": "ihtimal-v1.0",
    "sources": [
        {"name": "openfootball (football.json)", "use": "Match results, Premier League / La Liga / Ligue 1 / Bundesliga / Serie A, 2023-24 to 2026-27", "licence": "public domain (CC0)", "credit": "openfootball (github.com/openfootball)", "url": "https://github.com/openfootball/football.json"},
        {"name": "ESPN public scoreboard", "use": "Results and fixtures: Saudi Pro League, Champions League, and all matches openfootball lacks (the whole of 2026-27 after 20 Sep, a few gaps earlier). Scores, kick-off times and venues only", "credit": "ESPN", "url": "https://www.espn.com"},
        {"name": "ClubElo", "use": "Sanity check and display only, read by hand on 18 Oct 2026. Not used in any model", "credit": "Elo: clubelo.com", "url": "https://clubelo.com"},
        {"name": "statz.ai", "use": "Season xG totals for the five featured clubs (heuristic adjustment on the three featured games)", "credit": "xG: statz.ai", "url": "https://statz.ai"},
        {"name": "Opta / The Analyst", "use": "Public benchmark quoted for PSG v Barcelona only, added after our lock", "credit": "Benchmark: Opta / The Analyst", "url": "https://theanalyst.com"},
        {"name": "Team news", "use": "Injuries and suspensions for the three featured games, with each source cited per player in the match file", "credit": "Sports Mole, bundesliga.com, Bavarian Football Works", "url": "https://www.sportsmole.co.uk"}],
    "not_used": ["market prices of any kind", "football-data.co.uk (terms forbid AI/bot use)", "Football Charts (no permission yet)", "club crests, league logos, player photos"],
    "model": {"summary_en": "Statistical machine-learning model: time-decayed Dixon-Coles goals model fitted by maximum likelihood, one joint fit across the big-5 leagues and the Champions League; separate faster-decay model for the Saudi Pro League; Elo leg blended where the 2024-25 tuning selected it.",
              "european": eu["selected"], "saudi": spl["selected"], "grid": "0-8 x 0-8 scorelines", "headline_pick_rule": "most likely result (home/draw/away), then the most likely score within that result",
              "adjustments": "Featured games only: xG regression (capped 0.92-1.08) and injury/suspension multipliers (documented per player). Heuristic, not backtested; the tally counts the adjusted headline and the base is stored and scored alongside."},
    "data_coverage": cov, "espn_fetched_utc": fetched[-1] if fetched else None,
    "data_checks": {"overlap_matches_compared": json.load(open(f"{D}/build_report.json"))["overlap_matches"], "score_disagreements": json.load(open(f"{D}/build_report.json"))["overlap_score_mismatch"],
                    "featured_team_game_counts_2026_27": FEAT_COUNTS,
                    "snapshot_results_checked_19_oct_2026": ["Barcelona 5-2 Real Betis (as Real Betis 2-5 Barcelona)", "PSG 3-1 Strasbourg", "Bayern 6-1 Leipzig", "Arsenal 1-0 Nottingham Forest", "Real Madrid 4-1 Sevilla"]},
    "backtest": {"protocol": "walk-forward, weekly refits on data strictly before each match week; tuned on 2024-25; reported on 2025-26 (untouched); spec in BACKTEST_SPEC.md, numbers in BACKTEST.md",
                 "europe_holdout_2025_26": pack(R["all"]), "site_leagues_holdout_2025_26": pack(R["site_leagues_epl_laliga_ligue1"]), "champions_league_holdout_2025_26": pack(R["ucl"]),
                 "europe_2026_27_to_date": pack(C["all"]), "saudi_holdout_2025_26": pack(spl["report_2025_26"]["all"]), "saudi_2026_27_to_date": pack(spl["current_2026_27"]["all"])},
    "locks": {"file": "locks.json", "locked_at_utc": lk["locked_at_utc"], "matches": [{"match_id": x["match_id"], "sha256": x["sha256"]} for x in lk["matches"]]},
    "disclaimer": {"ar": "تنبؤات إحصائية للتسلية والتعلّم — ليست نصيحة مراهنة", "en": "Statistical predictions for fun and learning. Not betting advice."},
    "author": "@mo_ai_engineer",
}
json.dump(meta, open(f"{S}/meta.json", "w"), ensure_ascii=False, indent=1)
print("meta.json written")
