# Ablation joueurs pré-lineup

Le test principal retire toutes les features joueurs en conservant fixtures,
cibles, cutoff, odds, entraînement et calibration identiques. Les ablations
secondaires retirent force du onze, banc, continuité et incertitude.

Résultat actuel complet contre équipe seule : Δ Log Loss +0,00056; CI 95 %
[-0,00267 ; 0,00372], P(amélioration)=0,3662. Le gain est
`INCONCLUSIVE`. Le contrôle d’assignation aléatoire des lineups est
déterministe et doit supprimer tout uplift. Aucun zéro ne remplace un joueur
ou une statistique manquante.
