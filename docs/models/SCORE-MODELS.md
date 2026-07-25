# Modèles de score

Poisson estime les intensités domicile/extérieur uniquement depuis les matchs
antérieurs, puis normalise une matrice 0–10 buts. Dixon–Coles applique la
correction des faibles scores avec rho fixé avant OOS.

La même matrice fournit 1X2, Over/Under 2,5, BTTS et scores exacts. La somme de
chaque marché vaut 1. Dixon–Coles contre Poisson est actuellement
`INCONCLUSIVE` : Δ Log Loss +0,00196, CI 95 % croisant zéro.
