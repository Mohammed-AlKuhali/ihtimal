"""Head-to-head: build the H2H pool (data/h2h_pool.csv) and write site/data/h2h/<match_id>.json for every published fixture.

Sources (open only): ESPN public scoreboard JSON (older years + second tiers + cups, via fetch_h2h.py; the existing raw feeds for 2023+)
and data/matches.csv (openfootball where ESPN has a gap). Competitions: five leagues and their second tiers, Saudi Pro League
(ESPN only from Aug 2022), UEFA Champions League / Europa League / Conference League / Super Cup, the domestic cups and super cups of
England, Spain, France, Germany, Italy, the Saudi King's Cup, AFC Champions League, Club World Cup. Friendlies are not included.
usage: python h2h.py build | files
"""
import os, sys, json, glob, datetime as dt
import pandas as pd
from teams import team_record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site", "data")
POOL_CSV = os.path.join(DATA, "h2h_pool.csv")

COMP = {  # espn slug -> (key, en, ar)
    "eng.1": ("epl", "Premier League", "الدوري الإنجليزي الممتاز"), "eng.2": ("eng2", "EFL Championship", "التشامبيونشيب الإنجليزي"),
    "esp.1": ("laliga", "La Liga", "الدوري الإسباني (الليغا)"), "esp.2": ("esp2", "Segunda División", "الدرجة الثانية الإسبانية"),
    "fra.1": ("ligue1", "Ligue 1", "الدوري الفرنسي"), "fra.2": ("fra2", "Ligue 2", "الدرجة الثانية الفرنسية"),
    "ger.1": ("bundesliga", "Bundesliga", "الدوري الألماني (البوندسليغا)"), "ger.2": ("ger2", "2. Bundesliga", "الدرجة الثانية الألمانية"),
    "ita.1": ("seriea", "Serie A", "الدوري الإيطالي"), "ita.2": ("ita2", "Serie B", "الدرجة الثانية الإيطالية"),
    "ksa.1": ("spl", "Saudi Pro League", "دوري روشن السعودي"),
    "uefa.champions": ("ucl", "UEFA Champions League", "دوري أبطال أوروبا"), "uefa.europa": ("uel", "UEFA Europa League", "الدوري الأوروبي"),
    "uefa.europa.conf": ("uecl", "UEFA Conference League", "دوري المؤتمر الأوروبي"), "uefa.super_cup": ("usc", "UEFA Super Cup", "كأس السوبر الأوروبي"),
    "eng.fa": ("facup", "FA Cup", "كأس الاتحاد الإنجليزي"), "eng.league_cup": ("lcup", "EFL Cup", "كأس الرابطة الإنجليزية"),
    "eng.charity": ("shield", "Community Shield", "الدرع الخيرية"), "esp.copa_del_rey": ("copa", "Copa del Rey", "كأس ملك إسبانيا"),
    "esp.super_cup": ("supercopa", "Supercopa de España", "كأس السوبر الإسباني"), "fra.coupe_de_france": ("cdf", "Coupe de France", "كأس فرنسا"),
    "fra.coupe_de_la_ligue": ("cdl", "Coupe de la Ligue", "كأس الرابطة الفرنسية"), "fra.super_cup": ("tdc", "Trophée des Champions", "كأس أبطال فرنسا"),
    "ger.dfb_pokal": ("dfb", "DFB-Pokal", "كأس ألمانيا"), "ita.coppa_italia": ("coppa", "Coppa Italia", "كأس إيطاليا"),
    "ksa.kings.cup": ("kings", "King's Cup", "كأس الملك"), "afc.champions": ("acl", "AFC Champions League", "دوري أبطال آسيا"),
    "fifa.cwc": ("cwc", "FIFA Club World Cup", "كأس العالم للأندية"),
}
CSV_SLUG = {"epl": "eng.1", "laliga": "esp.1", "ligue1": "fra.1", "bundesliga": "ger.1", "seriea": "ita.1", "spl": "ksa.1", "ucl": "uefa.champions"}
SAUDI_SLUGS = ["ksa.1", "ksa.kings.cup", "afc.champions"]
FINISHED = {"STATUS_FULL_TIME": "ft", "STATUS_FINAL_AGT": "ft", "STATUS_FINAL_AET": "aet", "STATUS_FINAL_PEN": "pens"}
STAGE_EN = {"group-stage": "Group stage", "league-phase": "League phase", "round-of-16": "Round of 16", "quarterfinals": "Quarter-final",
            "semifinals": "Semi-final", "final": "Final", "knockout-round-playoffs": "Knockout play-off", "playoffs": "Play-off",
            "qualifying": "Qualifying"}


def _num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def espn_rows():
    rows = []
    files = glob.glob(os.path.join(DATA, "raw", "h2h", "*.json"))
    for f in files:
        for e in json.load(open(f))["events"]:
            slug = os.path.basename(f).rsplit("_", 1)[0]
            rows.append((slug, e))
    for f in glob.glob(os.path.join(DATA, "raw", "espn", "*_20*.json")):  # existing raw feeds (2023+): full event objects
        slug = os.path.basename(f).rsplit("_", 1)[0]
        if slug == "players_featured":
            continue
        for e in json.load(open(f))["events"]:
            c = e["competitions"][0]
            cs = {x["homeAway"]: x for x in c["competitors"]}
            if "home" not in cs or "away" not in cs:
                continue
            rows.append((slug, dict(id=e["id"], date=e["date"], status=c["status"]["type"]["name"], stage=(e.get("season") or {}).get("slug"),
                                    leg=(c.get("leg") or {}).get("value"), venue=(c.get("venue") or {}).get("fullName"),
                                    home=cs["home"]["team"]["displayName"], home_id=cs["home"]["team"]["id"], hs=cs["home"].get("score"), hp=cs["home"].get("shootoutScore"),
                                    away=cs["away"]["team"]["displayName"], away_id=cs["away"]["team"]["id"], as_=cs["away"].get("score"), ap=cs["away"].get("shootoutScore"))))
    return rows


OF_CODE = {"en.1": "eng.1", "en.2": "eng.2", "es.1": "esp.1", "es.2": "esp.2", "fr.1": "fra.1", "fr.2": "fra.2", "de.1": "ger.1", "it.1": "ita.1", "it.2": "ita.2"}


def add_openfootball_old(df):
    """Older seasons (2010-11..2022-23) from openfootball (public domain): cross-check against ESPN, fill what ESPN lacks."""
    import re
    from build_data import norm_tokens
    from teams import OF_TO_CANON
    canon = {}
    for r in df.itertuples():
        canon.setdefault(r.slug, set()).update((r.home, r.away))
    idx = {}
    for r in df.itertuples():
        idx.setdefault((r.slug, r.home, r.away), []).append((pd.Timestamp(r.date), r.hg, r.ag))
    add, n_cmp, n_mis, unmapped, cache = [], 0, 0, set(), {}
    for f in sorted(glob.glob(os.path.join(DATA, "raw", "h2h", "openfootball", "*.json"))):
        season, code = os.path.basename(f)[:-5].split("_")
        slug = OF_CODE[code]
        for m in json.load(open(f))["matches"]:
            sc = m.get("score")
            if not (isinstance(sc, dict) and sc.get("ft") and len(sc["ft"]) == 2):
                continue
            names = []
            for n in (m["team1"], m["team2"]):
                k = (slug, n)
                if k not in cache:
                    best = OF_TO_CANON.get(n)
                    if best is None and n in canon[slug]:
                        best = n
                    if best is None:
                        nt = set(norm_tokens(n)); bs, bb = 0, None
                        for e in canon[slug]:
                            ne = set(norm_tokens(e))
                            if ne and nt:
                                j = len(ne & nt) / len(ne | nt)
                                if j > bs:
                                    bs, bb = j, e
                        best = bb if bs >= 0.99 else None
                    cache[k] = best
                names.append(cache[k])
                if cache[k] is None:
                    unmapped.add((slug, n))
            if None in names:
                continue
            d = pd.Timestamp(m["date"])
            hit = [x for x in idx.get((slug, names[0], names[1]), []) if abs((x[0] - d).days) <= 1]
            if hit:
                n_cmp += 1
                n_mis += int((hit[0][1], hit[0][2]) != (sc["ft"][0], sc["ft"][1]))
            else:
                add.append(dict(date=m["date"], slug=slug, stage=None, leg=None, home=names[0], away=names[1], hg=sc["ft"][0], ag=sc["ft"][1], how="ft",
                                pens_h=None, pens_a=None, source="openfootball", espn_hid=None, espn_aid=None))
    print(f"openfootball older seasons: {n_cmp} matches also in ESPN, {n_mis} score disagreements; {len(add)} not in ESPN (added); unmapped club names {len(unmapped)}")
    return pd.concat([df, pd.DataFrame(add)], ignore_index=True) if add else df


def build_pool():
    rows, seen = [], set()
    for slug, e in espn_rows():
        if e["status"] not in FINISHED or (slug, e["id"]) in seen:
            continue
        seen.add((slug, e["id"]))
        hg, ag = _num(e["hs"]), _num(e["as_"])
        if hg is None or ag is None:
            continue
        rows.append(dict(date=e["date"][:10], slug=slug, stage=e.get("stage"), leg=e.get("leg"), home=e["home"], away=e["away"], hg=hg, ag=ag,
                         how=FINISHED[e["status"]], pens_h=_num(e.get("hp")), pens_a=_num(e.get("ap")), source="espn", espn_hid=e["home_id"], espn_aid=e["away_id"]))
    df = pd.DataFrame(rows)
    df = add_openfootball_old(df)
    # gaps: matches.csv rows (openfootball) that ESPN does not hold; same pair within +-1 day in the same competition counts as the same match
    m = pd.read_csv(os.path.join(DATA, "matches.csv"))
    m["slug"] = m.comp.map(CSV_SLUG)
    key = {(r.slug, r.home, r.away): [] for r in df.itertuples()}
    for r in df.itertuples():
        key[(r.slug, r.home, r.away)].append(pd.Timestamp(r.date))
    add, overlap, mism = [], 0, 0
    for r in m.itertuples():
        ds = key.get((r.slug, r.home, r.away), [])
        d = pd.Timestamp(r.date)
        hit = [x for x in ds if abs((x - d).days) <= 1]
        if hit:
            overlap += 1
            continue
        add.append(dict(date=r.date, slug=r.slug, stage=None, leg=None, home=r.home, away=r.away, hg=int(r.hg), ag=int(r.ag), how="ft",
                        pens_h=None, pens_a=None, source="openfootball", espn_hid=None, espn_aid=None))
    print(f"matches.csv rows {len(m)}; already in ESPN pool {overlap}; added (ESPN gap, openfootball) {len(add)}")
    df = pd.concat([df, pd.DataFrame(add)], ignore_index=True)
    # restrict to clubs that matter: every club that appears in matches.csv or in the published fixtures
    keep = set(m.home) | set(m.away)
    fx = json.load(open(os.path.join(DATA, "fixtures_raw.json")))
    keep |= {f["home"] for f in fx} | {f["away"] for f in fx}
    df = df[df.home.isin(keep) & df.away.isin(keep)].copy()
    df["regulation"] = df.how.eq("ft")
    df = df.sort_values(["date", "slug", "home"]).drop_duplicates(["slug", "date", "home", "away"]).reset_index(drop=True)
    df.to_csv(POOL_CSV, index=False)
    print("pool rows", len(df), "by how:", df.how.value_counts().to_dict())
    return df


def load_pool():
    return pd.read_csv(POOL_CSV)


def pair_index(pool):
    idx = {}
    for r in pool.sort_values("date").itertuples():
        idx.setdefault(frozenset((r.home, r.away)), []).append(r)
    return idx


def ar_count(n):
    return "لقاء واحد" if n == 1 else ("لقاءان" if n == 2 else (f"{n} لقاءات" if n <= 10 else f"{n} لقاء"))


def tid(name):
    return team_record(name)["id"]


def fixture_files():
    out = []
    for f in sorted(glob.glob(os.path.join(SITE, "matches", "*.json"))):
        d = json.load(open(f))
        out.append(d)
    return out


def make_files():
    pool = load_pool()
    idx = pair_index(pool)
    # id -> canonical (ESPN) name, from every name seen in the pool and the fixtures
    names = set(pool.home) | set(pool.away)
    fx = json.load(open(os.path.join(DATA, "fixtures_raw.json")))
    names |= {f["home"] for f in fx} | {f["away"] for f in fx}
    id2name = {}
    for n in names:
        id2name.setdefault(tid(n), n)
    meta = json.load(open(os.path.join(DATA, "team_meta.json")))
    os.makedirs(os.path.join(SITE, "h2h"), exist_ok=True)
    gen = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    through = pool.date.max()
    report = []

    def side(n):
        r = team_record(n)
        return {"id": r["id"], "en": r["en"], "ar": r["ar"]}
    for d in fixture_files():
        hid, aid = d["home"]["id"], d["away"]["id"]
        hn, an = id2name[hid], id2name[aid]
        before = d["kickoff_utc"][:10]
        rows = [r for r in idx.get(frozenset((hn, an)), []) if r.date < before]
        rows = sorted(rows, key=lambda r: r.date, reverse=True)
        ms = rows[:10]
        out_m, hw = [], dict(hw=0, dr=0, aw=0, hg=0, ag=0, pens=0)
        for r in ms:
            flip = (r.home != hn)  # fixture home team was the away side that day
            gh, ga = (r.ag, r.hg) if flip else (r.hg, r.ag)  # goals of fixture-home team, fixture-away team
            res = "W" if gh > ga else ("D" if gh == ga else "L")
            shoot = None
            if r.how == "pens" and not pd.isna(r.pens_h) and not pd.isna(r.pens_a):
                ph, pa = int(r.pens_h), int(r.pens_a)
                shoot = {"home": int(r.pens_a if flip else r.pens_h), "away": int(r.pens_h if flip else r.pens_a)}
                hw["pens"] += 1
            hw["hw" if res == "W" else ("dr" if res == "D" else "aw")] += 1
            hw["hg"] += gh; hw["ag"] += ga
            key, en, ar = COMP[r.slug]
            stage = r.stage if (not pd.isna(r.stage) and r.stage in STAGE_EN) else None
            out_m.append({"date": r.date, "competition": {"key": key, "en": en, "ar": ar}, "stage": stage, "stage_en": STAGE_EN.get(stage, None),
                          "home": side(r.home), "away": side(r.away), "home_goals": int(r.hg), "away_goals": int(r.ag),
                          "decided": r.how, "penalties": ({"home": int(r.pens_h), "away": int(r.pens_a)} if (r.how == "pens" and not pd.isna(r.pens_h)) else None),
                          "fixture_home_goals": int(gh), "fixture_away_goals": int(ga), "fixture_home_team_result": res})
        n = len(out_m)
        saudi = d["competition"]["key"] == "spl"
        covered = sorted({COMP[x][1] for x in (SAUDI_SLUGS if saudi else [k for k in COMP if k not in SAUDI_SLUGS])})
        cov = {"found": n, "wanted": 10, "complete": n >= 10, "covered_since": ("2022-08" if saudi else "2010-01"), "competitions_covered": covered}
        if n < 10:
            if saudi:
                cov["note_en"] = (f"Only {n} meeting{'s' if n != 1 else ''} found. ESPN's Saudi record covers the top flight from August 2022 only (about two league meetings per season), "
                                  "plus the King's Cup and AFC Champions League; a club that was in a lower division has little or no history here.")
                cov["note_ar"] = f"وُجد {ar_count(n)} فقط. سجلّ ESPN للدوري السعودي يغطي دوري الدرجة الأولى من أغسطس 2022 فقط (لقاءان في الموسم كحدٍّ أقصى) مع كأس الملك ودوري أبطال آسيا، والنادي الذي كان في الدرجة الأدنى يكاد لا يملك سجلًّا هنا."
            else:
                cov["note_en"] = (f"Only {n} meeting{'s' if n != 1 else ''} found in the sources (five leagues and their second tiers, Champions/Europa/Conference League, domestic cups and super cups, since 2010). "
                                  "The clubs did not meet more often in those competitions (often because one was in a lower division).")
                cov["note_ar"] = f"وُجد {ar_count(n)} فقط في المصادر (الدوريات الخمسة ودرجاتها الثانية وبطولات أوروبا والكؤوس المحلية منذ 2010)؛ لم يلتقِ الفريقان أكثر من ذلك في هذه البطولات، وغالبًا لأن أحدهما كان في درجة أدنى."
        obj = {"match_id": d["match_id"], "generated_at": gen, "data_through": through,
               "home": side(hn), "away": side(an), "perspective": "fixture home team (the team listed first), whichever side hosted that day",
               "meetings": out_m,
               "summary": {"n": n, "home_wins": hw["hw"], "draws": hw["dr"], "away_wins": hw["aw"], "home_goals": hw["hg"], "away_goals": hw["ag"],
                           "decided_on_penalties_counted_as_draws": hw["pens"]},
               "coverage": cov,
               "sources": "ESPN public scoreboard JSON; openfootball (public domain) for gaps; friendlies not included"}
        json.dump(obj, open(os.path.join(SITE, "h2h", d["match_id"] + ".json"), "w"), ensure_ascii=False, indent=1)
        report.append((d["match_id"], d["competition"]["key"], n))
    return report


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build_pool()
    elif sys.argv[1] == "files":
        rep = make_files()
        import collections
        print("files", len(rep), "with 10:", sum(1 for r in rep if r[2] >= 10))
        by = collections.defaultdict(list)
        for mid, comp, n in rep:
            by[comp].append(n)
        for k, v in by.items():
            print(k, "files", len(v), "full10", sum(1 for x in v if x >= 10), "dist", sorted(collections.Counter(v).items()))
