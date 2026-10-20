# Radar 2026-43

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
| betclic_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| winamax_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| unibet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |
| pmu_fr | 1 | 1 | 0 | 2.745% | 0.27 € | 2.745% | 0.27 € | — | 0.00 € |
| netbet_fr | 0 | 0 | 0 | — | 0.00 € | — | 0.00 € | — | 0.00 € |

## Première apparition par bande et horizon

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| pmu_fr | <30% | 24 | 1 | 1 | 0 |

## Détail par horizon (répétitions possibles)

| Book | Bande p juste | Premier horizon | EV+ n | ≥2% n | ≥5% n |
|---|---|---|---:|---:|---:|
| pmu_fr | <30% | 24 | 1 | 1 | 0 |
