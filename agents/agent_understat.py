"""AGENT UNDERSTAT — xG par match (BEST EFFORT, Tier A*).
Understat n'a pas d'API officielle : on extrait le JSON embarque des pages ligue.
Couverture : Ligue 1, Premier League, La Liga, Serie A, Bundesliga.
Si ce script casse (structure de page changee), le backtest tourne quand meme
en Tier A pur — les hypotheses xG passent en NON_EVALUE.
"""
import json, os, re, sys, time, unicodedata
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml

LIGUES_US = {"F1": "Ligue_1", "E0": "EPL", "SP1": "La_liga", "I1": "Serie_A", "D1": "Bundesliga"}
ALIAS = {  # football-data -> understat (complement au normalisateur)
    "man united": "manchester united", "man city": "manchester city",
    "wolves": "wolverhampton wanderers", "newcastle": "newcastle united",
    "paris sg": "paris saint germain", "ath bilbao": "athletic club",
    "ath madrid": "atletico madrid", "sociedad": "real sociedad", "betis": "real betis",
    "celta": "celta vigo", "espanol": "espanyol", "vallecano": "rayo vallecano",
    "ein frankfurt": "eintracht frankfurt", "m'gladbach": "borussia m.gladbach",
    "leverkusen": "bayer leverkusen", "dortmund": "borussia dortmund",
    "fc koln": "fc cologne", "st etienne": "saint-etienne",
}


def norm(nom):
    n = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().lower().strip()
    return ALIAS.get(n, n)


def extraire(html):
    m = re.search(r"datesData\s*=\s*JSON\.parse\('(.*?)'\)", html, re.S)
    if not m:
        raise RuntimeError("datesData introuvable — structure Understat changee ?")
    return json.loads(m.group(1).encode("utf-8").decode("unicode_escape"))


def main(config="config/ligues.yaml", data_dir="data"):
    with open(config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    saisons = cfg["saisons"]
    matches_path = os.path.join(data_dir, "matches.parquet")
    if not os.path.exists(matches_path):
        print("[understat] lance d'abord agent_collecte"); sys.exit(1)
    matchs = pd.read_parquet(matches_path)
    matchs["date"] = pd.to_datetime(matchs["date"])
    matchs["cle"] = (matchs["league"] + "|" + matchs["date"].dt.strftime("%Y-%m-%d")
                     + "|" + matchs["home"].map(norm) + "|" + matchs["away"].map(norm))
    index = dict(zip(matchs["cle"], matchs["match_id"]))
    lignes, rates = [], 0
    for code, nom_us in LIGUES_US.items():
        if code not in cfg["ligues"]:
            continue
        for s in saisons:
            annee = 2000 + int(s[:2])
            try:
                r = requests.get(f"https://understat.com/league/{nom_us}/{annee}",
                                 headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                data = extraire(r.text)
            except Exception as e:
                print(f"  [echec] {nom_us} {annee} : {e}")
                continue
            for m in data:
                if not m.get("isResult"):
                    continue
                d = m["datetime"][:10]
                cle = f"{code}|{d}|{norm(m['h']['title'])}|{norm(m['a']['title'])}"
                mid = index.get(cle)
                if mid is None:
                    rates += 1
                    continue
                lignes.append(dict(match_id=mid, xg_home=float(m["xG"]["h"]), xg_away=float(m["xG"]["a"])))
            print(f"  [ok] {nom_us} {annee}")
            time.sleep(1.5)  # politesse
    if lignes:
        pd.DataFrame(lignes).drop_duplicates("match_id").to_parquet(os.path.join(data_dir, "xg.parquet"), index=False)
        print(f"[understat] {len(lignes)} matchs xG apparies ({rates} non apparies -> completer ALIAS)")
    else:
        print("[understat] rien recupere — le backtest tournera en Tier A pur")


if __name__ == "__main__":
    main()
