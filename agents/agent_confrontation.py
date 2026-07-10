"""AGENT CONFRONTATION — le juge final (Sprint 3).
Chaque jour :
  1. SIGNAUX : matchs a venir presents dans l'archive -> calcule les atomes
     point-in-time (memes fonctions que le backtest, lignes virtuelles) ->
     journalise les candidats pre-enregistres qui se declenchent, AVEC les prix
     captures (Pinnacle = juge, Winamax/Unibet FR = execution), a la ligne reelle.
  2. REGLEMENT : signaux passes -> issue a la ligne capturee -> edge realise vs
     proba juste Pinnacle de-viggee + ROI papier a mise plate.
  3. RAPPORT : signaux a venir, bilan par candidat, couverture de l'archive
     (l'audit "qui price quoi" est automatise ici), noms non apparies.
ZERO pari reel. Verdict par candidat : N regles >= 150.
"""
import os, re, sys, unicodedata
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.agent_backtest import charger_config, charger_derbys, vue_adverse
from moteur.features import construire
from moteur.devig import probas_justes
from moteur.stats import wilson_ci

BOOKS = ["pinnacle", "winamax_fr", "unibet_fr"]
N_VERDICT = 150
STOP_TOKENS = {"fc", "cf", "ac", "afc", "sc", "cd", "ud", "ca", "rc", "as", "1", "de"}


# ---------- appariement des noms ----------
def norm(nom):
    n = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    toks = [t for t in n.split() if t not in STOP_TOKENS]
    return " ".join(toks)


def apparier(nom_api, roster_fd, alias):
    if nom_api in alias:
        return alias[nom_api]
    na = norm(nom_api)
    ta = na.split()
    meilleur, score = None, 0.0
    for fd in roster_fd:
        nf = norm(fd)
        if na == nf:
            return fd
        tf = nf.split()
        m = sum(1 for t in ta if any(
            t == f or (len(t) >= 3 and f.startswith(t)) or (len(f) >= 3 and t.startswith(f))
            for f in tf))
        if not m:
            continue
        s = 2 * m / (len(ta) + len(tf))
        if s > score:
            meilleur, score = fd, s
    return meilleur if score >= 0.5 else None


def saison_de(date):
    y = date.year
    return f"{y}-{str(y + 1)[-2:]}" if date.month >= 7 else f"{y - 1}-{str(y)[-2:]}"


# ---------- extraction des prix ----------
def dernier_snapshot(rows):
    """Prefere la phase CLOSE, sinon le snapshot le plus recent."""
    close = rows[rows["phase"] == "CLOSE"]
    src = close if len(close) else rows
    return src[src["snapshot_ts"] == src["snapshot_ts"].max()]


def prix_pour(rows_evt, marche, ligne_cible, team_api=None):
    """Retourne {book: (cote, juste, ligne, phase)} pour le sens Over/Yes/team-Over."""
    r = rows_evt[rows_evt["market"] == marche]
    if team_api is not None and "description" in r:
        r = r[r["description"].fillna("") == team_api]
    if not len(r):
        return {}
    out = {}
    for book in BOOKS:
        rb = dernier_snapshot(r[r["bookmaker"] == book])
        if not len(rb):
            continue
        if ligne_cible is None:   # btts : Yes/No
            oui = rb[rb["outcome"].str.lower() == "yes"]["price"]
            non = rb[rb["outcome"].str.lower() == "no"]["price"]
            if len(oui) and len(non):
                p = probas_justes([float(oui.iloc[0]), float(non.iloc[0])])
                out[book] = (float(oui.iloc[0]), float(p[0]) if p is not None else None,
                             None, rb["phase"].iloc[0])
            continue
        pts = rb["point"].dropna().unique()
        if not len(pts):
            continue
        ligne = min(pts, key=lambda x: abs(float(x) - ligne_cible))
        rl = rb[rb["point"] == ligne]
        over = rl[rl["outcome"].str.lower().str.startswith("over")]["price"]
        under = rl[rl["outcome"].str.lower().str.startswith("under")]["price"]
        if len(over):
            juste = None
            if len(under):
                p = probas_justes([float(over.iloc[0]), float(under.iloc[0])])
                juste = float(p[0]) if p is not None else None
            out[book] = (float(over.iloc[0]), juste, float(ligne), rl["phase"].iloc[0])
    return out


# ---------- evaluation des candidats ----------
def cond_vraie(row, cond):
    for a in cond.get("self_", []):
        if not bool(row.get(a, False)):
            return False
    for a in cond.get("adv", []):
        if not bool(row.get("adv_" + a, False)):
            return False
    for a in cond.get("match", []):
        if not bool(row.get(a, False)):
            return False
    return True


def issue_token(token, m, ligne, team_fd):
    cartons = m["hy"] + m["ay"] + m["hr"] + m["ar"]
    ht = m["hthg"] + m["htag"]
    if token == "O45_CARTONS":
        return cartons > ligne
    if token == "TEAM_O15_SELF":
        buts = m["fthg"] if team_fd == m["home"] else m["ftag"]
        return buts > ligne
    if token == "BTTS_Y":
        return m["fthg"] > 0 and m["ftag"] > 0
    if token in ("O15_MT1", "O05_MT1"):
        return ht > ligne
    return None


# ---------- agent ----------
def main(data_dir="data", rapport_dir="rapports", maintenant=None):
    now = maintenant or datetime.now(timezone.utc)
    cfg = charger_config("config/ligues.yaml")
    with open("config/candidats_prix.yaml", encoding="utf-8") as f:
        candidats = yaml.safe_load(f)["candidats"]
    alias = {}
    if os.path.exists("config/alias_equipes.yaml"):
        with open("config/alias_equipes.yaml", encoding="utf-8") as f:
            alias = yaml.safe_load(f) or {}
    with open("config/archive.yaml", encoding="utf-8") as f:
        sport_vers_fd = {v: k for k, v in yaml.safe_load(f)["sports"].items()}

    arch_dir = os.path.join(data_dir, "archive")
    fichiers = sorted(f for f in os.listdir(arch_dir) if f.startswith("odds_")) if os.path.isdir(arch_dir) else []
    conf_dir = os.path.join(data_dir, "confrontation")
    os.makedirs(conf_dir, exist_ok=True)
    os.makedirs(rapport_dir, exist_ok=True)
    if not fichiers:
        _rapport_vide(rapport_dir, "Archive vide : verifier le secret ODDS_API_KEY et le workflow 03.")
        print("[confrontation] archive vide — rapport diagnostic ecrit")
        return None
    arch = pd.concat([pd.read_parquet(os.path.join(arch_dir, f)) for f in fichiers], ignore_index=True)
    arch["commence"] = pd.to_datetime(arch["commence_time"], utc=True)
    matchs = pd.read_parquet(os.path.join(data_dir, "matches.parquet"))
    matchs["date"] = pd.to_datetime(matchs["date"])
    roster = {lg: set(g["home"]) | set(g["away"]) for lg, g in matchs.groupby("league")}

    # -- table des evenements apparies --
    evts = arch.groupby("event_id").agg(sport_key=("sport_key", "first"), commence=("commence", "first"),
                                        home_api=("home", "first"), away_api=("away", "first")).reset_index()
    evts["league"] = evts["sport_key"].map(sport_vers_fd)
    non_apparies = []
    def _map(r):
        ro = roster.get(r["league"], set())
        h = apparier(r["home_api"], ro, alias); a = apparier(r["away_api"], ro, alias)
        if h is None or a is None:
            non_apparies.append(f"{r['league']} : {r['home_api']} vs {r['away_api']}")
        return pd.Series({"home_fd": h, "away_fd": a})
    evts = pd.concat([evts, evts.apply(_map, axis=1)], axis=1)
    evts = evts.dropna(subset=["home_fd", "away_fd", "league"])

    # -- journal existant --
    sig_path = os.path.join(conf_dir, "signaux.parquet")
    journal = pd.read_parquet(sig_path) if os.path.exists(sig_path) else pd.DataFrame()
    deja = set(zip(journal.get("event_id", []), journal.get("candidat", []),
                   journal.get("team_fd", []))) if len(journal) else set()

    # -- phase SIGNAUX : matchs a venir --
    futurs = evts[evts["commence"] > now]
    nouveaux = []
    if len(futurs):
        virt = pd.DataFrame({
            "league": futurs["league"], "season": futurs["commence"].dt.tz_localize(None).map(saison_de),
            "date": futurs["commence"].dt.tz_localize(None),
            "home": futurs["home_fd"], "away": futurs["away_fd"],
            "fthg": np.nan, "ftag": np.nan, "hthg": np.nan, "htag": np.nan, "referee": None,
            "hy": np.nan, "ay": np.nan, "hr": np.nan, "ar": np.nan, "hc": np.nan, "ac": np.nan,
            "psh": np.nan, "psd": np.nan, "psa": np.nan,
            "match_id": "VIRT_" + futurs["event_id"],
        })
        for c in matchs.columns:
            if c not in virt.columns:
                virt[c] = np.nan
        combi = pd.concat([matchs, virt[matchs.columns]], ignore_index=True)
        zones = {l: v.get("zones", {}) for l, v in cfg.get("ligues", {}).items()}
        feats = construire(combi, derbys=charger_derbys(), zones_par_ligue=zones)
        atomes = [c for c in feats.columns if c.isupper()]
        feats = vue_adverse(feats, atomes)
        fv = feats[feats["match_id"].str.startswith("VIRT_")]
        for _, ev in futurs.iterrows():
            rows = fv[fv["match_id"] == "VIRT_" + ev["event_id"]]
            rows_evt = arch[arch["event_id"] == ev["event_id"]]
            for cand in candidats:
                token_self = cand["token"] in ("TEAM_O15_SELF", "CS_SELF", "MT1_SELF", "MT2_SELF")
                sides = rows.itertuples() if token_self else list(rows.itertuples())[:1] or []
                for r in sides:
                    rd = r._asdict()
                    if not token_self:
                        # marche neutre : signal si l'UNE des deux orientations declenche
                        autres = [x._asdict() for x in rows.itertuples()]
                        if not any(cond_vraie(x, cand["cond"]) for x in autres):
                            continue
                        team_fd = ""
                    else:
                        if not cond_vraie(rd, cand["cond"]):
                            continue
                        team_fd = rd["team"]
                    cle = (ev["event_id"], cand["id"], team_fd)
                    if cle in deja:
                        continue
                    team_api = None
                    if token_self:
                        team_api = ev["home_api"] if team_fd == ev["home_fd"] else ev["away_api"]
                    prix = prix_pour(rows_evt, cand["marche_api"], cand["ligne_cible"], team_api)
                    pin = prix.get("pinnacle", (None, None, cand["ligne_cible"], None))
                    ligne = pin[2] if pin[2] is not None else next(
                        (v[2] for v in prix.values() if v[2] is not None), cand["ligne_cible"])
                    nouveaux.append(dict(
                        event_id=ev["event_id"], candidat=cand["id"], token=cand["token"],
                        league=ev["league"], commence=ev["commence"],
                        home_fd=ev["home_fd"], away_fd=ev["away_fd"], team_fd=team_fd,
                        ligne=ligne, phase=pin[3],
                        prix_pinnacle=pin[0], juste_pinnacle=pin[1],
                        prix_winamax=prix.get("winamax_fr", (None,))[0],
                        prix_unibet=prix.get("unibet_fr", (None,))[0],
                        emis_ts=now.isoformat(), regle=False, issue=None, gain_pin=None, gain_fr=None))
                    deja.add(cle)
                    if not token_self:
                        break
    if nouveaux:
        journal = pd.concat([journal, pd.DataFrame(nouveaux)], ignore_index=True)

    # -- phase REGLEMENT --
    if len(journal):
        journal["commence"] = pd.to_datetime(journal["commence"], utc=True)
        a_regler = journal[(~journal["regle"].astype(bool)) & (journal["commence"] < now - timedelta(hours=3))]
        for i, s in a_regler.iterrows():
            ts = pd.Timestamp(s["commence"])
            ts = ts.tz_convert(None) if ts.tzinfo else ts
            cible = matchs[(matchs["league"] == s["league"])
                           & (matchs["home"] == s["home_fd"]) & (matchs["away"] == s["away_fd"])
                           & ((matchs["date"] - ts).abs() <= pd.Timedelta(days=1))]
            if not len(cible):
                continue
            m = cible.iloc[0]
            res = issue_token(s["token"], m, s["ligne"], s["team_fd"])
            if res is None:
                continue
            journal.loc[i, "regle"] = True
            journal.loc[i, "issue"] = bool(res)
            if pd.notna(s["prix_pinnacle"]):
                journal.loc[i, "gain_pin"] = (s["prix_pinnacle"] - 1.0) if res else -1.0
            fr = max([p for p in (s["prix_winamax"], s["prix_unibet"]) if pd.notna(p)], default=None)
            if fr is not None:
                journal.loc[i, "gain_fr"] = (fr - 1.0) if res else -1.0
    journal.to_parquet(sig_path, index=False)

    _rapport(rapport_dir, journal, evts, arch, candidats, non_apparies, now)
    print(f"[confrontation] {len(nouveaux)} nouveaux signaux, "
          f"{int(journal['regle'].sum()) if len(journal) else 0} regles au total, "
          f"{len(evts)} evenements archives apparies")
    return journal


def _rapport_vide(rapport_dir, message):
    with open(os.path.join(rapport_dir, "RAPPORT_CONFRONTATION.md"), "w", encoding="utf-8") as f:
        f.write(f"# RAPPORT CONFRONTATION\n\n{message}\n")


def _rapport(rapport_dir, journal, evts, arch, candidats, non_apparies, now):
    L = ["# RAPPORT CONFRONTATION — candidats prix vs archive", "",
         f"_Genere le {pd.Timestamp.now():%Y-%m-%d %H:%M}_ · **PAPIER — aucun pari reel** · "
         f"verdict par candidat a N regles >= {N_VERDICT}", "",
         f"Evenements archives apparies : {len(evts)} · signaux emis : {len(journal)} · "
         f"regles : {int(journal['regle'].sum()) if len(journal) else 0}", ""]
    if len(journal):
        fut = journal[pd.to_datetime(journal["commence"], utc=True) > now].sort_values("commence")
        if len(fut):
            L += ["## Signaux a venir", "",
                  "| Date | Match | Candidat | Marche | Ligne | Pinnacle (juste) | Winamax | Unibet |",
                  "|---|---|---|---|---|---|---|---|"]
            for _, s in fut.iterrows():
                juste = f"{s['juste_pinnacle']*100:.1f}%" if pd.notna(s["juste_pinnacle"]) else "—"
                pin = f"{s['prix_pinnacle']:.2f} ({juste})" if pd.notna(s["prix_pinnacle"]) else "—"
                L.append(f"| {pd.Timestamp(s['commence']):%d/%m %H:%M} | {s['home_fd']}–{s['away_fd']}"
                         f"{(' ['+s['team_fd']+']') if s['team_fd'] else ''} | {s['candidat']} | {s['token']}"
                         f" | {s['ligne'] if pd.notna(s['ligne']) else '—'} | {pin}"
                         f" | {s['prix_winamax'] if pd.notna(s['prix_winamax']) else '—'}"
                         f" | {s['prix_unibet'] if pd.notna(s['prix_unibet']) else '—'} |")
            L.append("")
        reg = journal[journal["regle"].astype(bool)]
        L += ["## Bilan par candidat (regles)", "",
              "| Candidat | N | Hit % | Juste % | Edge | ROI @Pin | ROI @FR | IC hit | Statut |",
              "|---|---|---|---|---|---|---|---|---|"]
        for cand in candidats:
            g = reg[reg["candidat"] == cand["id"]]
            if not len(g):
                L.append(f"| {cand['id']} {cand['nom']} | 0 | — | — | — | — | — | — | EN ATTENTE |")
                continue
            n = len(g); hits = int(g["issue"].sum())
            juste = g["juste_pinnacle"].dropna().mean()
            edge = hits / n - juste if pd.notna(juste) else np.nan
            roi_p = g["gain_pin"].dropna().mean(); roi_f = g["gain_fr"].dropna().mean()
            lo, hi = wilson_ci(hits, n)
            statut = "VERDICT POSSIBLE" if n >= N_VERDICT else f"EN COURS ({n}/{N_VERDICT})"
            L.append(f"| {cand['id']} {cand['nom']} | {n} | {hits/n*100:.1f} "
                     f"| {juste*100:.1f} | {edge*100:+.1f} pts | {roi_p*100:+.1f}% | {roi_f*100:+.1f}%"
                     f" | [{lo*100:.0f};{hi*100:.0f}] | {statut} |" if pd.notna(juste) else
                     f"| {cand['id']} {cand['nom']} | {n} | {hits/n*100:.1f} | — | — | — | — | — | {statut} |")
        L.append("")
    # couverture : qui price quoi
    L += ["## Couverture de l'archive (qui price quoi)", "",
          "| Marche | " + " | ".join(BOOKS) + " |", "|---|" + "---|" * len(BOOKS)]
    n_evts = arch["event_id"].nunique() or 1
    for m in sorted(arch["market"].unique()):
        am = arch[arch["market"] == m]
        cols = [f"{am[am['bookmaker']==b]['event_id'].nunique()/n_evts*100:.0f}%" for b in BOOKS]
        L.append(f"| {m} | " + " | ".join(cols) + " |")
    if non_apparies:
        L += ["", "## Noms non apparies (enrichir config/alias_equipes.yaml)", ""]
        L += [f"- {x}" for x in sorted(set(non_apparies))[:30]]
    with open(os.path.join(rapport_dir, "RAPPORT_CONFRONTATION.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
