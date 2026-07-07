"""Constructeur de features point-in-time.
Entree : DataFrame matchs normalise (agent_collecte) + xG optionnel.
Sortie : table (match_id, side) avec tous les atomes booleens + contexte marche.

REGLE ABSOLUE (delta 4) : toute feature d'un match n'utilise que des matchs
STRICTEMENT anterieurs. Verifie par tests/test_moteur.py::test_anti_lookahead.
"""
import numpy as np
import pandas as pd
from .classement import passe_enjeu
from .devig import probas_justes


# ---------- helpers series ----------
def _serie_avant(valeurs_bool):
    """serie[i] = longueur de la sequence True immediatement avant l'indice i."""
    out = np.zeros(len(valeurs_bool), dtype=int)
    run = 0
    for i, v in enumerate(valeurs_bool):
        out[i] = run
        run = run + 1 if v else 0
    return out


def _roll_prev(s, w, fn="mean", minp=None):
    """agregat glissant sur les w valeurs PRECEDENTES (shift(1))."""
    r = s.shift(1).rolling(w, min_periods=minp or w)
    return getattr(r, fn)()


# ---------- construction table longue ----------
def table_longue(matchs: pd.DataFrame) -> pd.DataFrame:
    base = []
    for side in ("home", "away"):
        opp = "away" if side == "home" else "home"
        d = pd.DataFrame({
            "match_id": matchs["match_id"], "league": matchs["league"],
            "season": matchs["season"], "date": matchs["date"],
            "team": matchs[side], "opp": matchs[opp], "side": side,
            "gf": matchs["fthg"] if side == "home" else matchs["ftag"],
            "ga": matchs["ftag"] if side == "home" else matchs["fthg"],
            "ht_gf": matchs["hthg"] if side == "home" else matchs["htag"],
            "ht_ga": matchs["htag"] if side == "home" else matchs["hthg"],
            "cartons_self": (matchs["hy"] + matchs["hr"]) if side == "home" else (matchs["ay"] + matchs["ar"]),
            "cote_self": matchs["psh"] if side == "home" else matchs["psa"],
        })
        base.append(d)
    lg = pd.concat(base, ignore_index=True).sort_values(["team", "date", "match_id"]).reset_index(drop=True)
    lg["win"] = lg["gf"] > lg["ga"]
    lg["loss"] = lg["gf"] < lg["ga"]
    lg["draw"] = lg["gf"] == lg["ga"]
    lg["marge"] = lg["gf"] - lg["ga"]
    lg["total_buts"] = lg["gf"] + lg["ga"]
    lg["mt2_gf"] = lg["gf"] - lg["ht_gf"]; lg["mt2_ga"] = lg["ga"] - lg["ht_ga"]
    return lg


def _features_forme(lg: pd.DataFrame, xg_dispo: bool) -> pd.DataFrame:
    def par_equipe(df):
        df = df.sort_values(["date", "match_id"]).copy()
        w = df["win"].to_numpy(); l_ = df["loss"].to_numpy(); d_ = df["draw"].to_numpy()
        df["serie_v"] = _serie_avant(w)
        df["serie_sans_v"] = _serie_avant(~w)
        df["serie_nuls"] = _serie_avant(d_)
        for k in (1, 2, 3):
            df[f"marge_m{k}"] = df["marge"].shift(k)
            df[f"win_m{k}"] = df["win"].shift(k)
        df["sansv_il_y_a_3"] = pd.Series(df["serie_sans_v"]).shift(3)
        df["v_l3"] = _roll_prev(df["win"], 3, "sum")
        df["gf_l5"] = _roll_prev(df["gf"], 5); df["ga_l5"] = _roll_prev(df["ga"], 5)
        df["gf_l5_max0"] = _roll_prev(df["gf"], 5, "max")
        df["nb_ge2_enc_l5"] = _roll_prev((df["ga"] >= 2).astype(float), 5, "sum")
        df["serie_sans_but"] = _serie_avant((df["gf"] == 0).to_numpy())
        df["cartons_l5"] = _roll_prev(df["cartons_self"], 5)
        # mi-temps (fenetre L4)
        df["mt1_but_l4"] = _roll_prev((df["ht_gf"] > 0).astype(float), 4, "sum")
        df["mt1_gf_l4"] = _roll_prev(df["ht_gf"], 4)
        df["mt1_enc_l4"] = _roll_prev((df["ht_ga"] > 0).astype(float), 4, "sum")
        df["mt1_ga_l4"] = _roll_prev(df["ht_ga"], 4)
        df["mt1_enc_l5_sum"] = _roll_prev(df["ht_ga"], 5, "sum")
        df["mt2_but_l4"] = _roll_prev((df["mt2_gf"] > 0).astype(float), 4, "sum")
        df["mt2_diff_l4"] = _roll_prev(df["mt2_gf"] - df["mt2_ga"], 4)
        df["o15_mt1_l4"] = _roll_prev(((df["ht_gf"] + df["ht_ga"]) >= 2).astype(float), 4, "sum")
        df["u05_mt1_l4"] = _roll_prev(((df["ht_gf"] + df["ht_ga"]) == 0).astype(float), 4, "sum")
        df["o35_l4"] = _roll_prev((df["total_buts"] >= 4).astype(float), 4, "sum")
        df["u15_l4"] = _roll_prev((df["total_buts"] <= 1).astype(float), 4, "sum")
        df["repos_jours"] = (df["date"] - df["date"].shift(1)).dt.days
        df["cote_prec"] = df["cote_self"].shift(1)
        # venue-specifique
        for venue in ("home", "away"):
            m = df["side"] == venue
            sub = df.loc[m]
            df.loc[m, f"serie_v_{venue}"] = _serie_avant(sub["win"].to_numpy())
            df.loc[m, f"serie_sansv_{venue}"] = _serie_avant((~sub["win"]).to_numpy())
            df.loc[m, f"winpct_std_{venue}"] = (
                sub.groupby("season")["win"].transform(lambda s: s.shift(1).expanding().mean())
            )
            df.loc[m, f"nb_std_{venue}"] = sub.groupby("season").cumcount()
        sub_h = df[df["side"] == "home"]
        df.loc[df["side"] == "home", "ga_dom_l10"] = _roll_prev(sub_h["ga"], 10)
        df.loc[df["side"] == "home", "cs_dom_l10"] = _roll_prev((sub_h["ga"] == 0).astype(float), 10, "sum")
        if xg_dispo:
            df["xg_l5"] = _roll_prev(df["xg_for"], 5); df["xga_l5"] = _roll_prev(df["xg_ag"], 5)
            df["xg_l6_10"] = _roll_prev(df["xg_for"].shift(5), 5)
            df["xga_l6_10"] = _roll_prev(df["xg_ag"].shift(5), 5)
            df["xg_std_l5"] = _roll_prev(df["xg_for"], 5, "std")
            df["gf_sum_l5"] = _roll_prev(df["gf"], 5, "sum")
            df["xg_sum_l5"] = _roll_prev(df["xg_for"], 5, "sum")
        return df

    morceaux = [par_equipe(df_t) for _, df_t in lg.groupby("team", sort=False)]
    return pd.concat(morceaux, ignore_index=True)


def _hist_fin_saison(lg: pd.DataFrame) -> dict:
    """(team, season) -> winrate sur les 8 derniers matchs de la saison."""
    out = {}
    for (team, season), df in lg.groupby(["team", "season"]):
        df = df.sort_values("date")
        if len(df) >= 8:
            out[(team, season)] = df["win"].tail(8).mean()
    return out


def _passe_contexte(matchs, derbys, zones_par_ligue):
    """Passe chronologique : enjeu, H2H, arbitre, bilans vs top/bas."""
    ctx = {}
    h2h = {}          # frozenset(pair) -> list de (date, home, hg, ag)
    arbitre_hist = {} # ref -> list de (date, cartons)
    vs_top = {}       # (team, season) -> [pos, n]
    vs_bas = {}       # (team, season) -> [wins, n]
    for (league, season), grp in matchs.groupby(["league", "season"], sort=False):
        grp = grp.sort_values(["date", "match_id"])
        zones = zones_par_ligue.get(league, {"releg_spots": 3, "promo_spots": 0, "europe_spots": 6})
        enjeu = passe_enjeu(grp, zones)
        for _, m in grp.iterrows():
            mid = m["match_id"]; pair = frozenset((m["home"], m["away"]))
            rencontres = h2h.get(pair, [])
            l5 = rencontres[-5:]
            btts5 = sum(1 for r in l5 if r[2] > 0 and r[3] > 0)
            u25_5 = sum(1 for r in l5 if r[2] + r[3] <= 2)
            meme_venue = [r for r in rencontres if r[1] == m["home"]][-3:]
            dom_loc = (
                len(meme_venue) >= 3
                and sum(1 for r in meme_venue if r[2] > r[3]) >= 2
            )
            visites = [r for r in rencontres if r[1] == m["home"]][-5:]
            visiteur_faible = len(visites) >= 3 and sum(1 for r in visites if r[3] > r[2]) <= 1
            derniere = rencontres[-1] if rencontres else None
            rev_home = rev_away = False
            if derniere:
                dh, da = derniere[2], derniere[3]
                perdant, marge = (derniere[1], da - dh) if da > dh else (
                    ({m["home"], m["away"]} - {derniere[1]}).pop(), dh - da) if dh > da else (None, 0)
                if perdant and marge >= 2:
                    rev_home = perdant == m["home"]; rev_away = perdant == m["away"]
            est_derby = pair in derbys
            cartons_h2h = [r[4] for r in l5 if len(r) > 4]
            derby_chaud = est_derby and len(cartons_h2h) >= 3 and np.mean(cartons_h2h) >= 4
            ref = m.get("referee")
            hist = [c for d, c in arbitre_hist.get(ref, []) if (m["date"] - d).days <= 730]
            arbitre_severe = len(hist) >= 15 and np.mean(hist) >= 5.0
            e = enjeu[mid]
            for side, team in (("home", m["home"]), ("away", m["away"])):
                key = (team, season)
                vt = vs_top.get(key, [0, 0]); vb = vs_bas.get(key, [0, 0])
                ctx[(mid, side)] = {
                    **e[side],
                    "H2H_BTTS": len(l5) >= 4 and btts5 >= 4,
                    "H2H_UNDER25": len(l5) >= 4 and u25_5 >= 4,
                    "H2H_DOMINATION_LOCALE": bool(dom_loc and visiteur_faible) if side == "home" else False,
                    "H2H_REVANCHE": rev_home if side == "home" else rev_away,
                    "DERBY": est_derby, "DERBY_CHAUD": bool(derby_chaud),
                    "ARBITRE_SEVERE": bool(arbitre_severe),
                    "FAIBLE_VS_TOP": vt[1] >= 5 and (vt[0] / vt[1]) <= 0.20,
                    "DOMINE_FAIBLES": vb[1] >= 4 and (vb[0] / vb[1]) >= 0.75,
                }
            # mises a jour post-match
            hg, ag = int(m["fthg"]), int(m["ftag"])
            cartons_tot = int(m["hy"] + m["ay"] + m["hr"] + m["ar"])
            h2h.setdefault(pair, []).append((m["date"], m["home"], hg, ag, cartons_tot))
            if ref is not None and isinstance(ref, str) and ref:
                arbitre_hist.setdefault(ref, []).append((m["date"], cartons_tot))
            for side, team, opp_side in (("home", m["home"], "away"), ("away", m["away"], "home")):
                e_s = enjeu[mid][side]
                res_pos = (hg > ag) if side == "home" else (ag > hg)
                nul = hg == ag
                key = (team, season)
                if e_s["opp_top_half"]:
                    v = vs_top.setdefault(key, [0, 0]); v[0] += 1 if (res_pos or nul) else 0; v[1] += 1
                if e_s["opp_bottom_third"]:
                    v = vs_bas.setdefault(key, [0, 0]); v[0] += 1 if res_pos else 0; v[1] += 1
    return ctx


def construire(matchs: pd.DataFrame, xg: pd.DataFrame | None = None,
               derbys: set | None = None, zones_par_ligue: dict | None = None) -> pd.DataFrame:
    matchs = matchs.sort_values(["date", "match_id"]).reset_index(drop=True)
    lg = table_longue(matchs)
    xg_dispo = False
    if xg is not None and len(xg):
        xg_l = []
        for side in ("home", "away"):
            xg_l.append(pd.DataFrame({
                "match_id": xg["match_id"], "side": side,
                "xg_for": xg["xg_home"] if side == "home" else xg["xg_away"],
                "xg_ag": xg["xg_away"] if side == "home" else xg["xg_home"]}))
        lg = lg.merge(pd.concat(xg_l), on=["match_id", "side"], how="left")
        xg_dispo = lg["xg_for"].notna().mean() > 0.3
    lg = _features_forme(lg, xg_dispo)
    hist_fs = _hist_fin_saison(lg)
    saisons = sorted(matchs["season"].unique())
    idx_saison = {s: i for i, s in enumerate(saisons)}
    def fin_saison_histo(row):
        i = idx_saison[row["season"]]
        prev = [hist_fs.get((row["team"], saisons[j])) for j in range(max(0, i - 3), i)]
        prev = [p for p in prev if p is not None]
        return len(prev) >= 2 and sum(1 for p in prev if p >= 0.65) >= 2
    lg["FIN_SAISON_FORTE_HISTO"] = lg.apply(fin_saison_histo, axis=1)
    ctx = _passe_contexte(matchs, derbys or set(), zones_par_ligue or {})
    ctx_df = pd.DataFrame([{"match_id": k[0], "side": k[1], **v} for k, v in ctx.items()])
    lg = lg.merge(ctx_df, on=["match_id", "side"], how="left")
    return calculer_atomes(lg, xg_dispo)


def calculer_atomes(lg: pd.DataFrame, xg_dispo: bool) -> pd.DataFrame:
    a = lg
    a["VENUE_DOM"] = a["side"] == "home"
    a["VENUE_EXT"] = a["side"] == "away"
    a["SERIE_VICTOIRES"] = a["serie_v"] >= 3
    a["SERIE_V_LONGUE"] = (a["serie_v"] >= 4) & (_moy(a, ["marge_m1", "marge_m2", "marge_m3"]) >= 1.5)
    a["SERIE_V_SERREES"] = (a["serie_v"] >= 3) & (a["marge_m1"] == 1) & (a["marge_m2"] == 1) & (a["marge_m3"] == 1)
    a["SERIE_SANS_V"] = a["serie_sans_v"] >= 4
    a["SERIE_NULS"] = a["serie_nuls"] >= 3
    a["CRISE_OFFENSIVE"] = (a["gf_l5"] <= 0.5) | (a["serie_sans_but"] >= 3)
    a["ATTAQUE_PROLIFIQUE"] = a["gf_l5"] >= 2.0
    a["DEFENSE_PASSOIRE"] = (a["ga_l5"] >= 2.0) & (a["nb_ge2_enc_l5"] >= 3)
    a["REPRISE_FORME"] = (a["v_l3"] >= 2) & (a["sansv_il_y_a_3"] >= 4)
    a["POST_DEFAITE_LOURDE"] = (a["marge_m1"] <= -3)
    a["POST_VICTOIRE_LARGE"] = (a["marge_m1"] >= 3)
    a["POST_VICTOIRE_SURPRISE"] = (a["win_m1"] == True) & (a["cote_prec"] >= 3.0)
    a["FORT_MT1"] = (a["mt1_but_l4"] >= 3) & (a["mt1_gf_l4"] >= 0.9)
    a["ENCAISSE_MT1"] = (a["mt1_enc_l4"] >= 3) & (a["mt1_ga_l4"] >= 0.8)
    a["SOLIDE_MT1"] = a["mt1_enc_l5_sum"] <= 1
    a["FORT_MT2"] = (a["mt2_but_l4"] >= 3) & (a["mt2_diff_l4"] >= 0.5)
    a["O15_MT1_FREQ"] = a["o15_mt1_l4"] >= 3
    a["U05_MT1_FREQ"] = a["u05_mt1_l4"] >= 3
    a["SCORING_FOU"] = a["o35_l4"] >= 3
    a["U15_FREQ"] = a["u15_l4"] >= 3
    a["EQUIPE_CARTONS"] = a["cartons_l5"] >= 2.5
    a["FORTERESSE"] = (a["winpct_std_home"] >= 0.70) & (a["nb_std_home"] >= 5) & (a["serie_v_home"] >= 3)
    a["FAIBLE_DOMICILE"] = a["serie_sansv_home"] >= 4
    a["VOYAGEUR_FORT"] = (a["winpct_std_away"] >= 0.60) & (a["nb_std_away"] >= 5) & (a["serie_v_away"] >= 2)
    a["FAIBLE_EXTERIEUR"] = a["serie_sansv_away"] >= 4
    a["STADE_FERME"] = (a["ga_dom_l10"] <= 0.7) & (a["cs_dom_l10"] >= 5)
    a["REPOS_COURT"] = a["repos_jours"] <= 4
    a["REPOS_LONG"] = a["repos_jours"] >= 7
    a["MATCH_A_ENJEU"] = a["MATCH_A_ENJEU_ST"].fillna(False) | a["DERBY"].fillna(False)
    a["FAVORI_NET"] = a["cote_self"] <= 1.60
    a["OUTSIDER"] = a["cote_self"] >= 3.50
    if xg_dispo:
        diff_fin = a["gf_l5"] - a["xg_l5"]
        a["XG_SURPERF"] = diff_fin >= 0.5
        a["XG_SOUSPERF"] = diff_fin <= -0.5
        a["XG_DIFF_POS"] = (a["xg_l5"] - a["xga_l5"]) >= 0.8
        a["XG_DIFF_NEG"] = (a["xg_l5"] - a["xga_l5"]) <= -0.8
        a["XG_ELEVE"] = a["xg_l5"] >= 1.75
        a["XG_FAIBLE"] = a["xg_l5"] <= 1.0
        a["XG_TREND_UP"] = (a["xg_l5"] - a["xg_l6_10"]) >= 0.5
        a["XG_TREND_DOWN"] = (a["xg_l5"] - a["xg_l6_10"]) <= -0.5
        a["XGA_TREND_UP"] = (a["xga_l5"] - a["xga_l6_10"]) >= 0.5
        a["XGA_TREND_DOWN"] = (a["xga_l5"] - a["xga_l6_10"]) <= -0.5
        ratio = a["gf_sum_l5"] / a["xg_sum_l5"].replace(0, np.nan)
        a["RATIO_FINITION_HAUT"] = (ratio >= 1.3) & (a["xg_sum_l5"] >= 5)
        a["RATIO_FINITION_BAS"] = (ratio <= 0.7) & (a["xg_sum_l5"] >= 5)
        a["XG_ELEVE_STABLE"] = (a["xg_l5"] >= 1.75) & (a["xg_std_l5"] <= 0.35)
    colonnes_atomes = [c for c in a.columns if c.isupper() and a[c].dtype != object]
    for c in colonnes_atomes:
        a[c] = a[c].fillna(False).astype(bool)
    a.attrs["xg_dispo"] = xg_dispo
    return a


def _moy(a, cols):
    return sum(a[c] for c in cols) / len(cols)
