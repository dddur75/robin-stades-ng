# Radar de prix 2026-27 — cumul

Statut **PARTIAL** — papier uniquement ; décision le 17/11/2026.
Claim source : `DATA.CLV202627.CUMUL.V1` ; dérivation : `DATA.RADAR202627.PAPER.V1`.
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
Une cote positive contre la clôture future est un constat rétrospectif, pas un signal disponible en direct.
Traçabilité : `SOURCES.json`, CSV détaillés et [couverture CLV](../../clv/2026-27/COVERAGE.md).
Boosts : aucun label observable dans les exports CLV ; absence dans les flux non démontrée.
Voir [audit et sources](../../../docs/RADAR-2026-27.md).
Aucun chiffre sur une semaine sans données ne prouve une absence de prix EV+.

## Opportunités uniques par book

| Book | EV+ n | ≥2% n | ≥5% n | EV moy. EV+ | Gain 10€ EV+ | EV moy. ≥2% | Gain ≥2% | EV moy. ≥5% | Gain ≥5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| betclic_fr | 25 | 12 | 5 | 4.115% | 10.29 € | 7.903% | 9.48 € | 15.302% | 7.65 € |
| winamax_fr | 23 | 13 | 7 | 5.469% | 12.58 € | 8.971% | 11.66 € | 14.257% | 9.98 € |
| unibet_fr | 16 | 9 | 5 | 6.174% | 9.88 € | 10.309% | 9.28 € | 16.185% | 8.09 € |
| pmu_fr | 10 | 3 | 2 | 3.357% | 3.36 € | 9.735% | 2.92 € | 13.229% | 2.65 € |
| netbet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |

## Première apparition par bande et horizon

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| betclic_fr | 30-45% | 24 | 3 | 1 | 0 |
| betclic_fr | 30-45% | 48 | 1 | 0 | 0 |
| betclic_fr | 45-60% | 24 | 4 | 1 | 0 |
| betclic_fr | <30% | 2 | 2 | 1 | 1 |
| betclic_fr | <30% | 24 | 4 | 2 | 0 |
| betclic_fr | <30% | 48 | 11 | 7 | 4 |
| pmu_fr | 30-45% | 2 | 2 | 0 | 0 |
| pmu_fr | 30-45% | 24 | 1 | 0 | 0 |
| pmu_fr | 45-60% | 48 | 2 | 0 | 0 |
| pmu_fr | <30% | 24 | 1 | 1 | 0 |
| pmu_fr | <30% | 48 | 3 | 2 | 2 |
| pmu_fr | >=60% | 48 | 1 | 0 | 0 |
| unibet_fr | 30-45% | 48 | 1 | 0 | 0 |
| unibet_fr | 45-60% | 24 | 2 | 0 | 0 |
| unibet_fr | <30% | 2 | 2 | 2 | 1 |
| unibet_fr | <30% | 24 | 4 | 2 | 0 |
| unibet_fr | <30% | 48 | 7 | 5 | 4 |
| winamax_fr | 30-45% | 24 | 1 | 0 | 0 |
| winamax_fr | 30-45% | 48 | 1 | 0 | 0 |
| winamax_fr | 45-60% | 24 | 2 | 0 | 0 |
| winamax_fr | 45-60% | 48 | 1 | 0 | 0 |
| winamax_fr | <30% | 2 | 1 | 0 | 0 |
| winamax_fr | <30% | 24 | 3 | 2 | 2 |
| winamax_fr | <30% | 48 | 14 | 11 | 5 |

## Boosts seuls

| Book | EV+ n | ≥2% n | ≥5% n | EV moy. EV+ | Gain 10€ EV+ | EV moy. ≥2% | Gain ≥2% | EV moy. ≥5% | Gain ≥5% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| betclic_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| winamax_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| unibet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| pmu_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| netbet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |

## Semaines

- [2026-40](SEMAINE-2026-40.md)
- [2026-41](SEMAINE-2026-41.md)
- [2026-42](SEMAINE-2026-42.md)
- [2026-43](SEMAINE-2026-43.md)
