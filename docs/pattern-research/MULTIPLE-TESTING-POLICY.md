# Politique de tests multiples

Version : `pattern-multiple-testing-v1.1-review-hardening`
État : `PREREGISTERED_BEFORE_CAMPAIGN`

## Univers des hypothèses

Le dénominateur comprend toutes les règles générées, y compris celles sans
gain, sans support, rejetées pour fuite, dupliquées ou dominées. Il est interdit
de publier seulement le meilleur résultat.

Le générateur commence par une, deux puis trois conditions. Une quatrième
condition n’est autorisée qu’après préenregistrement et preuve que la règle
simple ne suffit pas.

## Seuils de la campagne V1

| Gate | Seuil gelé |
|---|---:|
| Support total | au moins 80 paris |
| Saisons distinctes | au moins 3 |
| Support d’un fold test | au moins 15 paris |
| Folds test positifs | au moins 67 % |
| Nombre de folds admissibles | au moins 2 |
| Dernier fold admissible | ROI strictement positif |
| FDR Benjamini–Hochberg | q-value ≤ 0,05 |
| p-value marginale | unilatérale CR1, groupée par date de match |
| Bootstrap groupé | 1 000 réplications déterministes |
| Intervalle de profit | borne basse strictement positive |
| Contrôle permutation | requis sur la liste bornée de candidats |
| Mise | 1 unité fixe |

Les 1 000 réplications constituent le run borné V1, pas une autorisation de
faire une affirmation forte. Toute communication externe doit montrer
l’intervalle et le support.

## Procédure

1. calculer une statistique et une p-value CR1 groupée par date de match pour
   chaque hypothèse admissible ;
2. corriger la famille complète par Benjamini–Hochberg ;
3. appliquer le bootstrap par fixture ou groupe temporel, jamais ligne par
   ligne si les observations ne sont pas indépendantes ;
4. exécuter les folds temporels avec entraînement strictement antérieur
   lorsqu'un paramètre est appris ;
5. mesurer la stabilité par saison, ligue, équipe et bande de cote ;
6. comparer à des labels mélangés, features aléatoires et règles impossibles ;
7. conserver le résultat complet et la seed.

Un ROI positif brut n’est jamais un critère suffisant.

Les 700 règles se chevauchent et leur indépendance, ou la propriété PRDS, n'est
pas démontrée. Benjamini–Hochberg reste le calcul préenregistré V1, mais cette
limite interdit toute affirmation forte et le gate de promotion échoue fermé
si une preuve de permutation ou de concentration manque. Une révision future
devra préenregistrer BY ou un contrôle maxT/Westfall–Young avant de relancer
une nouvelle famille.

## Concentration et simplicité

Une promotion exige que les métriques de concentration soient présentes. Si
elles ne sont pas calculables, le gate échoue fermé. Une règle ne doit pas
dépendre d’une seule équipe, d’une seule saison ou de quelques gains extrêmes.
Une variante complexe dont le gain de ROI est inférieur à 1 point de
pourcentage face à sa sous-règle et dont le Jaccard des sélections est au moins
0,90 est `DOMINATED`.

Le contrôle de stabilité inter-ligues exposé V1 examine Bundesliga et Serie A
séparément : chacune exige au moins 40 paris et un ROI strictement positif.
Ces ligues appartiennent déjà au corpus de découverte ; ce contrôle n’est pas
un holdout externe indépendant.

Les bootstraps sont limités aux 40 meilleures règles positives ayant franchi
le support. Les permutations sont limitées aux 5 premières, avec 100
permutations chacune. Une règle hors de cette liste, une permutation absente,
ou une p-value de permutation supérieure à 0,05 échoue fermée. Ces bornes de
calcul sont publiées ; elles ne modifient pas le dénominateur FDR.

La permutation candidate V1 échange globalement les labels de sélection. Elle
ne démontre pas l'échangeabilité conditionnelle par compétition, saison et
bande de cote. Cette limite est publiée et ne crée aucune voie de promotion :
le gate de concentration reste fermé.

## Contrôles négatifs

Sont obligatoires :

- labels mélangés ;
- features aléatoires ;
- cotes décalées d’un match ;
- condition impossible ;
- règle triviale ;
- pattern construit après le résultat ;
- colonnes winner/loser ;
- test de performance parfaite.

Un contrôle négatif promu ou un signal robuste sur labels mélangés produit
`JALON_10_SCIENTIFIC_VALIDATION_FAILED`, pas une correction opportuniste des
seuils.

## Révision

Tout changement de seuil crée une nouvelle version du protocole et une nouvelle
famille d’hypothèses. Les seuils de V1 ne sont pas modifiés après lecture des
résultats.
