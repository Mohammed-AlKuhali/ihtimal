# Data licences and credits

The author's own code, documentation, forecasts and evaluation results in this repository are released under the MIT licence (see `LICENSE`). The third-party material below is not the author's and keeps its own status.

| Material | Where it is here | Status |
|---|---|---|
| openfootball match results | `data/matches.csv` (rows with `source = openfootball`, the training history from Aug 2023) | Public domain (CC0). https://github.com/openfootball |
| Match scores from ESPN's public scoreboard | `data/matches.csv` (rows with `source = espn`), `data/fixtures_raw.json`, `data/h2h_*`, and the scored results in `prospective/` | Factual results (scores, kick-off times, venues, event ids), used for research. No ESPN content and no odds are redistributed. The raw ESPN feeds are not in this repository. |
| Team crests | `site/assets/logos/` | Trademarks of their clubs, used for identification only (see `site/assets/logos/CREDITS.md`). They are not covered by the MIT licence. |
| Country flags | `site/assets/flags/` | From flag-icons (MIT), https://github.com/lipis/flag-icons. Licence text in `site/assets/flags/LICENSE`. |
| Player photos | none | Not part of this repo. |
| Hand-entered team news, xG and benchmark figures | `inputs/`, and the display-only fields of `site/data/` | Facts typed in by hand, each with its source URL and check date, and credited on the site (Sports Mole, bundesliga.com, Bavarian Football Works, statz.ai, ClubElo, Opta / The Analyst). The sources keep their own rights; only the figures needed for attribution are kept. |
| Odds and market data | none | Never used by the model or the evaluation and not included. |
