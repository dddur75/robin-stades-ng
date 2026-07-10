"""Moteur de classement point-in-time + atomes d'enjeu.
Passe chronologique par (ligue, saison) : avant chaque match, on fige l'etat
du classement tel qu'il etait connu la veille. Zero information future.

Eliminations / securisations mathematiques : criteres exacts fondes sur
"les points ne diminuent jamais" :
- RELEGUE_MATH  : nb d'equipes avec pts_actuels > notre_max_final >= n - releg_spots
- MAINTIEN_SUR  : nb d'equipes avec max_final < nos_pts_actuels >= releg_spots
- TITRE_ELIMINE : au moins 1 equipe avec pts_actuels > notre_max_final
- MONTEE_* : analogues avec promo_spots
"""
from collections import defaultdict
import pandas as pd


def passe_enjeu(matchs, zones):
    """matchs : DataFrame d'UNE ligue-saison trie par date.
    zones : dict {releg_spots, promo_spots, europe_spots}.
    Retourne dict match_id -> {home: {...atomes...}, away: {...}}"""
    equipes = sorted(set(matchs["home"]) | set(matchs["away"]))
    n = len(equipes)
    total_rounds = 2 * (n - 1)
    pts = defaultdict(int); played = defaultdict(int)
    gd = defaultdict(int); gf = defaultdict(int)
    # suivis "depuis N journees"
    round_maintien_sur = {}; round_objectif_rate = {}
    releg = zones.get("releg_spots", 3)
    promo = zones.get("promo_spots", 0)
    europe = zones.get("europe_spots", 6)
    out = {}

    def table():
        return sorted(equipes, key=lambda t: (-pts[t], -gd[t], -gf[t]))

    for _, m in matchs.iterrows():
        t = table()
        rang = {team: i + 1 for i, team in enumerate(t)}
        etat = {}
        for side, team, opp in (("home", m["home"], m["away"]), ("away", m["away"], m["home"])):
            mr = total_rounds - played[team]
            pts_rest = 3 * mr
            max_final = pts[team] + pts_rest
            nb_au_dessus_max = sum(1 for e in equipes if e != team and pts[e] > max_final)
            nb_condamnes_sous_nous = sum(
                1 for e in equipes if e != team and pts[e] + 3 * (total_rounds - played[e]) < pts[team]
            )
            # zones de reference (equipe au premier rang sauve / premier rang europeen / zone promo)
            premier = t[0] if t else team
            pts_premier = pts[premier]
            idx_safe = n - releg  # rang du dernier sauve
            pts_zone_rouge = pts[t[idx_safe]] if 0 <= idx_safe < n else 0      # 1er relegable
            pts_dernier_sauve = pts[t[idx_safe - 1]] if 0 < idx_safe <= n else 0
            pts_europe = pts[t[europe - 1]] if europe - 1 < n else 0
            pts_promo = pts[t[promo - 1]] if promo and promo - 1 < n else None

            marge_maintien = pts[team] - pts_zone_rouge
            retard_europe = pts_europe - pts[team]
            retard_titre = pts_premier - pts[team]
            retard_promo = (pts_promo - pts[team]) if pts_promo is not None else None

            relegue_math = nb_au_dessus_max >= (n - releg)
            maintien_sur = nb_condamnes_sous_nous >= releg
            titre_elimine = nb_au_dessus_max >= 1
            montee_assuree = promo > 0 and nb_condamnes_sous_nous >= (n - promo)
            montee_eliminee = promo > 0 and nb_au_dessus_max >= promo

            rnd = played[team]
            if maintien_sur and team not in round_maintien_sur:
                round_maintien_sur[team] = rnd
            if (titre_elimine if promo == 0 else montee_eliminee) and team not in round_objectif_rate:
                round_objectif_rate[team] = rnd

            sans_enjeu = (
                maintien_sur and marge_maintien >= pts_rest + 3
                and retard_europe >= pts_rest + 3
                and (promo == 0 or (retard_promo is not None and retard_promo >= pts_rest + 3))
            )
            etat[side] = {
                "rang": rang[team], "rang_opp": rang[opp], "mr": mr,
                "LUTTE_TITRE": retard_titre <= mr and mr <= 10 and not titre_elimine,
                "LUTTE_MAINTIEN": abs(marge_maintien) <= mr and mr <= 10 and not maintien_sur and not relegue_math,
                "LUTTE_MONTEE": promo > 0 and retard_promo is not None and retard_promo <= mr and mr <= 10 and not montee_eliminee,
                "SANS_ENJEU": bool(sans_enjeu),
                "RELEGUE_MATH": bool(relegue_math),
                "MONTEE_ASSUREE": bool(montee_assuree),
                "MAINTIEN_ASSURE_RECENT": team in round_maintien_sur and (rnd - round_maintien_sur[team]) <= 3 and sans_enjeu,
                "OBJECTIF_RATE_RECENT": team in round_objectif_rate and (rnd - round_objectif_rate[team]) <= 2,
                "FENETRE_FIN_SAISON": mr <= 8,
                "opp_top_half": rang[opp] <= n // 2,
                "opp_bottom_third": rang[opp] > n - max(1, n // 3),
            }
        # MATCH_A_ENJEU (niveau match)
        deux_en_lutte = all(
            etat[s]["LUTTE_TITRE"] or etat[s]["LUTTE_MAINTIEN"] or etat[s]["LUTTE_MONTEE"]
            for s in ("home", "away")
        )
        choc_direct = (
            etat["home"]["rang"] <= 6 and etat["away"]["rang"] <= 6
            and abs(pts[m["home"]] - pts[m["away"]]) <= 3
        )
        for s in ("home", "away"):
            etat[s]["MATCH_A_ENJEU_ST"] = bool(deux_en_lutte or choc_direct)
        out[m["match_id"]] = etat
        # mise a jour post-match — sautee pour les matchs A VENIR (scores NaN)
        h, a = m["home"], m["away"]
        if pd.isna(m["fthg"]) or pd.isna(m["ftag"]):
            continue
        hg, ag = int(m["fthg"]), int(m["ftag"])
        played[h] += 1; played[a] += 1
        gd[h] += hg - ag; gd[a] += ag - hg
        gf[h] += hg; gf[a] += ag
        if hg > ag: pts[h] += 3
        elif ag > hg: pts[a] += 3
        else: pts[h] += 1; pts[a] += 1
    return out
