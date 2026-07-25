# Prévision API-Football et stockage

## Mesures de référence

| Mesure | Valeur observée |
|---|---:|
| Appels pilote | 1 354 |
| Secondes/appel fournisseur | 0,146 |
| Cadence bornée | environ 1 appel/s |
| Lignes/appel pilote | 8,027 |
| Pages joueurs observées | 39–46 |
| Appels/jour retenus | 30 000 |
| Réserve protégée | 5 000 |

## Correction Jalon 5.2

L’ancienne ETA de 0,20 jour portait uniquement sur les tâches déjà
matérialisées. Elle ne comptait pas les enfants par fixture, les enfants par
équipe ni les pages futures. Elle reste publiée sous l’étiquette
`MATERIALIZED_TASKS_ONLY`, mais n’est plus présentée comme ETA complète.

Le registre `historical-dependency-registry-v1` projette désormais :

- quatre endpoints par fixture canonique ;
- trois endpoints par équipe canonique ;
- la pagination réelle des joueurs ;
- les blessures comme endpoint paginé selon le contrat fournisseur ;
- les formats 18/20 équipes et la Ligue des champions multi-phase ;
- l’exclusion des barrages du dataset régulier Ligue 1.

## Scénarios

Les sorties versionnées exposent :

| Champ | Sens |
|---|---|
| `calls_remaining_low` | cache efficace, couverture minimale |
| `calls_remaining_base` | cardinalités et pagination observées |
| `calls_remaining_high` | couverture maximale et marge de reprise |
| `eta_priority_a_*` | fin de la priorité A |
| `eta_priority_b_*` | fin cumulée A+B |
| `eta_full_*` | fin de tout le périmètre |
| `storage_projected_*` | croissance gzip + Parquet projetée |

Le stockage déclenche un warning à 750 MB et une pause à 900 MB. Aucune
augmentation de cadence, aucun achat de quota et aucun achat de stockage ne
sont automatiques.

## Mesure après le run 30154099512

| Mesure | Bas | Central | Haut |
|---|---:|---:|---:|
| Appels restants | 47 417 | 63 313 | 69 977 |
| ETA priorité A | 0,19 j | 0,26 j | 0,28 j |
| ETA priorité B cumulée | 0,87 j | 1,16 j | 1,28 j |
| ETA globale | 1,58 j | 2,11 j | 2,33 j |
| Stockage projeté restauré | 227 877 811 o | 427 181 466 o | 665 300 478 o |

Le plan contient 6 222 tâches matérialisées : 2 655 terminées et 3 567
restantes. L’ETA de ces seules tâches est 0,11 jour et reste explicitement
étiquetée `MATERIALIZED_TASKS_ONLY`.

Le travail latent central comprend 55 344 tâches fixture, 3 036 tâches équipe
et 1 677 pages joueurs, soit 60 057 appels latents. Le scénario central total
ajoute les 3 256 appels matérialisés restants. La croissance physique observée
sur le lot est 5 716,8 octets par appel.
