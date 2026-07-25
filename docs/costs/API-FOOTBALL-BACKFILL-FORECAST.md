# Prévision API-Football et stockage

## Mesure Jalon 5.1

| Mesure | Valeur observée |
|---|---:|
| Appels pilote | 1 354 |
| Durée | 197,683 s |
| Secondes/appel | 0,146 |
| Lignes/appel | 8,027 |
| Octets compressés/appel | 1 857 |
| Appels/fixture | 4,368 |
| Appels/jour retenus | 30 000 |
| ETA priorité A | 3 jours |
| ETA priorité B | 8 jours |
| ETA globale | 10 jours |

La projection haute reste 63 638 appels. La réserve protégée est 5 000 ; aucun
achat de crédit n’est autorisé.

Les appels réels du pilote détermineront la projection finale. Avant mesure, les
bornes de planification sont :

| Périmètre | Appels planchers | Appels profonds estimés |
|---|---:|---:|
| Ligue 1 2025 | 7 | 1 300–1 500 |
| Ligue 1, 8 saisons | 88 | 9 000–12 000 |
| 6 compétitions, 4 saisons | 264 | 28 000–40 000 |
| 6 compétitions, 8 saisons | 528 | 50 000–75 000 |

Le plan `ACCELERATED` conserve toujours une réserve configurable de 100 appels.
Le volume réel gzip, Parquet et PostgreSQL est mesuré après chaque lot. Aucun
achat de quota, stockage ou calcul n’est automatisé.
