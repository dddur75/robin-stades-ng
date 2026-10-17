# 028-robin-stades-ng — compositions et statistiques des petites ligues

**Projet :** Robin des Stades NG
**Construit :** Codex · **Relit :** Claude · **Valide :** David
**Statut :** À faire
**Acceptée le :** —
**Dépend de :** 027 phase 1 (même chaîne de collecte, mêmes garde-fous)

## Ce que veut David (3 lignes max, ses mots)

« l'idée maintenant, c'est intégrer le plus de match et de donnée possible. Y a
crédits illimité, je peux ajouter du budget. […] si nous voulions faire de la
longue traine, il fallait aller sur les petites ligues » (projet QG, 2026-10-17, 3 h 43).

## Prérequis

- Mêmes prérequis que la 027 : clé `API_FOOTBALL_KEY` vérifiée par le reçu de prévol
  de la 027 s'il a moins de 110 minutes, sinon un seul `/status` ; collecte des cotes,
  `prospective-deep-scheduler.yml`, robin-core et saison 2025 intouchés.
- Aucune dépense nouvelle : tout tient dans le quota existant (plan Mega,
  150 000 appels par jour, actif jusqu'au 2026-11-25). Tout achat ou changement de
  plan reste une décision de David (liste C).

## Ce qu'il faut collecter

**Périmètre.** Les 33 ligues hors top 5 européen de la base Football-Data de
l'assistant (divisions 2 à 5 anglaises et écossaises, D2, I2, SP2, F2, Pays-Bas,
Belgique, Portugal, Turquie, Grèce, et les 16 ligues « extra » : Argentine, Autriche,
Brésil, Chine, Danemark, Finlande, Irlande, Japon, Mexique, Norvège, Pologne,
Roumanie, Russie, Suède, Suisse, USA), saisons 2019-20 à 2024-25. Environ
60 500 matchs sur 198 saisons de ligue. Pourquoi ces ligues : ce sont les seules
petites ligues pour lesquelles on possède des cotes de clôture historiques, donc
les seules où une hypothèse peut être backtestée en rentabilité.

**Population figée (ne pas la reconstruire).** `file/028/cibles-028.csv` dans ce dépôt
`qg` : 60 515 matchs, 33 ligues, 198 saisons de ligue, du 2019-07-01 au 2025-06-01.
SHA-256 du fichier : `8cee89679b043fc9929a15c01bac538da2302f50fdbfc58117bc83b58092c17b`.
Colonnes : `ligue_fd, saison_fd, date, equipe_dom_fd, equipe_ext_fd, buts_dom, buts_ext`
(codes et noms d'équipe exactement comme chez Football-Data ; les buts servent à
contrôler le rapprochement). Origine : fichiers publics Football-Data
`mmz4281/<saison>/<code>.csv` (divisions E1, E2, E3, EC, SC0-SC3, D2, I2, SP2, F2, N1,
B1, P1, T1, G1) et `new/<pays>.csv` (ARG, AUT, BRA, CHN, DNK, FIN, IRL, JPN, MEX, NOR,
POL, ROU, RUS, SWE, SWZ, USA), matchs avec cotes de clôture, date ≥ 2019-07-01,
saisons 2025-26 et calendaires 2025 exclues. Copier ce fichier tel quel dans
`configs/execution/mission028-targets.csv` et vérifier l'empreinte avant tout appel.

**Phase 1 — correspondance (≈ 200 appels).** Un appel `/fixtures?league=&season=` par
saison de ligue pour obtenir les identifiants API-Football, puis rapprochement
avec chaque ligne de `cibles-028.csv` par date (± 1 jour), noms d'équipes et score final. Livrable : table de correspondance
avec taux de rapprochement par ligue (objectif ≥ 97 %), sans autre appel.

**Phase 2 — compositions (≈ 60 500 appels).** `/fixtures/lineups`, un appel par match,
jamais deux fois le même, comme la 027.

**Phase 3 — statistiques de match (≈ 60 500 appels).** `/fixtures/statistics` (tirs,
tirs cadrés, possession, corners, cartons, et xG quand le fournisseur le donne), un
appel par match.

**Plafonds.** 200 + 61 000 + 61 000 = 122 200 appels au total, jamais plus de
70 000 par jour UTC, réserve de 5 000 appels gardée chaque jour ; arrêt propre au
plafond. Sortie : mêmes partitions Parquet que la 027 (`entity_type=lineups` et
`entity_type=statistics`), réponses brutes selon le contrat append-only.

## Définition de « terminé »

- [ ] Table de correspondance livrée, ≥ 97 % des matchs rapprochés par ligue, écarts listés.
- [ ] ≥ 95 % des matchs rapprochés ont une composition des deux équipes (formation + 11 titulaires).
- [ ] ≥ 90 % ont des statistiques de match.
- [ ] Reçu par phase : appels, matchs distincts (égaux à 1 % près), quota au point bas, empreinte de la liste.
- [ ] Tests ciblés : plafond par jour, réserve, exclusion de la saison 2025, aucun double appel.

## Hors périmètre

- Cotes historiques (API-Football ne les a pas), absences, statistiques joueur par joueur.
- Toute analyse : faite ensuite par l'assistant (usine à hypothèses, projet QG).
- Aucun pari, aucune promotion, aucune publication, aucun achat.

## Pourquoi

L'usine à hypothèses de l'assistant tourne sur 120 446 matchs de 38 ligues, mais
la profondeur « composition / formation / statistiques » n'existe que pour les 5
grands championnats. Les petites ligues sont celles où David veut chercher la
longue traîne ; sans leurs compositions, les croisements profonds y sont impossibles.

## À coller dans Codex

```
Mission 028 du QG (dépôt dddur75/qg, fichier file/028-robin-stades-ng-petites-ligues.md).
Lis la spec en entier, puis AGENTS.md de robin-stades-ng. Réutilise la chaîne de la mission 027.
Branche tache-028-petites-ligues, PR « 028 — phase N — … », 400 lignes de code au plus par PR,
corps commençant par « Construit par : Codex ».
Phase 1 : correspondance Football-Data ↔ API-Football (≈ 200 appels /fixtures?league&season).
Phase 2 : /fixtures/lineups, un appel par match. Phase 3 : /fixtures/statistics, un appel par match.
Plafond total 122 200 appels, 70 000 par jour UTC au plus, réserve 5 000 chaque jour.
Ne touche ni à prospective-deep-scheduler.yml, ni à la collecte des cotes, ni à robin-core, ni à la saison 2025.
Bloqué deux fois : fiche d'escalade de 5 lignes dans la PR, puis continue ce qui ne dépend pas du blocage.
```

## Relecture de Claude

- Tour 1 :
- Tour 2 :

## Résumé de fin (10 lignes max)

- Fait :
- Reste :
- Risques :
