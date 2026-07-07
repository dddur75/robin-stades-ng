"""AGENT COLLECTE — football-data.co.uk.
Telecharge les CSV par ligue/saison, normalise, ecrit data/matches.parquet.
Gratuit, sans cle. Tolerant aux fichiers manquants ou mal formes.
"""
import io, os, sys
import pandas as pd
import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

URL = "https://www.football-data.co.uk/mmz4281/{saison}/{code}.csv"
RENOMMAGE = {
    "Div": "div", "Date": "date_str", "Time": "time_str",
    "HomeTeam": "home", "AwayTeam": "away",
    "FTHG": "fthg", "FTAG": "ftag", "HTHG": "hthg", "HTAG": "htag",
    "Referee": "referee",
    "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar", "HC": "hc", "AC": "ac",
    "PSH": "psh", "PSD": "psd", "PSA": "psa",
    "PSCH": "psch", "PSCD": "pscd", "PSCA": "psca",
    "P>2.5": "p_o25", "P<2.5": "p_u25", "PC>2.5": "pc_o25", "PC<2.5": "pc_u25",
}
COLS_NUM = ["fthg", "ftag", "hthg", "htag", "hy", "ay", "hr", "ar", "hc", "ac",
            "psh", "psd", "psa", "psch", "pscd", "psca", "p_o25", "p_u25", "pc_o25", "pc_u25"]


def saison_label(code4):  # "1516" -> "2015-16"
    return f"20{code4[:2]}-{code4[2:]}"


def telecharger(code, saison, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"{code}_{saison}.csv")
    if os.path.exists(cache) and os.path.getsize(cache) > 1000:
        brut = open(cache, "rb").read()
    else:
        r = requests.get(URL.format(saison=saison, code=code), timeout=30)
        if r.status_code != 200 or len(r.content) < 500:
            print(f"  [absent] {code} {saison}")
            return None
        brut = r.content
        open(cache, "wb").write(brut)
    try:
        df = pd.read_csv(io.BytesIO(brut), encoding="latin-1", on_bad_lines="skip")
    except Exception as e:
        print(f"  [illisible] {code} {saison} : {e}")
        return None
    df = df.rename(columns=RENOMMAGE)
    requis = {"date_str", "home", "away", "fthg", "ftag"}
    if not requis.issubset(df.columns):
        print(f"  [colonnes manquantes] {code} {saison}")
        return None
    df = df.dropna(subset=["home", "away", "fthg", "ftag"])
    df["date"] = pd.to_datetime(df["date_str"], dayfirst=True, format="mixed", errors="coerce")
    df = df.dropna(subset=["date"])
    df["league"] = code
    df["season"] = saison_label(saison)
    for c in COLS_NUM:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    for c in ("hthg", "htag"):
        df[c] = df[c].fillna(0)
    for c in ("hy", "ay", "hr", "ar", "hc", "ac"):
        df[c] = df[c].fillna(0)
    if "referee" not in df:
        df["referee"] = None
    garder = ["league", "season", "date", "home", "away", "fthg", "ftag", "hthg", "htag",
              "referee", "hy", "ay", "hr", "ar", "hc", "ac",
              "psh", "psd", "psa", "psch", "pscd", "psca", "p_o25", "p_u25", "pc_o25", "pc_u25"]
    for g in garder:
        if g not in df:
            df[g] = None
    return df[garder]


def main(config="config/ligues.yaml", data_dir="data"):
    with open(config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    codes = list(cfg["ligues"].keys())
    saisons = cfg["saisons"]
    morceaux = []
    for code in codes:
        for s in saisons:
            df = telecharger(code, s, os.path.join(data_dir, "brut"))
            if df is not None:
                morceaux.append(df)
                print(f"  [ok] {code} {s} : {len(df)} matchs")
    if not morceaux:
        print("[collecte] AUCUNE donnee recuperee"); sys.exit(1)
    tout = pd.concat(morceaux, ignore_index=True).sort_values(["date"]).reset_index(drop=True)
    tout["match_id"] = tout["league"] + "_" + tout["season"] + "_" + tout.groupby(["league", "season"]).cumcount().astype(str)
    os.makedirs(data_dir, exist_ok=True)
    tout.to_parquet(os.path.join(data_dir, "matches.parquet"), index=False)
    couverture_clot = tout["psch"].notna().mean()
    print(f"[collecte] {len(tout)} matchs -> {data_dir}/matches.parquet "
          f"(clotures Pinnacle presentes sur {couverture_clot*100:.0f}% des lignes)")


if __name__ == "__main__":
    main()
