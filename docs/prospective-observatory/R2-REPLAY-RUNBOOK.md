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

- namespace `prospective-deep-data/schema-v1` accessible en lecture ;
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

1. lister les reçus attendus ;
2. vérifier schéma, clé, hash, taille et provenance ;
3. télécharger l’objet correspondant dans un répertoire temporaire ;
4. décompresser sans écrire de payload dans Git ;
5. recalculer le SHA-256 ;
6. normaliser avec la révision déclarée ;
7. projeter dans la base jetable ;
8. rejouer une seconde fois ;
9. comparer dataset hash, identités et compteurs ;
10. publier `r2-replay-audit.json`.

## Critères verts

```text
provider_calls=0
provider_credits=0
business_duplicates=0
hash_mismatches=0
data_loss=0
deletions=0
postgresql_payload_body_rows=0
```

Le second passage doit insérer zéro nouvelle ligne métier et incrémenter le
compteur de doublons évités.

## Incident

- mismatch hash/taille : quarantaine et arrêt ;
- objet absent : `data_loss > 0`, arrêt ;
- receipt sans objet : lag R2 explicite ;
- objet sans receipt : non projetable ;
- migration incohérente : aucune projection ;
- secret détecté : artifact refusé.

Aucun replay ne supprime ni ne corrige en place un objet R2.
