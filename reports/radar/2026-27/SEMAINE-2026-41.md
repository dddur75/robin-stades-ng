# Radar 2026-41

Statut **PARTIAL** — papier uniquement ; décision le 17/11/2026.
Claim source : `DATA.CLV202627.CUMUL.V1` ; dérivation : `DATA.RADAR202627.PAPER.V1` ; EV directe : `DATA.RADAR202627.DIRECT.V1`.
Borne demandée : 2026-10-19 ; dernière journée de matchs disponible : 2026-10-19.
Période depuis le 03/10 ; semaines ISO des coups d'envoi UTC. Couverture R2 non établie.
Stock global : 3141 lignes horizon, 2691 EV calculables,
450 lignes non calculables ; 0 boosts manuels.

EV = prix FR × p juste Pinnacle clôture − 1 ; p juste = (1/cote) / somme(1/cote) sur 1,N,2.
La clôture est la dernière observation complète disponible avant le match, parfois distante.
EV+ signifie strictement >0 (zéro exclu) ; ≥2% et ≥5% inclusifs à 1e−12 près.
Pour chaque seuil : une seule opportunité par match/issue/book, au premier franchissement.
Les seuils se recouvrent : ne pas additionner leurs comptes ni leurs gains.
EV moyenne et gain sont ceux des prix au premier franchissement du seuil concerné.
Gain = somme(10 € × EV), hypothétique brut ; aucun pari ni résultat réalisé.
Pour un boost limité à <10 €, le gain fixe reste théorique et non éligible :
`BOOSTS.csv` expose `gain_10_eligible` et `gain_capped` à min(10 €, mise max).
Les détails par horizon ne constituent pas des opportunités supplémentaires.
Les boosts et prix standards sont dédupliqués ensemble dans le total ; leur détail reste séparé.
Fenêtres du moteur CLV : ±6h à T−48/T−24, ±90min à T−2, toujours avant coup d'envoi.
EV clôture est rétrospective. EV_direct = prix FR × fair Pinnacle du relevé contemporain − 1.
Référence directe : triplet 1N2 complet le plus proche à ±15 min inclusives, antérieur en cas d'égalité.
Le fair de clôture n'est jamais utilisé en remplacement d'un fair direct manquant.
Les deux timestamps et l'écart signé sont exportés ; un écart positif utilise la tolérance +15 min demandée.
Observations et ingestions Pinnacle doivent précéder le coup d'envoi et être disponibles au plus tard FR+15 min.
Bande directe selon p_fair_direct ; seuils et premiers franchissements calculés séparément pour chaque mesure.
Confirmation par seuil direct : prix du premier franchissement direct encore EV>0 contre la clôture,
confirmées / clôtures connues ; clôtures absentes séparées, taux N/C si aucune clôture connue.
Zéro opportunité observée sans fair direct disponible ne prouve pas l'absence d'opportunité.
Traçabilité : `SOURCES.json`, CSV détaillés et [couverture CLV](../../clv/2026-27/COVERAGE.md).
Boosts : aucun label observable dans les exports CLV ; absence dans les flux non démontrée.
Voir [audit et sources](../../../docs/RADAR-2026-27.md).
Aucun chiffre sur une semaine sans données ne prouve une absence de prix EV+.

## Opportunités uniques par book

| Book | EV+ n | ≥2% n | ≥5% n | EV moy. EV+ | Gain 10€ EV+ | EV moy. ≥2% | Gain ≥2% | EV moy. ≥5% | Gain ≥5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| betclic_fr | 15 | 8 | 3 | 4.876% | 7.31 € | 8.589% | 6.87 € | 18.685% | 5.61 € |
| winamax_fr | 16 | 10 | 5 | 6.123% | 9.80 € | 9.411% | 9.41 € | 15.920% | 7.96 € |
| unibet_fr | 9 | 4 | 3 | 7.476% | 6.73 € | 15.809% | 6.32 € | 20.186% | 6.06 € |
| pmu_fr | 1 | 0 | 0 | 0.558% | 0.06 € | — | 0.00 € | — | 0.00 € |
| netbet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |

## EV_direct et EV clôture — comparaison par book

| Book | Clôture >0 | Clôture ≥2% | Clôture ≥5% | Direct >0 | Direct ≥2% | Direct ≥5% | Relevés directs calculables / lignes |
|---|---:|---:|---:|---:|---:|---:|---:|
| betclic_fr | 15 | 8 | 3 | 0 | 0 | 0 | 384 / 387 |
| winamax_fr | 16 | 10 | 5 | 3 | 0 | 0 | 393 / 396 |
| unibet_fr | 9 | 4 | 3 | 1 | 1 | 0 | 384 / 387 |
| pmu_fr | 1 | 0 | 0 | 0 | 0 | 0 | 48 / 144 |
| netbet_fr | 0 | 0 | 0 | N/C | N/C | N/C | 0 / 0 |
| TOTAL | 41 | 22 | 11 | 4 | 1 | 0 | 1209 / 1314 |

### EV_direct — moyennes et gains théoriques

| Book | EV+ n | ≥2% n | ≥5% n | EV moy. EV+ | Gain 10€ EV+ | EV moy. ≥2% | Gain ≥2% | EV moy. ≥5% | Gain ≥5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| betclic_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| winamax_fr | 3 | 0 | 0 | 0.962% | 0.29 € | — | 0.00 € | — | 0.00 € |
| unibet_fr | 1 | 1 | 0 | 4.698% | 0.47 € | 4.698% | 0.47 € | — | 0.00 € |
| pmu_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| netbet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |

### Confirmation EV_direct à la clôture

| Book | Seuil direct | Opportunités directes | Confirmées / clôtures connues | Clôtures absentes | Confirmation |
|---|---|---:|---:|---:|---:|
| betclic_fr | >0 | 0 | 0 / 0 | 0 | N/C |
| betclic_fr | ≥2% | 0 | 0 / 0 | 0 | N/C |
| betclic_fr | ≥5% | 0 | 0 / 0 | 0 | N/C |
| winamax_fr | >0 | 3 | 3 / 3 | 0 | 100.0% |
| winamax_fr | ≥2% | 0 | 0 / 0 | 0 | N/C |
| winamax_fr | ≥5% | 0 | 0 / 0 | 0 | N/C |
| unibet_fr | >0 | 1 | 1 / 1 | 0 | 100.0% |
| unibet_fr | ≥2% | 1 | 1 / 1 | 0 | 100.0% |
| unibet_fr | ≥5% | 0 | 0 / 0 | 0 | N/C |
| pmu_fr | >0 | 0 | 0 / 0 | 0 | N/C |
| pmu_fr | ≥2% | 0 | 0 / 0 | 0 | N/C |
| pmu_fr | ≥5% | 0 | 0 / 0 | 0 | N/C |
| netbet_fr | >0 | 0 | 0 / 0 | 0 | N/C |
| netbet_fr | ≥2% | 0 | 0 / 0 | 0 | N/C |
| netbet_fr | ≥5% | 0 | 0 / 0 | 0 | N/C |
| TOTAL | >0 | 4 | 4 / 4 | 0 | 100.0% |
| TOTAL | ≥2% | 1 | 1 / 1 | 0 | 100.0% |
| TOTAL | ≥5% | 0 | 0 / 0 | 0 | N/C |

### EV_direct — première apparition par bande et horizon

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| unibet_fr | <30% | 2 | 1 | 1 | 0 |
| winamax_fr | <30% | 2 | 2 | 0 | 0 |
| winamax_fr | <30% | 48 | 1 | 0 | 0 |

### EV_direct — détail par horizon (répétitions possibles)

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| unibet_fr | <30% | 2 | 1 | 1 | 0 |
| winamax_fr | <30% | 2 | 2 | 0 | 0 |
| winamax_fr | <30% | 24 | 1 | 0 | 0 |
| winamax_fr | <30% | 48 | 1 | 0 | 0 |

## Première apparition par bande et horizon

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| betclic_fr | 30-45% | 24 | 2 | 1 | 0 |
| betclic_fr | 30-45% | 48 | 1 | 0 | 0 |
| betclic_fr | 45-60% | 24 | 1 | 0 | 0 |
| betclic_fr | <30% | 2 | 2 | 1 | 1 |
| betclic_fr | <30% | 24 | 3 | 2 | 0 |
| betclic_fr | <30% | 48 | 6 | 4 | 2 |
| pmu_fr | 30-45% | 2 | 1 | 0 | 0 |
| unibet_fr | 30-45% | 48 | 1 | 0 | 0 |
| unibet_fr | <30% | 2 | 1 | 1 | 1 |
| unibet_fr | <30% | 24 | 3 | 1 | 0 |
| unibet_fr | <30% | 48 | 4 | 2 | 2 |
| winamax_fr | 30-45% | 24 | 1 | 0 | 0 |
| winamax_fr | 30-45% | 48 | 1 | 0 | 0 |
| winamax_fr | <30% | 2 | 1 | 0 | 0 |
| winamax_fr | <30% | 24 | 3 | 2 | 2 |
| winamax_fr | <30% | 48 | 10 | 8 | 3 |

## Détail par horizon (répétitions possibles)

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| betclic_fr | 30-45% | 2 | 1 | 0 | 0 |
| betclic_fr | 30-45% | 24 | 3 | 1 | 0 |
| betclic_fr | 30-45% | 48 | 1 | 0 | 0 |
| betclic_fr | 45-60% | 24 | 1 | 0 | 0 |
| betclic_fr | <30% | 2 | 4 | 3 | 2 |
| betclic_fr | <30% | 24 | 9 | 5 | 2 |
| betclic_fr | <30% | 48 | 6 | 4 | 2 |
| pmu_fr | 30-45% | 2 | 1 | 0 | 0 |
| unibet_fr | 30-45% | 24 | 1 | 0 | 0 |
| unibet_fr | 30-45% | 48 | 1 | 0 | 0 |
| unibet_fr | <30% | 2 | 4 | 2 | 2 |
| unibet_fr | <30% | 24 | 6 | 3 | 1 |
| unibet_fr | <30% | 48 | 4 | 2 | 2 |
| winamax_fr | 30-45% | 24 | 2 | 0 | 0 |
| winamax_fr | 30-45% | 48 | 1 | 0 | 0 |
| winamax_fr | <30% | 2 | 8 | 4 | 2 |
| winamax_fr | <30% | 24 | 11 | 8 | 4 |
| winamax_fr | <30% | 48 | 10 | 8 | 3 |
