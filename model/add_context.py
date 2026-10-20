"""Run AFTER the lock. Adds ClubElo ratings, the sanity comparison and the Opta benchmark to the match files.
All of these live outside the sha256 (benchmarks, sanity, elo.clubelo_*), so they cannot have influenced the locked numbers.
Hand-read inputs: ClubElo ratings as of 18 Oct 2026 (clubelo.com, API unavailable so read by hand); Opta/The Analyst PSG-Barca numbers (19 Oct 2026)."""
import json, os, glob, datetime as dt
from lockutil import sha256_of

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(ROOT, "site", "data", "matches")
CLUBELO_DATE = "2026-10-18"
CLUBELO = {"Arsenal": 2048, "Bayern Munich": 2042, "Barcelona": 2037, "Real Madrid": 1983, "Paris Saint-Germain": 1973,
           "Al Hilal": 1756, "Al Nassr": 1693, "Al Ahli": 1662, "Al Qadsiah": 1641, "Al Ittihad": 1581, "Al Ettifaq": 1476, "Al Diriyah": 1475,
           "Neom SC": 1471, "Al Taawoun": 1455, "Al Shabab": 1431, "Al Hazem": 1403, "Al Faisaly": 1400, "Al Khaleej": 1392, "Al Kholood": 1390,
           "Al Fateh": 1388, "Al Fayha": 1370, "Al Riyadh": 1360, "Abha": 1346}
ID2CANON = {"arsenal": "Arsenal", "bayern": "Bayern Munich", "barcelona": "Barcelona", "real-madrid": "Real Madrid", "psg": "Paris Saint-Germain",
            "al-hilal": "Al Hilal", "al-nassr": "Al Nassr", "al-ahli": "Al Ahli", "al-qadsiah": "Al Qadsiah", "al-ittihad": "Al Ittihad", "al-ettifaq": "Al Ettifaq",
            "al-diriyah": "Al Diriyah", "neom": "Neom SC", "al-taawoun": "Al Taawoun", "al-shabab": "Al Shabab", "al-hazem": "Al Hazem", "al-faisaly": "Al Faisaly",
            "al-khaleej": "Al Khaleej", "al-kholood": "Al Kholood", "al-fateh": "Al Fateh", "al-fayha": "Al Fayha", "al-riyadh": "Al Riyadh", "abha": "Abha"}
OPTA = {"2026-10-20_psg-barcelona": {"h": 0.397, "d": 0.226, "a": 0.377, "source": "Opta supercomputer via The Analyst, 19 Oct 2026",
                                    "url": "https://theanalyst.com/articles/psg-vs-barcelona-prediction-champions-league-10-2026"}}
NOW = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    n = 0
    for f in sorted(glob.glob(M + "/*.json")):
        o = json.load(open(f))
        hc, ac = ID2CANON.get(o["home"]["id"]), ID2CANON.get(o["away"]["id"])
        if not (hc in CLUBELO and ac in CLUBELO):
            continue
        before = sha256_of(o) if o.get("sha256") else None
        o["elo"]["clubelo_home"], o["elo"]["clubelo_away"] = CLUBELO[hc], CLUBELO[ac]
        ours, theirs = o["elo"]["home"] - o["elo"]["away"], CLUBELO[hc] - CLUBELO[ac]
        o["sanity"] = {"added_at": NOW, "clubelo_date": CLUBELO_DATE, "source": "clubelo.com (read by hand)",
                       "our_elo_diff": round(ours, 1), "clubelo_diff": theirs, "gap": round(abs(ours - theirs), 1),
                       "flag_gap_over_40": bool(abs(ours - theirs) > 40),
                       "note": "Our Elo runs on a closed pool from 1500 (3 seasons), so only differences are comparable. Display only: no model value was changed after the lock."}
        if o["match_id"] in OPTA:
            o["benchmarks"] = {"opta": OPTA[o["match_id"]]}
        elif o.get("featured"):
            o["benchmarks"] = {"opta": None,
                               "note_ar": "لم نعثر على رقم منشور من أوبتا لهذه المباراة وقت قفلنا. سنضيفه هنا إن نُشر، ولن يغيّر توقّعنا المقفل.",
                               "note_en": "We found no published Opta number for this match when we locked. We will add it here if it appears; it will not change our locked prediction."}
        if before:
            assert sha256_of(o) == before == o["sha256"], "context changed the locked hash!"
        json.dump(o, open(f, "w"), ensure_ascii=False, indent=1)
        n += 1
    # refresh featured.json from the files
    fj = os.path.join(ROOT, "site", "data", "featured.json")
    feat = json.load(open(fj))
    feat["matches"] = [json.load(open(os.path.join(M, x["match_id"] + ".json"))) for x in feat["matches"]]
    json.dump(feat, open(fj, "w"), ensure_ascii=False, indent=1)
    print("context added to", n, "files")


if __name__ == "__main__":
    main()
