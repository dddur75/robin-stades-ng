# Jalon 10 — témoins de non-régression R3

## Portée

Ce contrôle rejoue uniquement les trois règles publiées dans le rapport Jalon 10.
Il vérifie la fidélité du calcul avant/après simplification ; il ne relance pas la
recherche, ne sélectionne aucune nouvelle règle et ne modifie pas le verdict
scientifique `JALON_10_NO_ROBUST_PATTERN_FOUND`.

Le rejeu est rattaché au claim de preuve
`DATA.ROBIN.SIMPLIFICATION.R3.JALON10.NON_REGRESSION.V1.001`.

## Sources figées

- révision historique : `5c85cf20b932df44dca8665de00e52e3f1e02236` ;
- arbre Parquet : `986010a776cb7c0f4948098660febea9577f159e` ;
- hash du dataset :
  `3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495` ;
- 30 partitions historiques lues comme blobs Git figés ;
- 865 paris/appartenances, correspondant à 863 fixtures distinctes, lus par
  filtre dans les Parquet canoniques ;
- aucun appel fournisseur, crédit, accès R2, pari, promotion ou autre effet externe.

Le script vérifie les SHA-256 des trois Parquet oracles, de la campagne complète,
de la campagne compacte et du registre avant tout calcul. Il reconstruit ensuite
seulement les trois règles cibles depuis les données historiques d'origine.

## Comparaison détaillée

Chaque ligne est contrôlée sur l'identité canonique du match, l'identifiant de
fixture, la date, la compétition, la saison, les équipes, le score, le marché,
la sélection, la classe et la valeur de cote, la marge, la mise unitaire, le
règlement, le retour brut, le profit, le profit cumulé, le hash d'appartenance et
le hash de la ligne source. Les doublons et tout ordre non canonique sont refusés.

La tolérance relative est nulle. Les tolérances absolues sont `1e-12` pour une
valeur par pari et le ROI, et `1e-9` unité pour les sommes et le drawdown. Elles
couvrent le seul bruit d'addition binary64 sur au plus 363 paris et restent très
inférieures à la précision publiée de 0,01 unité. Un écart supérieur, ou un écart
sur un champ non flottant, bloque immédiatement l'équivalence.

Pour cette référence initiale, l'égalité du SHA-256 des sérialisations canoniques
est volontairement plus stricte et prime sur ces tolérances : tout changement
d'octet bloque aussi la validation. Les seuils restent documentés pour distinguer
un éventuel bruit binary64 d'un écart matériel dans le diagnostic d'échec ; ils
ne permettent pas de faire passer ce témoin.

Le profit, le ROI et le drawdown chronologique sont aussi recalculés
indépendamment avec une mise fixe de 1 unité.

## Résultats internes

| Témoin | Paris | G/P/N | Profit (u) | ROI interne | Drawdown max (u) |
| --- | ---: | ---: | ---: | ---: | ---: |
| J10-M001 — La Liga, extérieur, 2,00–2,50 | 261 | 135/126/0 | 43,43 | 0,1663984674329502 | 9,269999999999982 |
| J10-M002 — Serie A, nul, 2,50–3,25 | 363 | 136/227/0 | 57,88 | 0,1594490358126722 | 19,519999999999868 |
| J10-M003 — Serie A, extérieur, 1,60–2,00 | 241 | 154/87/0 | 33,42 | 0,1386721991701245 | 7,220000000000027 |

Les 865 lignes avant/après sont byte-identiques après sérialisation canonique :

`61ed7022cbc79c39f715e594ae0a8b3aeb6ba5d43c415810582b0e8e1c94d86c`

Le nombre d'écarts inexpliqués est zéro et tous les deltas maximaux observés sont
exactement `0.0`. Aucune correction d'un ancien bug n'est invoquée.

Le rapport compact suivi est
`reports/hypothesis-evidence/r3-jalon10-non-regression.json`. Les deux JSONL
détaillés et leur manifeste restent sous
`artifacts/r3-jalon10-non-regression/`, hors Git. La CI SAFE les régénère à partir
des sources figées et exige que le rapport compact obtenu soit byte-identique à
la référence suivie.

Hors CI, si les caches gelés sont conservés dans un autre checkout, les fournir
explicitement avec `--evidence-root` et `--campaign-root`. Sans `--report`, la CLI
écrit le rapport généré sous le répertoire `--output-root` ignoré ; elle interdit
d'écraser le rapport de référence passé à `--verify-report`.
