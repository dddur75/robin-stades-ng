"""VAGUE 1B — annexe PRE-ENREGISTREE (2026-07-07, apres lecture du rapport vague 1).
Famille FDR SEPAREE de la vague 1 (le spec vague 1 reste fige, delta 5).
Trois hypotheses nees de la lecture du premier rapport :
- HC-26 : les donnees ont INVERSE HC-06 (le public sur-achete l'over des duels de
  passoires) -> on pre-enregistre la lecture under.
- HC-27 : triangulation S021 (fade du vainqueur surprise, -10.6%) / HC-12 (+4.4%
  a l'exterieur) / DC 8-10 saisons -> fade toutes venues.
- S038b : REPOS_LONG >=7j capte le rythme hebdomadaire standard (61% du dataset) ;
  le seuil >=8j isole les vraies coupures.
"""

VAGUE1B = [
    dict(id="HC-26", nom="Duel de passoires — lecture under", cond=dict(self_=["DEFENSE_PASSOIRE"], adv=["DEFENSE_PASSOIRE"]), marches=["U25"]),
    dict(id="HC-27", nom="Fade du vainqueur surprise (toutes venues)", cond=dict(self_=["POST_VICTOIRE_SURPRISE"]), marches=["WIN_ADV", "DC_ADV"]),
    dict(id="S038b", nom="Vraie coupure (repos >= 8j)", cond=dict(self_=["REPOS_TRES_LONG"]), marches=["WIN_SELF", "CS_SELF"]),
]
