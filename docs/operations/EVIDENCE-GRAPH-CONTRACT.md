# Contrat du graphe de preuves

## Nœud de preuve

Chaque claim contient : `claim_id`, `claim`, `scope`, `source`, `grain`,
`temporal_class`, `artifact`, `hash`, `code_revision`, `status` et `verified_by`.
Les IDs sont immuables. Une correction crée une nouvelle révision ou invalide le
nœud précédent sans effacer son historique.

Statuts autorisés : `VERIFIED`, `PARTIAL`, `BLOCKED`, `INVALIDATED` et
`SUPERSEDED`. `verified_by` contient au moins deux rôles indépendants pour une
preuve de livraison.

## Résolution

1. résoudre l'artefact depuis son manifeste ou emplacement borné ;
2. vérifier le type et la version ;
3. recalculer uniquement le hash du fichier ou segment concerné ;
4. comparer `code_revision`, lignée et scope ;
5. refuser fermé si une compatibilité manque.

Le hash d'un payload ne prouve pas son grain, son dénominateur ou sa temporalité.
Ces propriétés restent des champs explicites du claim.

## Ledger chaîné

Chaque ligne JSON du ledger contient `previous_hash`, `hash_algorithm=SHA-256` et
`hash`. Le premier `previous_hash` vaut 64 zéros. Pour chaque ligne, sérialiser en
UTF-8 l'objet sans `hash`, avec clés triées, sans espaces (`separators=(",",":")`)
et sans échapper les caractères Unicode; `hash` est le SHA-256 hexadécimal de ces
octets. Le `previous_hash` suivant doit être égal au `hash` courant. Le test de
contrat recalcule toute la chaîne.

## Lignées

Une exécution renseigne séparément `execution_id`, `scientific_lineage_id` et
`dataset_lineage_id`. Une reprise peut changer l'exécution sans changer la lignée
scientifique ni le dataset. Une preuve scientifique ne dépend jamais uniquement
d'un run, d'une tentative, d'un artefact GitHub ou de l'horloge système.

## Consommation produit

Tout chiffre affiché comme réel par le cockpit référence son `claim_id`. Si le
claim est `PARTIAL` ou `BLOCKED`, l'interface montre la limite et ne transforme
pas le chiffre en signal validé.
