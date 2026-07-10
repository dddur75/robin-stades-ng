"""AGENT VAGUE 2 — exploration combinatoire machine (protocole config/vague2.yaml).
Grammaire : mono | duo (self x adv, self x self, self x match, adv x match)
            | trio (self x adv x match).
Etage 1 uniquement : lift vs taux de base ligue-saison-venue.
Les survivants FDR forment le STOCK a confronter aux prix de l'archive maison.
"""
import argparse, os, sys, itertools
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.agent_backtest import preparer, vue_adverse, calcul_issues_et_prix, taux_de_base, charger_config
from moteur.stats import p_value_bilaterale, benjamini_hochberg


def preparer_matrices(feats, cfg2, bases):
    self_at = [a for a in cfg2["atomes_self"] if a in feats.columns]
    adv_at = ["adv_" + a for a in cfg2["atomes_self"] if "adv_" + a in feats.columns]
    match_at = [a for a in cfg2["atomes_match"] if a in feats.columns]
    S = feats[self_at].fillna(False).to_numpy(dtype=bool)
    A = feats[adv_at].fillna(False).to_numpy(dtype=bool)
    M = feats[match_at].fillna(False).to_numpy(dtype=bool)
    tokens = [t for t in cfg2["marches_cibles"] if "iss__" + t in feats.columns]
    ISS, BASE, VALID = {}, {}, {}
    for t in tokens:
        col = feats["iss__" + t]
        VALID[t] = col.notna().to_numpy()
        ISS[t] = col.fillna(False).to_numpy(dtype=bool)
        b = feats.merge(bases[t], on=["league", "season", "side"], how="left")["base"]
        BASE[t] = b.fillna(b.mean()).to_numpy(dtype=float)
    saisons = sorted(feats["season"].unique())
    k = max(1, len(saisons) // 3)
    blocs = {s: min(i // k, 2) for i, s in enumerate(saisons)}
    TIER = feats["season"].map(blocs).to_numpy()
    return (self_at, adv_at, match_at), (S, A, M), tokens, ISS, BASE, VALID, TIER


def generer_combos(noms, mats):
    (self_at, adv_at, match_at), (S, A, M) = noms, mats
    ns, na, nm = S.shape[1], A.shape[1], M.shape[1]
    for i in range(ns):
        yield (self_at[i],), S[:, i]
    for j in range(na):
        yield (adv_at[j],), A[:, j]
    for k in range(nm):
        yield (match_at[k],), M[:, k]
    for i in range(ns):
        si = S[:, i]
        for j in range(na):
            yield (self_at[i], adv_at[j]), si & A[:, j]
        for k in range(nm):
            yield (self_at[i], match_at[k]), si & M[:, k]
    for i, i2 in itertools.combinations(range(ns), 2):
        yield (self_at[i], self_at[i2]), S[:, i] & S[:, i2]
    for j in range(na):
        aj = A[:, j]
        for k in range(nm):
            yield (adv_at[j], match_at[k]), aj & M[:, k]
    for i in range(ns):
        si = S[:, i]
        for j in range(na):
            sij = si & A[:, j]
            if sij.sum() < 200:   # elagage precoce du trio
                continue
            for k in range(nm):
                yield (self_at[i], adv_at[j], match_at[k]), sij & M[:, k]


def main(data_dir="data", rapport_dir="rapports", config="config/ligues.yaml",
         config_v2="config/vague2.yaml"):
    cfg = charger_config(config)
    with open(config_v2, encoding="utf-8") as f:
        cfg2 = yaml.safe_load(f)
    n_min = int(cfg2["n_min"]); q = float(cfg2["q_fdr"])
    matchs, feats, holdout, _ = preparer(data_dir, cfg)
    atomes = [c for c in feats.columns if c.isupper()]
    feats = vue_adverse(feats, atomes)
    feats = calcul_issues_et_prix(feats)
    bases = taux_de_base(feats)
    noms, mats, tokens, ISS, BASE, VALID, TIER = preparer_matrices(feats, cfg2, bases)

    resultats, n_combos, n_tests = [], 0, 0
    for combo, mask in generer_combos(noms, mats):
        n_combos += 1
        if mask.sum() < n_min:
            continue
        for t in tokens:
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
            # coherence walk-forward (3 blocs chronologiques)
            coh = 0; blocs_evalues = 0
            for b in range(3):
                mb = m & (TIER == b)
                nb = int(mb.sum())
                if nb < 50:
                    continue
                blocs_evalues += 1
                db = ISS[t][mb].mean() - BASE[t][mb].mean()
                if np.sign(db) == np.sign(delta) and db != 0:
                    coh += 1
            resultats.append(dict(
                combo=" x ".join(combo), profondeur=len(combo), marche=t, n=n,
                obs=hits / n, ref=mu / n, delta=delta,
                z=z, p=p_value_bilaterale(z), blocs_coherents=coh, blocs=blocs_evalues))
    res = pd.DataFrame(resultats)
    if len(res):
        res["fdr"] = benjamini_hochberg(res["p"].to_numpy(), q=q)
        seuil = np.minimum(int(cfg2["tiers_coherents_min"]), res["blocs"].to_numpy())
        res["stable"] = res["blocs_coherents"].to_numpy() >= np.maximum(seuil, 1)
    os.makedirs(rapport_dir, exist_ok=True)
    res.to_csv(os.path.join(rapport_dir, "resultats_vague2.csv"), index=False)
    survivants = res[(res.get("fdr", False)) & (res.get("stable", False))].copy() if len(res) else res
    survivants = survivants.reindex(survivants["delta"].abs().sort_values(ascending=False).index)
    lignes = ["# RAPPORT VAGUE 2 — recherche machine (Etage 1 exotiques)", "",
              f"_Genere le {pd.Timestamp.now():%Y-%m-%d %H:%M}_", "",
              f"**Espace explore** : {n_combos} combinaisons · {n_tests} tests valides (N>={n_min}) · "
              f"FDR BH q={q} · holdout exclu : {sorted(holdout)}",
              f"**Survivants (FDR + stabilite {cfg2['tiers_coherents_min']}/3 blocs)** : {len(survivants)}",
              "",
              "> Ces signaux battent le TAUX DE BASE, pas encore un PRIX.",
              "> Ils forment le stock d'hypotheses a confronter a l'archive maison des cotes.",
              "> Un delta negatif = signal sur le complementaire du marche.", "",
              "| Combo | Marche | N | Obs % | Ref % | Δ | p | Blocs |", "|---|---|---|---|---|---|---|---|"]
    for _, r in survivants.head(200).iterrows():
        lignes.append(f"| {r['combo']} | {r['marche']} | {int(r['n'])} | {r['obs']*100:.1f} "
                      f"| {r['ref']*100:.1f} | {r['delta']*100:+.1f} pts | {r['p']:.2e} "
                      f"| {int(r['blocs_coherents'])}/{int(r['blocs'])} |")
    with open(os.path.join(rapport_dir, "RAPPORT_VAGUE2.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))
    print(f"[vague2] {n_combos} combos, {n_tests} tests, {len(survivants)} survivants "
          f"-> {rapport_dir}/RAPPORT_VAGUE2.md")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rapport", default="rapports")
    ap.add_argument("--v1", action="store_true", help="forcer l'ancienne famille v1 (reference ligue)")
    a = ap.parse_args()
    if not a.v1 and os.path.exists("config/vague2b.yaml"):
        print("[vague2] famille 2B detectee (reference ajustee) — delegation a agent_vague2b")
        from agents.agent_vague2b import main as main_2b
        main_2b(a.data, a.rapport)
    else:
        main(a.data, a.rapport)
