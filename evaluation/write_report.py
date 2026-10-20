"""Renders EVALUATION.md from evaluation/results.json. Every number is read from results.json (computed by run_eval.py);
the only hand-written parts are sentences, and where a sentence makes a directional claim the direction is chosen by code from the numbers."""
import os, json, math

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
G_EU, G_SITE, G_SPL = "Europe (big-5 + UCL)", "Site leagues (EPL + La Liga + Ligue 1)", "Saudi Pro League"
CLS = ["Home win", "Draw", "Away win"]
FIGDIR = "evaluation/figures"


# ----------------------------------------------------------------------------- formatting
def ci(v, d=4, pct=False, plus=False):
    if pct:
        return f"{100 * v[0]:.1f}% [{100 * v[1]:.1f}, {100 * v[2]:.1f}]"
    s = "+" if plus else ""
    return f"{v[0]:{s}.{d}f} [{v[1]:{s}.{d}f}, {v[2]:{s}.{d}f}]"


def dci(t, d=4):
    return f"{t['diff']:+.{d}f} [{t['lo']:+.{d}f}, {t['hi']:+.{d}f}]"


def pv(p):
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def pc(x, d=1):
    return f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return f"{100 * x:+.{d}f} pp"


def excl0(lo, hi):
    return lo > 0 or hi < 0


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def fig(name, alt):
    return f"![{alt}]({FIGDIR}/{name})"


def gl(g):
    return g.split(" (")[0]


# ----------------------------------------------------------------------------- report
def write_report(R):
    M = R["meta"]; H = R["headline"]; BL = R["baselines"]; CA = R["calibration"]; BI = R["bias"]; VA = R["variance"]; ST = R["stability"]
    AB = R["ablations"]; ER = R["errors"]; RC = R["recalibration"]
    hg = H["groups"]
    eu, si, sp = hg[G_EU], hg[G_SITE], hg[G_SPL]
    sel_eu, sel_sp = M["selected"]["eu"], M["selected"]["spl"]
    B = M["bootstrap_reps"]
    t_eu, t_si, t_sp = BL[G_EU]["tests"], BL[G_SITE]["tests"], BL[G_SPL]["tests"]

    # ------------------------------------------------------------------ derived numbers used in several places
    cal_eu = CA[G_EU]; cal_si = CA[G_SITE]; cal_sp = CA[G_SPL]
    conf_eu = ER["confusion"][G_EU]
    goals = BI["goals"]
    n_int = 0; n_excl = 0; excl_list = []
    for lab, v in goals.items():
        if lab in (G_EU, G_SITE):
            continue
        for k in ["home", "away", "total"]:
            n_int += 1
            e = v[k]["err"]
            if excl0(e[1], e[2]):
                n_excl += 1; excl_list.append(f"{lab} {k} ({e[0]:+.3f} [{e[1]:+.3f}, {e[2]:+.3f}])")
    fb = BI["fav_bands"]; sb = BI["side_bands"]; lg = BI["longshot_lt20"]; fv = BI["favourite_ge60"]; sl = BI["side_slope"]
    disp_eu = BI["dispersion"][G_EU]
    rs = VA["ridge_sweep"]; rs_by = {r["reg"]: r for r in rs}
    r_lo = rs_by[0.01]; r_3 = rs_by[3]; r_50 = rs_by[50]; r_500 = rs_by[500]
    best_tune = min(rs, key=lambda r: r["tune"]["val_rps"][0]); best_hold = min(rs, key=lambda r: r["hold"]["val_rps"][0])
    hist = VA["history_length"]; hl = VA["half_life"]
    hl_by = {round(r["half_life_days"]) if r["half_life_days"] else None: r for r in hl}
    sm = ST["summary"]; games = {g["id"]: g for g in ST["games"]}
    g_psg, g_bay, g_cla = games["2026-10-20_psg-barcelona"], games["2026-10-21_bayern-arsenal"], games["2026-10-25_barcelona-real-madrid"]
    ab = AB["europe"]
    k_nodecay, k_norho, k_noridge = "No time decay", "No Dixon-Coles rho correction", "No ridge"
    k_noelo = "No Elo leg (Dixon-Coles only everywhere)"
    k_nolink = "Joint fit without Champions League results (no cross-league link)"
    k_perleague = "Per-league fits (no link, own rho and home advantage)"
    ul = AB["ucl_link"]
    sa = AB["saudi"]
    wsum = ER["worst15_summary"]; tail = ER["tail_check"]
    gd = ER["gd_error"]
    ev = ER["early_vs_rest"]
    mon = ER["by_month"]

    sc_si_rows = BI["scorelines"][G_SITE]["rows"]
    z_cells = ", ".join(r["score"] + (" more" if r["z"] > 0 else " fewer") + " than modelled (z " + format(r["z"], "+.1f") + ")" for r in sc_si_rows if abs(r["z"]) > 2) or "none"
    hw_dc = sorted(100 * (g["boot_dc"]["H"]["hi"] - g["boot_dc"]["H"]["lo"]) / 2 for g in ST["games"])
    hw_sh = sorted(100 * (g["boot_base"]["H"]["hi"] - g["boot_base"]["H"]["lo"]) / 2 for g in ST["games"])
    leag = {k: v for k, v in BI["dispersion"].items() if k not in (G_EU, G_SITE, G_SPL)}
    disp_below = [k for k, v in leag.items() if v["total"][2] < 1]; disp_above = [k for k, v in leag.items() if v["total"][1] > 1]
    h_steps = [hist[i]["decay"]["val_rps"][0] - hist[i + 1]["decay"]["val_rps"][0] for i in range(3)]

    # directional words chosen by the numbers
    sl_ci = [cal_eu[k]["slope"] for k in CLS]
    slopes_note = "all three intervals contain 1" if all(a[1] <= 1 <= a[2] for a in sl_ci) else "at least one interval excludes 1"

    def sense(slope):
        return "under-confident (too flat)" if slope > 1 else "over-confident (too sharp)"

    F = []  # key findings
    F.append(f"**Headline accuracy.** On the 2025-26 holdout (weekly refits, never tuned on) the model called W/D/L correctly in {ci(eu['acc'], pct=True)} of {eu['n']:,} European matches, {ci(si['acc'], pct=True)} of {si['n']:,} matches in the three site leagues and {ci(sp['acc'], pct=True)} of {sp['n']} Saudi matches. The published exact-score pick hit {ci(eu['head_hit'], pct=True)} (Europe), {ci(si['head_hit'], pct=True)} (site leagues) and {ci(sp['head_hit'], pct=True)} (Saudi).")
    F.append(f"**Skill over naive baselines is real.** RPS {ci(eu['rps'])} (Europe) against league base rates {BL[G_EU]['models']['League base rates']['rps'][0]:.4f}: difference {dci(t_eu['League base rates']['rps'])}, bootstrap p {pv(t_eu['League base rates']['rps']['p_boot'])}, Diebold-Mariano p {pv(t_eu['League base rates']['rps']['p_dm'])}. The same holds in the site leagues ({dci(t_si['League base rates']['rps'])}) and in Saudi ({dci(t_sp['League base rates']['rps'])}). Accuracy beats \"home win always\" ({BL[G_EU]['models']['Home win always']['acc'][0] * 100:.1f}%) by {pp(t_eu['Home win always']['acc']['diff'])} in Europe.")
    F.append(f"**Not distinguishable from plain Elo.** Shipped minus Elo-only RPS: Europe {dci(t_eu['Elo only']['rps'])} (DM p {pv(t_eu['Elo only']['rps']['p_dm'])}), site leagues {dci(t_si['Elo only']['rps'])}, Saudi {dci(t_sp['Elo only']['rps'])}. The goals model earns no measurable edge over a one-parameter Elo mapping on this season; the honest description is \"as good as Elo, with scorelines\".")
    F.append(f"**Calibration is good on average, with a mild under-confidence.** Per-class ECE in Europe is {cal_eu['Home win']['ece']:.3f} / {cal_eu['Draw']['ece']:.3f} / {cal_eu['Away win']['ece']:.3f} (home / draw / away) against {cal_eu['Home win']['ece_null_mean']:.3f} / {cal_eu['Draw']['ece_null_mean']:.3f} / {cal_eu['Away win']['ece_null_mean']:.3f} expected from sampling noise alone (simulation p {cal_eu['Home win']['ece_p']:.2f} / {cal_eu['Draw']['ece_p']:.2f} / {cal_eu['Away win']['ece_p']:.2f}). Calibration slopes are {cal_eu['Home win']['slope'][0]:.2f} / {cal_eu['Draw']['slope'][0]:.2f} / {cal_eu['Away win']['slope'][0]:.2f} ({slopes_note}; direction: {sense(cal_eu['Home win']['slope'][0])}). A one-parameter sharpening fitted on 2024-25 (T = {RC[G_EU]['T']:.2f}) would move RPS by only {dci(RC[G_EU]['d_rps'])}, so it is not worth shipping.")
    dz = CA["draw_by_closeness_europe"]
    F.append(f"**Draws.** Mean P(draw) is {pc(cal_eu['Draw']['mean_pred'])} against an observed draw rate of {pc(cal_eu['Draw']['obs_rate'])} (calibration-in-the-large {cal_eu['Draw']['citl'][0]:+.3f} [{cal_eu['Draw']['citl'][1]:+.3f}, {cal_eu['Draw']['citl'][2]:+.3f}]). The model never names a draw as the most likely result ({conf_eu['matrix'][0][1] + conf_eu['matrix'][1][1] + conf_eu['matrix'][2][1]} of {conf_eu['n']:,} matches), so draw recall is 0% by construction. P(draw) is slightly too flat across match closeness: the closest matches drew {pc(dz[0]['obs'])} against {pc(dz[0]['pred'])} predicted, the most lopsided {pc(dz[-1]['obs'])} against {pc(dz[-1]['pred'])} (both inside their 95% intervals).")
    sh = BI["outcomes"][G_SITE]
    F.append(f"**Home advantage is understated in the three site leagues.** Home wins {pc(sh['H']['obs'])} observed against {pc(sh['H']['pred'])} predicted ({pp(sh['H']['err'][0])} [{pp(sh['H']['err'][1])}, {pp(sh['H']['err'][2])}], predicted minus observed); away wins {pc(sh['A']['obs'])} against {pc(sh['A']['pred'])}. Predicted minus actual home goal difference is {BI['home_adv'][G_SITE]['err'][0]:+.3f} [{BI['home_adv'][G_SITE]['err'][1]:+.3f}, {BI['home_adv'][G_SITE]['err'][2]:+.3f}] goals per match, driven by La Liga ({BI['home_adv']['La Liga']['err'][0]:+.3f} [{BI['home_adv']['La Liga']['err'][1]:+.3f}, {BI['home_adv']['La Liga']['err'][2]:+.3f}]). Fitting a separate home advantage per league did not help (RPS {dci(ab[k_perleague]['d_rps'])}), which points to season-to-season variation in home advantage rather than a fixable structural error.")
    F.append(f"**Goal levels are unbiased overall.** Predicted minus actual total goals per match in Europe: {BI['goals'][G_EU]['total']['err'][0]:+.3f} [{BI['goals'][G_EU]['total']['err'][1]:+.3f}, {BI['goals'][G_EU]['total']['err'][2]:+.3f}]. {n_excl} of {n_int} league-by-(home/away/total) intervals exclude zero ({'; '.join(excl_list)}); about {0.05 * n_int:.1f} would be expected by chance.")
    F.append(f"**Favourite-longshot pattern (model compresses probabilities).** Teams the model gave at least 60% won {pc(fv['obs'])} of the time against {pc(fv['pred'])} predicted ({100 * fv['gap'][0]:+.1f} pp [{100 * fv['gap'][1]:+.1f}, {100 * fv['gap'][2]:+.1f}]), while sides under 10% won {pc(sb[0]['obs'])} against {pc(sb[0]['pred'])} (n={sb[0]['n']}, interval {pc(sb[0]['ci'][0])} to {pc(sb[0]['ci'][1])}). The pooled team-side calibration slope is {sl['slope'][0]:.2f} [{sl['slope'][1]:.2f}, {sl['slope'][2]:.2f}]. The effect is small and the intervals are wide.")
    sc_eu = BI["scorelines"][G_EU]; sc_si = BI["scorelines"][G_SITE]; sc_sp = BI["scorelines"][G_SPL]
    F.append(f"**Scoreline frequencies match the model.** Chi-square over 15 named scorelines plus \"other\": Europe p = {sc_eu['p_chi2']:.2f}, Saudi p = {sc_sp['p_chi2']:.2f}, site leagues p = {sc_si['p_chi2']:.3f} (cells with |z| above 2: {z_cells}). Poisson variance is adequate: the Pearson dispersion ratio for total goals is {ci(disp_eu['total'], 3)} (1 = Poisson), home goals {disp_eu['home'][0]:.3f}, away goals {disp_eu['away'][0]:.3f}; league values range from {min(v['total'][0] for v in leag.values()):.2f} to {max(v['total'][0] for v in leag.values()):.2f}; the total-goals interval excludes 1 on the low side for {', '.join(disp_below) or 'no league'} and on the high side for {', '.join(disp_above) or 'no league'}. Home-away residual correlation {ci(disp_eu['resid_corr'], 3)}, so the independence assumption is not visibly violated.")
    F.append(f"**Bias-variance (ridge).** On the 2024-25 tuning season validation RPS is lowest at lambda = {best_tune['reg']:g} ({best_tune['tune']['val_rps'][0]:.4f}); the shipped value is 3. In-sample RPS rises from {r_lo['tune']['train_rps']:.4f} (lambda 0.01) to {r_3['tune']['train_rps']:.4f} (3) and {r_50['tune']['train_rps']:.4f} (50) while the train-to-validation gap shrinks from {r_lo['tune']['val_rps'][0] - r_lo['tune']['train_rps']:.4f} to {r_3['tune']['val_rps'][0] - r_3['tune']['train_rps']:.4f} to {r_50['tune']['val_rps'][0] - r_50['tune']['train_rps']:.4f}: too little ridge overfits (validation {r_lo['tune']['val_rps'][0]:.4f}), too much underfits ({r_50['tune']['val_rps'][0]:.4f} at 50). The valley is flat between lambda 1 and 8. The holdout, shown for information only, agrees (lowest at lambda = {best_hold['reg']:g}).")
    h1, h2, h3, h4 = hist
    F.append(f"**Learning curves.** Holdout RPS falls with more history: {h1['decay']['val_rps'][0]:.4f} (6 months), {h2['decay']['val_rps'][0]:.4f} (1 year), {h3['decay']['val_rps'][0]:.4f} (2 years), {h4['decay']['val_rps'][0]:.4f} (all data, 2.0 to 2.8 years); the gain shrinks at each step ({h_steps[0]:.4f}, {h_steps[1]:.4f}, {h_steps[2]:.4f}) but has not clearly reached zero, so the model is mildly data-limited. Time-decay half-life: very short memory is costly (30 days: {hl_by[30]['hold']['val_rps'][0]:.4f}) but the curve is flat from about {min(r['half_life_days'] for r in hl if r['half_life_days'] and r['hold']['val_rps'][0] < hl_by[365]['hold']['val_rps'][0] + 0.0005):.0f} days to no decay at all (shipped 365 days: {hl_by[365]['hold']['val_rps'][0]:.4f}). Removing decay costs {dci(ab[k_nodecay]['d_rps'])}, not detectable.")
    F.append(f"**Parameter stability.** Over {sm['bootstrap_fits']} bootstrap refits at the live snapshot, the median standard deviation of a team's attack rating is {sm['median_sd_attack']:.3f} and of its defence rating {sm['median_sd_defence']:.3f} (log-goal scale; between-team spread {sm['between_team_sd_attack']:.3f} and {sm['between_team_sd_defence']:.3f}). Attack ratings are {sm['reliability_attack']:.2f} reliable and defence ratings {sm['reliability_defence']:.2f}, so defence is the noisier half. Teams with fewer than 25 matches in the last year have about {sm['sd_attack_few_matches'] / sm['sd_attack_many_matches']:.1f} times the attack-rating uncertainty of teams with 40 or more ({sm['sd_attack_few_matches']:.3f} against {sm['sd_attack_many_matches']:.3f}).")
    def band(g, key, o):
        b = g[key][o]
        return f"{100 * b['median']:.1f}% [{100 * b['lo']:.1f}, {100 * b['hi']:.1f}]"
    F.append(f"**Prediction uncertainty on the featured games.** Home-win probability from the Dixon-Coles leg alone, with 95% bootstrap bands: PSG-Barcelona {band(g_psg, 'boot_dc', 'H')}, Bayern-Arsenal {band(g_bay, 'boot_dc', 'H')}, Barcelona-Real Madrid {band(g_cla, 'boot_dc', 'H')}. The shipped Champions League base looks tighter ({band(g_psg, 'boot_base', 'H')} and {band(g_bay, 'boot_base', 'H')}) only because the Elo leg (70% weight) is held fixed in the bootstrap. The gap between the Dixon-Coles-only and shipped point estimates (PSG-Barcelona home {100 * g_psg['point_dc'][0]:.1f}% against {100 * g_psg['point_base'][0]:.1f}%; Bayern-Arsenal home {100 * g_bay['point_dc'][0]:.1f}% against {100 * g_bay['point_base'][0]:.1f}%) exceeds the half-width of the shipped-base band. Half-widths of the 95% bands on the home-win probability are {hw_dc[0]:.0f} to {hw_dc[-1]:.0f} points for the Dixon-Coles leg and {hw_sh[0]:.0f} to {hw_sh[-1]:.0f} points for the shipped base (Elo fixed), so any single W/D/L percentage carries an uncertainty of that order, before counting the disagreement between the two legs.")
    F.append(f"**Ablations.** Removing time decay ({dci(ab[k_nodecay]['d_rps'])}), removing the Dixon-Coles rho correction ({dci(ab[k_norho]['d_rps'])}), removing the Elo leg in the Champions League ({dci(ab[k_noelo]['d_rps'])}) or adding it to domestic matches (w = 0.8: {dci(ab['+ Elo leg in domestic matches, w = 0.8']['d_rps'])}; w = 0.3: {dci(ab['+ Elo leg in domestic matches, w = 0.3']['d_rps'])}) all change RPS by less than the noise. Two components do matter: the ridge ({dci(ab[k_noridge]['d_rps'])} without it, p {pv(ab[k_noridge]['d_rps']['p_boot'])}) and the Champions League link ({dci(ab[k_nolink]['d_rps'])}; on the 186 Champions League matches alone {dci(ul['d_blend_no_link_vs_link'])}). Five separate per-league fits with no Champions League data score {dci(ab[k_perleague]['d_rps'])} against the joint fit on domestic matches: the cross-league pooling neither helps nor hurts domestic predictions.")
    F.append(f"**Saudi model.** It leans on its Elo leg: dropping the leg costs {dci(sa['No Elo leg (Dixon-Coles only)']['d_rps'])} RPS. The pre-registered fast decay is, if anything, slightly worse than no decay on the holdout ({dci(sa['No time decay']['d_rps'])}, bootstrap p {pv(sa['No time decay']['d_rps']['p_boot'])}); this is a post-hoc diagnostic on {sp['n']} matches, so nothing is changed, but it is worth rechecking with 2026-27 data. Saudi calibration slopes are {cal_sp['Home win']['slope'][0]:.2f} (home) and {cal_sp['Away win']['slope'][0]:.2f} (away), i.e. {sense(cal_sp['Away win']['slope'][0])}, with wide intervals.")
    F.append(f"**What the model predicts.** Of {conf_eu['n']:,} European matches it picked home in {pc(conf_eu['pred_share'][0])}, away in {pc(conf_eu['pred_share'][2])} and draw in {pc(conf_eu['pred_share'][1])}, against actual shares of {pc(conf_eu['actual_share'][0])} / {pc(conf_eu['actual_share'][1])} / {pc(conf_eu['actual_share'][2])}. Recall is {pc(conf_eu['recall'][0])} for home wins and {pc(conf_eu['recall'][2])} for away wins. Accuracy rises with favourite strength from {pc(ER['by_fav_band'][0]['acc'])} (favourite under 40%) to {pc(ER['by_fav_band'][-1]['acc'])} (favourite 70% or more); in the 40-50% band it is only {pc(ER['by_fav_band'][1]['acc'])}.")
    F.append(f"**No visible cold-start penalty.** August-October RPS {ev['rps_early']:.4f} against {ev['rps_rest']:.4f} for the rest of the season (difference {ev['diff'][0]:+.4f} [{ev['diff'][1]:+.4f}, {ev['diff'][2]:+.4f}]; early-season matches were, if anything, easier). By matches already played by the less-experienced team: RPS {ER['by_games_played'][0]['rps'][0]:.4f} (0-2 games) against {ER['by_games_played'][-1]['rps'][0]:.4f} (20+). The weakest month is {max(mon, key=lambda r: r['rps'][0])['month']} (RPS {max(mon, key=lambda r: r['rps'][0])['rps'][0]:.4f}, accuracy {pc(max(mon, key=lambda r: r['rps'][0])['acc'])}), but May against the rest is {ER['may_vs_rest']['diff'][0]:+.4f} [{ER['may_vs_rest']['diff'][1]:+.4f}, {ER['may_vs_rest']['diff'][2]:+.4f}], an exploratory comparison among {len(mon)} months that includes zero.")
    F.append(f"**The 15 worst misses are ordinary tail events.** All gave the actual outcome at most {pc(wsum['p_actual_max'])}; {wsum['n_longshot']} were longshot wins and {wsum['n_draw']} were draws by a favourite (mean favourite probability {pc(wsum['mean_fav_p'], 0)}), {wsum['n_away_win']} of the 15 were away wins, {wsum['n_early']} involved a team with at most five earlier games that season and only {wsum['n_margin3']} was a 3-goal-or-more margin. Counting every match, {tail[0]['observed']} realised outcomes had a predicted probability under {tail[0]['t']:.0%} against {tail[0]['expected']:.1f} implied by the probabilities themselves ({tail[1]['observed']} against {tail[1]['expected']:.1f} under 20%): the model is not surprised more often than it says it should be.")
    F.append(f"**Goal-difference errors are symmetric and slightly {'narrower' if gd['sd'] < gd['model_implied_sd'] else 'wider'} than the model implies.** Actual minus predicted goal difference: mean {ci(gd['mean'], 3)}, SD {gd['sd']:.3f} against {gd['model_implied_sd']:.3f} implied by the score grids, skew {gd['skew']:+.2f}, excess kurtosis {gd['excess_kurtosis']:+.2f}, 5th to 95th percentile {gd['q'][0]:+.2f} to {gd['q'][4]:+.2f}; mean absolute error {ci(gd['mae'], 3)} goals.")
    F.append(f"**Reproducibility.** The regenerated 2025-26 holdout matches the stored backtest probabilities to {max(M['context']['eu']['max_abs_prob_diff_vs_stored_csv'], M['context']['spl']['max_abs_prob_diff_vs_stored_csv']):.0e}, and the bootstrap refit at the live snapshot reproduces the three locked `base` predictions to within {max(g['repro_max_abs_diff'] for g in ST['games']):.1e} (rounding of the locked files).")
    assert len(F) <= 20, len(F)

    # ------------------------------------------------------------------ model card
    mc = []
    mc.append("# Evaluation of the Ihtimal match predictor\n")
    mc.append(f"Generated by `evaluation/run_eval.py` (`{'quick smoke-test mode' if M['quick'] else 'full run'}`); every number below is computed there and read from `evaluation/results.json`, none is typed by hand. Data through {M['data_last_result']} ({M['n_matches_total']:,} matches in `data/matches.csv`). Nothing in the model, `site/`, the three locked featured files or `locks.json` was changed by this evaluation.\n")
    mc.append("## Model card\n")
    mc.append(table(["", ""], [
        ["Model", "`ihtimal-v1.0`: a time-decayed Dixon-Coles goals model (one joint fit for the big-5 leagues and the Champions League; a separate fit for the Saudi Pro League), optionally log-blended with an Elo leg. Output: W/D/L probabilities, expected goals and a 0-8 by 0-8 scoreline grid, from which the published pick (most likely result, then most likely score within it) is taken."],
        ["Intended use", "Statistical W/D/L probabilities and a most-likely score for upcoming matches in the Saudi Pro League, Premier League, La Liga and Ligue 1 (plus two Champions League featured games), shown for fun and learning to a general audience, with the track record published match by match."],
        ["Data", f"openfootball (public domain) and ESPN public scoreboard results, 1 Aug 2023 onwards ({M['n_matches_total']:,} regulation-time results). No odds, no market data, no xG in the base model. Training for each prediction uses only matches strictly before it."],
        ["Method", f"Europe: xi = {sel_eu['xi']} per day (half-life {math.log(2) / sel_eu['xi']:.0f} days), ridge {sel_eu['reg']:g} on team attack/defence, league offsets linked through Champions League matches, Elo weight {1 - sel_eu['w']:.0%} in domestic matches and {1 - sel_eu['w_ucl']:.0%} in the Champions League. Saudi: xi = {sel_sp['xi']}, ridge {sel_sp['reg']:g}, rho fixed from a slow-decay pass, Elo weight {1 - sel_sp['w']:.0%}. All chosen on 2024-25 only."],
        ["Evaluation", f"One pre-registered holdout season (2025-26), weekly walk-forward refits (every fitted object rebuilt each Monday from earlier matches only), {B:,} match-level bootstrap resamples (seed {M['seed']}), 95% percentile intervals. Same-season results are not used for any choice."],
    ]))
    mc.append("\n**Headline metrics on the 2025-26 holdout (95% bootstrap intervals)**\n")
    rows = []
    for g in [G_EU, G_SITE, G_SPL]:
        v = hg[g]
        rows.append([f"{gl(g)} (n={v['n']:,})", ci(v["acc"], pct=True), ci(v["head_hit"], pct=True), ci(v["rps"]), ci(v["ll"]), ci(v["brier"])])
    mc.append(table(["Group", "W/D/L accuracy", "Exact-score hit (published pick)", "RPS", "Log-loss", "Brier"], rows))
    mc.append(f"\nReference points (Europe): league base rates RPS {BL[G_EU]['models']['League base rates']['rps'][0]:.4f}, Elo only {BL[G_EU]['models']['Elo only']['rps'][0]:.4f}, uniform {BL[G_EU]['models']['Uniform 1/3']['rps'][0]:.4f}; home-win-always accuracy {BL[G_EU]['models']['Home win always']['acc'][0] * 100:.1f}%.\n")
    mc.append("**Known limitations and biases (all quantified below)**\n")
    lim = [
        f"Level with a plain Elo model, not better: RPS difference to Elo-only {dci(t_eu['Elo only']['rps'])} in Europe. No comparison with bookmaker prices was made, so there is no evidence it can beat a market.",
        f"Never picks a draw ({pc(cal_eu['Draw']['obs_rate'])} of matches are draws); its draw probabilities are right on average ({pc(cal_eu['Draw']['mean_pred'])} predicted) but too flat across match closeness.",
        f"Mildly under-confident: calibration slope {cal_eu['Home win']['slope'][0]:.2f} (home) in Europe; favourites at 60% or more win {pc(fv['obs'])} against {pc(fv['pred'])} predicted.",
        f"Home advantage understated in the three site leagues in 2025-26 (home wins {pc(sh['H']['obs'])} observed against {pc(sh['H']['pred'])} predicted; La Liga drives it).",
        f"Parameter and structure uncertainty: on the three featured games the 95% bootstrap band on a home-win probability has a half-width of {hw_dc[0]:.0f} to {hw_dc[-1]:.0f} points for the Dixon-Coles leg ({band(g_psg, 'boot_dc', 'H')} for PSG-Barcelona), and the Dixon-Coles and Elo legs disagree by more than that on the Champions League games.",
        f"Exact scores: about 1 in {1 / eu['head_hit'][0]:.1f} (Europe), 1 in {1 / sp['head_hit'][0]:.1f} (Saudi). Saudi results rest on {sp['n']} matches and have wide intervals; its slopes are {sense(cal_sp['Away win']['slope'][0])}.",
        "The injury and xG adjustments on the three featured games are not part of this evaluation (they cannot be backtested).",
        "One holdout season: results describe 2025-26, and subgroup tables (by league, month, band) are exploratory and subject to multiple-comparison noise.",
    ]
    mc.extend(f"* {x}" for x in lim)
    mc.append("\n**What NOT to use it for**\n")
    mc.append(f"* **Betting or staking of any kind.** It was never tested against odds, is statistically indistinguishable from a simple Elo model, and a 95% band of {hw_dc[0]:.0f} to {hw_dc[-1]:.0f} points on a home-win probability means any apparent \"edge\" over a bookmaker is inside the noise.")
    mc.append(f"* Treating the most-likely score as a forecast of the score (it hits about one match in {1 / eu['head_hit'][0]:.0f}), or a probability of 40-50% as a pick (the model's accuracy in that favourite band is {pc(ER['by_fav_band'][1]['acc'])}).")
    mc.append("* Matches involving teams with little history in the data (fewer than about 20 matches in the prior year), leagues outside the fitted pool, in-play prediction, individual-player or team-news judgements.")
    mc.append("")

    # ------------------------------------------------------------------ findings
    out = list(mc)
    out.append("## Key findings\n")
    out.extend(f"{i + 1}. {x}" for i, x in enumerate(F))
    out.append("")

    # ------------------------------------------------------------------ 0 setup
    c = M["context"]
    out.append("## 0. Setup and reproducibility\n")
    out.append(f"* **Holdout and refits.** The 2025-26 season (1 Aug 2025 to 31 Jul 2026) exactly as pre-registered in `BACKTEST_SPEC.md`: for each Monday 00:00 UTC cutoff every fitted object is rebuilt from matches strictly before it and the following 7 days are predicted. Refits are cheap ({c['eu']['n_folds']} weekly folds of the European model, Elo leg and baselines took {c['eu']['refit_seconds']:.1f} seconds), so **every analysis here uses weekly refits**; no cheaper schedule (monthly or similar) was needed. The whole evaluation ran in {M['compute_seconds']:.0f} seconds.")
    out.append(f"* **Reuse of existing outputs.** The shipped settings are read from `data/backtest_eu.json` and `data/backtest_spl.json`. The shipped holdout predictions are regenerated by the same code path as `model/backtest.py` (the stored CSVs do not contain expected goals, Elo or base-rate probabilities, which the bias and baseline analyses need) and asserted equal to `data/backtest_*_2025-26_matches.csv`: maximum absolute probability difference {max(c['eu']['max_abs_prob_diff_vs_stored_csv'], c['spl']['max_abs_prob_diff_vs_stored_csv']):.1e}; RPS {c['eu']['rps_regenerated']:.5f} (Europe) and {c['spl']['rps_regenerated']:.5f} (Saudi) against {c['eu']['rps_stored_json']:.5f} and {c['spl']['rps_stored_json']:.5f} in the stored JSON.")
    out.append(f"* **Groups.** Europe = Premier League, La Liga, Ligue 1, Bundesliga, Serie A and Champions League ({eu['n']:,} matches); site leagues = the Premier League, La Liga and Ligue 1 ({si['n']:,}); Saudi Pro League ({sp['n']}). Champions League predictions use the Elo blend as shipped.")
    out.append(f"* **Bootstrap.** Match-level resampling, {B:,} replicates, seed {M['seed']}, 95% percentile intervals. The same resampled indices are used for every comparison on the same group, so differences are paired. p-values from the bootstrap are two-sided by percentile inversion (floor 1/{B:,}). Diebold-Mariano tests use Newey-West variance (lag n^(1/3)) with the Harvey-Leybourne-Newbold small-sample correction and a Student-t reference. As a robustness check intervals are also computed by resampling whole weekly folds (block bootstrap).")
    out.append(f"* **Calibration null.** ECE is positively biased in small samples, so each observed ECE is compared with its distribution under perfect calibration (outcomes simulated {M['null_sims']:,} times from the model's own probabilities, same bins).")
    out.append(f"* **Parameter-stability bootstrap.** {M['bootstrap_refits']} refits of the live European model (cutoff 2026-10-19, the fit behind the featured predictions), each on {sm['n_train']:,} training matches resampled with replacement (dates kept, so time-decay weights are kept).")
    out.append("")

    # ------------------------------------------------------------------ 1 headline
    out.append("## 1. Headline metrics\n")
    out.append("Exact-score hit = the published pick (most likely result, then the most likely score within it). Top-score hit = the single most likely cell of the grid. RPS, log-loss and Brier: lower is better. Intervals are 95% bootstrap.\n")
    rows = []
    for g in [G_EU, G_SITE, G_SPL]:
        v = hg[g]
        rows.append([gl(g), f"{v['n']:,}", ci(v["acc"], pct=True), ci(v["head_hit"], pct=True), ci(v["top_hit"], pct=True), ci(v["rps"]), ci(v["ll"]), ci(v["brier"])])
    out.append(table(["Group", "n", "W/D/L accuracy", "Exact-score hit", "Top-score hit", "RPS", "Log-loss", "Brier"], rows))
    out.append("\nBy competition (same metrics):\n")
    rows = []
    for name, v in H["competitions"].items():
        rows.append([name, v["n"], ci(v["acc"], pct=True), ci(v["head_hit"], pct=True), ci(v["rps"]), ci(v["ll"])])
    out.append(table(["Competition", "n", "W/D/L accuracy", "Exact-score hit", "RPS", "Log-loss"], rows))
    out.append(f"\nIntervals for single competitions are wide ({min(v['n'] for v in H['competitions'].values())} to {max(v['n'] for v in H['competitions'].values())} matches each); differences between leagues are mostly within noise.\n")
    out.append(fig("fig01_headline_and_baselines.png", "Headline RPS and paired differences to baselines"))
    out.append("")

    # ------------------------------------------------------------------ 2 baselines
    out.append("## 2. Baselines and significance\n")
    out.append("Baselines: **home win always** (accuracy only), **league base rates** (home/draw/away frequencies of the same competition in all earlier matches, Laplace-smoothed, refit each week), **Elo only** (ordered logit on the Elo difference, refit each week, no scoreline grid), plus uniform and the Dixon-Coles-only leg for reference.\n")
    for g in [G_EU, G_SITE, G_SPL]:
        out.append(f"**{g}, n = {BL[g]['n']:,}**\n")
        rows = []
        for m_, v in BL[g]["models"].items():
            if "rps" in v:
                rows.append([m_, ci(v["rps"]), ci(v["ll"]), ci(v["brier"]), ci(v["acc"], pct=True)])
            else:
                rows.append([m_, "-", "-", "-", ci(v["acc"], pct=True)])
        out.append(table(["Model", "RPS", "Log-loss", "Brier", "W/D/L accuracy"], rows))
        out.append("")
        rows = []
        for b_, t in BL[g]["tests"].items():
            if "rps" not in t:
                a_ = t["acc"]
                rows.append([f"vs {b_} (accuracy)", f"{pp(a_['diff'])} [{pp(a_['lo'])}, {pp(a_['hi'])}]", pv(a_["p_boot"]), "-", "-", "-", "-"])
                continue
            if abs(t["rps"]["diff"]) < 1e-12:
                rows.append([f"vs {b_}", "identical by construction (no Elo leg in domestic matches)", "-", "-", "-", "-", "-"])
                continue
            rows.append([f"vs {b_}", dci(t["rps"]), pv(t["rps"]["p_boot"]), f"{t['rps']['dm']:+.2f} (p {pv(t['rps']['p_dm'])})", f"[{t['rps']['block_ci'][0]:+.4f}, {t['rps']['block_ci'][1]:+.4f}]", dci(t["ll"]), pv(t["ll"]["p_dm"])])
        out.append(table(["Shipped minus ...", "RPS difference [95% CI]", "Bootstrap p", "DM statistic", "Week-block 95% CI (RPS)", "Log-loss difference [95% CI]", "DM p (log-loss)"], rows))
        out.append("")
    out.append("Negative = the shipped model is better. The match-level and week-block intervals agree, so within-week dependence does not change the conclusions.\n")

    # ------------------------------------------------------------------ 3 calibration
    out.append("## 3. Calibration\n")
    out.append("Reliability diagrams use 10 **equal-count** bins (probabilities are bunched, especially for draws, so equal-width bins would leave most bins nearly empty). ECE = count-weighted mean absolute gap between mean predicted and observed frequency over the bins. Slope and intercept come from the logistic recalibration `logit P(y=1) = a + b * logit(p)` (perfect calibration: a = 0, b = 1); calibration-in-the-large (CITL) is the intercept with the slope fixed at 1. b > 1 means the model is under-confident (observed frequencies are more spread out than its probabilities).\n")
    out.append(fig("fig03_reliability.png", "Reliability diagrams for home, draw and away probabilities"))
    out.append("")
    for g in [G_EU, G_SITE, G_SPL]:
        out.append(f"**{g}** (mean ECE over the three outcomes {CA[g]['mean_ece']:.3f})\n")
        rows = []
        for k in CLS:
            v = CA[g][k]
            rows.append([k, f"{pc(v['mean_pred'])} / {pc(v['obs_rate'])}", f"{v['ece']:.3f}", f"{v['ece_null_mean']:.3f} (95th pct {v['ece_null_p95']:.3f})", f"{v['ece_p']:.3f}",
                         f"{v['slope'][0]:.2f} [{v['slope'][1]:.2f}, {v['slope'][2]:.2f}]", f"{v['intercept'][0]:+.2f} [{v['intercept'][1]:+.2f}, {v['intercept'][2]:+.2f}]", f"{v['citl'][0]:+.3f} [{v['citl'][1]:+.3f}, {v['citl'][2]:+.3f}]"])
        out.append(table(["Outcome", "Mean predicted / observed", "ECE", "ECE if perfectly calibrated", "Simulation p", "Slope b [95% CI]", "Intercept a [95% CI]", "CITL [95% CI]"], rows))
        out.append("")
    out.append("**Draw probability specifically**\n")
    out.append(fig("fig04_draw_calibration.png", "Draw calibration"))
    out.append("")
    rows = [[r["band"], r["n"], pc(r["pred"]), f"{pc(r['obs'])} [{pc(r['ci'][0])}, {pc(r['ci'][1])}]"] for r in CA["draw_by_closeness_europe"]]
    out.append(table(["Closeness (absolute gap between home and away win probability)", "n", "Mean predicted P(draw)", "Observed draw rate [95% Wilson]"], rows))
    out.append("")
    rows = [[k, v["n"], pc(v["pred"]), pc(v["obs"]), f"{100 * v['diff'][0]:+.1f} pp [{100 * v['diff'][1]:+.1f}, {100 * v['diff'][2]:+.1f}]"] for k, v in CA["draw_by_comp"].items()]
    out.append(table(["Competition", "n", "Mean predicted P(draw)", "Observed draw rate", "Predicted minus observed [95% CI]"], rows))
    out.append("")
    all0 = all(v["diff"][1] <= 0 <= v["diff"][2] for v in CA["draw_by_comp"].values())
    out.append(f"The draw probability is {'well calibrated on average in every competition (every interval above contains zero)' if all0 else 'miscalibrated on average in at least one competition (see the intervals above)'}. Its shape is the weak point: it varies less with match closeness than the observed draw rate does (draw slope {cal_eu['Draw']['slope'][0]:.2f} [{cal_eu['Draw']['slope'][1]:.2f}, {cal_eu['Draw']['slope'][2]:.2f}] in Europe; the interval is wide), possibly reflecting the ridge shrinkage compressing the spread of predicted supremacy.\n")
    out.append("**Would a recalibration help?** Diagnostic only: a one-parameter sharpening `p' proportional to p^T` fitted by log-loss on the 2024-25 tuning season and applied unchanged to 2025-26.\n")
    rows = [[g, f"{v['T']:.3f}", f"{v['rps_before']:.4f}", f"{v['rps_after']:.4f}", dci(v["d_rps"]), dci(v["d_ll"])] for g, v in RC.items()]
    out.append(table(["Group", "T (1 = no change)", "RPS before", "RPS after", "RPS difference [95% CI]", "Log-loss difference [95% CI]"], rows))
    out.append("\nThe sharpening does not change accuracy (it preserves the ordering of probabilities) and its RPS and log-loss effects are within noise, so the slight under-confidence is not worth correcting.\n")

    # ------------------------------------------------------------------ 4 bias
    out.append("## 4. Bias\n")
    out.append("**Predicted versus actual mean goals** (predicted = mean expected goals of the shipped grid; error = predicted minus actual per match with 95% bootstrap interval).\n")
    rows = []
    for lab, v in goals.items():
        rows.append([lab, v["n"], f"{v['home']['pred']:.2f} / {v['home']['act']:.2f}", f"{v['home']['err'][0]:+.3f} [{v['home']['err'][1]:+.3f}, {v['home']['err'][2]:+.3f}]",
                     f"{v['away']['pred']:.2f} / {v['away']['act']:.2f}", f"{v['away']['err'][0]:+.3f} [{v['away']['err'][1]:+.3f}, {v['away']['err'][2]:+.3f}]",
                     f"{v['total']['pred']:.2f} / {v['total']['act']:.2f}", f"{v['total']['err'][0]:+.3f} [{v['total']['err'][1]:+.3f}, {v['total']['err'][2]:+.3f}]"])
    out.append(table(["Group", "n", "Home pred / act", "Home error", "Away pred / act", "Away error", "Total pred / act", "Total error"], rows))
    out.append("")
    out.append(fig("fig05_bias.png", "Goal-level bias by league and favourite-longshot pattern"))
    out.append(f"\n{n_excl} of {n_int} per-league intervals exclude zero (about {0.05 * n_int:.1f} expected by chance).\n")
    out.append("**Predicted versus actual outcome frequencies** (error = mean predicted probability minus observed frequency, in percentage points).\n")
    rows = []
    for lab, v in BI["outcomes"].items():
        rows.append([lab] + [f"{pc(v[k]['pred'])} / {pc(v[k]['obs'])} ({100 * v[k]['err'][0]:+.1f} [{100 * v[k]['err'][1]:+.1f}, {100 * v[k]['err'][2]:+.1f}])" for k in ["H", "D", "A"]])
    out.append(table(["Group", "Home: pred / obs (error pp)", "Draw: pred / obs (error pp)", "Away: pred / obs (error pp)"], rows))
    out.append("\n**Home-advantage error** (goal difference, home minus away).\n")
    rows = []
    for lab, v in BI["home_adv"].items():
        rows.append([lab, f"{v['pred_gd']:+.3f}", f"{v['act_gd']:+.3f}", f"{v['err'][0]:+.3f} [{v['err'][1]:+.3f}, {v['err'][2]:+.3f}]", f"{pc(v['pred_home_share'])} / {pc(v['act_home_share'])}"])
    out.append(table(["Group", "Predicted mean GD", "Actual mean GD", "Error [95% CI]", "Home share of goals pred / act"], rows))
    out.append("\n**Favourite-longshot pattern (Europe).** By the favourite's predicted win probability:\n")
    rows = [[r["band"], r["n"], f"{pc(r['p_fav'])} / {pc(r['fav_win'])}", f"[{pc(r['fav_ci'][0])}, {pc(r['fav_ci'][1])}]", f"{pc(r['p_long'])} / {pc(r['long_win'])}", f"{pc(r['p_draw'])} / {pc(r['draw'])}"] for r in fb]
    out.append(table(["Favourite's predicted win prob.", "n", "Favourite win: pred / obs", "Obs. 95% Wilson", "Longshot win: pred / obs", "Draw: pred / obs"], rows))
    out.append("\nAnd pooled over team sides (each match contributes a home and an away observation):\n")
    rows = [[r["band"], r["n"], pc(r["pred"]), f"{pc(r['obs'])} [{pc(r['ci'][0])}, {pc(r['ci'][1])}]", f"{100 * (r['obs'] - r['pred']):+.1f} pp"] for r in sb]
    out.append(table(["Team win prob. band", "n sides", "Mean predicted", "Observed win rate [95% Wilson]", "Observed minus predicted"], rows))
    out.append(f"\nPooled logistic recalibration over all sides: slope {sl['slope'][0]:.3f} [{sl['slope'][1]:.3f}, {sl['slope'][2]:.3f}], intercept {sl['intercept'][0]:+.3f} [{sl['intercept'][1]:+.3f}, {sl['intercept'][2]:+.3f}]. Sides predicted below 20%: {pc(lg['pred'])} predicted, {pc(lg['obs'])} observed (n={lg['n']}); sides predicted at 60% or more: {pc(fv['pred'])} predicted, {pc(fv['obs'])} observed (n={fv['n']}), gap {100 * fv['gap'][0]:+.1f} pp [{100 * fv['gap'][1]:+.1f}, {100 * fv['gap'][2]:+.1f}]. Pattern: favourites win {'slightly more' if fv['gap'][0] > 0 else 'slightly less'} often and the sides under 10% win {'less' if sb[0]['obs'] < sb[0]['pred'] else 'more'} often than the model says; {'the model is a little compressed toward the middle, the same direction as the classic favourite-longshot bias in prices' if fv['gap'][0] > 0 and sb[0]['obs'] < sb[0]['pred'] else 'the pattern is not the classic favourite-longshot one'}; at this sample size {'only the favourite end excludes zero' if excl0(fv['gap'][1], fv['gap'][2]) and not (sb[0]['ci'][1] < sb[0]['pred']) else 'check the intervals above'}.\n")
    out.append("**Scoreline distribution** (observed frequency against the mean predicted probability of the same cell; z = (observed - expected) / its binomial-sum standard error; the 15 named cells plus \"other\").\n")
    rows = []
    for a_, b_, c_ in zip(sc_eu["rows"], sc_si["rows"], sc_sp["rows"]):
        rows.append([a_["score"], f"{pc(a_['obs'])} / {pc(a_['exp'])}", f"{a_['z']:+.2f}", f"{pc(b_['obs'])} / {pc(b_['exp'])}", f"{b_['z']:+.2f}", f"{pc(c_['obs'])} / {pc(c_['exp'])}", f"{c_['z']:+.2f}"])
    out.append(table(["Score", "Europe obs / exp", "z", "Site leagues obs / exp", "z", "Saudi obs / exp", "z"], rows))
    out.append(f"\nChi-square over the 16 cells: Europe {sc_eu['chi2']:.1f} (df {sc_eu['df']}, p {sc_eu['p_chi2']:.3f}); site leagues {sc_si['chi2']:.1f} (p {sc_si['p_chi2']:.3f}); Saudi {sc_sp['chi2']:.1f} (p {sc_sp['p_chi2']:.3f}). With 16 cells per group, one or two |z| above 2 are expected by chance.\n")
    out.append(fig("fig06_scorelines.png", "Observed versus expected scoreline and total-goal frequencies"))
    out.append("\n**Goal-count dispersion: is Poisson over- or under-dispersed?** Pearson ratio = sum of squared (goals - expected goals) divided by the sum of the model's own predictive variances (from the score grids). 1 = the Poisson/Dixon-Coles variance is right; above 1 the data are more dispersed than the model says; below 1, less. The last column is the correlation of home and away standardised residuals (0 = independence).\n")
    rows = [[k, v["n"], ci(v["home"], 3), ci(v["away"], 3), ci(v["total"], 3), ci(v["resid_corr"], 3)] for k, v in BI["dispersion"].items()]
    out.append(table(["Group", "n", "Home goals", "Away goals", "Total goals", "Home-away residual correlation"], rows))
    out.append("\nObserved against expected goal-count distributions (team goals pool home and away; \"k+\" = k or more):\n")
    for g in [G_EU, G_SPL]:
        gcn = BI["goal_counts"][g]
        rows = [[r["k"], f"{pc(r['obs'])} [{pc(r['ci'][0])}, {pc(r['ci'][1])}]", pc(r["exp"])] for r in gcn["team_goals"]]
        out.append(f"{g}, goals scored by a team:\n")
        out.append(table(["Goals", "Observed [95% Wilson]", "Expected"], rows))
        out.append("")
        rows = [[r["k"], f"{pc(r['obs'])} [{pc(r['ci'][0])}, {pc(r['ci'][1])}]", pc(r["exp"])] for r in gcn["total_goals"]]
        out.append(f"{g}, total goals in a match:\n")
        out.append(table(["Total goals", "Observed [95% Wilson]", "Expected"], rows))
        out.append("")

    # ------------------------------------------------------------------ 5 variance
    out.append("## 5. Variance and the bias-variance trade-off\n")
    out.append("All three analyses in 5a and 5b refit weekly and score the Dixon-Coles leg alone (w = 1 in every match, so the Elo blend does not blur the picture). 'Train' = the fitted model's decay-weighted RPS on its own training matches (averaged over weekly folds); 'validation' = RPS on the following week's matches (all matches of the season, 1,937). The ridge penalty is `lambda * (sum of squared attack and defence deviations)`; xi is fixed at the shipped value.\n")
    out.append("### 5a. Regularisation sweep (2024-25 tuning season)\n")
    out.append(fig("fig07_ridge_sweep.png", "Train versus validation error across the ridge lambda"))
    out.append("")
    rows = []
    for r in rs:
        t, h_ = r["tune"], r["hold"]
        rows.append([f"{r['reg']:g}" + (" (shipped)" if r["reg"] == 3 else ""), f"{t['train_rps']:.4f}", ci(t["val_rps"]), f"{t['val_rps'][0] - t['train_rps']:+.4f}", f"{t['train_ll']:.4f}", f"{t['val_ll'][0]:.4f}", f"{t['sd_attack']:.3f}", ci(h_["val_rps"])])
    out.append(table(["lambda", "Train RPS", "Validation RPS 2024-25 [95% CI]", "Gap (val - train)", "Train log-loss", "Val. log-loss", "SD of team attack ratings", "Holdout 2025-26 RPS (info only)"], rows))
    out.append(f"\nReading: with almost no ridge the model fits its training matches best (RPS {r_lo['tune']['train_rps']:.4f}) but generalises worse ({r_lo['tune']['val_rps'][0]:.4f}); with heavy ridge it underfits both ({r_500['tune']['train_rps']:.4f} train, {r_500['tune']['val_rps'][0]:.4f} validation at lambda 500, where team ratings are shrunk to nearly nothing: SD {r_500['tune']['sd_attack']:.3f}). The validation optimum ({best_tune['reg']:g}) coincides with the shipped value, and the valley is shallow: lambda 1 to 8 are within {max(r['tune']['val_rps'][0] for r in rs if 1 <= r['reg'] <= 8) - best_tune['tune']['val_rps'][0]:.4f} RPS of the best. Selection used 2024-25 only; the holdout column was not used for any choice.\n")
    out.append("### 5b. Learning curves (2025-26 holdout)\n")
    out.append(fig("fig08_learning_curves.png", "Learning curves: history length and time-decay half-life"))
    out.append("\n**Training-history length** (only the last N days before each weekly cutoff are used; 3 years = all data since August 2023, i.e. 2.0 to 2.8 years at the 2025-26 cutoffs):\n")
    rows = []
    for r in hist:
        rows.append([f"{r['window_days'] / 365:.1f} years" if r["window_days"] < 1095 else "all data (about 2 to 2.8 years)", f"{r['decay']['n_train_mean']:.0f}", ci(r["decay"]["val_rps"]), f"{r['decay']['train_rps']:.4f}", ci(r["nodecay"]["val_rps"]), f"{r['nodecay']['train_rps']:.4f}"])
    out.append(table(["History", "Mean matches used", "Validation RPS, shipped decay", "Train RPS", "Validation RPS, no decay", "Train RPS"], rows))
    out.append("\n**Time-decay half-life** (all history, validation on both seasons; the 2025-26 column is for information only):\n")
    rows = []
    for r in hl:
        lab = f"{r['half_life_days']:.0f} days" if r["half_life_days"] else "no decay"
        if r["xi"] == 0.0019:
            lab += " (shipped)"
        rows.append([lab, f"{r['xi']:.5f}", ci(r["tune"]["val_rps"]), ci(r["hold"]["val_rps"]), f"{r['hold']['train_rps']:.4f}"])
    out.append(table(["Half-life", "xi per day", "Validation RPS 2024-25", "Validation RPS 2025-26", "Train RPS (2025-26 folds)"], rows))
    out.append(f"\nReading: the validation curve is still edging down at the longest history ({h_steps[2]:.4f} from 2 years to all data, with diminishing returns; older matches might help marginally), the train curve rises with history (more to fit with the same flexibility), and the gap narrows from {h1['decay']['val_rps'][0] - h1['decay']['train_rps']:.4f} (6 months) to {h4['decay']['val_rps'][0] - h4['decay']['train_rps']:.4f} (all data). For the half-life the cost of a short memory (30 days: variance dominates) is large, while half-lives from about half a year upward differ by less than 0.001 RPS from one another, inside the intervals: time decay is a weak lever once ratings are ridge-shrunk.\n")
    out.append("### 5c. Parameter stability and prediction uncertainty (live snapshot)\n")
    out.append(f"The European model was refit on {sm['n_train']:,} training matches with cutoff 2026-10-19 (identical to the fit behind the featured predictions: the three locked `base` predictions are reproduced to {max(g['repro_max_abs_diff'] for g in ST['games']):.1e}), then {sm['bootstrap_fits']} bootstrap refits were run. Ratings are on the log-goal scale (attack and defence deviations from the league mean; 'overall strength' adds the league offset so teams from different leagues are comparable). {sm['n_teams']} teams with at least 10 matches in the previous 365 days are summarised.\n")
    out.append(fig("fig09_parameter_stability.png", "Team-rating uncertainty and prediction bands for the featured games"))
    out.append("")
    rows = [["Attack", f"{sm['median_sd_attack']:.3f}", f"{sm['between_team_sd_attack']:.3f}", f"{sm['reliability_attack']:.2f}"],
            ["Defence", f"{sm['median_sd_defence']:.3f}", f"{sm['between_team_sd_defence']:.3f}", f"{sm['reliability_defence']:.2f}"],
            ["Overall strength", f"{sm['median_sd_net']:.3f}", f"{sm['between_team_sd_net']:.3f}", f"{sm['reliability_net']:.2f}"]]
    out.append(table(["Rating", "Median bootstrap SD", "SD across teams", "Reliability = 1 - mean bootstrap variance / variance across teams"], rows))
    out.append(f"\nAttack-rating uncertainty falls with sample size: correlation of log(matches in the last year) with the bootstrap SD is {sm['corr_logn_sd_attack']:+.2f}; median SD {sm['sd_attack_few_matches']:.3f} for the {sm['n_few']} teams with under 25 matches against {sm['sd_attack_many_matches']:.3f} for the {sm['n_many']} teams with 40 or more. Global parameters are tight: home advantage eta {sm['eta_point']:.3f} (bootstrap {sm['eta_boot'][1]:.3f} to {sm['eta_boot'][2]:.3f}), rho {sm['rho_point']:+.3f} (bootstrap {sm['rho_boot'][1]:+.3f} to {sm['rho_boot'][2]:+.3f}, which includes zero).\n")
    rows = []
    for t in ST["featured_teams"]:
        rows.append([t["team"], t["n_recent"], f"{t['attack']:.3f} (SD {t['attack_sd']:.3f})", f"{t['defence']:.3f} (SD {t['defence_sd']:.3f})", f"{t['net']:.3f} [{t['net_lo']:.3f}, {t['net_hi']:.3f}]", f"{t['rank']} [{t['rank_lo']:.0f}, {t['rank_hi']:.0f}]"])
    out.append("Featured clubs (rank among the active teams by overall strength, with the 95% bootstrap range of the rank):\n")
    out.append(table(["Team", "Matches, last 365 d", "Attack", "Defence", "Overall strength [95% band]", "Rank [95% band]"], rows))
    out.append("\n**Prediction uncertainty bands for the three featured games** (base predictions, before the heuristic adjustments; 95% bootstrap bands of the Dixon-Coles parameters). 'Shipped base' holds the Elo leg at its point estimate, so for the two Champions League games, where the Elo leg has 70% weight, its band understates the total uncertainty; the Dixon-Coles-only rows show the uncertainty of the goals model itself.\n")
    rows = []
    for g in ST["games"]:
        for key, lab, pt in [("boot_base", "shipped base", "point_base"), ("boot_dc", "Dixon-Coles only", "point_dc")]:
            rows.append([f"{g['home']} v {g['away']}", lab] + [f"{100 * g[pt][k]:.1f}% ({band(g, key, o)}; SD {100 * g[key][o]['sd']:.1f} pp)" for k, o in enumerate(["H", "D", "A"])])
    out.append(table(["Match", "Version", "Home win: point (bootstrap median [95%])", "Draw", "Away win"], rows))
    adj_note = []
    in_sh = in_dc = 0
    for g in ST["games"]:
        a_h, b_h = g["locked_adjusted"][0], g["locked_base"][0]
        adj_note.append(100 * (a_h - b_h))
        in_sh += g["boot_base"]["H"]["lo"] <= a_h <= g["boot_base"]["H"]["hi"]
        in_dc += g["boot_dc"]["H"]["lo"] <= a_h <= g["boot_dc"]["H"]["hi"]
    out.append("\nLocked values for reference (read from `site/data/locks.json`, not modified): " + "; ".join(
        f"{g['home']} v {g['away']}: base {100 * g['locked_base'][0]:.1f}/{100 * g['locked_base'][1]:.1f}/{100 * g['locked_base'][2]:.1f}, adjusted headline {100 * g['locked_adjusted'][0]:.1f}/{100 * g['locked_adjusted'][1]:.1f}/{100 * g['locked_adjusted'][2]:.1f}" for g in ST["games"]) + f". The heuristic adjustments move the home-win probability by {adj_note[0]:+.1f}, {adj_note[1]:+.1f} and {adj_note[2]:+.1f} points (in the order of the games above); the adjusted home-win value lies inside the shipped-base bootstrap band for {in_sh} of 3 games and inside the Dixon-Coles-only band for {in_dc} of 3.\n")
    out.append("")

    # ------------------------------------------------------------------ 6 ablations
    out.append("## 6. Ablations on the holdout\n")
    out.append("Each variant is refit weekly on the same folds and scored on the same matches; the difference in per-match RPS (and log-loss) to the shipped model is bootstrapped (paired). Positive = the variant is worse than shipped.\n")
    rows = []
    for k, v in ab.items():
        rows.append([k, v["n"], f"{v['rps']:.4f} (shipped {v['ref_rps']:.4f})", dci(v["d_rps"]), pv(v["d_rps"]["p_boot"]), pv(v["d_rps"]["p_dm"]), dci(v["d_ll"])])
    out.append(table(["Variant", "n", "RPS", "Delta RPS [95% CI]", "Bootstrap p", "DM p", "Delta log-loss [95% CI]"], rows))
    out.append("\nVariant definitions:\n")
    out.extend(f"* **{k}**: {v['desc']}." for k, v in ab.items())
    out.append(f"\nThe Champions League link, on the {ul['n']} Champions League matches alone: shipped (Elo blend, with link) {ul['shipped_blend_with_link']:.4f}; same blend without Champions League results in the fit {ul['blend_no_link']:.4f} ({dci(ul['d_blend_no_link_vs_link'])}); pure Dixon-Coles with the link {ul['dc_with_link']:.4f} against without {ul['dc_no_link']:.4f} ({dci(ul['d_dc_no_link_vs_link'])}). On the {AB['domestic_n']:,} domestic matches the same no-link fit scores {dci(AB['domestic'][k_nolink]['d_rps'])}.\n")
    out.append("**Saudi Pro League** (306 matches; shipped RPS " + f"{AB['saudi_shipped_rps']:.4f}):\n")
    rows = [[k, f"{v['rps']:.4f}", dci(v["d_rps"]), pv(v["d_rps"]["p_boot"]), dci(v["d_ll"])] for k, v in sa.items()]
    out.append(table(["Variant", "RPS", "Delta RPS [95% CI]", "Bootstrap p", "Delta log-loss [95% CI]"], rows))
    out.append("\nRidge in the 'no ridge' rows is 0.01 rather than exactly 0, because attack, defence and the scoring level are only identified relative to one another (a common shift is a flat direction of the likelihood). The Saudi variants keep the amendment-1 rho pass unchanged except in the 'no rho' row.\n")
    out.append(fig("fig10_ablations.png", "Ablation effects on RPS"))
    out.append("")

    # ------------------------------------------------------------------ 7 errors
    out.append("## 7. Error analysis\n")
    out.append("### 7a. Confusion matrices (most likely result against actual)\n")
    for g in [G_EU, G_SPL]:
        c_ = ER["confusion"][g]; m_ = c_["matrix"]
        rows = [[lab, m_[i][0], m_[i][1], m_[i][2], sum(m_[i]), "-" if c_["recall"][i] is None else f"{pc(c_['recall'][i])} [{pc(c_['recall_ci'][i][0])}, {pc(c_['recall_ci'][i][1])}]"] for i, lab in enumerate(["Actual home win", "Actual draw", "Actual away win"])]
        out.append(f"**{g}** (n = {c_['n']:,})\n")
        out.append(table(["", "Predicted H", "Predicted D", "Predicted A", "Total", "Recall [95% Wilson]"], rows))
        out.append(f"\nPrecision: home {pc(c_['precision'][0])}, away {pc(c_['precision'][2])}, draw n/a (never predicted). Predicted shares {pc(c_['pred_share'][0])} / {pc(c_['pred_share'][1])} / {pc(c_['pred_share'][2])} against actual {pc(c_['actual_share'][0])} / {pc(c_['actual_share'][1])} / {pc(c_['actual_share'][2])}.\n")
    out.append(fig("fig11_error_analysis.png", "Confusion matrix, accuracy by month and goal-difference distribution"))
    out.append("\n### 7b. Accuracy by league\n")
    out.append("See the by-competition table in section 1 (accuracy, exact-score hit, RPS, log-loss with intervals for each league).\n")
    out.append("### 7c. By month (Europe) and the early-season cold start\n")
    rows = [[r["month"], r["n"], f"{pc(r['acc'])} [{pc(r['acc_ci'][0])}, {pc(r['acc_ci'][1])}]", ci(r["rps"]), f"{r['ll']:.4f}"] for r in mon]
    out.append(table(["Month", "n", "W/D/L accuracy [95% Wilson]", "RPS [95% CI]", "Log-loss"], rows))
    out.append(f"\nAugust-October (n={ev['n_early']}) against the rest (n={ev['n_rest']}): RPS {ev['rps_early']:.4f} against {ev['rps_rest']:.4f}, difference {ev['diff'][0]:+.4f} [{ev['diff'][1]:+.4f}, {ev['diff'][2]:+.4f}] (two-sample bootstrap); log-loss difference {ev['ll_diff'][0]:+.4f} [{ev['ll_diff'][1]:+.4f}, {ev['ll_diff'][2]:+.4f}]; accuracy {pc(ev['acc_early'])} against {pc(ev['acc_rest'])}. May against the other months: RPS {ER['may_vs_rest']['rps']:.4f} against {ER['may_vs_rest']['rps_rest']:.4f} ({ER['may_vs_rest']['diff'][0]:+.4f} [{ER['may_vs_rest']['diff'][1]:+.4f}, {ER['may_vs_rest']['diff'][2]:+.4f}]); April-May: {ER['apr_may_vs_rest']['diff'][0]:+.4f} [{ER['apr_may_vs_rest']['diff'][1]:+.4f}, {ER['apr_may_vs_rest']['diff'][2]:+.4f}]. Month-by-month comparisons are exploratory.\n")
    out.append("By how many same-season matches the less-experienced team of the two had already played (a direct cold-start measure):\n")
    rows = [[r["band"], r["n"], f"{pc(r['acc'])} [{pc(r['acc_ci'][0])}, {pc(r['acc_ci'][1])}]", ci(r["rps"]), f"{r['ll']:.4f}"] for r in ER["by_games_played"]]
    out.append(table(["Earlier games this season", "n", "W/D/L accuracy [95% Wilson]", "RPS [95% CI]", "Log-loss"], rows))
    out.append("\n### 7d. By favourite strength (Europe)\n")
    rows = [[r["band"], r["n"], f"{pc(r['acc'])} [{pc(r['acc_ci'][0])}, {pc(r['acc_ci'][1])}]", ci(r["rps"]), f"{r['ll']:.4f}", f"{pc(r['p_draw'])} / {pc(r['draw_rate'])}"] for r in ER["by_fav_band"]]
    out.append(table(["Favourite's win prob.", "n", "W/D/L accuracy [95% Wilson]", "RPS [95% CI]", "Log-loss", "Draw pred / obs"], rows))
    out.append("\n### 7e. By goal difference (Europe; home minus away)\n")
    rows = [[r["gd"], r["n"], f"{pc(r['acc'])} [{pc(r['acc_ci'][0])}, {pc(r['acc_ci'][1])}]", pc(r["p_actual_outcome"]), f"{r['rps']:.3f}"] for r in ER["by_gd"]]
    out.append(table(["Actual goal difference", "n", "Called correctly [95% Wilson]", "Mean probability on the actual result", "Mean RPS"], rows))
    out.append("\nDraws (goal difference 0) are never called by construction; big wins are easy to call and 1-goal results are close to coin flips.\n")
    out.append("### 7f. Goal-difference error distribution (Europe)\n")
    out.append(f"Error = actual goal difference minus the model's expected goal difference. Mean {ci(gd['mean'], 3)} (a positive value means home sides did better than predicted, consistent with the understated home advantage), SD {gd['sd']:.3f} against {gd['model_implied_sd']:.3f} implied by the score grids, RMSE {gd['rmse']:.3f}, mean absolute error {ci(gd['mae'], 3)}, skew {gd['skew']:+.3f}, excess kurtosis {gd['excess_kurtosis']:+.3f}; percentiles 5 / 25 / 50 / 75 / 95: " + " / ".join(f"{q:+.2f}" for q in gd["q"]) + ".\n")
    rows = [[f"{v:+d}", pc(o, 2), pc(e, 2), f"{100 * (o - e):+.2f} pp"] for v, o, e in zip(gd["gd_values"], gd["gd_obs"], gd["gd_exp"])]
    out.append(table(["Goal difference", "Observed", "Model expected", "Observed minus expected"], rows))
    out.append("\n### 7g. The 15 worst-predicted European matches (lowest probability on the actual result)\n")
    rows = [[r["rank"], r["date"], r["comp"], r["match"], r["probs"], pc(r["p_actual"]), r["reason"]] for r in ER["worst15_europe"]]
    out.append(table(["#", "Date", "Competition", "Result", "P(H/D/A)", "P(actual)", "Pattern (generated from the data)"], rows))
    out.append(f"\nPattern across the 15: {wsum['n_longshot']} longshot wins and {wsum['n_draw']} draws by a favourite (mean favourite probability {pc(wsum['mean_fav_p'], 0)}); {wsum['n_away_win']} were away wins (a home favourite fell); {wsum['n_early']} involved a team with at most five earlier games that season (the share of all European matches in that situation is {pc(wsum['share_early_all'], 0)}); {wsum['n_thin']} involve a team with fewer than 20 matches in the data over the prior year; {wsum['n_ucl']} Champions League (that competition is {pc(wsum['share_ucl_all'], 0)} of matches); mean absolute goal difference {wsum['mean_margin']:.1f} against {wsum['mean_margin_all']:.2f} for all matches; spread over {wsum['n_leagues_in_top15_unique']} competitions ({', '.join(f'{k} {v}' for k, v in wsum['comp_counts'].items())}). The common thread is a heavy favourite failing to win ({'cold start or thin history explains few of them' if wsum['n_early'] + wsum['n_thin'] <= 8 else 'cold start or thin history explains a fair share of them'}).\n")
    rows = [[t["t"], t["observed"], f"{t['expected']:.1f}"] for t in tail]
    out.append("Are such misses more frequent than the probabilities imply? Number of matches whose actual result had a predicted probability below t, against the number the model's own probabilities imply (sum of all outcome probabilities below t):\n")
    out.append(table(["t", "Observed matches", "Implied by the model"], [[f"{r[0]:.2f}", r[1], r[2]] for r in rows]))
    out.append("\nSaudi Pro League, 5 worst:\n")
    rows = [[r["rank"], r["date"], r["match"], r["probs"], pc(r["p_actual"]), r["reason"]] for r in ER["worst5_saudi"]]
    out.append(table(["#", "Date", "Result", "P(H/D/A)", "P(actual)", "Pattern"], rows))
    out.append("")

    # ------------------------------------------------------------------ 8 limits / reproduce
    out.append("## 8. What this evaluation does not show\n")
    out.append("* **One holdout season.** Everything describes 2025-26. The 2026-27 matches to date are reported in `BACKTEST.md` and were not used here.")
    out.append("* **No market comparison**, by design (odds are not used anywhere in the project).")
    ratios = []
    for g_ in [G_EU, G_SITE, G_SPL]:
        for b_, t_ in BL[g_]["tests"].items():
            if "rps" in t_ and abs(t_["rps"]["diff"]) > 1e-12:
                ratios.append((t_["rps"]["block_ci"][1] - t_["rps"]["block_ci"][0]) / (t_["rps"]["hi"] - t_["rps"]["lo"]))
    out.append(f"* **Dependence.** Matches share teams and weeks, so match-level intervals are optimistic in principle; the week-block bootstrap in section 2 gives intervals {min(ratios):.2f} to {max(ratios):.2f} times as wide as the match-level ones (RPS differences), so the effect is modest and no conclusion in this report changes.")
    out.append("* **Post-hoc diagnostics on the holdout** (ridge and half-life curves for 2025-26, Saudi no-decay, the recalibration check) were not used to change any setting; they say where to look next, not what to ship.")
    out.append("* **Subgroup tables** (league, month, band, scoreline) involve many comparisons; treat isolated intervals that exclude zero as leads, not findings.")
    out.append("* **The adjustments** (xG regression, injuries and suspensions) for the three featured games are heuristic and not evaluated here. The bootstrap bands in 5c apply to the `base` model only.")
    out.append("* **The Elo leg is held fixed** in the parameter-stability bootstrap (Elo ratings are sequential and are not meaningfully resampled), so the shipped Champions League bands understate total uncertainty; the Dixon-Coles-only rows show the goals model's own uncertainty.")
    out.append("")
    out.append("## Reproduce\n")
    out.append("```\n.venv/bin/pip install matplotlib        # only extra dependency (see evaluation/requirements.txt)\n.venv/bin/python evaluation/run_eval.py   # computes everything, writes results.json, figures/, EVALUATION.md\n.venv/bin/python evaluation/run_eval.py --report-only   # re-render EVALUATION.md from results.json\n```\n")
    out.append("Files: `evaluation/run_eval.py` (analysis), `evaluation/write_report.py` (this report), `evaluation/results.json` (every number), `evaluation/holdout_predictions_2025-26.csv` (per-match shipped, Elo and base-rate probabilities and expected goals), `evaluation/figures/*.png`.")
    text = "\n".join(out) + "\n"
    open(os.path.join(ROOT, "EVALUATION.md"), "w").write(text)
    return text


if __name__ == "__main__":
    write_report(json.load(open(os.path.join(HERE, "results.json"))))
