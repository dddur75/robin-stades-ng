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
