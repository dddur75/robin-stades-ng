# Registre des décisions

## 2026-07-24 — Conserver et faire évoluer l'existant

Statut : `VERIFIED`

Le moteur actuel contient des garde-fous point-in-time et des tests synthétiques
utiles. Une reconstruction destructive ferait perdre cette preuve. La migration
vers l'architecture cible sera incrémentale, avec adaptateurs autour des modules
existants.

## 2026-07-24 — Python 3.12 comme version d'exécution de référence

Statut : `VERIFIED`

Les workflows existants utilisent Python 3.12. Le projet accepte Python 3.12 et
plus récent, tandis que la CI de référence reste sur 3.12 pour rester alignée sur
la production GitHub Actions.

## 2026-07-24 — PostgreSQL pour l'état métier, Parquet pour l'analytique

Statut : `IN_PROGRESS`

PostgreSQL portera les identités, versions, prédictions, décisions, incidents et
états transactionnels. Parquet portera les snapshots bruts immuables et les
datasets analytiques versionnés. DuckDB pourra interroger les Parquet localement.

## 2026-07-24 — Aucun pari réel

Statut : `PRODUCTION_LOCKED`

Le système reste exclusivement en simulation. Toute intégration d'exécution réelle
nécessitera une décision séparée, une validation hors échantillon et une
autorisation explicite de l'utilisateur.

## 2026-07-24 — La réussite d'un workflow n'est pas une preuve de données

Statut : `VERIFIED`

Un pipeline n'est considéré utile que si ses artefacts, volumes, fraîcheur et
contrôles de qualité sont observables. Les futurs workflows publieront un manifeste
de run et échoueront si leur contrat de sortie attendu n'est pas respecté.
