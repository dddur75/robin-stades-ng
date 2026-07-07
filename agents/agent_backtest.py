"""AGENT BACKTEST — Vague 1.
Charge les donnees, construit les features point-in-time, evalue les 68
hypotheses pre-enregistrees, applique la FDR, ecrit le rapport honnete.

Usage : python agents/agent_backtest.py [--data data/] [--rapport rapports/]
"""
import argparse, os, sys, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from moteur.features import construire
from moteur.marches import issues, prix_et_probas, TOKENS
from moteur.stats import wilson_ci, z_vs_probas, p_value_bilaterale, benjamini_hochberg, roi_flat
from agents.vague1_spec import VAGUE1
import yaml

ETAGE2_PRIX = {"WIN_SELF", "WIN_ADV", "O25", "U25"}
ETAGE2_FAIR = {"DC_SELF", "DC_ADV"}
N_MIN_RAPPORT = 50
N_MIN_VERDICT = 300


def charger_config(chemin="config/ligues.yaml"):
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def charger_derbys(chemin="config/derbys.yaml"):
    if not os.path.exists(chemin):
        return set()
    with open(chemin, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    paires = set()
    for lst in d.values():
        for p in lst or []:
            paires.add(frozenset(p))
    return paires


def preparer(data_dir, cfg):
    matchs = pd.read_parquet(os.path.join(data_dir, "matches.parquet"))
    matchs["date"] = pd.to_datetime(matchs["date"])
    holdout = set(cfg.get("holdout_seasons", []))
    n_avant = len(matchs)
    matchs = matchs[~matchs["season"].isin(holdout)].copy()
    xg = None
    xg_path = os.path.join(data_dir, "xg.parquet")
    if os.path.exists(xg_path):
        xg = pd.read_parquet(xg_path)
    zones = {l: v.get("zones", {}) for l, v in cfg.get("ligues", {}).items()}
    derbys = charger_derbys()
    feats = construire(matchs, xg=xg, derbys=derbys, zones_par_ligue=zones)
    cols_match = ["match_id", "psch", "pscd", "psca", "psh", "psd", "psa",
                  "pc_o25", "pc_u25", "p_o25", "p_u25", "hy", "ay", "hr", "ar"]
    cols_match = [c for c in cols_match if c in matchs.columns]
    mm = matchs[cols_match].copy()
    mm["cartons_tot"] = mm[[c for c in ("hy", "ay", "hr", "ar") if c in mm]].sum(axis=1)
    feats = feats.merge(mm, on="match_id", how="left")
    return matchs, feats, holdout, n_avant - len(matchs)


def vue_adverse(feats, atomes):
    adv = feats[["match_id", "side"] + atomes].copy()
    adv["side"] = adv["side"].map({"home": "away", "away": "home"})
    adv = adv.rename(columns={a: "adv_" + a for a in atomes})
    return feats.merge(adv, on=["match_id", "side"], how="left")


def calcul_issues_et_prix(feats):
    iss = pd.DataFrame([issues(r) for r in feats[["gf", "ga", "ht_gf", "ht_ga", "cartons_tot"]].to_dict("records")],
                       index=feats.index)
    cols_prix = ["side", "psch", "pscd", "psca", "psh", "psd", "psa",
                 "pc_o25", "pc_u25", "p_o25", "p_u25"]
    prix = [prix_et_probas(r) for r in feats.reindex(columns=cols_prix).to_dict("records")]
    nouvelles = {}
    for tok in ETAGE2_PRIX | ETAGE2_FAIR:
        nouvelles["cote__" + tok] = [p.get(tok, (None, None, None))[0] for p in prix]
        nouvelles["fair__" + tok] = [p.get(tok, (None, None, None))[1] for p in prix]
        nouvelles["clot__" + tok] = [p.get(tok, (None, None, None))[2] for p in prix]
    return pd.concat([feats, pd.DataFrame(nouvelles, index=feats.index),
                      iss.add_prefix("iss__")], axis=1)


def masque_hypothese(df, spec, xg_dispo):
    if spec.get("xg") and not xg_dispo:
        return None
    c = spec["cond"]
    m = pd.Series(True, index=df.index)
    for a in c.get("self_", []):
        m &= df[a].fillna(False)
    for a in c.get("adv", []):
        col = "adv_" + a
        m &= df[col].fillna(False)
    for a in c.get("match", []):
        m &= df[a].fillna(False)
    for grp in c.get("any_self", []):
        m &= np.logical_or.reduce([df[a].fillna(False) for a in grp])
    for grp in c.get("any_adv", []):
        m &= np.logical_or.reduce([df["adv_" + a].fillna(False) for a in grp])
    if c.get("match_opp_top"):
        m &= df["opp_top_half"].fillna(False)
    if c.get("match_opp_bas"):
        m &= df["opp_bottom_third"].fillna(False)
    return m


def evaluer(feats, bases, xg_dispo):
    lignes = []
    for spec in VAGUE1:
        m = masque_hypothese(feats, spec, xg_dispo)
        if m is None:
            lignes.append(dict(id=spec["id"], nom=spec["nom"], marche="-", etage="-", n=0,
                               statut="NON_EVALUE (xG absent)"))
            continue
        sel = feats[m]
        for tok in spec["marches"]:
            l = _evaluer_marche(sel, tok, bases)
            l.update(id=spec["id"], nom=spec["nom"])
            lignes.append(l)
    return pd.DataFrame(lignes)


def _evaluer_marche(sel, tok, bases):
    col_iss = "iss__" + tok
    d = sel.dropna(subset=[col_iss])
    if tok in ETAGE2_PRIX:
        d = d[d["fair__" + tok].notna() & d["cote__" + tok].notna()]
        etage = "2"
    elif tok in ETAGE2_FAIR:
        d = d[d["fair__" + tok].notna()]
        etage = "2*"
    else:
        etage = "1"
    n = len(d)
    if n == 0:
        return dict(marche=tok, etage=etage, n=0, statut="VIDE")
    hits = int(d[col_iss].sum())
    obs = hits / n
    if etage in ("2", "2*"):
        ref = d["fair__" + tok].to_numpy(dtype=float)
        pct_cloture = float(pd.Series(d["clot__" + tok]).fillna(False).mean())
    else:
        ref = d.merge(bases[tok], on=["league", "season", "side"], how="left")["base"].fillna(
            bases[tok]["base"].mean()).to_numpy(dtype=float)
        pct_cloture = np.nan
    z = z_vs_probas(hits, ref)
    p = p_value_bilaterale(z)
    delta = obs - float(np.mean(ref))
    roi, roi_ic = (np.nan, (np.nan, np.nan))
    if etage == "2":
        cotes = d["cote__" + tok].to_numpy(dtype=float)
        gains = np.where(d[col_iss].to_numpy(dtype=bool), cotes - 1.0, -1.0)
        roi, roi_ic = roi_flat(gains)
    lo, hi = wilson_ci(hits, n)
    saisons_ok = saisons_tot = 0
    for saison, g in d.groupby("season"):
        if len(g) < 10:
            continue
        if etage != "1":
            ref_s = g["fair__" + tok].mean()
        else:
            ref_s = g.merge(bases[tok], on=["league", "season", "side"], how="left")["base"].mean()
        saisons_tot += 1
        if g[col_iss].mean() - ref_s > 0:
            saisons_ok += 1
    return dict(marche=tok, etage=etage, n=n, obs=obs, ref=float(np.mean(ref)), delta=delta,
                roi=roi, roi_lo=roi_ic[0], roi_hi=roi_ic[1], ic_lo=lo, ic_hi=hi,
                z=z, p=p, saisons_pos=saisons_ok, saisons_tot=saisons_tot,
                pct_cloture=pct_cloture, statut="")


def taux_de_base(feats):
    bases = {}
    for tok in TOKENS:
        col = "iss__" + tok
        b = feats.dropna(subset=[col]).groupby(["league", "season", "side"])[col].mean().rename("base").reset_index()
        bases[tok] = b
    return bases


def verdicts(res, q_fdr):
    ok = res[res["n"] >= N_MIN_RAPPORT].copy()
    if len(ok):
        ok["fdr"] = benjamini_hochberg(ok["p"].to_numpy(), q=q_fdr)
    res = res.merge(ok[["id", "marche", "fdr"]], on=["id", "marche"], how="left")
    res["fdr"] = res["fdr"].fillna(False)

    def tag(r):
        if r.get("n", 0) == 0:
            return r.get("statut") or "VIDE"
        if r["n"] < N_MIN_RAPPORT:
            return "N_TROP_FAIBLE"
        if not r["fdr"]:
            return "BRUIT"
        if r["etage"] == "2" and r["delta"] > 0 and r["n"] >= N_MIN_VERDICT and r["saisons_pos"] >= max(2, int(np.ceil(2 * r["saisons_tot"] / 3))):
            return "CANDIDAT_VALIDE_E2"
        if r["n"] >= N_MIN_VERDICT:
            return "SIGNAL_" + ("E2" if r["etage"] != "1" else "E1")
        return "INTERESSANT_N_INSUFFISANT"
    res["verdict"] = res.apply(tag, axis=1)
    return res


def rapport_markdown(res, chemin, meta, famille="VAGUE1"):
    lignes = [f"# RAPPORT {famille} — Robin des Stades NG",
              "", f"_Genere le {pd.Timestamp.now():%Y-%m-%d %H:%M}_", "",
              f"**Perimetre** : {meta['n_matchs']} matchs · {meta['n_ligues']} ligues · "
              f"saisons {meta['saisons']} · holdout exclu : {meta['holdout']} ({meta['n_holdout_exclus']} matchs scelles)",
              f"**Protocole** : FDR Benjamini-Hochberg q={meta['q_fdr']} sur {meta['n_tests']} tests · "
              f"N min rapport {N_MIN_RAPPORT} · N min verdict {N_MIN_VERDICT} · xG : {'oui' if meta['xg'] else 'non (Tier A seul)'}",
              "",
              "> AUCUN PARI REEL. Etage 2 = juge par la cloture Pinnacle de-viggee (ROI a mise plate).",
              "> Etage 2* = proba juste derivee du 1X2, prix du marche non archive (pas de ROI).",
              "> Etage 1 = lift vs taux de base ligue-saison-venue : un lift ne paie RIEN tant que le prix n'est pas battu.",
              ""]
    res = res.sort_values(["fdr", "etage", "delta"], ascending=[False, True, False])
    ordre_sections = [("CANDIDAT_VALIDE_E2", "## Candidats valides (Etage 2, FDR OK, stables)"),
                      ("SIGNAL_E2", "## Signaux Etage 2 a suivre"),
                      ("SIGNAL_E1", "## Signaux Etage 1 (lift reel, prix inconnu)"),
                      ("INTERESSANT_N_INSUFFISANT", "## Interessants mais N insuffisant"),
                      ("BRUIT", "## Bruit (FDR non passee)"),
                      ("N_TROP_FAIBLE", "## N trop faible pour juger")]
    en_tete = ("| Hypo | Marche | Et. | N | Obs % | Ref % | Δ | ROI flat | p | Saisons+ |\n"
               "|---|---|---|---|---|---|---|---|---|---|")
    for tag, titre in ordre_sections:
        bloc = res[res["verdict"] == tag]
        if not len(bloc):
            continue
        lignes += [titre, "", en_tete]
        for _, r in bloc.iterrows():
            roi = f"{r['roi']*100:+.1f}%" if pd.notna(r.get("roi")) else "—"
            lignes.append(
                f"| {r['id']} {r['nom']} | {r['marche']} | {r['etage']} | {int(r['n'])} "
                f"| {r['obs']*100:.1f} | {r['ref']*100:.1f} | {r['delta']*100:+.1f} pts "
                f"| {roi} | {r['p']:.4f} | {int(r['saisons_pos'])}/{int(r['saisons_tot'])} |")
        lignes.append("")
    autres = res[~res["verdict"].isin([t for t, _ in ordre_sections])]
    if len(autres):
        lignes += ["## Non evalues", ""]
        for _, r in autres.iterrows():
            lignes.append(f"- {r['id']} {r['nom']} : {r['verdict']}")
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))


def main(data_dir="data", rapport_dir="rapports", config="config/ligues.yaml",
         spec_module="agents.vague1_spec", famille="VAGUE1"):
    import importlib
    global VAGUE1
    mod = importlib.import_module(spec_module)
    VAGUE1 = getattr(mod, "VAGUE1", None) or getattr(mod, "VAGUE1B")
    cfg = charger_config(config)
    q_fdr = float(cfg.get("q_fdr", 0.10))
    matchs, feats, holdout, n_exclus = preparer(data_dir, cfg)
    xg_dispo = feats.attrs.get("xg_dispo", False)
    atomes = [c for c in feats.columns if c.isupper()]
    feats = vue_adverse(feats, atomes)
    feats = calcul_issues_et_prix(feats)
    bases = taux_de_base(feats)
    res = evaluer(feats, bases, xg_dispo)
    n_tests = int((res["n"] >= N_MIN_RAPPORT).sum())
    res = verdicts(res, q_fdr)
    meta = dict(n_matchs=len(matchs), n_ligues=matchs["league"].nunique(),
                saisons=f"{matchs['season'].min()} → {matchs['season'].max()}",
                holdout=sorted(holdout), n_holdout_exclus=n_exclus,
                q_fdr=q_fdr, n_tests=n_tests, xg=xg_dispo)
    os.makedirs(rapport_dir, exist_ok=True)
    res.to_csv(os.path.join(rapport_dir, f"resultats_{famille.lower()}.csv"), index=False)
    rapport_markdown(res, os.path.join(rapport_dir, f"RAPPORT_{famille}.md"), meta, famille)
    print(f"[backtest] {len(res)} lignes evaluees, {n_tests} tests en famille FDR, "
          f"{int(res['fdr'].sum())} passent la FDR q={q_fdr}")
    print(f"[backtest] rapport -> {rapport_dir}/RAPPORT_{famille}.md")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rapport", default="rapports")
    ap.add_argument("--config", default="config/ligues.yaml")
    ap.add_argument("--spec", default="agents.vague1_spec")
    ap.add_argument("--famille", default="VAGUE1")
    a = ap.parse_args()
    main(a.data, a.rapport, a.config, a.spec, a.famille)
