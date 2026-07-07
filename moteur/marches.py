"""Resolution des marches : issue observee + prix de cloture + proba juste.

Deux etages (doctrine delta 1-bis) :
- Etage 2 : marches a cloture Pinnacle archivee -> ROI@cloture + edge vs proba juste.
  (WIN_SELF, WIN_ADV, O25, U25)
- Etage 2* : proba juste derivable du 1X2 mais prix du marche non archive -> edge, pas de ROI.
  (DC_SELF, DC_ADV)
- Etage 1 : resultat mesurable, aucun prix historique -> lift vs taux de base.
"""
import numpy as np
from .devig import probas_justes

TOKENS = [
    "WIN_SELF", "WIN_ADV", "O25", "U25", "DC_SELF", "DC_ADV",
    "BTTS_Y", "O05_MT1", "O15_MT1", "U05_MT1", "MT1_SELF", "MT1_ADV",
    "MT2_SELF", "MT2_ADV", "O35", "U15", "O45_CARTONS",
    "TEAM_O15_SELF", "TEAM_O15_ADV", "TEAM_U15_SELF", "TEAM_U15_ADV",
    "CS_SELF", "CS_ADV",
]


def issues(row):
    gf, ga = row["gf"], row["ga"]
    ht_gf, ht_ga = row["ht_gf"], row["ht_ga"]
    tot = gf + ga
    return {
        "WIN_SELF": gf > ga, "WIN_ADV": ga > gf,
        "DC_SELF": gf >= ga, "DC_ADV": ga >= gf,
        "O25": tot >= 3, "U25": tot <= 2, "O35": tot >= 4, "U15": tot <= 1,
        "BTTS_Y": (gf > 0) and (ga > 0),
        "O05_MT1": (ht_gf + ht_ga) >= 1, "O15_MT1": (ht_gf + ht_ga) >= 2,
        "U05_MT1": (ht_gf + ht_ga) == 0,
        "MT1_SELF": ht_gf > ht_ga, "MT1_ADV": ht_ga > ht_gf,
        "MT2_SELF": (gf - ht_gf) > (ga - ht_ga), "MT2_ADV": (ga - ht_ga) > (gf - ht_gf),
        "O45_CARTONS": row["cartons_tot"] >= 5,
        "TEAM_O15_SELF": gf >= 2, "TEAM_O15_ADV": ga >= 2,
        "TEAM_U15_SELF": gf <= 1, "TEAM_U15_ADV": ga <= 1,
        "CS_SELF": ga == 0, "CS_ADV": gf == 0,
    }


def prix_et_probas(row):
    """Retourne dict token -> (cote, proba_juste, cloture: bool) pour les marches prices,
    + probas justes derivees pour DC. None si cotes absentes."""
    out = {}
    trio_c = [row.get("psch"), row.get("pscd"), row.get("psca")]
    trio_p = [row.get("psh"), row.get("psd"), row.get("psa")]
    trio, cloture = (trio_c, True) if all(_ok(c) for c in trio_c) else (
        (trio_p, False) if all(_ok(c) for c in trio_p) else (None, False))
    if trio is not None:
        p = probas_justes(trio)
        p_home, p_draw, p_away = p
        est_dom = row["side"] == "home"
        p_self = p_home if est_dom else p_away
        p_adv = p_away if est_dom else p_home
        c_self = trio[0] if est_dom else trio[2]
        c_adv = trio[2] if est_dom else trio[0]
        out["WIN_SELF"] = (c_self, p_self, cloture)
        out["WIN_ADV"] = (c_adv, p_adv, cloture)
        out["DC_SELF"] = (None, p_self + p_draw, cloture)
        out["DC_ADV"] = (None, p_adv + p_draw, cloture)
    duo_c = [row.get("pc_o25"), row.get("pc_u25")]
    duo_p = [row.get("p_o25"), row.get("p_u25")]
    duo, cl2 = (duo_c, True) if all(_ok(c) for c in duo_c) else (
        (duo_p, False) if all(_ok(c) for c in duo_p) else (None, False))
    if duo is not None:
        p = probas_justes(duo)
        out["O25"] = (duo[0], p[0], cl2)
        out["U25"] = (duo[1], p[1], cl2)
    return out


def _ok(c):
    try:
        return c is not None and np.isfinite(float(c)) and float(c) > 1.0
    except (TypeError, ValueError):
        return False
