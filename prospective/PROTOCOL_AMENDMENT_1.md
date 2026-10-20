# Protocol amendment 1: two-week study period

Study: Ihtimal prospective forecast study (protocol v1.0, sha256 02af6b1ee6b24cf30af3e589ae40135b76a74025efbc7caf60acfd9bd5fe1a9a, deposited at doi:10.5281/zenodo.23500445).
Written: 2026-10-20T13:50:47Z, before the first locked kick-off (2026-10-20T15:00:00Z) and before any result of a locked match was known. Deposited as a new version of the same Zenodo record before that kick-off.
Author: Mohammed Hashem Mohammed Al Kuhali (ORCID 0009-0008-2632-8350).

## What changes

1. **Period (section 2).** The primary analysis covers every match in the first lock manifest (`2026-10-20_manifest.json`, sha256 4e33d4fa7330d332149a754f35a38e22871285fa3e9c86671a4339e8c34cae90) that kicks off between 20 Oct 2026 15:00 UTC and 1 Nov 2026 23:59:59 UTC. This replaces the end date of 6 Dec 2026. The first manifest holds 82 matches with kick-offs from 2026-10-20T15:00:00Z to 2026-11-01T20:00:00Z (epl: 19, laliga: 20, ligue1: 18, spl: 23, ucl: 2).
2. **Lock runs (section 4).** No further lock run is part of the primary analysis. Weekly lock runs may continue for the public site; any match locked after 20 Oct 2026 is outside the primary analysis and is reported, if at all, as a separately labelled follow-up.
3. **Postponed or rescheduled matches (section 6).** The original forecast stands and is scored if the match is played on or before 8 Nov 2026 (7 days after the new end date). Otherwise it is listed as unresolved and excluded, and the number is reported.
4. **Final scoring.** The single final scoring run takes place after 8 Nov 2026 23:59:59 UTC with the unchanged scoring script.
5. **Expected precision (section 10).** With about 82 scored matches, the 95% interval half-width is about 0.009 RPS against Elo-only and about 0.027 against base rates (Bonferroni 97.5%: 0.031). The study is therefore underpowered: H1 (skill over base rates) may not reach the pre-set threshold even if it holds, and H2 (difference from Elo-only) is very unlikely to be detectable. Either outcome will be reported as stated in section 10; the sample is not extended or cut depending on results.

## Unchanged

Hypotheses, metrics, baselines, the counted forecast (earliest lock; featured matches use the adjusted headline), the paired bootstrap with the Bonferroni-adjusted 97.5% interval, the six sensitivity analyses, the handling of abandoned and extra-time matches, and the scoring script.

## Reason

The author's available time. The decision was made before any locked match had kicked off and before any of its results were known.
