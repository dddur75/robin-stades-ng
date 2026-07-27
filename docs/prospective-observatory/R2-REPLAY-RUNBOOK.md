# Runbook de replay R2

## Finalité

Reconstruire les projections à partir des payloads bruts sans fournisseur :

```text
R2
→ vérification SHA-256 et taille
→ lecture du receipt
→ validation temporelle
→ normalisation
→ PostgreSQL jetable
→ gates
→ rapports
```

## Préconditions

- namespaces `prospective-deep-data/schema-v1` et
  `prospective-deep-data-recovery/schema-v1` accessibles en lecture ;
- aucune variable de clé fournisseur transmise au job ;
- destination PostgreSQL jetable vide et migrée ;
- inventaire borné ou curseur explicite ;
- `PRODUCTION_LOCKED` et tous les invariants actifs.

La révision attendue est `0009_jalon12_observatory`.

## Commande

Le CLI canonique est :

```text
python scripts/run_prospective_observatory.py replay-audit ...
```

Les paramètres exacts sont exposés par `--help`. Ne jamais inclure une URL
Neon, une clé R2 ou un secret dans un argument persisté, un artifact ou un
rapport.

## Séquence

1. inventorier et valider exhaustivement toutes les intentions de reprise ;
2. matérialiser de façon idempotente le payload et le reçu exacts de chaque
   intention valide, sans appel fournisseur ;
3. inventorier exhaustivement toutes les clés, payloads et reçus ;
4. refuser avant toute projection les payloads orphelins, reçus orphelins,
   clés inattendues, objets illisibles et divergences d’intégrité ;
5. vérifier schéma, clé, hash, taille et provenance ;
6. télécharger l’objet correspondant sans l’écrire dans Git ;
7. décompresser et recalculer le SHA-256 ;
8. normaliser avec la révision déclarée ;
9. projeter dans la base jetable ;
10. rejouer une seconde fois ;
11. comparer dataset hash, identités, ensemble exact des reçus et compteurs ;
12. publier séparément objets/octets physiques uniques, objets/octets de
    reprise et
    références/octets logiques lus ;
13. publier `r2-replay-audit.json`.

## Critères verts

```text
provider_calls=0
provider_credits=0
business_duplicates=0
hash_mismatches=0
data_loss=0
deletions=0
postgresql_payload_body_rows=0
namespace_verified=true
```

Le second passage doit insérer zéro nouvelle ligne métier et incrémenter le
compteur de doublons évités.

## Incident

- mismatch hash/taille : quarantaine et arrêt ;
- objet absent : `data_loss > 0`, arrêt ;
- receipt sans objet : audit bloqué ;
- intention valide sans objet final : récupération automatique et contrôlée ;
- intention invalide ou divergente : audit bloqué ;
- objet sans receipt et sans intention attribuable : audit bloqué, jamais
  ignoré comme un replay vide ;
- clé inattendue ou illisible : audit bloqué avant PostgreSQL ;
- migration incohérente : aucune projection ;
- secret détecté : artifact refusé.

Aucun replay ne supprime ni ne corrige en place un objet R2.
