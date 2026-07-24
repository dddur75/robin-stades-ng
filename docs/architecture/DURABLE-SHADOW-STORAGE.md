# Architecture du stockage shadow durable

## Décision

La source de vérité cible est PostgreSQL. Neon est le service recommandé. Le
pont temporaire est la branche Git orpheline `shadow-data`. Les GitHub Artifacts
ne sont qu’un journal d’exécution et une reprise courte.

## Trois niveaux

### Niveau A — observation brute

Emplacement : `shadow-data/objects/sha256/<préfixe>/<hash>.bin.gz`.

Chaque réponse fournisseur est expurgée, hashée avant compression et stockée une
seule fois. Plusieurs observations peuvent référencer le même objet. Rétention
cible : toute la durée du burn-in plus une saison ; aucune suppression automatique.

### Niveau B — registre normalisé

Emplacement transitoire : `shadow-data/bundles/*.json.gz` et
`shadow-data/manifests/index.jsonl`. Emplacement cible : tables PostgreSQL
versionnées par Alembic.

Le registre contient runs, demandes fournisseur, fixtures durables, mappings,
bookmakers, marchés, snapshots, prédictions, décisions, règlements, qualité,
incidents, quota, fenêtres et métriques de burn-in. L’unicité métier et les clés
étrangères sont contrôlées en base et à l’écriture du bundle.

### Niveau C — preuves et vues

Emplacements : `data/live-proof`, `rapports`, `docs`, Cockpit Live V2 et
Artifacts GitHub à rétention courte. Ces sorties sont reconstructibles depuis A
et B et ne sont jamais la source de vérité.

## Protocole d’écriture

1. produire l’état local et le bundle déterministe ;
2. vérifier hashes, références, unicité et schéma ;
3. écrire transactionnellement dans PostgreSQL si `DATABASE_URL` existe ;
4. acquitter l’écriture ;
5. append dans `shadow-data`, vérifier le registre, puis pousser ;
6. publier seulement ensuite l’Artifact de journal.

Une décision shadow est bloquée si le mode durable requis n’obtient aucun accusé
de réception. Une interruption avant acquittement se reprend avec le même
`run_id` et les mêmes clés d’idempotence.

## Restauration et perte maximale

- PostgreSQL : restauration managée et replay du dernier bundle manquant ;
- branche data : checkout, `manage_durable_registry.py verify`, puis replay ;
- Artifact : reprise rapide uniquement, jamais unique copie.

Perte maximale avec le pont actif : le run non poussé en cours. Perte maximale
avec PostgreSQL et pont : nulle après double acquittement. Tout le Niveau C est
reconstructible sans appel fournisseur via `manage_durable_registry.py replay`.

## Migration Jalon 3

Le bundle initial contient 393 enregistrements, 5 observations, 5 références de
payload et 3 objets physiques. Deux objets identiques ont été dédupliqués. Les
cinq hashes ont été vérifiés, sans erreur ni ligne irrécupérable.

## Capacité

La volumétrie estimée pour 306 matchs de Ligue 1, 9 fenêtres et environ 90 cotes
par fenêtre est de 0,4 à 0,8 Go par saison, index et brut inclus. Le plan Neon
Free peut amorcer le burn-in ; Launch devient pertinent au-delà de 0,5 Go.

Production : `PRODUCTION_LOCKED`.
