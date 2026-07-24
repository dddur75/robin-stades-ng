# Migration des données live du Jalon 3

Source : Artifact `shadow-state-30095263615`.
Cible initiale : branche `shadow-data`.
Statut : `VERIFIED`.

## Inventaire

| Élément | Trouvé | Migré | Erreurs |
|---|---:|---:|---:|
| observations | 5 | 5 | 0 |
| références payload | 5 | 5 | 0 |
| objets physiques uniques | 3 | 3 | 0 |
| snapshots | 2 | 2 | 0 |
| enregistrements totaux | 393 | 393 | 0 |

Deux payloads identiques ont été réutilisés par adresse de contenu. Les cinq
références ont été revérifiées contre leur SHA-256. Aucune ligne irrécupérable.

## Validation

Le replay a reconstruit des octets identiques avec 0 appel fournisseur et
0 crédit. La commande `verify` contrôle manifestes, hashes, objets manquants,
unicité et schéma. La migration PostgreSQL `0003_jalon4_durable_shadow` a été
testée en upgrade, downgrade et nouvel upgrade.

Les fichiers source Jalon 3 restent inchangés.
