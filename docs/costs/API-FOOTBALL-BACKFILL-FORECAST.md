# Prévision API-Football et stockage

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

