"""Moteur de classement point-in-time et atomes d'enjeu.

La passe est chronologique par ligue-saison. Tous les matchs qui partagent la
meme date voient exactement le meme classement pre-date, car les historiques ne
garantissent pas toujours une heure fiable. Les resultats du batch ne sont
appliques qu'apres le calcul de tous les contextes de cette date.
"""

from collections import defaultdict

import pandas as pd


def passe_enjeu(matchs, zones):
    """Calculer l'etat connu avant chaque match d'une ligue-saison.

    Args:
        matchs: DataFrame contenant au minimum match_id, date, equipes et scores.
        zones: Nombre de places de relegation, promotion et Europe.

    Returns:
        Dictionnaire ``match_id -> {home: etat, away: etat}``.
    """
    equipes = sorted(set(matchs["home"]) | set(matchs["away"]))
    n = len(equipes)
    total_rounds = 2 * (n - 1)
    pts = defaultdict(int)
    played = defaultdict(int)
    gd = defaultdict(int)
    gf = defaultdict(int)
    round_maintien_sur = {}
    round_objectif_rate = {}
    releg = zones.get("releg_spots", 3)
    promo = zones.get("promo_spots", 0)
    europe = zones.get("europe_spots", 6)
    out = {}

    def table():
        return sorted(equipes, key=lambda team: (-pts[team], -gd[team], -gf[team]))

    def etat_avant_match(match):
        classement = table()
        rang = {team: i + 1 for i, team in enumerate(classement)}
        etat = {}

        for side, team, opp in (
            ("home", match["home"], match["away"]),
            ("away", match["away"], match["home"]),
        ):
            matchs_restants = total_rounds - played[team]
            points_restants = 3 * matchs_restants
            max_final = pts[team] + points_restants
            nb_au_dessus_max = sum(
                1 for autre in equipes if autre != team and pts[autre] > max_final
            )
            nb_condamnes_sous_nous = sum(
                1
                for autre in equipes
                if autre != team
                and pts[autre] + 3 * (total_rounds - played[autre]) < pts[team]
            )

            premier = classement[0] if classement else team
            pts_premier = pts[premier]
            idx_safe = n - releg
            pts_zone_rouge = (
                pts[classement[idx_safe]] if 0 <= idx_safe < n else 0
            )
            pts_europe = pts[classement[europe - 1]] if europe - 1 < n else 0
            pts_promo = (
                pts[classement[promo - 1]]
                if promo and promo - 1 < n
                else None
            )

            marge_maintien = pts[team] - pts_zone_rouge
            retard_europe = pts_europe - pts[team]
            retard_titre = pts_premier - pts[team]
            retard_promo = (
                pts_promo - pts[team] if pts_promo is not None else None
            )

            relegue_math = nb_au_dessus_max >= (n - releg)
            maintien_sur = nb_condamnes_sous_nous >= releg
            titre_elimine = nb_au_dessus_max >= 1
            montee_assuree = promo > 0 and nb_condamnes_sous_nous >= (n - promo)
            montee_eliminee = promo > 0 and nb_au_dessus_max >= promo

            round_actuel = played[team]
            if maintien_sur and team not in round_maintien_sur:
                round_maintien_sur[team] = round_actuel
            objectif_rate = titre_elimine if promo == 0 else montee_eliminee
            if objectif_rate and team not in round_objectif_rate:
                round_objectif_rate[team] = round_actuel

            sans_enjeu = (
                maintien_sur
                and marge_maintien >= points_restants + 3
                and retard_europe >= points_restants + 3
                and (
                    promo == 0
                    or (
                        retard_promo is not None
                        and retard_promo >= points_restants + 3
                    )
                )
            )
            etat[side] = {
                "rang": rang[team],
                "rang_opp": rang[opp],
                "mr": matchs_restants,
                "LUTTE_TITRE": (
                    retard_titre <= matchs_restants
                    and matchs_restants <= 10
                    and not titre_elimine
                ),
                "LUTTE_MAINTIEN": (
                    abs(marge_maintien) <= matchs_restants
                    and matchs_restants <= 10
                    and not maintien_sur
                    and not relegue_math
                ),
                "LUTTE_MONTEE": (
                    promo > 0
                    and retard_promo is not None
                    and retard_promo <= matchs_restants
                    and matchs_restants <= 10
                    and not montee_eliminee
                ),
                "SANS_ENJEU": bool(sans_enjeu),
                "RELEGUE_MATH": bool(relegue_math),
                "MONTEE_ASSUREE": bool(montee_assuree),
                "MAINTIEN_ASSURE_RECENT": (
                    team in round_maintien_sur
                    and round_actuel - round_maintien_sur[team] <= 3
                    and sans_enjeu
                ),
                "OBJECTIF_RATE_RECENT": (
                    team in round_objectif_rate
                    and round_actuel - round_objectif_rate[team] <= 2
                ),
                "FENETRE_FIN_SAISON": matchs_restants <= 8,
                "opp_top_half": rang[opp] <= n // 2,
                "opp_bottom_third": rang[opp] > n - max(1, n // 3),
            }

        deux_en_lutte = all(
            etat[side]["LUTTE_TITRE"]
            or etat[side]["LUTTE_MAINTIEN"]
            or etat[side]["LUTTE_MONTEE"]
            for side in ("home", "away")
        )
        choc_direct = (
            etat["home"]["rang"] <= 6
            and etat["away"]["rang"] <= 6
            and abs(pts[match["home"]] - pts[match["away"]]) <= 3
        )
        for side in ("home", "away"):
            etat[side]["MATCH_A_ENJEU_ST"] = bool(deux_en_lutte or choc_direct)
        return etat

    def appliquer_resultat(match):
        if pd.isna(match["fthg"]) or pd.isna(match["ftag"]):
            return
        home, away = match["home"], match["away"]
        buts_home, buts_away = int(match["fthg"]), int(match["ftag"])
        played[home] += 1
        played[away] += 1
        gd[home] += buts_home - buts_away
        gd[away] += buts_away - buts_home
        gf[home] += buts_home
        gf[away] += buts_away
        if buts_home > buts_away:
            pts[home] += 3
        elif buts_away > buts_home:
            pts[away] += 3
        else:
            pts[home] += 1
            pts[away] += 1

    tries = matchs.sort_values(["date", "match_id"])
    for _, batch in tries.groupby("date", sort=True, dropna=False):
        lignes = [match for _, match in batch.iterrows()]
        for match in lignes:
            out[match["match_id"]] = etat_avant_match(match)
        for match in lignes:
            appliquer_resultat(match)

    return out
