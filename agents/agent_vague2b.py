"""AGENT VAGUE 2B — recherche machine a REFERENCE AJUSTEE (config/vague2b.yaml).

Difference fondamentale avec la v1 : le taux de reference d'une ligne n'est plus
la moyenne de la ligue mais la moyenne des matchs COMPARABLES (meme bucket de
force 1X2, meme bucket de tempo O2.5, meme venue). Ce que le prix principal
explique deja disparait ; ne survit que l'orthogonal au prix.

Grammaire canonique (zero doublon) :
- mono self ; mono match (evalue au niveau MATCH, marches neutres seulement)
- duo self+self (paires non ordonnees) ; duo self x adv (ordonne pour les marches
  SELF, non ordonne pour les neutres) ; duo self x match
- trio self x adv x match (meme regle d'ordre)
Les monos/duos 'adv' et les marches *_ADV sont des miroirs : exclus par construction.
"""
import argparse, os, sys, itertools
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.agent_backtest import preparer, vue_adverse, calcul_issues_et_prix, charger_config
from moteur.stats import p_value_bilaterale, benjamini_hochberg


def assigner_cellules(feats, cfg2):
    pf = feats["fair__WIN_SELF"].astype(float)
    pt = feats["fair__O25"].astype(float)
    fb = pd.cut(pf, bins=cfg2["buckets_force"], labels=False, include_lowest=True)
    tb = pd.cut(pt, bins=cfg2["buckets_tempo"], labels=False, include_lowest=True)
    tb = tb.where(pt.notna(), other=-1)  # bucket NA = tempo inconnu
    venue = (feats["side"] == "home").astype(int)
    cellule = fb * 100 + (tb + 1) * 10 + venue
    cellule = cellule.where(fb.notna())
    return cellule, pf.notna()


def references(feats, tokens, cellule, cfg2):
    """Par marche : reference AJUSTEE (moyenne de cellule) + reference BRUTE
    (ligue-saison-venue, pour la pedagogie du rapport)."""
    BASE_ADJ, BASE_BRUT, ISS, VALID = {}, {}, {}, {}
    cmin = int(cfg2["cellule_min"])
    for t in tokens:
        col = feats["iss__" + t]
        ok = col.notna() & cellule.notna()
        VALID[t] = ok.to_numpy()
        ISS[t] = col.fillna(False).to_numpy(dtype=bool)
        d = pd.DataFrame({"c": cellule, "y": col.astype(float), "v": feats["side"],
                          "l": feats["league"], "s": feats["season"]})[ok]
        moy_cell = d.groupby("c")["y"].agg(["mean", "size"])
        moy_venue = d.groupby("v")["y"].mean()
        rep = cellule.map(moy_cell["mean"])
        petits = cellule.map(moy_cell["size"]).fillna(0) < cmin
        rep = rep.where(~petits, feats["side"].map(moy_venue))
        BASE_ADJ[t] = rep.to_numpy(dtype=float)
        brut = d.groupby(["l", "s", "v"])["y"].transform("mean")
        BASE_BRUT[t] = pd.Series(brut, index=d.index).reindex(feats.index).to_numpy(dtype=float)
    return BASE_ADJ, BASE_BRUT, ISS, VALID


def generer(feats, cfg2):
    """Genere (nom_combo, mask, liste_marches) sans doublon miroir/complement."""
    sa = [a for a in cfg2["atomes_self"] if a in feats.columns]
    ma = [a for a in cfg2["atomes_match"] if a in feats.columns]
    S = {a: feats[a].fillna(False).to_numpy(dtype=bool) for a in sa}
    A = {a: feats["adv_" + a].fillna(False).to_numpy(dtype=bool)
         for a in sa if "adv_" + a in feats.columns}
    M = {a: feats[a].fillna(False).to_numpy(dtype=bool) for a in ma}
    home = (feats["side"] == "home").to_numpy()
    T_SELF = cfg2["marches_canoniques"]["self"]
    T_NEUT = cfg2["marches_canoniques"]["neutres"]
    TOUS = T_SELF + T_NEUT

    for a in sa:                                  # mono self
        yield (a,), S[a], TOUS
    for m in ma:                                  # mono match -> niveau match
        yield (m,), M[m] & home, T_NEUT
    for a, b in itertools.combinations(sa, 2):    # duo self+self
        yield (a, b), S[a] & S[b], TOUS
    idx = {a: i for i, a in enumerate(sa)}
    for a in sa:                                  # duo self x adv
        for b in sa:
            if b not in A:
                continue
            mk = S[a] & A[b]
            toks = list(T_SELF) + (T_NEUT if idx[a] <= idx[b] else [])
            yield (a, "adv_" + b), mk, toks
    for a in sa:                                  # duo self x match
        for m in ma:
            yield (a, m), S[a] & M[m], TOUS
    for a in sa:                                  # trio self x adv x match
        for b in sa:
            if b not in A:
                continue
            sab = S[a] & A[b]
            if sab.sum() < 200:
                continue
            toks = list(T_SELF) + (T_NEUT if idx[a] <= idx[b] else [])
            for m in ma:
                yield (a, "adv_" + b, m), sab & M[m], toks


def main(data_dir="data", rapport_dir="rapports", config="config/ligues.yaml",
         config_v2="config/vague2b.yaml"):
    cfg = charger_config(config)
    with open(config_v2, encoding="utf-8") as f:
        cfg2 = yaml.safe_load(f)
    n_min = int(cfg2["n_min"]); q = float(cfg2["q_fdr"])
    dmin = float(cfg2["delta_min_rapport"])
    matchs, feats, holdout, _ = preparer(data_dir, cfg)
    atomes = [c for c in feats.columns if c.isupper()]
    feats = vue_adverse(feats, atomes)
    feats = calcul_issues_et_prix(feats).reset_index(drop=True)
    cellule, force_ok = assigner_cellules(feats, cfg2)
    tokens = cfg2["marches_canoniques"]["self"] + cfg2["marches_canoniques"]["neutres"]
    tokens = [t for t in tokens if "iss__" + t in feats.columns]
    BASE, BRUT, ISS, VALID = references(feats, tokens, cellule, cfg2)
    saisons = sorted(feats["season"].unique())
    k = max(1, len(saisons) // 3)
    TIER = feats["season"].map({s: min(i // k, 2) for i, s in enumerate(saisons)}).to_numpy()
    pct_sans_ref = 100 * (1 - force_ok.mean())

    res, n_combos, n_tests = [], 0, 0
    for combo, mask, toks in generer(feats, cfg2):
        n_combos += 1
        if mask.sum() < n_min:
            continue
        for t in toks:
            if t not in ISS:
                continue
            m = mask & VALID[t]
            n = int(m.sum())
            if n < n_min:
                continue
            n_tests += 1
            hits = int(ISS[t][m].sum())
            p_arr = BASE[t][m]
            mu, var = p_arr.sum(), (p_arr * (1 - p_arr)).sum()
            if var <= 0:
                continue
            z = (hits - mu) / np.sqrt(var)
            delta = hits / n - mu / n
            brut_arr = BRUT[t][m]
            delta_brut = hits / n - np.nanmean(brut_arr)
            coh = 0; blocs = 0
            for b in range(3):
                mb = m & (TIER == b)
                if mb.sum() < 50:
                    continue
                blocs += 1
                db = ISS[t][mb].mean() - BASE[t][mb].mean()
                if db != 0 and np.sign(db) == np.sign(delta):
                    coh += 1
            res.append(dict(combo=" x ".join(combo), profondeur=len(combo), marche=t,
                            n=n, obs=hits / n, ref_aj=mu / n, delta=delta,
                            delta_brut=delta_brut, z=z, p=p_value_bilaterale(z),
                            blocs_coherents=coh, blocs=blocs))
    res = pd.DataFrame(res)
    if len(res):
        res["fdr"] = benjamini_hochberg(res["p"].to_numpy(), q=q)
        seuil = np.minimum(int(cfg2["tiers_coherents_min"]), res["blocs"].to_numpy())
        res["stable"] = res["blocs_coherents"].to_numpy() >= np.maximum(seuil, 1)
        res["reportable"] = res["fdr"] & res["stable"] & (res["delta"].abs() >= dmin)
    os.makedirs(rapport_dir, exist_ok=True)
    res.to_csv(os.path.join(rapport_dir, "resultats_vague2b.csv"), index=False)
    surv = res[res["reportable"]].copy() if len(res) else res
    surv = surv.reindex(surv["delta"].abs().sort_values(ascending=False).index)
    lignes = ["# RAPPORT VAGUE 2B — recherche machine, reference AJUSTEE", "",
              f"_Genere le {pd.Timestamp.now():%Y-%m-%d %H:%M}_", "",
              f"**Espace** : {n_combos} combinaisons canoniques · {n_tests} tests (N>={n_min}) · "
              f"FDR q={q} · seuil rapport |Δaj|>={dmin*100:.0f} pts · holdout : {sorted(holdout)}",
              f"**Reference** : buckets force x tempo x venue (probas de cloture de-viggees) · "
              f"lignes sans cote exploitable exclues : {pct_sans_ref:.1f}%",
              f"**Survivants reportables** : {len(surv)}",
              "",
              "> Δ ajuste = ecart aux matchs COMPARABLES (meme force, meme tempo, meme venue).",
              "> Δ brut = l'ancien calcul v1 (vs moyenne de ligue) — affiche pour voir l'artefact.",
              "> Un Δ ajuste ~0 avec un Δ brut enorme = le prix principal savait deja.", "",
              "| Combo | Marche | N | Obs % | Ref aj. % | Δ ajuste | Δ brut (v1) | p | Blocs |",
              "|---|---|---|---|---|---|---|---|---|"]
    for _, r in surv.head(150).iterrows():
        lignes.append(f"| {r['combo']} | {r['marche']} | {int(r['n'])} | {r['obs']*100:.1f} "
                      f"| {r['ref_aj']*100:.1f} | {r['delta']*100:+.1f} pts | {r['delta_brut']*100:+.1f} pts "
                      f"| {r['p']:.1e} | {int(r['blocs_coherents'])}/{int(r['blocs'])} |")
    with open(os.path.join(rapport_dir, "RAPPORT_VAGUE2B.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))
    print(f"[vague2b] {n_combos} combos, {n_tests} tests, {len(surv)} reportables "
          f"-> {rapport_dir}/RAPPORT_VAGUE2B.md")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rapport", default="rapports")
    a = ap.parse_args()
    main(a.data, a.rapport)
