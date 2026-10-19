# CLV papier 2026-27 — cumul

Statut : PARTIAL — stock local traité ; exhaustivité du stock durable non établie.
Claim : `DATA.CLV202627.CUMUL.V1`. Voir `COVERAGE.md` pour l'inventaire de livraison.

Période des coups d'envoi UTC : 2026-07-01 → 2026-10-19 inclus.
Observations disponibles avant la borne : 2026-10-03T20:53:57+00:00 → 2026-10-19T20:26:30+00:00.
Sources locales : 270 fichiers ; 8 journées avec matchs ;
3141 lignes book × issue × horizon ; 2691 CLV calculables.
Matchs exclus pour preuve contradictoire : 1 (`EXCLUSIONS.csv`).
MISSING_HORIZON : 450 / 3141 lignes.
Traçabilité : `SOURCES.json` (SHA-256 de chaque entrée). Aucune collecte nouvelle.

## Méthode et limites

Le moteur `robin.clv.load/calculate/summarize` est réutilisé sans modifier les fenêtres,
le fair de clôture ni la définition de late. Une observation répétée ne multiplie pas
les lignes ; toute contradiction de prix ou de coup d'envoi exclut le match entier,
avec motif et horaires dans `EXCLUSIONS.csv`, sans choisir une version des faits.
Les journées sont celles des matchs, pas celles des captures. Les données hors
saison/borne sont exclues ; une journée avec seulement Pinnacle a des CSV à en-tête.
`n` compte les CLV calculables ; IC95 Student, vide pour n < 2. CLV et IC affichés
ici en pourcentage, CSV en ratios. `late n` compte uniquement late=True avec CLV
calculable. Part MISSING_HORIZON = nombre de ces statuts / toutes les lignes du
groupe (y compris les autres statuts manquants). INCONNUE = fair de clôture absent.
Un book absent d'un match ne produit aucune ligne : le dénominateur n'est pas
une mesure de couverture de tous les books sur tous les matchs.
Les IC sont descriptifs : dépendances entre issues, books et horizons non corrigées.
La clôture est la dernière observation Pinnacle complète disponible, parfois éloignée
du coup d'envoi. Ces chiffres ne prouvent aucun edge ni rendement réalisable.

## 10 plus forts CLV moyens, n ≥ 30

| Book FR | Bande | Horizon | n | CLV moyen | IC95 | late n | late CLV moyen | MISSING_HORIZON / total | Part |
|---|---|---|---:|---:|---|---:|---:|---:|---:|
| betclic_fr | 45-60% | T−24 h | 37 | -5.907% | [-7.408% ; -4.407%] | 0 | — | 0 / 37 | 0.000% |
| betclic_fr | 30-45% | T−2 h | 43 | -6.755% | [-7.521% ; -5.988%] | 0 | — | 20 / 63 | 31.746% |
| winamax_fr | 45-60% | T−48 h | 38 | -6.943% | [-8.519% ; -5.367%] | 0 | — | 0 / 38 | 0.000% |
| winamax_fr | 45-60% | T−24 h | 38 | -7.060% | [-8.426% ; -5.694%] | 0 | — | 0 / 38 | 0.000% |
| betclic_fr | <30% | T−2 h | 112 | -7.180% | [-8.088% ; -6.273%] | 0 | — | 45 / 157 | 28.662% |
| betclic_fr | 45-60% | T−48 h | 37 | -7.317% | [-8.952% ; -5.683%] | 0 | — | 0 / 37 | 0.000% |
| betclic_fr | 30-45% | T−24 h | 63 | -7.671% | [-8.764% ; -6.578%] | 0 | — | 0 / 63 | 0.000% |
| unibet_fr | 45-60% | T−24 h | 36 | -7.843% | [-9.442% ; -6.244%] | 0 | — | 0 / 36 | 0.000% |
| betclic_fr | <30% | T−24 h | 157 | -7.847% | [-8.931% ; -6.764%] | 0 | — | 0 / 157 | 0.000% |
| pmu_fr | 30-45% | T−24 h | 37 | -8.447% | [-9.812% ; -7.082%] | 0 | — | 7 / 44 | 15.909% |

## Cumul complet

| Book FR | Bande | Horizon | n | CLV moyen | IC95 | late n | late CLV moyen | MISSING_HORIZON / total | Part |
|---|---|---|---:|---:|---|---:|---:|---:|---:|
| betclic_fr | <30% | T−48 h | 156 | -8.457% | [-9.642% ; -7.271%] | 0 | — | 1 / 157 | 0.637% |
| betclic_fr | <30% | T−24 h | 157 | -7.847% | [-8.931% ; -6.764%] | 0 | — | 0 / 157 | 0.000% |
| betclic_fr | <30% | T−2 h | 112 | -7.180% | [-8.088% ; -6.273%] | 0 | — | 45 / 157 | 28.662% |
| betclic_fr | 30-45% | T−48 h | 61 | -8.463% | [-9.517% ; -7.408%] | 0 | — | 2 / 63 | 3.175% |
| betclic_fr | 30-45% | T−24 h | 63 | -7.671% | [-8.764% ; -6.578%] | 0 | — | 0 / 63 | 0.000% |
| betclic_fr | 30-45% | T−2 h | 43 | -6.755% | [-7.521% ; -5.988%] | 0 | — | 20 / 63 | 31.746% |
| betclic_fr | 45-60% | T−48 h | 37 | -7.317% | [-8.952% ; -5.683%] | 0 | — | 0 / 37 | 0.000% |
| betclic_fr | 45-60% | T−24 h | 37 | -5.907% | [-7.408% ; -4.407%] | 0 | — | 0 / 37 | 0.000% |
| betclic_fr | 45-60% | T−2 h | 26 | -5.642% | [-6.437% ; -4.848%] | 0 | — | 11 / 37 | 29.730% |
| betclic_fr | >=60% | T−48 h | 25 | -7.722% | [-8.905% ; -6.540%] | 0 | — | 0 / 25 | 0.000% |
| betclic_fr | >=60% | T−24 h | 25 | -7.110% | [-8.138% ; -6.082%] | 0 | — | 0 / 25 | 0.000% |
| betclic_fr | >=60% | T−2 h | 17 | -5.957% | [-6.781% ; -5.132%] | 0 | — | 8 / 25 | 32.000% |
| betclic_fr | INCONNUE | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| betclic_fr | INCONNUE | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| betclic_fr | INCONNUE | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| winamax_fr | <30% | T−48 h | 158 | -9.090% | [-10.574% ; -7.605%] | 0 | — | 1 / 159 | 0.629% |
| winamax_fr | <30% | T−24 h | 159 | -9.185% | [-10.534% ; -7.837%] | 0 | — | 0 / 159 | 0.000% |
| winamax_fr | <30% | T−2 h | 114 | -9.544% | [-11.019% ; -8.069%] | 0 | — | 45 / 159 | 28.302% |
| winamax_fr | 30-45% | T−48 h | 61 | -9.443% | [-10.490% ; -8.397%] | 0 | — | 2 / 63 | 3.175% |
| winamax_fr | 30-45% | T−24 h | 63 | -9.419% | [-10.632% ; -8.205%] | 0 | — | 0 / 63 | 0.000% |
| winamax_fr | 30-45% | T−2 h | 43 | -9.061% | [-10.026% ; -8.097%] | 0 | — | 20 / 63 | 31.746% |
| winamax_fr | 45-60% | T−48 h | 38 | -6.943% | [-8.519% ; -5.367%] | 0 | — | 0 / 38 | 0.000% |
| winamax_fr | 45-60% | T−24 h | 38 | -7.060% | [-8.426% ; -5.694%] | 0 | — | 0 / 38 | 0.000% |
| winamax_fr | 45-60% | T−2 h | 27 | -7.426% | [-8.111% ; -6.742%] | 0 | — | 11 / 38 | 28.947% |
| winamax_fr | >=60% | T−48 h | 25 | -7.563% | [-8.778% ; -6.349%] | 0 | — | 0 / 25 | 0.000% |
| winamax_fr | >=60% | T−24 h | 25 | -7.789% | [-8.761% ; -6.818%] | 0 | — | 0 / 25 | 0.000% |
| winamax_fr | >=60% | T−2 h | 17 | -7.131% | [-7.924% ; -6.339%] | 0 | — | 8 / 25 | 32.000% |
| winamax_fr | INCONNUE | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| winamax_fr | INCONNUE | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| winamax_fr | INCONNUE | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| unibet_fr | <30% | T−48 h | 154 | -10.127% | [-11.420% ; -8.833%] | 0 | — | 1 / 155 | 0.645% |
| unibet_fr | <30% | T−24 h | 155 | -8.856% | [-9.992% ; -7.721%] | 0 | — | 0 / 155 | 0.000% |
| unibet_fr | <30% | T−2 h | 112 | -9.041% | [-10.212% ; -7.871%] | 1 | 21.877% | 43 / 155 | 27.742% |
| unibet_fr | 30-45% | T−48 h | 61 | -10.070% | [-11.134% ; -9.006%] | 0 | — | 2 / 63 | 3.175% |
| unibet_fr | 30-45% | T−24 h | 63 | -9.529% | [-10.625% ; -8.433%] | 0 | — | 0 / 63 | 0.000% |
| unibet_fr | 30-45% | T−2 h | 43 | -8.977% | [-10.071% ; -7.884%] | 0 | — | 20 / 63 | 31.746% |
| unibet_fr | 45-60% | T−48 h | 36 | -8.631% | [-10.358% ; -6.903%] | 0 | — | 0 / 36 | 0.000% |
| unibet_fr | 45-60% | T−24 h | 36 | -7.843% | [-9.442% ; -6.244%] | 0 | — | 0 / 36 | 0.000% |
| unibet_fr | 45-60% | T−2 h | 26 | -7.774% | [-8.507% ; -7.042%] | 0 | — | 10 / 36 | 27.778% |
| unibet_fr | >=60% | T−48 h | 25 | -8.599% | [-9.807% ; -7.391%] | 0 | — | 0 / 25 | 0.000% |
| unibet_fr | >=60% | T−24 h | 25 | -8.431% | [-9.390% ; -7.471%] | 0 | — | 0 / 25 | 0.000% |
| unibet_fr | >=60% | T−2 h | 17 | -7.946% | [-8.838% ; -7.054%] | 0 | — | 8 / 25 | 32.000% |
| unibet_fr | INCONNUE | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| unibet_fr | INCONNUE | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| unibet_fr | INCONNUE | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| pmu_fr | <30% | T−48 h | 78 | -11.347% | [-12.989% ; -9.705%] | 0 | — | 34 / 112 | 30.357% |
| pmu_fr | <30% | T−24 h | 83 | -10.103% | [-11.350% ; -8.856%] | 0 | — | 29 / 112 | 25.893% |
| pmu_fr | <30% | T−2 h | 67 | -9.117% | [-9.854% ; -8.380%] | 0 | — | 45 / 112 | 40.179% |
| pmu_fr | 30-45% | T−48 h | 32 | -9.176% | [-10.441% ; -7.912%] | 0 | — | 12 / 44 | 27.273% |
| pmu_fr | 30-45% | T−24 h | 37 | -8.447% | [-9.812% ; -7.082%] | 0 | — | 7 / 44 | 15.909% |
| pmu_fr | 30-45% | T−2 h | 24 | -7.811% | [-9.549% ; -6.073%] | 0 | — | 20 / 44 | 45.455% |
| pmu_fr | 45-60% | T−48 h | 20 | -7.224% | [-9.861% ; -4.586%] | 0 | — | 10 / 30 | 33.333% |
| pmu_fr | 45-60% | T−24 h | 21 | -6.399% | [-8.289% ; -4.508%] | 0 | — | 9 / 30 | 30.000% |
| pmu_fr | 45-60% | T−2 h | 19 | -6.977% | [-8.030% ; -5.924%] | 0 | — | 11 / 30 | 36.667% |
| pmu_fr | >=60% | T−48 h | 11 | -7.468% | [-10.192% ; -4.743%] | 0 | — | 4 / 15 | 26.667% |
| pmu_fr | >=60% | T−24 h | 12 | -6.188% | [-7.774% ; -4.602%] | 0 | — | 3 / 15 | 20.000% |
| pmu_fr | >=60% | T−2 h | 7 | -6.481% | [-7.337% ; -5.626%] | 0 | — | 8 / 15 | 53.333% |
| pmu_fr | INCONNUE | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| pmu_fr | INCONNUE | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| pmu_fr | INCONNUE | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | <30% | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | <30% | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | <30% | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 30-45% | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 30-45% | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 30-45% | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 45-60% | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 45-60% | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | 45-60% | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | >=60% | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | >=60% | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | >=60% | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | INCONNUE | T−48 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | INCONNUE | T−24 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
| netbet_fr | INCONNUE | T−2 h | 0 | — | [— ; —] | 0 | — | 0 / 0 | — |
