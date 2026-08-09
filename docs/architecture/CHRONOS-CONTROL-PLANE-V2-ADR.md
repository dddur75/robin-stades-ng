# Chronos Control Plane V2 — ADR

- Statut : **ACCEPTED FOR IMPLEMENTATION — E1**
- Décision : `DB_CLOCKED_RUN_BOUND_EFFECT_LEDGER`
- Portée : autorité provider-free, horloge, identité GitHub, clôture restore/restart,
  journal d'effets R2 et comptabilité
- Hors portée : activation, canari, migration Neon, appel fournisseur, lecture/écriture R2
  réelle, résultat scientifique Phase C V2

## Contexte

La PR #39 est gelée au head
`ea983c0f42177317a9c8e91f4e49974df2b63525` avec deux P1 DP6 :

1. une commande PostgreSQL provider-free peut autoriser depuis un `--now` fourni par
   l'appelant ;
2. la présence ultérieure d'un objet R2 byte-identique ne prouve pas que l'opération
   courante l'a créé.

Toute troisième correction de cette architecture est interdite. Cette ADR définit donc
une nouvelle frontière E1, indépendante du control-plane de PR39.

## Forces de décision

| Critère | Poids |
|---|---:|
| Sécurité et anti-replay | 18 |
| Crash consistency | 18 |
| Restore safety | 14 |
| Testabilité | 10 |
| Complexité | 10 |
| Coût | 8 |
| Maintenance | 8 |
| Compatibilité Neon | 5 |
| Compatibilité GitHub | 5 |
| Compatibilité R2 | 4 |
| **Total** | **100** |

## Options

### A — Corriger encore l'architecture PR39

Verdict : `SAME_ARCHITECTURE_PROHIBITED`.

Cette option conserve l'autorité du monolithe CLI, le même modèle de budget mutable et
la même inférence R2. Elle est éliminée avant notation : elle violerait le second veto et
ne constitue pas une décision E1.

### B — Horloge PostgreSQL et journal d'effets append-only lié au run

PostgreSQL est l'unique arbitre du temps de production. Une autorité à usage unique est
liée au run GitHub exact, à la tentative, aux SHA, au workflow, au dépôt, à la référence,
à l'epoch du serveur et à une génération externe protégée. Chaque frontière R2 devient
un événement durable append-only ; une réponse réseau perdue reste explicitement
`PUT_COMMITTED_ACTUAL_PENDING`.

### C — Service coordinateur externe complet

Un service séparé signe les autorisations, appelle R2 et journalise les résultats. Cette
frontière est forte, mais ajoute un déploiement, une identité machine, un protocole
distribué supplémentaire, une disponibilité à opérer et un coût permanent avant même
un canari borné.

## Évaluation

| Critère | A | B | C |
|---|---:|---:|---:|
| Sécurité / 18 | 0 | 18 | 18 |
| Crash consistency / 18 | 0 | 18 | 17 |
| Restore safety / 14 | 0 | 14 | 13 |
| Testabilité / 10 | 0 | 10 | 7 |
| Complexité / 10 | 0 | 8 | 4 |
| Coût / 8 | 0 | 8 | 3 |
| Maintenance / 8 | 0 | 6 | 4 |
| Neon / 5 | 0 | 5 | 4 |
| GitHub / 5 | 0 | 5 | 4 |
| R2 / 4 | 0 | 4 | 4 |
| **Score** | **REJETÉE** | **96/100** | **78/100** |

## Décision

Choisir l'option B : `DB_CLOCKED_RUN_BOUND_EFFECT_LEDGER`.

Le système accepte volontairement qu'un résultat réseau perdu reste inconnu. Il préfère
une sous-attribution explicite à une création physique inventée. Les revues DP6, SEC,
SRE, C2, RP8 et RED concluent toutes PASS, avec zéro P0/P1 et un score conservateur
de 96/100. RP8 conserve son veto sur tout canari fournisseur et sur l'ouverture V3.

## Frontière d'horloge

L'adaptateur PostgreSQL de production :

- ne reçoit ni `now`, ni `--now`, ni variable d'environnement temporelle ;
- refuse `injected_clock`, `test_now`, `fake_now` et tout alias équivalent avec
  `CHRONOS_PRODUCTION_CLOCK_INJECTION_FORBIDDEN` ;
- appelle une fonction PostgreSQL qui capture `clock_timestamp()` une seule fois par
  transaction ;
- vérifie `planned_at <= db_now AND db_now < expires_at` ;
- enregistre et compare `pg_postmaster_start_time()`.

Une interface `TestClock` existe seulement pour les adaptateurs Memory et SQLite de
test. Aucun chemin de production PostgreSQL ne l'accepte.

## Identité et génération

Toute autorité lie exactement :

- `mission_id` ;
- `github_run_id` ;
- `github_run_attempt` ;
- `github_sha` ;
- `github_workflow_ref` ;
- `github_workflow_sha` ;
- `github_repository` ;
- `github_ref` ;
- `code_revision` ;
- `postgres_server_epoch` ;
- `control_plane_generation_hash`.

La génération provient d'un nonce aléatoire externe de 256 bits conservé uniquement
dans l'environnement GitHub protégé. PostgreSQL n'en stocke que le SHA-256. Un hash
public fourni seul par le client ne constitue pas une fence de restore.

Après PITR, restore, branch swap ou rotation de compute, le runbook exige dans cet
ordre : révocation des logins runtime, rotation du nonce, rotation/réémission des
credentials, nouveau run et nouvelle autorité. Une ancienne base restaurée contient
l'ancien hash et ne peut donc accepter le nouveau nonce. Une ancienne autorité échoue
également si l'epoch PostgreSQL diffère.

## Identité d'opération

```text
operation_id = SHA256(
  mission_id
  github_run_id
  github_run_attempt
  resource_kind
  canonical_key
  canonical_payload_hash
)
```

Les champs sont encodés de façon canonique et séparés par longueur, pas concaténés de
façon ambiguë. Un retry dans la même tentative réutilise l'identifiant ; un rerun GitHub
change `github_run_attempt` et obtient une nouvelle opération.

## Modèle PostgreSQL

### Autorités

`chronos_effect_authorities` est append-only dans ses attributs d'identité. La
consommation n'est pas un UPDATE métier : elle est prouvée par le premier événement
`EFFECT_RESERVED` lié à l'autorité. Une contrainte unique empêche une autorité de
réserver plusieurs opérations.

La fonction transactionnelle `chronos_claim_effect_authority(...)` :

1. verrouille l'autorité ;
2. capture `db_now := clock_timestamp()` et
   `server_epoch := pg_postmaster_start_time()` après le verrou ;
3. compare run, attempt, SHA, workflow ref/SHA, repository, ref, code revision,
   génération et epoch ;
4. vérifie la fenêtre demi-ouverte avec l'horloge DB ;
5. refuse toute autorité déjà consommée par une autre opération ;
6. ajoute `AUTHORITY_GRANTED` et `EFFECT_RESERVED` dans la même transaction ;
7. retourne `authority_id`, `db_authorized_at`, `expires_at`,
   `postgres_server_epoch` et `authority_receipt_hash`.

Le reçu est un SHA-256 PostgreSQL des champs canoniques retournés et de toute l'identité
du run.

### Journal

`chronos_effect_events` contient :

`event_id`, `event_seq`, `operation_id`, `authority_id`, `event_type`, `resource_kind`,
`resource_key`, `payload_hash`, `db_recorded_at`, `recorded_server_epoch`, `github_run_id`,
`github_run_attempt`, `code_revision`, `previous_event_hash`, `event_hash`.

Les fonctions de transition utilisent `clock_timestamp()`, verrouillent la dernière
ligne de l'opération, vérifient le hash précédent, l'identité immuable et la transition,
puis calculent le nouveau SHA-256 côté PostgreSQL. Les rôles runtime n'ont aucun droit
direct d'INSERT, UPDATE ou DELETE sur les tables.

Les fonctions testent `pg_has_role(..., 'USAGE')`, pas la simple appartenance. Le lien
ADMIN-only que PostgreSQL 16 impose au migrateur `CREATEROLE` (`INHERIT=false`,
`SET=false`, grantor bootstrap) est audité mais ne donne donc aucune autorité runtime;
toute autre membership pendant la migration est refusée.

Les triggers refusent tout UPDATE, DELETE ou TRUNCATE du journal et des autorités sur
PostgreSQL, ainsi que tout UPDATE ou DELETE sur SQLite. Le downgrade
refuse de supprimer le schéma dès qu'une ligne existe.

## Machine d'état

```text
AUTHORITY_GRANTED
  -> EFFECT_RESERVED

EFFECT_RESERVED
  -> FAILED_BEFORE_DISPATCH
  -> PUT_DISPATCHED

PUT_DISPATCHED
  -> CREATED_CONFIRMED
  -> R2_GET_DISPATCHED
  -> PUT_COMMITTED_ACTUAL_PENDING
  -> FAILED_AFTER_DISPATCH

PUT_COMMITTED_ACTUAL_PENDING
  -> R2_GET_DISPATCHED

R2_GET_DISPATCHED
  -> PREEXISTING_CONFIRMED
  -> PUT_COMMITTED_ACTUAL_PENDING
  -> RECOVERY_OBSERVED_MATCHING_OBJECT
  -> INTEGRITY_CONFLICT
```

`INTEGRITY_CONFLICT` est terminal et couvre un 412 suivi d'octets différents ou une
métadonnée contradictoire. `RECOVERY_OBSERVED_MATCHING_OBJECT` ne devient pas
`CREATED_CONFIRMED` dans V2 : les contrats actuels ne fournissent pas encore une
preuve d'auteur suffisamment forte.

## Frontière R2

L'adaptateur V2 utilise exclusivement un PUT conditionnel if-none-match. Il désactive
les retries automatiques du SDK pour le write.
Une seule tentative HTTP est autorisée par événement `PUT_DISPATCHED`. Toute lecture
exacte est précédée d'un unique permit durable `R2_GET_DISPATCHED`; crash, concurrence
et replay ne peuvent donc pas déclencher un second GET pour la même opération.

- réponse de création 2xx reçue : `CREATED_CONFIRMED` ;
- 412 sur le premier et unique essai, puis lecture exacte : `PREEXISTING_CONFIRMED` ;
- 409 : jamais préexistant, toujours pending dans V2 ;
- le status HTTP reçu est autoritatif sur un code d'erreur contradictoire ;
- timeout, reset ou réponse perdue après dispatch :
  `PUT_COMMITTED_ACTUAL_PENDING` ;
- objet exact observé plus tard sans preuve d'auteur :
  `RECOVERY_OBSERVED_MATCHING_OBJECT`, toujours non attribué.

Un 412 après retry SDK n'est jamais une preuve de préexistence : le premier essai peut
avoir créé l'objet avant la perte de réponse.

La métadonnée `operation_id`, le request ID, l'ETag et les custom metadata seront
audités par un test contractuel séparé. Tant que leur persistance et leur attribution
ne sont pas prouvées, ils ne permettent aucune promotion automatique vers
`CREATED_CONFIRMED`.

## Comptabilité

Les vues dérivées exposent :

- `r2_write_units_reserved` = événements `EFFECT_RESERVED` ;
- `r2_put_requests_dispatched` = événements `PUT_DISPATCHED` ;
- `r2_get_requests_dispatched` = événements `R2_GET_DISPATCHED` ;
- `r2_objects_created_confirmed` = `CREATED_CONFIRMED` ;
- `r2_objects_preexisting_confirmed` = `PREEXISTING_CONFIRMED` ;
- `r2_write_outcomes_pending` = état final pending ou recovery observée sans auteur ;
- `r2_integrity_conflicts` = `INTEGRITY_CONFLICT`.

Chaque tentative HTTP conditionnelle possède son permit durable et consomme une unité
au moment de `PUT_DISPATCHED`, y compris un 412. Aucun compteur
`physical_writes_actual` n'est calculé depuis la présence d'un objet.
Une opération ne peut consommer qu'un seul permit GET durable.

## Rôles

- `chronos_reader` : SELECT sur vues d'audit ;
- `chronos_test_writer` : aucun EXECUTE sur les fonctions de production ;
- `chronos_runtime_writer` : EXECUTE sur claim/transition seulement, pas de DML direct ;
- `chronos_authority_executor` : émission d'autorité seulement.

Les fonctions sont `SECURITY DEFINER`, avec `search_path` figé et droits
`PUBLIC` révoqués. Le login runtime est disponible uniquement dans un environnement
GitHub protégé. Les commandes locales n'obtiennent ni ce login ni le nonce de génération.

## Crash consistency

La réservation est durable avant tout PUT. Le callback de dispatch journalise
`PUT_DISPATCHED` et doit réussir avant que l'adaptateur n'envoie le premier octet.
Un crash juste après ce callback peut donc consommer une unité sans effet R2 ; c'est la
sous-attribution volontaire et sûre.

De même, `R2_GET_DISPATCHED` est committé avant la lecture exacte. Une perte d'ACK DB
ou un crash après ce permit laisse l'issue pending et interdit toute seconde lecture.

Aucun retry automatique ne part depuis un état après dispatch ambigu. Le replay dans
la même tentative lit l'état durable et reste idempotent. Un rerun GitHub exige une
nouvelle autorité et un nouvel `operation_id`.
Après restore ou rotation de génération, une ancienne chaîne reste strictement en
lecture locale : la nouvelle autorité ne peut ni la muter ni déclencher son GET.

## Compatibilité

- Neon PostgreSQL : `clock_timestamp()`, `pg_postmaster_start_time()`, transactions et
  `pg_catalog.sha256(bytea)` sont compatibles, sans extension ; aucune lecture/écriture Neon
  n'est requise pour valider cette PR.
- GitHub Actions : l'identité standard du run est liée, y compris
  `GITHUB_RUN_ATTEMPT` et `GITHUB_WORKFLOW_SHA`; le job runtime devra référencer un
  environnement protégé dans une mission ultérieure.
- R2 : l'architecture n'invente aucune garantie au-delà du PUT conditionnel et de la
  réponse effectivement reçue.

## Conséquences

Bénéfices : suppression de l'heure CLI en production, anti-replay exact, fence de
restart/restore, budget non sous-compté et attribution honnête.

Coûts : une migration principale, deux petites surfaces de production (ledger DB et
orchestrateur R2), rotation opératoire obligatoire après restore, et des états pending
qui nécessitent parfois une décision humaine.

## Garde de mise en œuvre

Aucun code de production ne peut être écrit avant :

```text
DP6 = PASS
SEC = PASS
SRE = PASS
C2 = PASS
RP8 = PASS
RED = PASS
open_p0 = 0
open_p1 = 0
architecture_score >= 95
```

Toute nouvelle objection P0/P1 arrête l'implémentation et renvoie cette ADR en revue.
