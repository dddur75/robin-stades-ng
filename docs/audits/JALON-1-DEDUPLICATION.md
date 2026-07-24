# Rapport avant/après — déduplication Vague 2B

Date : 2026-07-24
Clé métier : `(match_id, marché neutre, combinaison de signal)`
Représentant canonique : ligne `home` unique du fixture

## Origine

Le moteur travaille au grain équipe-match, soit deux lignes par fixture. Les
marchés neutres — première mi-temps, total buts, cartons et BTTS — produisent une
seule issue au niveau du match. Lorsqu'un signal était vrai pour les deux équipes,
la même issue pouvait être comptée deux fois.

La correction ne repose pas sur un `drop_duplicates()` arbitraire :

1. la combinaison sélectionne les `match_id` éligibles ;
2. un marché neutre est ramené à la ligne canonique `home` ;
3. le moteur vérifie qu'il existe exactement un représentant par `match_id` ;
4. une jointure multi-fournisseur ambiguë provoque une erreur bloquante ;
5. les marchés équipe conservent leurs deux orientations légitimes.

## Résultats mesurés

| Mesure | Avant | Après |
|---|---:|---:|
| Tests statistiques | 13 420 | 13 152 |
| Tests sur marchés neutres | 6 672 | 6 396 |
| Résultats reportables | 525 | 374 |
| Évaluations brutes des marchés neutres après correction | — | 10 068 270 |
| Évaluations canoniques conservées | — | 8 857 908 |
| Doubles évaluations métier retirées | — | 1 210 362 |
| Ambiguïtés de représentant dans les données actuelles | non contrôlées | 0 |

Les volumes d'évaluations sont cumulés sur l'ensemble des hypothèses : une ligne
source peut participer à plusieurs tests. Ils mesurent l'impact statistique de la
correction, pas le nombre de matchs physiques.

Sur les clés présentes avant et après, la comparaison retire 1 224 438
observations répétées. L'écart avec le total direct provient des tests qui passent
ou non le seuil minimal après la correction temporelle arbitre.

## Enregistrements

- volume source : 36 423 matchs historiques ;
- doublons exacts de `match_id` : 0 ;
- doublons métier : deux orientations pour un même marché neutre ;
- enregistrements conservés : une observation canonique par fixture et test ;
- enregistrements versionnés : rapport historique avant correction conservé dans
  `rapports/`, rapport corrigé conservé sous `rapports/jalon1/vague2b-after/` ;
- enregistrements rejetés : représentants multiples ou absents ;
- ambiguïtés restantes observées : 0 dans le run corrigé.

## Conséquences

151 résultats auparavant reportables ne le sont plus. Tous les rapports Vague 2B
antérieurs restent consultables, mais sont classés `UNVERIFIED`. Le nouveau
rapport ne devient pas une preuve de rentabilité : les références sont encore
exploratoires et le holdout reste scellé.
