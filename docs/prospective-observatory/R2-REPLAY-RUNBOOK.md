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
- journal `prospective-deep-budget/prospective-provider-budget-v1`
  accessible en lecture ;
- aucune variable de clé fournisseur transmise au job ;
- destination PostgreSQL explicite et migrée ; en exploitation, les tables
  d’autorité du canari doivent déjà exister et correspondre exactement au
  contrat gelé ; le replay refuse de les inventer ;
- inventaire exhaustif du namespace pour l’intégrité, puis sélection bornée
  par la cohorte, les fenêtres liées et `planned_at` ;
- `PRODUCTION_LOCKED` et tous les invariants actifs.

La révision attendue est `0015_chronos_fail_closed`.

Le replay certifié reconstruit les projections scientifiques de capture et le
journal des coûts fournisseur depuis le watermark R2 figé. Les tables
d'autorité du canari (`chronos_canary_runs`, cohorte, usages et liens de
fenêtres) sont préservées mais ne sont jamais réinventées depuis des payloads :
une autorisation d'exécution n'est pas une donnée scientifique reconstructible.

## Commande

Le CLI canonique est :

```text
python scripts/run_prospective_observatory.py replay-audit ...
```

Les paramètres exacts sont exposés par `--help`. Ne jamais inclure une URL
Neon, une clé R2 ou un secret dans un argument persisté, un artifact ou un
rapport.

## Séquence

1. lire l’autorité PostgreSQL existante et geler cohorte, fenêtres et
   `planned_at` sans créer de grant ;
2. inventorier et valider exhaustivement toutes les intentions de reprise,
   mais ne matérialiser que celles qui appartiennent au canari ;
3. inventorier exhaustivement toutes les clés, payloads et reçus ;
4. refuser avant toute projection les payloads orphelins, reçus orphelins,
   clés inattendues, objets illisibles et divergences d’intégrité ;
5. vérifier schéma, clé, hash, taille et provenance ;
6. télécharger l’objet correspondant sans l’écrire dans Git ;
7. décompresser et recalculer le SHA-256 ;
8. normaliser avec la révision déclarée ;
9. reprojeter uniquement les coûts R2 enregistrés depuis `planned_at` ; le
   seeding legacy global est interdit dans le chemin canari ;
10. projeter dans la base cible autorisée ;
11. vérifier la parité bidirectionnelle des reçus, index payloads et budgets
    du canari, puis l’égalité exacte de toutes les tables de projection
    scientifique entre R2 et PostgreSQL ;
12. rejouer une seconde fois ;
13. comparer dataset hash, identités, ensemble exact des reçus et compteurs ;
14. publier séparément objets/octets physiques uniques, objets/octets de
    reprise et
    références/octets logiques lus ;
15. publier `r2-replay-audit.json`.

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
status=R2_REPLAY_VERIFIED
postgresql.reconstruction_status=CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2
```

Le second passage doit insérer zéro nouvelle ligne métier et incrémenter le
compteur de doublons évités.

Les tables comparées par empreinte de ligne complète sont :

```text
prospective_player_status
prospective_injuries
prospective_lineups
prospective_formations
prospective_odds_snapshots
known_at_fact_metadata
price_snapshot_metadata
price_derivation_metadata
market_snapshot_metadata
tag_snapshot_metadata
data_quality_events
chronos_lineage_nodes
chronos_lineage_edges
```

Une ligne supplémentaire, manquante ou mutée produit
`R2_POSTGRESQL_PROJECTION_PARITY_FAILED:<table>`. Un reçu
`CAPTURED_EMPTY` demeure une preuve durable mais ne produit aucune ligne dans
ces tables ; pour `INJURY`, le gate conserve la sémantique bornée
`NO_INJURY_REPORTED_AT_CAPTURE`.

`R2_REPLAY_PARTIAL_FIXTURE_INDEX` et `RECONSTRUCTION_INCOMPLETE` sont des
sorties bloquantes : elles signifient que les fixtures nécessaires aux reçus
n’ont pas toutes été reconstruites. Un ancien libellé générique de
reconstruction ne doit plus être utilisé dans les rapports Jalon 12.

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
- reçu ou index présent d’un seul côté : `R2_POSTGRESQL_*_PARITY_FAILED` ;
- journal budget différent : `R2_POSTGRESQL_PROVIDER_BUDGET_PARITY_FAILED` ;
- guard zéro unité avec reçu R2 durable mais lien absent : créer
  idempotemment
  `pcc1:<guard_sha256>:<receipt_hash>`, puis réutiliser la preuve
  sans fournisseur ;
- guard zéro unité retrouvé pour la même fenêtre et tentative, sans reçu R2
  vérifiable :
  `PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED`, avant tout preflight et sans
  second appel ;
- lien de complétion invalide, conflictuel ou sans reçu correspondant : audit
  bloqué ;
- projection supplémentaire, manquante ou mutée :
  `R2_POSTGRESQL_PROJECTION_PARITY_FAILED:<table>` ;
- secret détecté : artifact refusé.

Les clés compactes `pcg1` des guards restent sous 250 caractères et les clés
`pcc1` de complétion en comptent 134 ; leur replay est compatible avec
`provider_budget_ledger.idempotency_key VARCHAR(250)` dans PostgreSQL.

Aucun replay ne supprime ni ne corrige en place un objet R2.

Un run de capture, même sans fenêtre due, ne réconcilie jamais le namespace
R2. Son rapport conserve les compteurs distincts :

```text
r2_puts=<objets de la capture courante>
recovery_r2_puts=<objets rematérialisés depuis une intention antérieure>
```

`recovery_r2_puts` reste donc à zéro dans la capture. Toute réparation
provider-free appartient exclusivement à `replay-audit` et consomme les
plafonds cumulatifs du même canari.

## Matrice d’interruption

| Point d’arrêt | Reprise attendue |
|---|---|
| guard présent, reçu R2 durable, complétion absente | ajouter le lien append-only ; pour une fraîcheur `/fixtures`, réutiliser le reçu puis autoriser le transport profond |
| réponse fournisseur possible, guard zéro unité présent, aucun reçu R2 vérifiable | arrêt `PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED`, 0 second appel, 0 second crédit |
| intention seule | rematérialiser payload puis reçu exacts |
| payload présent, reçu absent | rematérialiser le reçu depuis l’intention |
| payload et reçu présents, PostgreSQL absent | reconstruire index et projections |
| PostgreSQL partiellement projeté | compléter par upserts idempotents |
| timeout après index | vérifier la parité et reprendre sans fournisseur |
| replay complet | `R2_REPLAY_VERIFIED` |
| replay répété | 0 appel, 0 crédit, 0 insertion métier |

Dans les neuf cas, les SHA-256 et tailles disponibles sont recalculés. Le reçu
immuable résout un guard seulement si son hash permet un lien de complétion
univoque. Sans reçu, le guard prouve uniquement le franchissement possible de
la frontière réseau, pas le contenu de la réponse. Une intention invalide, un
objet non attribuable ou une parité divergente bloque aussi la reprise ; aucun
appel fournisseur ne sert à « réparer » l’historique.
