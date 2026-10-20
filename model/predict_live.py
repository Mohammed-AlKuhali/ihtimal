"""Live predictions + featured adjustments + lock.

usage: python predict_live.py [--lock]
 * fits the shipped models (settings chosen on 2024-25 in the backtest; see data/backtest_*.json) on ALL results before today
 * predicts every fixture of the four site leagues in the next 14 days (+ the three featured games)
 * featured games: base prediction (backtested model) + capped, documented adjustments -> `adjusted` (the headline, counted in the tally)
 * with --lock: writes featured match files with sha256 + locked_at (immutable: an existing locked file is never overwritten) and locks.json
"""
import sys, os, json, datetime as dt, math
import numpy as np
import pandas as pd
from core import *
from dc import score_grids, wdl
from lockutil import sha256_of, round_floats
from teams import team_record, AR

SITE = os.path.join(ROOT, "site", "data")
INPUTS = os.path.join(ROOT, "inputs")
LOCK = "--lock" in sys.argv
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
NOW_S = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
def _default_cutoff():
    """The fit uses every result in data/matches.csv: cutoff = 00:00 UTC on the day after the latest result. Override with IHTIMAL_CUTOFF=YYYY-MM-DD."""
    if os.environ.get("IHTIMAL_CUTOFF"):
        return pd.Timestamp(os.environ["IHTIMAL_CUTOFF"])
    return pd.Timestamp(pd.read_csv(os.path.join(ROOT, "data", "matches.csv"), usecols=["date"])["date"].max()) + pd.Timedelta(days=1)


CUTOFF = _default_cutoff()
CUTOFF_S = CUTOFF.strftime("%Y-%m-%dT00:00:00Z")
LAST_RESULT_LABEL = (CUTOFF - pd.Timedelta(days=1)).strftime("%d %b %Y").lstrip("0")
MODEL_VERSION = "ihtimal-v1.0"
REGULAR_MIN = 0.50  # PLAN section 3.2: a regular has played >= 50% of the club's available league+UCL minutes this season

COMP_META = {
    "spl": {"key": "spl", "ar": "دوري روشن السعودي", "en": "Saudi Pro League"},
    "epl": {"key": "epl", "ar": "الدوري الإنجليزي الممتاز", "en": "Premier League"},
    "laliga": {"key": "laliga", "ar": "الدوري الإسباني (الليغا)", "en": "La Liga"},
    "ligue1": {"key": "ligue1", "ar": "الدوري الفرنسي", "en": "Ligue 1"},
    "ucl": {"key": "ucl", "ar": "دوري أبطال أوروبا", "en": "UEFA Champions League"},
}
PLAYER_AR = {"Manuel Neuer": "نوير", "Jamal Musiala": "موسيالا", "Michael Olise": "أوليسي", "Vinícius Júnior": "فينيسيوس جونيور",
             "Jules Koundé": "كوندي", "Andreas Christensen": "كريستنسن", "Eric García": "إريك غارسيا", "Gerard Martín": "جيرارد مارتين",
             "Piero Hincapié": "هينكابي", "William Saliba": "ساليبا", "Christos Tzolis": "تزوليس", "Éder Militão": "ميليتاو"}
TEAM_KEY = {"Barcelona": "barcelona", "Paris Saint-Germain": "psg", "Bayern Munich": "bayern", "Arsenal": "arsenal", "Real Madrid": "real-madrid"}


def pyify(o):
    if isinstance(o, dict):
        return {k: pyify(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [pyify(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return pyify(o.tolist())
    return o


# ------------------------------------------------------------------ models
class Live:
    def __init__(self, df, comps, xi, reg, w_dom, w_ucl=None):
        self.df = df
        self.space = Space(df, comps)
        train = df[df.dt < CUTOFF]
        assert train.dt.max() < CUTOFF
        self.fit = fit_at(self.space, train, CUTOFF, xi, reg)
        self.elo, (self.t0, self.t1, self.b), self.gcoef = elo_models(train)
        self.xi, self.reg, self.w_dom, self.w_ucl = xi, reg, w_dom, (w_ucl if w_ucl is not None else w_dom)
        self.n_train = len(train)
        # recent activity per team (matches in last 365 days) for thin-data warnings
        last = train[train.dt >= CUTOFF - pd.Timedelta(days=365)]
        cnt = pd.concat([last.home, last.away]).value_counts()
        self.recent = cnt.to_dict()

    def lambdas(self, h, a, comp, w=None):
        sp = self.space
        hi, ai, ci = sp.tix[h], sp.tix[a], sp.cix[comp]
        lh, la = lambdas(self.fit, np.array([hi]), np.array([ai]), ci)
        lh, la = float(lh[0]), float(la[0])
        if w is None:
            w = self.w_ucl if comp == "ucl" else self.w_dom
        if w < 1.0:
            x = (self.elo.get(h) - self.elo.get(a) + self.elo.H) / 400.0
            sup = self.gcoef[0] + self.gcoef[1] * x
            T = lh + la
            leh, lea = max((T + sup) / 2, 0.2), max((T - sup) / 2, 0.2)
            lh = math.exp(w * math.log(lh) + (1 - w) * math.log(leh))
            la = math.exp(w * math.log(la) + (1 - w) * math.log(lea))
        return lh, la, self.fit.rho, w


def block(lh, la, rho):
    G = score_grids(np.array([lh]), np.array([la]), rho)[0]
    p = wdl(G)
    k, sc, ps = pick_from_grid(G)
    flat = np.dstack(np.unravel_index(np.argsort(-G.ravel())[:5], G.shape))[0]
    top = [{"score": [int(i), int(j)], "p": float(G[i, j])} for i, j in flat]
    ii, jj = np.indices(G.shape)
    return {"lambda_home": lh, "lambda_away": la, "rho": rho, "p_home": float(p[0]), "p_draw": float(p[1]), "p_away": float(p[2]),
            "pick": {"outcome": "HDA"[k], "score": [sc[0], sc[1]], "p_score": ps},
            "top_scores": top, "grid_6x6": G[:6, :6].tolist(),
            "expected_goals": {"home": float((G * ii).sum()), "away": float((G * jj).sum())}}


# ------------------------------------------------------------------ featured adjustments
def load_players():
    return json.load(open(os.path.join(ROOT, "data", "raw", "espn", "players_featured.json")))


def team_minutes_goals(m, team):
    s = m[(m.season == 2026) & ((m.home == team) | (m.away == team)) & m.comp.isin(["epl", "laliga", "ligue1", "bundesliga", "ucl"])]
    games = len(s)
    gf = int(sum(r.hg if r.home == team else r.ag for r in s.itertuples()))
    return games, gf


def sv(s, k):
    return float((s or {}).get(k, 0) or 0)


def pc1(x):
    # share as a percentage with one decimal (so 49.7% is not shown as 50% next to a 50% threshold)
    return ('%.1f' % (x * 100)).rstrip('0').rstrip('.')


def pct(x):
    return "%+d%%" % round((x - 1) * 100)


def adjust_featured(feat, base_lh, base_la, m, players, avail, xgm, tmeta):
    mid = feat["match_id"]
    home, away = feat["home"], feat["away"]
    hid, aid = tmeta[home]["id"], tmeta[away]["id"]
    adjs, why = [], []
    # ---- xG regression (heuristic, capped)
    def xg_ratio(team):
        t = xgm["teams"][team]
        att = min(max(math.sqrt(t["xgf"] / t["gf"]), 0.92), 1.08)
        dfn = min(max(math.sqrt(t["xga"] / t["ga"]), 0.92), 1.08)
        return att, dfn, t
    atth, defh, th = xg_ratio(home)
    atta, defa, ta = xg_ratio(away)
    xg_h = min(max(atth * defa, 0.92), 1.08)  # home lambda: own attack x opponent's defence over/under-performance
    xg_a = min(max(atta * defh, 0.92), 1.08)
    for team, att, dfn, t in [(home, atth, defh, th), (away, atta, defa, ta)]:
        adjs.append({"kind": "xg", "team": tmeta[team]["id"], "type": "attack", "metric": "sqrt(xG for / goals for)", "xg": t["xgf"], "goals": t["gf"], "games": t["games"],
                     "multiplier": att, "applies_to": "own", "source": "https://statz.ai (team xG tables, 18 Oct 2026)", "checked_at": xgm["checked_at"],
                     "effect_en": f"{tmeta[team]['en']} expected goals {pct(att)} (scored {t['gf']} vs {t['xgf']} xG)", "effect_ar": ""})
        adjs.append({"kind": "xg", "team": tmeta[team]["id"], "type": "defence", "metric": "sqrt(xG against / goals against)", "xg": t["xga"], "goals": t["ga"], "games": t["games"],
                     "multiplier": dfn, "applies_to": "opponent", "source": "https://statz.ai (team xG tables, 18 Oct 2026)", "checked_at": xgm["checked_at"],
                     "effect_en": f"opponent expected goals {pct(dfn)} (conceded {t['ga']} vs {t['xga']} xG)", "effect_ar": ""})
    adjs.append({"kind": "xg_combined", "team": hid, "type": "combined", "multiplier": xg_h, "applies_to": "home", "cap": [0.92, 1.08],
                 "effect_en": f"{tmeta[home]['en']} expected goals {pct(xg_h)} from the xG check (capped 0.92-1.08)", "effect_ar": ""})
    adjs.append({"kind": "xg_combined", "team": aid, "type": "combined", "multiplier": xg_a, "applies_to": "away", "cap": [0.92, 1.08],
                 "effect_en": f"{tmeta[away]['en']} expected goals {pct(xg_a)} from the xG check (capped 0.92-1.08)", "effect_ar": ""})
    for team, opp, mult, own_t, opp_t in [(home, away, xg_h, th, ta), (away, home, xg_a, ta, th)]:
        if abs(mult - 1) >= 0.005:
            why.append({"ar": f"فحص الفرص المتوقعة (xG): {tmeta[team]['ar']} سجّل {own_t['gf']} من فرص تساوي {own_t['xgf']}، و{tmeta[opp]['ar']} استقبل {opp_t['ga']} من فرص تساوي {opp_t['xga']}، فتتغيّر أهداف {tmeta[team]['ar']} المتوقعة {abs(round((mult - 1) * 100))}% {'للأسفل' if mult < 1 else 'للأعلى'} (تعديل تجريبي محدود بـ ±8%).",
                        "en": f"xG check: {tmeta[team]['en']} scored {own_t['gf']} from {own_t['xgf']} xG and {tmeta[opp]['en']} conceded {opp_t['ga']} from {opp_t['xga']} xG, so {tmeta[team]['en']}'s expected goals move {pct(mult)} (heuristic, capped at +/-8%)."})
    for a_ in adjs:
        if a_["kind"] == "xg":
            a_["effect_ar"] = ("أهداف الفريق المتوقعة " if a_["type"] == "attack" else "أهداف المنافس المتوقعة ") + ("%+d%%" % round((a_["multiplier"] - 1) * 100))
        elif a_["kind"] == "xg_combined":
            a_["effect_ar"] = f"أهداف {tmeta[home]['ar'] if a_['applies_to'] == 'home' else tmeta[away]['ar']} المتوقعة " + ("%+d%%" % round((a_["multiplier"] - 1) * 100)) + " من فحص xG"
    # ---- availability
    att_f = {home: 1.0, away: 1.0}
    def_sum = {home: 0.0, away: 0.0}  # boost applied to the key team's lambda (caused by the OTHER team's absentees)
    for it in avail["matches"][mid]:
        if it["p_out"] <= 0:
            continue
        team = it["team"]
        opp = away if team == home else home
        pk = TEAM_KEY[team]
        pl = next(p for p in players[pk] if p["name"] == it["player"])
        games, gf = team_minutes_goals(m, team)
        mins = sv(pl["league"], "minutes") + sv(pl["ucl"], "minutes")
        mshare = mins / (90.0 * games)
        ga = sv(pl["league"], "totalGoals") + sv(pl["ucl"], "totalGoals") + sv(pl["league"], "goalAssists") + sv(pl["ucl"], "goalAssists")
        gshare = ga / gf if gf else 0.0
        regular = mshare >= REGULAR_MIN
        pos = pl["pos"]
        typ = "goalkeeper" if pos == "G" else ("defence" if pos == "D" else "attack")
        mult, applies = 1.0, ("home" if team == away else "away")  # defence boosts apply to the opponent's lambda
        if regular:
            if typ == "attack":
                mult = 1.0 - 0.4 * gshare * it["p_out"]
                att_f[team] *= mult; applies = "home" if team == home else "away"
            elif typ == "defence":
                mult = 1.0 + 0.03 * it["p_out"]; def_sum[opp] += 0.03 * it["p_out"]
            else:
                mult = 1.0 + 0.04 * it["p_out"]; def_sum[opp] += 0.04 * it["p_out"]
        else:
            applies = "none"
        name_ar = PLAYER_AR.get(it["player"], it["player"])
        if regular and typ == "attack":
            eff_en = f"{tmeta[team]['en']} expected goals {pct(mult)} ({it['player']} {it['status']}; {round(gshare * 100)}% of the team's goals+assists, p_out {it['p_out']})"
            eff_ar = f"غياب {name_ar} يخفّض أهداف {tmeta[team]['ar']} المتوقعة {abs(round((mult - 1) * 100))}%"
        elif regular:
            eff_en = f"{tmeta[opp]['en']} expected goals {pct(mult)} ({it['player']} {it['status']}, p_out {it['p_out']})"
            eff_ar = f"غياب {name_ar} (احتمال {round(it['p_out'] * 100)}%) يرفع أهداف {tmeta[opp]['ar']} المتوقعة {abs(round((mult - 1) * 100))}%"
        else:
            eff_en = f"no change: {it['player']} is below the 50% regular line this season ({pc1(mshare)}% of the club's minutes)"
            eff_ar = f"غياب {name_ar} لا يغيّر الحساب: لعب {pc1(mshare)}% من دقائق الفريق هذا الموسم، دون حدّ الأساسي (50%)"
        adjs.append({"kind": "availability", "team": tmeta[team]["id"], "player": it["player"], "player_ar": PLAYER_AR.get(it["player"]), "position": pos, "type": typ if regular else "none",
                     "status": it["status"], "p_out": it["p_out"], "regular": bool(regular), "minutes_share": round(mshare, 3), "goal_involvement_share": round(gshare, 3) if typ == "attack" else None,
                     "multiplier": mult, "applies_to": applies, "note": it["note"], "source": it["source"], "checked_at": avail["checked_at"], "effect_en": eff_en, "effect_ar": eff_ar})
        if regular and abs(mult - 1) >= 0.005:
            why.append({"ar": eff_ar + ".", "en": eff_en[0].upper() + eff_en[1:] + "."})
        elif not regular:
            why.append({"ar": eff_ar + ".", "en": eff_en[0].upper() + eff_en[1:] + "."})
    mult_h = xg_h * max(att_f[home], 0.85) * min(1.0 + def_sum[home], 1.08)
    mult_a = xg_a * max(att_f[away], 0.85) * min(1.0 + def_sum[away], 1.08)
    return base_lh * mult_h, base_la * mult_a, adjs, why, (mult_h, mult_a)


# ------------------------------------------------------------------ assembly
def build_match(mid, comp_key, stage, kickoff, venue, h, a, tmeta, model, w, extra):
    lh, la, rho, w_used = model.lambdas(h, a, comp_key, w)
    base = block(lh, la, rho)
    elo_h, elo_a = model.elo.get(h), model.elo.get(a)
    legs = {"model": "dc" if w_used >= 1 else "dc+elo", "w_goals": w_used, "elo_weight": 1 - w_used, "xi": model.xi, "half_life_days": round(math.log(2) / model.xi, 1),
            "reg_team": model.reg, "train_matches": model.n_train, "refit_cutoff": CUTOFF.strftime("%Y-%m-%d")}
    obj = {"match_id": mid,
           "competition": {**COMP_META[comp_key], "stage": stage, "stage_ar": ""},
           "kickoff_utc": kickoff, "venue": venue,
           "home": {k: tmeta[h][k] for k in ("id", "ar", "en", "colour")}, "away": {k: tmeta[a][k] for k in ("id", "ar", "en", "colour")},
           "model_version": MODEL_VERSION, "data_cutoff_utc": CUTOFF_S, "featured": False}
    obj.update(base)
    obj["elo"] = {"home": round(elo_h, 1), "away": round(elo_a, 1), "clubelo_home": None, "clubelo_away": None}
    obj["legs"] = legs
    obj["base"] = dict(base)
    obj["adjusted"] = None
    obj["headline"] = "base"
    obj["adjustments"] = []
    obj["why"] = [{"ar": "بدون تعديل الغيابات", "en": "No availability adjustment (base model only)"}]
    obj["benchmarks"] = {}
    obj["generated_at"] = NOW_S
    obj["locked_at"] = None
    obj["version"] = 1
    obj["sha256"] = None
    obj.update(extra)
    return obj


def main():
    m = load_matches()
    tmeta = json.load(open(os.path.join(ROOT, "data", "team_meta.json")))
    bt_eu = json.load(open(os.path.join(ROOT, "data", "backtest_eu.json")))["selected"]
    bt_spl = json.load(open(os.path.join(ROOT, "data", "backtest_spl.json")))["selected"]
    eu = Live(m[m.comp.isin(EU_COMPS)].copy(), EU_COMPS, bt_eu["xi"], bt_eu["reg"], bt_eu["w"], bt_eu["w_ucl"])
    spl = Live(m[m.comp == "spl"].copy(), ["spl"], bt_spl["xi"], bt_spl["reg"], bt_spl["w"])
    print("EU fit", eu.fit.success, eu.n_train, "rho", round(eu.fit.rho, 3), "eta", round(eu.fit.eta, 3), "| SPL fit", spl.fit.success, spl.n_train, "rho", round(spl.fit.rho, 3))
    fx = json.load(open(os.path.join(ROOT, "data", "fixtures_raw.json")))
    feat_in = json.load(open(os.path.join(INPUTS, "fixtures_featured.json")))
    avail = json.load(open(os.path.join(INPUTS, "availability.json")))
    xgm = json.load(open(os.path.join(INPUTS, "xg_manual.json")))
    players = load_players()
    os.makedirs(os.path.join(SITE, "matches"), exist_ok=True); os.makedirs(os.path.join(SITE, "leagues"), exist_ok=True)

    # sanity: ESPN agrees on featured kickoffs
    for f in feat_in:
        hit = [x for x in fx if x["home"] == f["home"] and x["away"] == f["away"] and x["comp"] == f["comp"]]
        assert hit, f"featured fixture missing in ESPN schedule: {f['match_id']}"
        if hit[0]["kickoff_utc"][:16] != f["kickoff_utc"][:16]:
            print("WARNING kickoff differs", f["match_id"], hit[0]["kickoff_utc"], f["kickoff_utc"])

    # ---------------- featured
    featured = []
    locks = []
    for f in feat_in:
        mid = f["match_id"]
        path = os.path.join(SITE, "matches", mid + ".json")
        if os.path.exists(path) and json.load(open(path)).get("locked_at"):
            print("LOCKED already, keeping immutable:", mid)
            featured.append(json.load(open(path)))
            continue
        obj = build_match(mid, f["comp"], f["competition"]["stage"], f["kickoff_utc"], f["venue"], f["home"], f["away"], tmeta, eu, None, {})
        obj["competition"] = f["competition"]
        base = obj["base"]
        alh, ala, adjs, why, (mh, ma) = adjust_featured(f, base["lambda_home"], base["lambda_away"], m, players, avail, xgm, tmeta)
        adj = block(alh, ala, base["rho"])
        adj["multiplier_home"], adj["multiplier_away"] = mh, ma
        obj.update({k: adj[k] for k in ("lambda_home", "lambda_away", "rho", "p_home", "p_draw", "p_away", "pick", "top_scores", "grid_6x6", "expected_goals")})
        obj["adjusted"] = adj
        obj["headline"] = "adjusted"
        obj["featured"] = True
        obj["adjustments"] = adjs
        obj["why"] = why
        obj["adjustments_label"] = {"ar": "تعديلات تجريبية (غير مُختبرة على موسم كامل): الغيابات وفحص الفرص المتوقعة", "en": "Heuristic adjustments, not backtested: availability and an xG check. The base model is the backtested one."}
        # sensitivity: Dixon-Coles only (w=1) for UCL games where the shipped blend uses Elo (w_ucl=0.3)
        if f["comp"] == "ucl":
            lh1, la1, rho1, _ = eu.lambdas(f["home"], f["away"], "ucl", 1.0)
            b1 = block(lh1, la1, rho1)
            obj["sensitivity"] = {"dc_only_base": {k: b1[k] for k in ("lambda_home", "lambda_away", "p_home", "p_draw", "p_away", "pick")},
                                  "note": "Same base model with the Elo leg switched off (w=1). Shown for transparency; the published base uses the pre-registered weight."}
        obj["tally_rule"] = "The public tally counts `adjusted` (the headline). `base` is the backtested model and is scored alongside it. v1 only: later versions are shown but never swapped in."
        if f["match_id"].endswith("barcelona-real-madrid"):
            obj["tally_rule"] += " A later (v2) refresh of this match, if any, is labelled and never replaces this file."
        obj = pyify(round_floats(obj))
        if LOCK:
            obj["locked_at"] = NOW_S
            obj["sha256"] = sha256_of(obj)
            json.dump(obj, open(path, "w"), ensure_ascii=False, indent=1)
            locks.append({"match_id": mid, "file": f"site/data/matches/{mid}.json", "sha256": obj["sha256"], "locked_at_utc": obj["locked_at"], "kickoff_utc": obj["kickoff_utc"],
                          "headline": {"p_home": obj["p_home"], "p_draw": obj["p_draw"], "p_away": obj["p_away"], "pick": obj["pick"]},
                          "base": {k: obj["base"][k] for k in ("p_home", "p_draw", "p_away", "pick")}})
        featured.append(obj)
    if LOCK and locks:
        lk = {"locked_at_utc": NOW_S, "model_version": MODEL_VERSION,
              "algorithm": "sha256 over the canonical JSON of the match file excluding top-level sha256, locked_at, benchmarks, sanity and elo.clubelo_home/away (see model/lockutil.py and site/data/SCHEMA.md)",
              "sequence": [f"1. model fitted on results through {LAST_RESULT_LABEL} and adjustments computed from the cited team news", "2. match files hashed and written (this file)", "3. only afterwards: Opta benchmark and ClubElo sanity check added outside the hash"],
              "matches": locks}
        rh = os.path.join(INPUTS, "relock_history.json")
        if os.path.exists(rh):  # a lock replaced BEFORE anything was published; kept here so the history is never hidden
            lk["relock_history"] = json.load(open(rh))
        json.dump(lk, open(os.path.join(SITE, "locks.json"), "w"), ensure_ascii=False, indent=1)
        print("locked", [x["match_id"] for x in locks])

    # ---------------- all fixtures next 14 days, four leagues
    end = NOW + dt.timedelta(days=14)
    leagues = {"spl": [], "epl": [], "laliga": [], "ligue1": []}
    featured_keys = {(f["home"], f["away"], f["kickoff_utc"][:10]): obj for f, obj in zip(feat_in, featured)}
    missing_ar = set()
    for x in sorted(fx, key=lambda r: r["kickoff_utc"]):
        if x["comp"] not in leagues:
            continue
        ko = dt.datetime.strptime(x["kickoff_utc"][:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
        if not (NOW < ko <= end):
            continue
        key = (x["home"], x["away"], x["kickoff_utc"][:10])
        if key in featured_keys:
            obj = featured_keys[key]
        else:
            for t in (x["home"], x["away"]):
                if not tmeta[t].get("ar"):
                    missing_ar.add(t)
            mid = f"{ko.strftime('%Y-%m-%d')}_{tmeta[x['home']]['id']}-{tmeta[x['away']]['id']}"
            model = spl if x["comp"] == "spl" else eu
            for t in (x["home"], x["away"]):
                assert t in model.space.tix, f"unknown team {t}"
            obj = build_match(mid, x["comp"], "", ko.strftime("%Y-%m-%dT%H:%M:%SZ"), x.get("venue"), x["home"], x["away"], tmeta, model, None, {})
            obj = pyify(round_floats(obj))
            json.dump(obj, open(os.path.join(SITE, "matches", mid + ".json"), "w"), ensure_ascii=False, indent=1)
        leagues[x["comp"]].append(obj)
    assert not missing_ar, f"missing Arabic names: {missing_ar}"
    counts = {}
    for lk_, lst in leagues.items():
        slim = []
        for o in lst:
            slim.append({"match_id": o["match_id"], "kickoff_utc": o["kickoff_utc"], "venue": o["venue"], "home": o["home"], "away": o["away"],
                         "p_home": o["p_home"], "p_draw": o["p_draw"], "p_away": o["p_away"], "pick": o["pick"], "top_scores": o["top_scores"],
                         "lambda_home": o["lambda_home"], "lambda_away": o["lambda_away"], "featured": o["featured"],
                         "has_adjustments": bool(o["adjustments"]), "locked": bool(o["locked_at"]), "sha256": o["sha256"]})
        doc = {"league": COMP_META[lk_], "generated_at": NOW_S, "window_days": 14, "window_end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "model_version": MODEL_VERSION, "data_cutoff_utc": CUTOFF_S, "n_matches": len(slim), "matches": slim}
        json.dump(pyify(round_floats(doc)), open(os.path.join(SITE, "leagues", f"{lk_}.json"), "w"), ensure_ascii=False, indent=1)
        counts[lk_] = len(slim)
    print("fixtures predicted:", counts)
    json.dump({"generated_at": NOW_S, "matches": featured}, open(os.path.join(SITE, "featured.json"), "w"), ensure_ascii=False, indent=1)
    return counts


if __name__ == "__main__":
    main()
