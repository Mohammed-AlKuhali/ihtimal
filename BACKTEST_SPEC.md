# Backtest specification (pre-registered)

Written Mon 19 Oct 2026, before any backtest metric was computed. This file is committed to the project folder first; `model/backtest.py` implements exactly this and nothing else. Any later change is logged at the bottom under "Amendments", with the reason, and never silently.

## What is being tested

The **base model** that gets published for every match: a time-decayed Dixon-Coles goals model, optionally log-blended with an Elo leg. The hand-entered adjustments on the three featured games (xG regression, injuries and suspensions) are **not backtestable** and are labelled "heuristic" on the site. The public tally counts the `adjusted` prediction, `base` is shown next to it and both are stored (critic C.2 #4).

## Data

* `data/matches.csv`, built by `model/build_data.py`: openfootball (public domain) where it holds a real full-time score, ESPN public scoreboard JSON for everything else. One source per match, deduped on (competition, season, home, away). Where both sources cover a match they were compared: results are in `data/build_report.json` (5,355 overlapping matches, 0 score disagreements).
* European pool: Premier League, La Liga, Ligue 1, Bundesliga, Serie A and Champions League, from 2023-08-01. Regulation-time results only (matches decided in extra time or on penalties and abandoned matches are excluded).
* Saudi Pro League: ESPN only, from 2023-08-01, fitted as its own separate model.
* No odds, no market data, no football-data.co.uk. No ClubElo numbers enter any model or any backtest.

## Protocol (walk-forward, no shuffling)

* Folds are weekly. For each Monday 00:00 UTC cutoff, **every fitted object** is rebuilt from matches strictly before the cutoff: the Dixon-Coles parameters (attack, defence, league offsets, scoring levels, home advantage, rho), the Elo ratings, the Elo-to-outcome mapping (ordered logit thresholds and slope), the Elo-to-goal-difference mapping and the base rates. All of them receive the same single `train` frame, and an assertion checks `max(train.date) < min(test.date)` in every fold (critic C.2 #5).
* The matches played in the following 7 days are predicted from that fit.
* Time decay weights: `w = exp(-xi * days_before_cutoff)`.
* Elo: neutral 1500 start for every club at 2023-08-01 (also for the Saudi league, and for promoted or Champions-League-only clubs), K = 20 with the standard goal-difference multiplier, home advantage +65. The first 150 days of each Elo run are not used to fit the mappings.
* **Tuning period: season 2024-25** (2024-08-01 to 2025-07-31). **Report period: season 2025-26** (2025-08-01 to 2026-07-31), untouched by any choice. 2026-27 to date (2026-08-01 to 2026-10-18) is reported separately, also untouched.

## Hyper-parameter grid (tuned on 2024-25 only)

| Parameter | European pool | Saudi league |
|---|---|---|
| xi (decay per day) | 0.0010, 0.0019, 0.0030 | 0.0030, 0.0046, 0.0077, 0.0120 |
| Ridge on team attack/defence deviations (`reg_team`) | 3, 8 | 3, 8 |
| w = weight of the Dixon-Coles leg in `log lambda = w log lambda_G + (1-w) log lambda_E` | 1.0, 0.8, 0.6, 0.3 | 1.0, 0.8, 0.6, 0.3 |

* `lambda_E` comes from the Elo supremacy `s = a + b (dElo + H)/400` (a, b fitted on the training window), keeping the Dixon-Coles total `T`: `lambda_E,home = max((T+s)/2, 0.2)`, `lambda_E,away = max((T-s)/2, 0.2)`.
* For the European pool `w` is chosen separately for domestic matches and for Champions League matches (so the Champions League value is noisy, about 185 matches, and is reported with that caveat).
* Selection criterion: lowest mean RPS on the 2024-25 tuning matches. Differences below 0.0005 RPS are treated as ties and broken by log-loss, then by the simpler setting (larger `w`, smaller `xi` grid index).
* **Decision rule** (decided on 2024-25, never on 2025-26): if no blended setting (`w < 1`) beats the best `w = 1` (Dixon-Coles only) by at least 0.0005 RPS, ship Dixon-Coles only. Whatever is shipped is then reported against Elo-only on the untouched 2025-26 holdout, even if it loses.
* Fixed (not tuned): grid size 0-8 by 0-8, rho bounded to [-0.25, 0.25], league-strength ridge 0.2, K = 20, home advantage 65.

## Metrics (all on the report period)

RPS (primary), log-loss (co-primary), multiclass Brier, W/D/L accuracy (argmax), **headline-score hit rate** (the published pick: most likely outcome, then most likely score within that outcome), top-score hit rate (the single most likely scoreline overall), mean probability given to the actual scoreline. Reported for: all European pool matches, the three site leagues (Premier League, La Liga, Ligue 1) combined, Champions League, and the Saudi league.

## Baselines

1. Uniform (1/3, 1/3, 1/3).
2. Home win always (accuracy only).
3. Base rates: home/draw/away frequencies of the same competition in all earlier matches.
4. Elo-only: ordered logit on the Elo difference, refit every fold. No scoreline grid.
5. No bookmaker or market baseline (that data is not used). Opta numbers for the three showcase games are quoted on the site only after the lock.

## Statistics

Paired bootstrap, 2,000 resamples, seed 2026, on per-match differences in RPS and log-loss (model minus baseline), 95% percentile intervals.

## Pre-registered expectations (from the plan)

* RPS clearly below base rates (about 0.235 to 0.215 or better) on 2025-26.
* No worse than Elo-only.
* W/D/L accuracy 50-55%, headline-score hit rate about 10-12% (about 1 in 9).
* Saudi league: noisier and less accurate than the European pool.
* A model that is worse than base rates on the report period is not shipped as "the model"; it would be reported as failing.

## Amendments

* Clarification written before any run: for the European pool `(xi, reg_team, w_domestic)` are selected jointly by mean RPS on the 2024-25 **domestic** matches; `w_ucl` is then chosen by RPS on the 2024-25 Champions League matches at that `(xi, reg_team)`.
* **Amendment 1 (Mon 19 Oct 2026, after the external review, written before the Saudi backtest was re-run). Saudi league only: how rho is estimated.** With the shipped Saudi settings (xi = 0.0077, half-life 90 days) the weekly rho estimate wandered between +0.12 and -0.23 across folds, and the live fit sits at -0.230, next to the -0.25 bound. A rho that negative pushes 1-0 and 0-1 below 2-0 and 0-2 in every Saudi score grid, which is not what Saudi results look like. Change: rho is now estimated in a first pass with fixed slow decay (xi = 0.0019, half-life one year, the same as the European model) on the same pre-cutoff data, then held fixed in the fast-decay fit that produces the team strengths. The Saudi grid (xi, ridge, w) is re-tuned on 2024-25 only, same rules. **Acceptance rule, decided before the re-run:** adopt if the selected setting's 2024-25 RPS is no worse than the previous selected value (0.2062) by more than 0.0005 (the spec's own tie threshold); otherwise revert to the original estimator. No 2025-26 result is used to choose. The European pool, the featured games and every locked file are untouched (they do not use the Saudi model).
  * **Outcome of Amendment 1 (same day).** Re-tuning on 2024-25: best blend RPS 0.20627 against 0.20623 before, so the acceptance rule is met and the amendment is adopted. The selected Saudi settings moved from xi 0.0077 to xi 0.012 (half-life 58 days): the two are tied on RPS (0.206265 v 0.206267) and the spec's tie-break on log-loss picks 0.012. On the untouched 2025-26 holdout the Saudi numbers are essentially unchanged (RPS 0.1766 -> 0.1770, W/D/L accuracy 57.5% -> 57.5%, headline-score hit 8.8% -> 8.5%, mean probability of the actual score 6.76% -> 6.77%): the amendment fixes the shape of the score grid, not the accuracy. The live Saudi rho moved from -0.230 to -0.109.
* **Amendment 2 (Mon 19 Oct 2026, written after the head-to-head data was built and BEFORE any model metric with a head-to-head feature was computed). Does the last-10-meetings record improve the forecast?** Mo asked for the last 10 meetings between the two clubs to be taken into account. The literature expectation is that, once team strengths are fitted, head-to-head history adds almost nothing (the pair-specific signal is small and noisy), so the **expected outcome is "not accepted"**. This amendment tests it the way every other choice in this project is tested: on the 2024-25 dev set, with the 2025-26 holdout touched at most once.
  * **Data.** `data/h2h_pool.csv`, built by `model/h2h.py` from ESPN's public scoreboard JSON (older years, second tiers, cups; fetched by `model/fetch_h2h.py`), the existing ESPN raw feeds (2023+), `data/matches.csv` and openfootball older seasons 2010-11 to 2022-23 (cross-check and gap fill; ESPN wins where they disagree). Competitions: five leagues and their second tiers, Saudi Pro League (ESPN only from Aug 2022), Champions / Europa / Conference League and UEFA Super Cup, the domestic cups and super cups of England, Spain, France, Germany and Italy, the Saudi King's Cup, AFC Champions League, Club World Cup. No friendlies. For the experiment only **regulation-time** rows are used (matches decided in extra time or on penalties are left out, as in the training data).
  * **Feature (fixed before running; none of these constants is tuned).** For a test match (home h, away a) in the weekly fold with cutoff K: take the up to 10 most recent meetings of the two clubs with date **strictly before K** (the same information cut-off as every fitted object; `train`-style leak guard, plus a perturbation test: scrambling the pool results from K onward must leave every feature unchanged). For each meeting j compute the goal difference of h minus a, and subtract the goal difference the fold's own Dixon-Coles fit expects for that meeting in its actual orientation (home advantage included, scoring level of the test match's competition): residual `r_j`. Recency weight `v_j = 0.5^(age_j / 3 years)`. Shrunk mean residual `R = sum(v_j r_j) / (sum(v_j) + 5)` (5 pseudo-meetings of zero residual; `R = 0` with no meetings).
  * **Use.** After the Elo blend, `lambda_home' = lambda_home * exp(+w_h2h * R)` and `lambda_away' = lambda_away * exp(-w_h2h * R)`; rho and the grid are unchanged. `w_h2h` in {0, 0.05, 0.1, 0.2}; `w_h2h = 0` must reproduce the shipped model exactly (asserted against the tuning grid).
  * **Pools and settings.** Two separate tests, each at that pool's shipped settings (European pool: xi 0.0019, ridge 3, w 1.0 domestic and 0.3 Champions League; Saudi: Amendment 1 settings). One `w_h2h` per pool, chosen on all 2024-25 matches of the pool.
  * **Acceptance rule.** Accept `w_h2h > 0` for a pool only if its 2024-25 mean RPS is at least **0.0005 lower** than at `w_h2h = 0` (the spec's own tie threshold) **and** its 2024-25 log-loss is not higher. If several weights qualify take the lowest RPS; weights within 0.0005 RPS of each other are tied and the smaller one is taken. If no weight qualifies the live model stays unchanged for that pool.
  * **Holdout.** The 2025-26 holdout is run **once, and only for a pool whose dev result was accepted** (guard in `model/h2h_experiment.py`: refuses a second run). It is reported against `w_h2h = 0` with the paired bootstrap (2,000 resamples, seed 2026). Even if accepted on dev, the live pipeline is only switched if the holdout RPS is no worse than at `w_h2h = 0`; a switch is a separate change. Locked featured files and `locks.json` are never touched: if accepted, the H2H-adjusted featured numbers are reported as "what they would have been".
  * **Diagnostics (not used for any decision):** share of matches with at least 1, 5 and 10 prior meetings; mean absolute `R`; the least-squares slope of the match's actual goal-difference residual on `R` with a bootstrap 95% interval (the weight the data would pick directly); dev RPS by weight restricted to matches with at least 5 prior meetings.
