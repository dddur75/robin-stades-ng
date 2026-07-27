# Registre des décisions

## 2026-07-25 — Isolation et accélération historique

Statut : `VERIFIED`.

Le live conserve `shadow-data` / `shadow-state`; l’historique utilise
`historical-data` / `historical-state`. Le backfill passe à
`ACCELERATED_SAFE`, toutes les deux heures, avec cible 30 000 appels/jour,
réserve 5 000, seuil d’erreur 5 %, alerte stockage 750 MB et pause 900 MB.
La saison régulière est définie par un contrat de format versionné, jamais par
une constante globale 18/306.

## 2026-07-24 — Verticale initiale Ligue 1 en shadow

Statut : `VERIFIED`

Le Jalon 2 reste limité à la Ligue 1. Les marchés activés sont le 1X2 et
l'Over/Under 2,5 ; BTTS, double chance et marchés enrichis restent désactivés
tant que la couverture réelle n'est pas démontrée. La bankroll de 1 000 unités
est fictive et les mises réelles restent techniquement verrouillées.

## 2026-07-24 — Sources principales et contrôle

Statut : `VERIFIED`

API-Football est retenu comme adaptateur sportif profond, The Odds API comme
source de fixtures, résultats courts et cotes prospectives immédiatement
activable, et Football-Data.co.uk comme contrôle historique. Aucun abonnement
n'a été souscrit. Sans `API_FOOTBALL_KEY`, le périmètre opérationnel utilise
The Odds API sans masquer la couverture sportive partielle.

## 2026-07-24 — Aucune stratégie promue après recalcul OOS

Statut : `VERIFIED`

Le walk-forward 2025–2026 ne fournit aucune preuve robuste de rentabilité.
L'Over 2,5 à +2,83 % reste inconclusif car son IC 95 % traverse zéro. Les autres
stratégies sont rejetées ou insuffisamment documentées.

## 2026-07-24 — Cockpit fondé sur la provenance

Statut : `VERIFIED`

Chaque surface analytique expose l'origine `DEMO DATA`, `LEGACY SOURCE` ou
`LIVE SOURCE`. Une vue vide explicite est préférée à une cote synthétique
présentée comme réelle. Le verrou de production reste visible en permanence.

## 2026-07-24 — Faire évoluer l'existant sans reconstruction destructive

Statut : `VERIFIED`

Le moteur existant est conservé et entouré de contrats typés, de contrôles et de
tests. La migration vers la cible est incrémentale afin de préserver les preuves
du Jalon 0 et les données historiques.

## 2026-07-24 — Politique temporelle stricte et versionnée

Statut : `VERIFIED`

Toute feature doit respecter `data_observed_at < as_of_time`, porter son instant de
calcul et ses versions de source/feature. Les matchs partageant un instant sont
calculés avant toute mise à jour d'historique. Une correction tardive crée une
nouvelle version et ne réécrit aucune prédiction passée.

## 2026-07-24 — Contextes arbitre distincts

Statut : `VERIFIED`

Les historiques global, compétition et saison sont des signaux séparés. L'atome
legacy `ARBITRE_SEVERE` désigne explicitement le contexte compétition pour éviter
tout mélange silencieux.

## 2026-07-24 — Identité interne indépendante des fournisseurs

Statut : `VERIFIED`

Les entités reçoivent des UUID internes. Un nom seul n'est jamais une preuve
d'identité. Les correspondances fournisseur ont une période de validité, une
méthode, une confiance et un statut de revue ; les liens inter-fournisseurs sont
explicites.

## 2026-07-24 — Brut append-only adressé par contenu

Statut : `VERIFIED`

Chaque réponse fournisseur crée une observation. Un payload identique réutilise le
même objet physique par SHA-256, mais conserve une nouvelle observation et ses
métadonnées. L'écriture exclusive interdit tout écrasement ; les secrets sont
expurgés avant persistance.

## 2026-07-24 — PostgreSQL pour l'état, fichiers analytiques pour les preuves

Statut : `VERIFIED`

PostgreSQL porte identités, mappings, runs, observations, fixtures, features,
contrôles qualité et cycle des paris. Les migrations Alembic sont la source de
vérité. SQLite reste autorisé pour les tests locaux reproductibles ; les Parquet,
CSV, JSON, notebooks et rapports servent d'artefacts analytiques versionnés.

## 2026-07-24 — Déduplication au grain métier

Statut : `VERIFIED`

Un marché neutre possède une seule observation canonique par fixture et combinaison
de signal. Les lignes équipe légitimes restent distinctes. Une ambiguïté est
bloquante ; aucun `drop_duplicates()` arbitraire n'est admis.

## 2026-07-24 — Cote distincte de l'opportunité et du pari

Statut : `VERIFIED`

Les concepts `market_opportunity`, `bookmaker_quote`, `selected_bet` et
`settled_bet` sont séparés. Le règlement est versionné et ne dépend jamais du
nombre de bookmakers ayant coté le marché.

## 2026-07-24 — Aucun pari réel

Statut : `PRODUCTION_LOCKED`

Le système reste exclusivement en simulation. Une archive prospective réelle, une
validation shadow et une autorisation explicite séparée sont obligatoires avant
toute évolution de ce verrou.

## 2026-07-24 — Un workflow vert doit produire des preuves

Statut : `VERIFIED`

La CI contrôle installation, lint, typage strict, sécurité, migrations, tests et
construction du dashboard. La santé data expose volumes, fraîcheur, alertes,
erreurs, lignes affectées et identifiant du run.
## 2026-07-24 — PostgreSQL managé comme cible, branche data comme pont

Statut : `VERIFIED`

La cible durable est PostgreSQL managé chez Neon. Tant que `DATABASE_URL` est
absente, la branche orpheline `shadow-data` conserve bundles et objets bruts
append-only ; les GitHub Artifacts deviennent un journal court et non la source
de vérité. Ce pont a été retenu pour démarrer le burn-in sans achat ni perte de
données.

## 2026-07-24 — Le diagnostic ne compte pas comme couverture

Statut : `VERIFIED`

Un appel manuel hors fenêtre peut vérifier le fournisseur, mais ne passe jamais
une fenêtre J-7 à H-0:10 en `COLLECTED`. Les taux de couverture ne reposent que
sur les fenêtres réellement éligibles.

## 2026-07-24 — Burn-in descriptif et verrou de production

Statut : `SHADOW_BURN_IN_ACTIVE`

Le burn-in mesure durabilité, complétude, incidents, quota et couverture. Il ne
permet aucune conclusion statistique avant une période prospective suffisante.
`PRODUCTION_LOCKED` reste invariant.

## 2026-07-24 — Stockage historique à trois niveaux

Statut : `IMPLEMENTED`

PostgreSQL conserve les métadonnées et résultats synthétiques, Parquet les faits
volumineux, et les payloads gzip immuables permettent le replay. Le pont
`shadow-data` est utilisé jusqu’à mesure réelle du pilote ; aucun stockage
externe payant n’est créé automatiquement.

## 2026-07-24 — Validation temporelle avant sophistication

Statut : `IMPLEMENTED`

La baseline Elo interprétable précède les modèles joueurs et ensembles. Les
saisons 2024–2025 sont aveugles et ne règlent aucun paramètre. Un échec
anti-fuite bloque la chaîne ; un résultat historique positif ne peut au mieux
devenir que `LIVE_SHADOW_CANDIDATE`.

## ADR Jalon 6 — Gates avant calcul

Les datasets sont produits uniquement après readiness explicite. Le rapprochement
des endpoints fixture-scoped utilise le hash du payload et les paramètres de
l'observation brute. Discovery devient 2020–2022, Validation 2023 et Blind OOS
2024–2025, car 2018–2019 ne sont pas encore disponibles.

Le store joueurs conserve les nulls et l'identité fournisseur lors des
transferts. La composition cible est réservée à `POST_LINEUP_SIMULATED`. Les
calibrations sont choisies sur Validation seulement. DuckDB 1.5.4 et Polars
1.43.0 sont épinglés pour la validation croisée des Parquet.

## ADR — Jalon 7

- La comparaison est strictement appariée par fixture, saison, cible, snapshot
  marché et politique temporelle.
- La calibration est sélectionnée sur des prédictions cross-fit uniquement.
- L'incertitude utilise 5 000 bootstraps groupés saison-semaine (CI 90/95 %).
- 2024–2025 est exposé et interdit à tout nouveau réglage.
- scikit-learn 1.9.0 est épinglé pour le benchmark
  `HistGradientBoostingClassifier`.
- Aucun résultat historique seul ne peut créer un candidat live.
## 2026-07-25 — Validation externe par gates

- geler `EXTERNAL_VALIDATION_PROTOCOL_V1` avant ouverture des résultats ;
- évaluer uniquement les ligues dont TEAM_GATE passe ;
- ne pas assimiler les effectifs à des statistiques joueurs par match ;
- ne jamais inventer un marché historique absent ;
- conserver `NO_EXTERNAL_VALIDATED_EDGE` et `NO_BET_DEFAULT` tant que les gates
  externes ne sont pas complets ;
- standardiser par ligue pour le pooled et interdire tout retuning externe.

## ADR Jalon 9

- Football-Data est la source massive historique domestique; The Odds API reste
  un pilote ciblé plafonné à 500 crédits.
- La priorité métier s’ajoute à la priorité historique et ne supprime aucune
  tâche.
- Les mappings fixture/marché ambigus ne sont jamais utilisés.
- Pinnacle récent dégradé est conservé pour audit mais exclu des agrégats.
- R2 est privé, S3-compatible, sans suppression par défaut.
