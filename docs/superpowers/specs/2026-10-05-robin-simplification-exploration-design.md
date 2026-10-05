# Robin — simplification et exploration autonome

## Autorité et résultat attendu

Cette spécification traduit le mandat consolidé `ROBIN_BOUCLE_SIMPLIFICATION_100.md`
dont le SHA-256 est
`cba3fd7074ca102fb629c5e1b1507412f53bbd1a680cc6307e0043f4a1e46dd9`.
Le mandat reste l'autorité en cas d'écart.

Le résultat livré doit réunir, dans la même boucle contrôlée :

1. un explorateur local utilisable sans terminal, copie manuelle ni prompt Codex ;
2. une comparaison descriptive reproductible de deux acquisitions réelles ;
3. une actualisation autonome, sûre et atomique depuis le canal GitHub existant ;
4. une CI simplifiée sans suppression de garantie ;
5. une recette R1–R8 avec preuves consultables sur la version intégrée.

Le collecteur cloud demeure indépendant du poste local. Aucun appel fournisseur,
backfill, achat, pari, promotion, publication sociale, accès holdout ou nouveau canal
public n'est autorisé par cette mission.

## Architecture retenue

### Modèle descriptif unique

`real_data_dashboard.py` porte une fonction pure qui compare deux acquisitions
normalisées. Une offre est identifiée par `sport_key`, `event_id`,
`bookmaker_key`, `market_key`, issue et seuil exact. Les doublons, prix invalides,
branches non comparables et instants non ordonnés sont exclus explicitement au lieu
d'être écrasés. Le résultat contient : anciennes et nouvelles cotes, delta,
direction, apparitions, non-observations, exclusions, dénominateur apparié et
ventilations ligue/bookmaker/marché avec offres appariées et matchs distincts.

Cette structure alimente l'interface, les exports et le rapport d'expérience. La
recette scientifique recalcule les mêmes grandeurs par une implémentation QA
indépendante, directement depuis les deux JSON gelés.

### Explorateur

L'exploration précède les distributions secondaires. Le même ensemble filtré sert
au tableau, aux compteurs et aux exports complets CSV/JSON, indépendamment de la
pagination. Les contrôles couvrent recherche équipe/match, ligue, bookmaker,
marché, acquisition, bornes de cote et variation, tri numérique et remise à zéro.
Les lignes affichent créneau, capture, source, coup d'envoi, cote ancienne/nouvelle,
delta, issue et seuil totals. Les états frais, ancien, incident, vide et marché
absent sont distincts.

### Actualisation locale

Un service Python standard local interroge GitHub par le client `gh` côté serveur :
aucun jeton n'atteint le navigateur. Il télécharge en staging, refuse tout reçu,
hash ou schéma incohérent, publie un dossier immuable versionné, puis bascule un
pointeur atomique. Le dossier précédent reste le dernier bon état. Le mode
`latest` recharge automatiquement une version validée ; le mode historique reste
épinglé. Un lanceur Windows durable ouvre la vue sans commande manuelle et permet
état, arrêt, reprise et diagnostic.

### CI

La suite complète ne dépend que des artefacts qu'elle consomme réellement. Elle
s'exécute en parallèle des profils Chronos et contrôles indépendants. Une clé finale
`quality-gate` exige explicitement chaque résultat, y compris la régression visuelle.
Les relances de domaines déjà incluses dans la suite complète sont retirées ; les
smokes non couverts restent. Le workflow historique dupliqué reste désactivé et le
test de contrat pointe sur SAFE V2.

## Baselines et cibles gelées

- CI : trois runs PR SAFE V2 comparables `37285435788`, `37257455182`,
  `37251657005`, même blob CI `c8b509d3` et requirements `fb75c5fa`; durées
  65,13 / 66,48 / 63,05 min, médiane 65,13 min.
- Cible CI : médiane de trois runs PR verts comparables au plus 45 min, gain absolu
  au moins 20,13 min, relatif au moins 30,9 %, tolérance bruit 5 min. La somme des
  minutes de jobs et le temps humain sont rapportés séparément.
- Vue : artifact réel attesté d'au moins 7 731 lignes ; ouverture interactive p95
  au plus 2 s et saisie-vers-affichage p95 au plus 100 ms sur 30 répétitions, aux
  largeurs 1366 px et 390 px, même poste et même corpus avant/après.
- Expérience : paire candidate 08:00Z–10:00Z du 2026-10-05, figée seulement après
  validation des reçus, hashes, branches et admissibilité descriptive. Elle est
  déclarée exposée et ne valide aucun edge ni causalité.

### Addendum R3 — témoins de fidélité Jalon 10

L'addendum `ROBIN_SIMPLIFICATION_R3_JALON10_20261005` autorise uniquement le rejeu
des règles gelées J10-M001, J10-M002 et J10-M003. La source logique reste la
révision historique `5c85cf20b932df44dca8665de00e52e3f1e02236`, l'arbre Parquet
`986010a776cb7c0f4948098660febea9577f159e` et le dataset
`3197b6cbe13dcbc4e851ad83550f4fed0741812df5eb4c386b2a52236a27d495`.
Le Parquet d'appartenance gelé est l'oracle avant simplification, après vérification
de son SHA-256 `95f5745803cd76d93bbd949debd5219723506838d15d3d8d034cb82bf710aeea`.
La mission R3 ne télécharge pas cet oracle : elle lit la copie locale déjà présente
dans le checkout principal ou l'artefact produit localement par le job gelé SAFE V2.
Son absence dans ces deux emplacements produit `PARTIAL`, jamais un substitut.

La comparaison est ordonnée par coup d'envoi puis identifiant de fixture. Identité,
marché, sélection, état de prix et règlement sont exacts. Les cotes, mises et profits
unitaires ont une tolérance absolue de `1e-12`; profits cumulés, profit total et
drawdown `1e-9` unité; ROI `1e-12`, sans tolérance relative. Ces bornes couvrent le
bruit float64 sur au plus 363 additions et restent très inférieures au centième
d'unité publié. Toute divergence inexpliquée bloque R3. Les sorties détaillées restent
hors Git; Git conserve leurs hashes, comptes, bornes et écarts maximaux.

Ces témoins sont des tests d'ingénierie sur un corpus déjà exposé. Ils ne constituent
ni une nouvelle recherche, ni une validation prospective, ni une promotion. Les
trois règles restent `EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING`, avec `q=1`, et
le verdict `JALON_10_NO_ROBUST_PATTERN_FOUND` est immuable dans cette mission.

## Recette figée

R1 à R8 sont ceux du §7 du mandat, sans compensation entre critères. Les preuves
doivent viser le commit effectivement intégré. Les 24 heures de R1 réconcilient tous
les créneaux attendus, pas une sélection rétrospective. Une modification du trajet
local exige une recette de ce trajet ; elle ne remet pas arbitrairement à zéro les
heures déjà acquises sur le collecteur inchangé.

## Sécurité immuable

Les huit verrous restent : `STORAGE_PAUSED=true`, `P3_P4_PAUSED=true`,
`PRODUCTION_LOCKED=true`, `REAL_BETS=false`, `NO_BET_DEFAULT=true`,
`PROMOTION_LOCKED=true`, `SOCIAL_PUBLISHING_ENABLED=false`,
`DEMO_MODE_ENABLED=false`.
