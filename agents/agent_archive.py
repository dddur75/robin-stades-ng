"""AGENT ARCHIVE — capture des cotes exotiques (The Odds API).
Deux snapshots par match : J-1 (16-36h avant) et QUASI-CLOTURE (<=2.5h avant).
Le dernier snapshot avant coup d'envoi = "cloture maison" (convention documentee).

Cout : len(marches) x len(regions) credits par snapshot par match.
Garde-fous : plafond mensuel projete + arret si quota compte trop bas.
Secret requis : ODDS_API_KEY (Settings -> Secrets and variables -> Actions).
"""
import os, sys, json
from datetime import datetime, timezone
import pandas as pd
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = "https://api.the-odds-api.com/v4"


def charger_config(chemin="config/archive.yaml"):
    with open(chemin, encoding="utf-8") as f:
        return yaml.safe_load(f)


def maintenant():
    return datetime.now(timezone.utc)


def lister_evenements(sport_key, api_key):
    """Endpoint /events : GRATUIT (0 credit)."""
    r = requests.get(f"{BASE}/sports/{sport_key}/events",
                     params={"apiKey": api_key}, timeout=30)
    if r.status_code != 200:
        print(f"  [events {sport_key}] HTTP {r.status_code} : {r.text[:120]}")
        return []
    return r.json()


def decision_snapshot(commence, ledger_evt, cfg, now):
    """Retourne 'J1', 'CLOSE' ou None selon les fenetres et l'historique."""
    h = (commence - now).total_seconds() / 3600
    f = cfg["fenetres"]
    if 0 <= h <= f["cloture_heures"]:
        dernier = ledger_evt.get("dernier_snap")
        if dernier is None or (now - dernier).total_seconds() / 60 >= f["cloture_refresh_min"]:
            return "CLOSE"
        return None
    if f["j1_heures"][0] <= h <= f["j1_heures"][1] and not ledger_evt.get("a_j1"):
        return "J1"
    if f.get("h6") and 4 <= h <= 8 and not ledger_evt.get("a_h6"):
        return "H6"
    return None


def capturer(sport_key, event, phase, cfg, api_key):
    """Endpoint /events/{id}/odds : cout = marches x regions credits."""
    params = {
        "apiKey": api_key,
        "regions": ",".join(cfg["regions"]),
        "markets": ",".join(cfg["marches"]),
        "oddsFormat": "decimal",
    }
    r = requests.get(f"{BASE}/sports/{sport_key}/events/{event['id']}/odds",
                     params=params, timeout=30)
    restant = r.headers.get("x-requests-remaining")
    utilise = r.headers.get("x-requests-used")
    if r.status_code != 200:
        print(f"  [odds {event['id']}] HTTP {r.status_code} : {r.text[:120]}")
        return [], restant, utilise
    data = r.json()
    ts = maintenant().isoformat()
    garder = set(cfg["bookmakers_gardes"])
    lignes = []
    for bm in data.get("bookmakers", []):
        if bm["key"] not in garder:
            continue
        for m in bm.get("markets", []):
            for o in m.get("outcomes", []):
                lignes.append(dict(
                    snapshot_ts=ts, phase=phase,
                    event_id=data["id"], sport_key=sport_key,
                    commence_time=data["commence_time"],
                    home=data["home_team"], away=data["away_team"],
                    bookmaker=bm["key"], market=m["key"],
                    outcome=o.get("name"), point=o.get("point"),
                    price=o.get("price"), description=o.get("description"),
                ))
    return lignes, restant, utilise


def charger_ledger(chemin):
    if os.path.exists(chemin):
        df = pd.read_parquet(chemin)
        out = {}
        for _, r in df.iterrows():
            out[r["event_id"]] = dict(
                a_j1=bool(r["a_j1"]), a_h6=bool(r.get("a_h6", False)),
                dernier_snap=pd.Timestamp(r["dernier_snap"]).to_pydatetime()
                if pd.notna(r["dernier_snap"]) else None)
        return out
    return {}


def sauver_ledger(ledger, chemin):
    lignes = [dict(event_id=k, a_j1=v.get("a_j1", False), a_h6=v.get("a_h6", False),
                   dernier_snap=v.get("dernier_snap")) for k, v in ledger.items()]
    pd.DataFrame(lignes).to_parquet(chemin, index=False)


def credits_du_mois(dossier, mois):
    """Comptage local approximatif : snapshots enregistres ce mois x cout unitaire."""
    compteur = os.path.join(dossier, f"credits_{mois}.json")
    if os.path.exists(compteur):
        return json.load(open(compteur))["credits"], compteur
    return 0, compteur


def main(config="config/archive.yaml", data_dir="data/archive"):
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("[archive] ODDS_API_KEY absent — configurer le secret GitHub. Rien a faire.")
        return 0
    cfg = charger_config(config)
    os.makedirs(data_dir, exist_ok=True)
    now = maintenant()
    mois = now.strftime("%Y-%m")
    cout_snapshot = len(cfg["marches"]) * len(cfg["regions"])
    credits_locaux, chemin_compteur = credits_du_mois(data_dir, mois)
    ledger_path = os.path.join(data_dir, "ledger.parquet")
    ledger = charger_ledger(ledger_path)
    plafond = cfg["budget"]["credits_mois_max"]

    toutes_lignes, n_snaps = [], 0
    arret = False
    for code_fd, sport_key in cfg["sports"].items():
        if arret:
            break
        for evt in lister_evenements(sport_key, api_key):
            commence = datetime.fromisoformat(evt["commence_time"].replace("Z", "+00:00"))
            le = ledger.setdefault(evt["id"], {})
            phase = decision_snapshot(commence, le, cfg, now)
            if phase is None:
                continue
            if credits_locaux + cout_snapshot > plafond:
                # priorite absolue aux clotures ; on saute les J1 si le budget serre
                if phase != "CLOSE" or credits_locaux + cout_snapshot > plafond + 500:
                    print(f"[budget] plafond mensuel {plafond} atteint — snapshot {phase} saute")
                    continue
            lignes, restant, _ = capturer(sport_key, evt, phase, cfg, api_key)
            credits_locaux += cout_snapshot
            n_snaps += 1
            toutes_lignes.extend(lignes)
            le["dernier_snap"] = now
            if phase == "J1":
                le["a_j1"] = True
            if phase == "H6":
                le["a_h6"] = True
            if restant is not None and float(restant) < cfg["budget"]["arret_si_restant_sous"]:
                print(f"[budget] quota compte critique ({restant} restants) — ARRET")
                arret = True
                break

    if toutes_lignes:
        fichier = os.path.join(data_dir, f"odds_{mois}.parquet")
        df_new = pd.DataFrame(toutes_lignes)
        if os.path.exists(fichier):
            df_new = pd.concat([pd.read_parquet(fichier), df_new], ignore_index=True)
            df_new = df_new.drop_duplicates(subset=["snapshot_ts", "event_id", "bookmaker", "market", "outcome", "point"])
        df_new.to_parquet(fichier, index=False)
        print(f"[archive] {n_snaps} snapshots, {len(toutes_lignes)} lignes -> {fichier}")
    else:
        print(f"[archive] aucun snapshot necessaire ({len(ledger)} evenements suivis)")
    sauver_ledger(ledger, ledger_path)
    json.dump({"credits": credits_locaux}, open(chemin_compteur, "w"))
    print(f"[budget] ~{credits_locaux}/{plafond} credits estimes ce mois (cout snapshot={cout_snapshot})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
