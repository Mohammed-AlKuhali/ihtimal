# Prospective evaluation protocol (pre-registered)

Project: Ihtimal (احتمالات), probabilistic football match-outcome model, model version `ihtimal-v1.0`.
Author: Mohammed Hashem Mohammed Al Kuhali, Independent researcher, Birmingham, UK (ORCID 0009-0008-2632-8350). Sole author.
Protocol version 1.0, written on 20 October 2026 (UTC) after the first lock manifest and before the first locked match kicked off (earliest kick-off 20 Oct 2026 15:00 UTC). No result of any locked match was known when this was written. The exact registration time and the sha256 of this file are in `prospective/PROTOCOL_REGISTRATION.json`.

This document fixes, before outcomes exist, which forecasts are counted, which baselines they are compared with, which numbers are computed, and how awkward cases are handled. The retrospective backtest (`BACKTEST_SPEC.md`, `BACKTEST.md`, `EVALUATION.md`) tuned and tested the model on past seasons; this study asks whether the same frozen model keeps its skill on matches that had not been played when the forecasts were published.

## 1. Question and hypotheses

Do the published W/D/L probabilities of `ihtimal-v1.0` score better, by ranked probability score (RPS), than two pre-specified baselines on matches that were still in the future when the forecast was locked?

* H1 (expected to hold): model RPS is lower than league base-rate RPS.
* H2 (open; the backtest found no clear difference): model RPS is lower than Elo-only RPS.

Both are tested with the same primary metric, and both are reported whatever the outcome. A null result against Elo-only is an expected and acceptable result.

## 2. Population

* Competitions: Saudi Pro League (`spl`), Premier League (`epl`), La Liga (`laliga`), Ligue 1 (`ligue1`), plus the featured UEFA Champions League matches (`ucl`). The three hash-locked featured games (PSG v Barcelona, Bayern v Arsenal, Barcelona v Real Madrid) are included; Barcelona v Real Madrid is a La Liga match and is reported under `laliga` and as featured.
* Period: every match that appears in a lock manifest (section 4) and kicks off between 20 Oct 2026 15:00 UTC and 6 Dec 2026 23:59:59 UTC. Weekly lock runs continue until 29 Nov 2026, so that every fixture of the period is covered.
* Matches that had already kicked off when a lock run happened are listed as excluded in the manifest and are not counted. This exclusion depends only on the clock, never on a result. The first manifest excludes five matches of 19 Oct 2026.
* Only matches that the site published as a match file are in scope; fixtures of other competitions are out of scope. A match that kicked off before a lock run could reach it (for example because a weekly run was skipped, or the fixture was added to the schedule late) is excluded under the clock rule above; the number of such matches is reported in the paper.
* Matches that kick off after 6 Dec 2026 are locked if they appear in a manifest, but are not part of the primary analysis; they are kept for a pre-declared follow-up.

## 3. Counted forecast

* The counted forecast of a match is the earliest locked version: the headline W/D/L probabilities stored in the first manifest that contains the match. Later refits (the site refits every week) never replace it. The manifest also stores the sha256 of the published file; `earliest lock wins` is enforced by `lock_week.py`.
* Featured games: the `adjusted` headline (the model plus the capped, heuristic availability and xG adjustments; this is what the public tally counts). The `base` forecast of featured games (the backtested model without adjustments) is stored and scored as a secondary analysis.
* All other matches: the `base` model, which is the backtested model with no manual input.
* No forecast, parameter, hyper-parameter or model structure is changed during the study. Weekly refits only add new results to the training data. If the model is changed anyway, the new forecasts carry a new `model_version`, are analysed as a separate stratum and are never pooled into the primary result.
* Evidence that a forecast was public before kick-off: the manifest stores a read-only GET of the public file at lock time; when the file is not yet deployed at lock time, `lock_week.py --attest` fetches the public copy right after the deploy and writes a separate attestation file. A forecast counts as publicly evidenced if the sha256 of the public bytes equals the locked bytes and the fetch time is before kick-off. All locked matches are in the primary analysis; the publicly evidenced subset is reported as a sensitivity analysis (section 7).

## 4. Locking procedure

`prospective/lock_week.py` reads `site/data/matches/*.json` and writes a dated manifest `prospective/locks/<date>_manifest.json` containing, for every match whose kick-off is later than the lock time and that is not in an earlier manifest: match id, ESPN event id, league, kick-off, teams, the published headline probabilities, the most likely score and the headline 6x6 score grid, the base forecast, the sha256 of the file bytes, for featured games the project's own content hash and original lock time, the baselines (section 5) and the UTC lock time. A manifest has a self-hash; `lock_week.py` and `score.py` stop if any manifest was edited afterwards. Every run also appends the current hash and probabilities of every file to `locks/versions_log.jsonl` so later refits remain visible.

## 5. Baselines (computed at lock time, stored in the manifest, never recomputed afterwards)

Both use only results strictly before the match file's `data_cutoff_utc`, the same information as the model, and the project's own code and the parameters of the pre-registered backtest.

* League base rates: home/draw/away frequencies of the match's competition, with add-one smoothing `(count+1)/(n+3)`.
* Elo-only: the project's own closed-pool Elo (neutral 1500 start, K = 20, home advantage +65, goal-difference multiplier), mapped to W/D/L by an ordered logit fitted on pre-cutoff data (`model/core.py`, `elo_models`). One pool for the European leagues and the Champions League, a separate pool for the Saudi Pro League. For the Saudi league this is the Saudi pool's own Elo.

A uniform 1/3 forecast is shown as a reference line only.

## 6. Outcomes and metrics

Outcome = the result after 90 minutes plus stoppage time: home win (H), draw (D), away win (A), from ESPN's public scoreboard JSON (`score.py` uses the project's fetcher `model/fetch_espn.py`, matching on the ESPN event id stored in the manifest).

Primary: RPS for the ordered outcomes H, D, A (`model/core.py`, `rps`), mean over matches. For each baseline b the paired per-match difference `d_i = RPS_model,i - RPS_b,i` is computed, negative values favour the model. Reported: mean difference with a 95% percentile interval from a paired bootstrap over matches (10,000 resamples, seed 2026). Because two baselines are compared, a statement that the model is better than a baseline is made only if the Bonferroni-adjusted 97.5% interval also lies below zero; both intervals are reported. No claim of equivalence is made for either comparison.

Secondary (descriptive, same matches):

* log-loss (mean of minus the log of the probability given to the actual outcome) and multi-class Brier score, for model and both baselines, with the same paired bootstrap for differences;
* W/D/L accuracy (outcome with the highest probability equals the result) with a Wilson 95% interval, and the share of matches in which the model's top outcome was a draw;
* exact-score hit rate (headline most likely score equals the final score) with a Wilson 95% interval, and the share of matches whose final score is among the five most likely scores;
* the probability the model gave to the final score (from the stored 6x6 grid; missing if a team scored six or more);
* calibration: pooled reliability table over the three outcome probabilities (bins <0.15, 0.15 to 0.25, 0.25 to 0.35, 0.35 to 0.45, 0.45 to 0.55, 0.55 to 0.70, 0.70 and above) giving mean predicted probability, observed frequency and n per bin, and mean predicted minus observed frequency per outcome. No significance test is run on calibration;
* all of the above by league, and for the three featured games individually. League-level results are descriptive and are not used for claims of difference between leagues.

## 7. Pre-specified sensitivity analyses

S1 cluster bootstrap resampling calendar weeks (ISO week of kick-off) instead of single matches, for the primary differences. S2 excluding the featured games. S3 featured games scored with their `base` forecast instead of `adjusted`. S4 using the latest forecast seen before kick-off in `versions_log.jsonl` instead of the earliest. S5 restricted to publicly evidenced matches. S6 Europe (EPL, La Liga, Ligue 1, UCL) and Saudi Pro League separately. None of these changes the primary result; they are reported next to it. If a sensitivity analysis disagrees with the primary result in sign, this is stated in the paper.

## 8. Postponed, abandoned and unusual matches

* Postponed or rescheduled: the original forecast stands and is scored if the match is played on or before 20 Dec 2026 (14 days after the end date). Otherwise it is listed as unresolved and excluded; the number is reported.
* Cancelled, abandoned and not replayed, forfeited or awarded results: excluded and listed (a result decided by the table rather than by play is not a played match). Abandoned and replayed in full: the replayed result is scored.
* Extra time or penalties (knock-out games only): the 90-minute result is entered by hand in `prospective/manual_overrides.json` with a source; until then the match is `manual_review` and is not scored. The league-phase games in the period do not go to extra time.
* A source score that looks wrong is checked against a second public source and entered in `manual_overrides.json` with the source and date; every override is listed in the paper.
* Matches are never dropped because of their result, their probability or their effect on the average.

## 9. Weekly procedure

1. `make fetch` (refresh results), then the hand inputs for any featured game.
2. `make predict` (forecasts for the next 14 days; locked featured files are never overwritten).
3. `make prospective-lock` (lock new matches, before anything is deployed). Check the summary: counts per league, none excluded unexpectedly.
4. `make verify`, then deploy from `site/`.
5. `make prospective-attest` straight after the deploy (public-copy evidence for the newly locked matches).
6. From the day after the matches: `make prospective-score` (and `make score` for the public record). `score.py` only reads manifests and writes `results.json` and `results_table.csv`; it never changes a lock.

Interim `results.json` files are for monitoring and the public record. The numbers in the paper come from the single final run after 20 Dec 2026, produced by the unchanged `score.py`, and no number is typed by hand.

## 10. Expected precision

From the 2025-26 holdout (2,243 matches), the standard deviation of the per-match RPS difference is about 0.040 against Elo-only and about 0.124 against base rates, with mean differences of about -0.001 and -0.030. With roughly 250 scored matches the 95% interval half-width is about 0.005 against Elo-only and about 0.015 against base rates. This study can therefore confirm skill over base rates if it persists, and can detect a difference from Elo-only only if it is several times larger than in the backtest; a result level with Elo-only is the expected outcome and will be reported as no evidence of a difference, not as equivalence. The final sample size is whatever the period yields; it is not extended or cut depending on results.

## 11. Integrity, conflicts and changes

The author built the model, runs the lock and the scoring and has no blinding; the safeguards are the self-hashed manifests, the public file hashes, the append-only version log and the open scripts. Competing interests: none. Funding: none. Data: ESPN public scoreboard JSON for results, openfootball and ESPN for the training history. No odds, market or betting data are used anywhere in the model or the evaluation.

Any change to this protocol after registration is appended below with date and reason, and the paper states it. The registered text above is not edited.

### Amendments

(none)
