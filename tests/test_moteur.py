"""Tests du moteur sur donnees SYNTHETIQUES avec effet implante.
Prouve : (1) zero lookahead, (2) le classement point-in-time est exact,
(3) un vrai lift Etage 1 ne fabrique PAS d'edge Etage 2 quand le prix est efficient."""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from moteur.features import construire, _serie_avant
from moteur.devig import probas_justes
from moteur.classement import passe_enjeu


# ---------- generateur synthetique ----------
def _calendrier(equipes):
    n = len(equipes)
    rounds = []
    rot = equipes[1:]
    for _ in range(n - 1):
        paires = [(equipes[0], rot[-1])] + [(rot[i], rot[-2 - i]) for i in range(n // 2 - 1)]
        rounds.append(paires)
        rot = rot[1:] + rot[:1]
    return rounds + [[(b, a) for a, b in r] for r in rounds]


def _poisson_matrix(lh, la, kmax=9):
    from math import exp, factorial
    ph = np.array([exp(-lh) * lh**k / factorial(k) for k in range(kmax)])
    pa = np.array([exp(-la) * la**k / factorial(k) for k in range(kmax)])
    return np.outer(ph, pa)


def genere(seed=7, saisons=("2019-20", "2020-21", "2021-22", "2022-23"), n_eq=16):
    rng = np.random.default_rng(seed)
    equipes = [f"T{i:02d}" for i in range(1, n_eq + 1)]
    att = rng.lognormal(0, 0.18, n_eq); dfc = rng.lognormal(0, 0.18, n_eq)
    arbitres = [f"REF{i:02d}" for i in range(1, 13)]
    severes = {"REF01", "REF02"}
    derby = ("T01", "T02")
    lignes = []
    for si, saison in enumerate(saisons):
        streak = {e: 0 for e in equipes}
        d0 = pd.Timestamp(f"{2019 + si}-08-10")
        for ri, rnd in enumerate(_calendrier(equipes)):
            date = d0 + pd.Timedelta(days=7 * ri)
            for h, a in rnd:
                ih, ia = equipes.index(h), equipes.index(a)
                mh = (0.65 if streak[h] >= 4 else 1.0)   # EFFET IMPLANTE
                ma = (0.65 if streak[a] >= 4 else 1.0)
                lh = 1.45 * att[ih] * dfc[ia] * mh * (1.35 if streak[a] >= 4 else 1.0)
                la = 1.15 * att[ia] * dfc[ih] * ma * (1.35 if streak[h] >= 4 else 1.0)
                gh, ga = rng.poisson(lh), rng.poisson(la)
                M = _poisson_matrix(lh, la)
                p1 = np.tril(M, -1).sum(); px = np.trace(M); p2 = np.triu(M, 1).sum()
                po25 = 1 - (M[0, 0] + M[1, 0] + M[0, 1] + M[1, 1] + M[2, 0] + M[0, 2])
                marge = 1.06
                psch, pscd, psca = 1 / (p1 * marge), 1 / (px * marge), 1 / (p2 * marge)
                bruit = rng.normal(1, 0.02, 3)
                ref = rng.choice(arbitres)
                base_cartons = 1.7 + (1.2 if ref in severes else 0) + (1.0 if {h, a} == set(derby) else 0)
                hy, ay = rng.poisson(base_cartons), rng.poisson(base_cartons)
                hthg = sum(rng.random() < 0.45 for _ in range(gh))
                htag = sum(rng.random() < 0.45 for _ in range(ga))
                lignes.append(dict(
                    league="XX", season=saison, date=date, home=h, away=a,
                    fthg=gh, ftag=ga, hthg=hthg, htag=htag, referee=ref,
                    hy=hy, ay=ay, hr=0, ar=0, hc=rng.poisson(5), ac=rng.poisson(4),
                    psh=psch * bruit[0], psd=pscd * bruit[1], psa=psca * bruit[2],
                    psch=psch, pscd=pscd, psca=psca,
                    p_o25=1 / (po25 * 1.05), p_u25=1 / ((1 - po25) * 1.05),
                    pc_o25=1 / (po25 * 1.05), pc_u25=1 / ((1 - po25) * 1.05),
                ))
                # maj streaks (comme le reel : apres le match)
                if gh > ga: streak[h] = 0; streak[a] += 1
                elif ga > gh: streak[a] = 0; streak[h] += 1
                else: streak[h] += 1; streak[a] += 1
    df = pd.DataFrame(lignes).sort_values("date").reset_index(drop=True)
    df["match_id"] = df["league"] + "_" + df["season"] + "_" + df.groupby(["league", "season"]).cumcount().astype(str)
    return df


# ---------- tests unitaires ----------
def test_serie_avant():
    assert list(_serie_avant(np.array([True, True, False, True, True, True]))) == [0, 1, 2, 0, 1, 2]


def test_devig():
    p = probas_justes([2.10, 3.40, 3.60])
    assert abs(p.sum() - 1) < 1e-9 and p[0] > p[1] > 0


def test_enjeu_relegation_math():
    lignes = []
    equipes = ["A", "B", "C", "D"]
    d = pd.Timestamp("2022-01-01"); k = 0
    for tour in range(2):
        for i in range(4):
            for j in range(i + 1, 4):
                h, a = (equipes[i], equipes[j]) if tour == 0 else (equipes[j], equipes[i])
                gh, ga = (2, 0) if h != "D" else (0, 2)   # D perd tout
                lignes.append(dict(match_id=f"m{k}", date=d, home=h, away=a, fthg=gh, ftag=ga))
                d += pd.Timedelta(days=7); k += 1
    df = pd.DataFrame(lignes)
    etats = passe_enjeu(df, {"releg_spots": 1, "promo_spots": 0, "europe_spots": 1})
    dern = [etats[m["match_id"]]["home" if m["home"] == "D" else "away"]
            for _, m in df.iterrows() if "D" in (m["home"], m["away"])]
    assert dern[-1]["RELEGUE_MATH"], "D doit etre mathematiquement relegue avant son dernier match"
    assert not dern[0]["RELEGUE_MATH"]


def test_anti_lookahead():
    df = genere()
    derbys = {frozenset(("T01", "T02"))}
    zones = {"XX": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}
    f1 = construire(df.copy(), derbys=derbys, zones_par_ligue=zones)
    cible = df[df["season"] == "2022-23"].iloc[40]["match_id"]
    d0 = df.loc[df["match_id"] == cible, "date"].iloc[0]
    df2 = df.copy()
    futur = df2["date"] > d0
    df2.loc[futur, ["fthg", "ftag", "hthg", "htag"]] = [9, 0, 5, 0]
    df2.loc[futur, ["psch", "pscd", "psca"]] = [1.11, 9.0, 21.0]
    f2 = construire(df2, derbys=derbys, zones_par_ligue=zones)
    atomes = [c for c in f1.columns if c.isupper()]
    a1 = f1[f1["match_id"] == cible].sort_values("side")[atomes].reset_index(drop=True)
    a2 = f2[f2["match_id"] == cible].sort_values("side")[atomes].reset_index(drop=True)
    pd.testing.assert_frame_equal(a1, a2)


def test_lift_reel_mais_edge_nul(tmp_path):
    """Le coeur doctrinal : SERIE_SANS_V a un VRAI effet (implante) ->
    lift Etage 1 significatif ; mais le prix synthetique connait l'effet ->
    edge Etage 2 ~ 0. Battre le taux de base != battre le prix."""
    import yaml
    df = genere()
    (tmp_path / "data").mkdir()
    df.to_parquet(tmp_path / "data" / "matches.parquet", index=False)
    cfg = dict(saisons=[], holdout_seasons=[], q_fdr=0.10,
               ligues={"XX": {"nom": "Synth", "zones": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}})
    (tmp_path / "config").mkdir()
    with open(tmp_path / "config" / "ligues.yaml", "w") as f:
        yaml.dump(cfg, f)
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        sys.path.insert(0, cwd)
        from agents.agent_backtest import main
        res = main(data_dir="data", rapport_dir="rapports", config="config/ligues.yaml")
    finally:
        os.chdir(cwd)
    s6 = res[(res["id"] == "S006") & (res["marche"] == "WIN_ADV")].iloc[0]
    assert s6["n"] > 200
    # Etage 2 : pas d'edge exploitable face a un prix qui connait l'effet
    assert abs(s6["delta"]) < 0.03, f"edge E2 devrait etre ~0, obtenu {s6['delta']:.3f}"
    assert abs(s6["roi"]) < 0.08
    # Etage 1 : le lift existe bel et bien (verification directe)
    from moteur.features import construire as C
    fx = C(df, derbys=set(), zones_par_ligue={"XX": cfg["ligues"]["XX"]["zones"]})
    base = fx["win"].mean()
    lift = fx.loc[fx["SERIE_SANS_V"], "win"].mean() - fx.loc[~fx["SERIE_SANS_V"], "win"].mean()
    assert lift < -0.05, f"le malus implante doit se voir en E1 (obtenu {lift:.3f})"
    assert (tmp_path / "rapports" / "RAPPORT_VAGUE1.md").exists()


def test_vague2_trouve_arbitre(tmp_path):
    """La recherche machine doit retrouver l'effet arbitre implante (cartons)."""
    import yaml, shutil
    df = genere()
    (tmp_path / "data").mkdir(); (tmp_path / "config").mkdir()
    df.to_parquet(tmp_path / "data" / "matches.parquet", index=False)
    cfg = dict(saisons=[], holdout_seasons=[], q_fdr=0.10,
               ligues={"XX": {"nom": "Synth", "zones": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}})
    yaml.dump(cfg, open(tmp_path / "config" / "ligues.yaml", "w"))
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v2 = yaml.safe_load(open(os.path.join(racine, "config", "vague2.yaml")))
    v2["n_min"] = 80
    yaml.dump(v2, open(tmp_path / "config" / "vague2.yaml", "w"))
    cwd = os.getcwd(); os.chdir(tmp_path)
    try:
        from agents.agent_vague2 import main as v2main
        res = v2main(data_dir="data", rapport_dir="rapports",
                     config="config/ligues.yaml", config_v2="config/vague2.yaml")
    finally:
        os.chdir(cwd)
    hits = res[(res["combo"].str.contains("ARBITRE_SEVERE")) & (res["marche"] == "O45_CARTONS") & res["fdr"]]
    assert len(hits) >= 1, "l'effet arbitre implante doit survivre a la FDR"
    assert (tmp_path / "rapports" / "RAPPORT_VAGUE2.md").exists()


def test_vague1b_famille_separee(tmp_path):
    """La famille annexe 1B tourne avec son propre rapport."""
    import yaml
    df = genere()
    (tmp_path / "data").mkdir(); (tmp_path / "config").mkdir()
    df.to_parquet(tmp_path / "data" / "matches.parquet", index=False)
    cfg = dict(saisons=[], holdout_seasons=[], q_fdr=0.10,
               ligues={"XX": {"nom": "Synth", "zones": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}})
    yaml.dump(cfg, open(tmp_path / "config" / "ligues.yaml", "w"))
    cwd = os.getcwd(); os.chdir(tmp_path)
    try:
        from agents.agent_backtest import main as btmain
        res = btmain(data_dir="data", rapport_dir="rapports", config="config/ligues.yaml",
                     spec_module="agents.vague1b_spec", famille="VAGUE1B")
    finally:
        os.chdir(cwd)
    assert (tmp_path / "rapports" / "RAPPORT_VAGUE1B.md").exists()
    assert set(res["id"]) == {"HC-26", "HC-27", "S038b"}


def test_vague2b_reference_ajustee(tmp_path):
    """Le coeur du fix 2B : la reference par buckets doit TUER les artefacts de
    force (le prix savait) et GARDER l'effet arbitre (orthogonal au prix)."""
    import yaml
    df = genere()
    (tmp_path / "data").mkdir(); (tmp_path / "config").mkdir()
    df.to_parquet(tmp_path / "data" / "matches.parquet", index=False)
    cfg = dict(saisons=[], holdout_seasons=[], q_fdr=0.10,
               ligues={"XX": {"nom": "Synth", "zones": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}})
    yaml.dump(cfg, open(tmp_path / "config" / "ligues.yaml", "w"))
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    v2b = yaml.safe_load(open(os.path.join(racine, "config", "vague2b.yaml")))
    v2b["n_min"] = 80
    v2b["cellule_min"] = 40
    yaml.dump(v2b, open(tmp_path / "config" / "vague2b.yaml", "w"))
    cwd = os.getcwd(); os.chdir(tmp_path)
    try:
        from agents.agent_vague2b import main as v2bmain
        res = v2bmain(data_dir="data", rapport_dir="rapports",
                      config="config/ligues.yaml", config_v2="config/vague2b.yaml")
    finally:
        os.chdir(cwd)
    # 1. L'artefact de force est tue : SERIE_VICTOIRES x TEAM_O15_SELF avait un
    #    delta brut enorme ; ajuste, il doit s'effondrer.
    sv = res[(res["combo"] == "SERIE_VICTOIRES") & (res["marche"] == "TEAM_O15_SELF")]
    if len(sv):
        assert abs(sv.iloc[0]["delta"]) < 0.07, f"delta ajuste devrait ~0, obtenu {sv.iloc[0]['delta']:.3f}"
        assert abs(sv.iloc[0]["delta_brut"]) > abs(sv.iloc[0]["delta"]), "l'ajustement doit reduire le delta"
    # 2. L'effet arbitre (orthogonal au prix 1X2/O2.5) survit.
    arb = res[(res["combo"].str.contains("ARBITRE_SEVERE")) & (res["marche"] == "O45_CARTONS") & res["fdr"]]
    assert len(arb) >= 1, "l'effet arbitre doit survivre a la reference ajustee"
    # 3. Zero doublon : chaque (combo, marche) apparait une seule fois.
    assert not res.duplicated(subset=["combo", "marche"]).any()
    # 4. Aucun marche *_ADV ni complementaire dans les resultats.
    assert not res["marche"].str.endswith("_ADV").any()
    assert not res["marche"].isin(["TEAM_U15_SELF", "U05_MT1"]).any()
    assert (tmp_path / "rapports" / "RAPPORT_VAGUE2B.md").exists()


def test_confrontation_e2e(tmp_path):
    """Bout-en-bout du juge en DEUX runs (protocole prospectif) :
    run 1 avant les matchs -> journalisation des signaux aux prix captures ;
    run 2 apres -> reglement du match joue, a la ligne capturee."""
    import yaml
    from datetime import timedelta
    df = genere()
    racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    (tmp_path / "data" / "archive").mkdir(parents=True)
    (tmp_path / "config").mkdir(); (tmp_path / "rapports").mkdir()
    df.to_parquet(tmp_path / "data" / "matches.parquet", index=False)
    cfg = dict(saisons=[], holdout_seasons=[], q_fdr=0.10,
               ligues={"XX": {"nom": "Synth", "zones": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}})
    yaml.dump(cfg, open(tmp_path / "config" / "ligues.yaml", "w"))
    yaml.dump({"sports": {"XX": "soccer_xx"}}, open(tmp_path / "config" / "archive.yaml", "w"))
    (tmp_path / "config" / "candidats_prix.yaml").write_text(
        open(os.path.join(racine, "config", "candidats_prix.yaml")).read())
    yaml.dump({"XX": [["T01", "T02"]]}, open(tmp_path / "config" / "derbys.yaml", "w"))
    passe = df[(df["home"] == "T01") & (df["away"] == "T02")].iloc[-1]
    t_passe = pd.Timestamp(passe["date"]).tz_localize("UTC")
    t_futur = (df["date"].max() + pd.Timedelta(days=3)).tz_localize("UTC")
    lignes = []
    for eid, commence in [("EVFUTUR", t_futur), ("EVPASSE", t_passe)]:
        for book, over, under in [("pinnacle", 1.85, 1.95), ("winamax_fr", 1.90, 1.86)]:
            for outcome, price in [("Over", over), ("Under", under)]:
                lignes.append(dict(snapshot_ts="2026-01-01T00:00:00", phase="CLOSE",
                                   event_id=eid, sport_key="soccer_xx",
                                   commence_time=commence.isoformat(),
                                   home="T01", away="T02", bookmaker=book,
                                   market="alternate_totals_cards", outcome=outcome,
                                   point=4.5, price=price, description=None))
    pd.DataFrame(lignes).to_parquet(tmp_path / "data" / "archive" / "odds_2026-01.parquet", index=False)
    cwd = os.getcwd(); os.chdir(tmp_path)
    try:
        from agents.agent_confrontation import main as cmain
        now1 = (t_passe - pd.Timedelta(days=2)).to_pydatetime()
        j1 = cmain(data_dir="data", rapport_dir="rapports", maintenant=now1)
        assert (j1["event_id"] == "EVPASSE").any() and (j1["candidat"] == "CP-03").any()
        now2 = (df["date"].max().tz_localize("UTC") + pd.Timedelta(days=1)).to_pydatetime()
        j2 = cmain(data_dir="data", rapport_dir="rapports", maintenant=now2)
    finally:
        os.chdir(cwd)
    reg = j2[(j2["event_id"] == "EVPASSE") & (j2["regle"] == True) & (j2["candidat"] == "CP-03")]
    assert len(reg) >= 1, "le derby passe journalise doit etre regle au run 2"
    cartons = passe["hy"] + passe["ay"] + passe["hr"] + passe["ar"]
    attendu = cartons > 4.5
    r = reg.iloc[0]
    assert bool(r["issue"]) == bool(attendu)
    assert abs(r["gain_pin"] - ((1.85 - 1) if attendu else -1.0)) < 1e-9
    assert abs(r["juste_pinnacle"] - (1/1.85) / (1/1.85 + 1/1.95)) < 1e-6
    texte = open(tmp_path / "rapports" / "RAPPORT_CONFRONTATION.md").read()
    assert "Couverture" in texte and "CP-03" in texte


def test_features_virtuelles_inoffensives():
    """Ajouter des matchs a venir (scores NaN) ne change pas les atomes des matchs passes."""
    import pandas as pd, numpy as np
    df = genere()
    derbys = {frozenset(("T01", "T02"))}
    zones = {"XX": {"releg_spots": 3, "promo_spots": 0, "europe_spots": 4}}
    f1 = construire(df.copy(), derbys=derbys, zones_par_ligue=zones)
    virt = df.iloc[-1:].copy()
    virt["match_id"] = "VIRT_test"
    virt["date"] = df["date"].max() + pd.Timedelta(days=5)
    virt["home"], virt["away"] = "T03", "T09"
    for c in ["fthg", "ftag", "hthg", "htag", "hy", "ay", "hr", "ar", "psh", "psd", "psa"]:
        virt[c] = np.nan
    f2 = construire(pd.concat([df, virt], ignore_index=True), derbys=derbys, zones_par_ligue=zones)
    cible = df.iloc[-1]["match_id"]
    atomes = [c for c in f1.columns if c.isupper()]
    a1 = f1[f1["match_id"] == cible].sort_values("side")[atomes].reset_index(drop=True)
    a2 = f2[f2["match_id"] == cible].sort_values("side")[atomes].reset_index(drop=True)
    pd.testing.assert_frame_equal(a1, a2)
    assert (f2["match_id"] == "VIRT_test").sum() == 2
