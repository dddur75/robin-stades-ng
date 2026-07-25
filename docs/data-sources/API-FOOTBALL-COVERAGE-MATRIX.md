# Matrice de couverture API-Football

La représentation machine se trouve dans
`data/contracts/api-football-coverage.json` et couvre 528 scopes :

- 6 compétitions ;
- 8 saisons, de 2018 à 2025 ;
- 11 endpoints cœur.

Avant l’appel live, les scopes restent `UNKNOWN` ou `FAILED` si l’identifiant
n’a pas encore été validé. Les identifiants sont acceptés uniquement après une
réponse `/leagues` correspondant exactement au nom et au pays attendus.

Statuts : `AVAILABLE`, `PARTIAL`, `UNAVAILABLE`, `UNKNOWN`, `FAILED`.

Les champs mesurés sont : identifiant fournisseur, couverture annoncée, premier
test, lignes, pages, quota, volumes brut/compressé/normalisé, qualité et date de
vérification. Une absence n’est jamais remplacée par zéro.

