# Exploitation de l’Observatoire

## Workflows

| Workflow | Cadence/rôle |
|---|---|
| `prospective-fixture-registry.yml` | workflow 60, `07 03 * * *`, fixtures futures |
| `prospective-deep-scheduler.yml` | workflow 61, `13 * * * *`, sélection horaire |
| `prospective-player-capture.yml` | workflow 62, `19 * * * *`, joueurs, squads, statuts et blessures |
| `prospective-lineup-capture.yml` | workflow 63, `29 * * * *`, lineups et formations |
| `prospective-odds-capture.yml` | workflow 64, `37 * * * *`, snapshots 1X2 et O/U 2,5 |
| `prospective-r2-replay-audit.yml` | workflow 65, `47 05 * * *`, replay sans fournisseur |
| `prospective-gate-report.yml` | workflow 66, `53 06 * * *`, couverture, temporalité et cockpit |

Tous utilisent `prospective-deep-state`, sans `historical-state` ni
`shadow-state`. Les schedules GitHub ne descendent pas sous une heure.
`cancel-in-progress=false` interdit qu’un run plus récent annule une écriture
active.
La configuration partagée est
`configs/prospective_observatory_v1.json`.

Le registre actif contient Ligue 1, Premier League, Liga, Bundesliga et Serie A.
La Ligue 1 utilise `FULL`; les quatre autres utilisent
`DEEP_FULL_ODDS_REDUCED`. Toute exécution conserve `PRODUCTION_LOCKED`,
`REAL_BETS=false`,
`NO_BET_DEFAULT=true`, publication sociale et démo désactivées.

## CLI

```text
scripts/run_five_league_expansion.py registry
scripts/run_five_league_expansion.py projection
scripts/run_five_league_expansion.py summary
scripts/run_prospective_observatory.py fixture-registry
scripts/run_prospective_observatory.py scheduler
scripts/run_prospective_observatory.py capture-player
scripts/run_prospective_observatory.py capture-lineup
scripts/run_prospective_observatory.py capture-odds
scripts/run_prospective_observatory.py replay-audit
scripts/run_prospective_observatory.py gate-report
scripts/run_prospective_observatory.py next-due-report
```

Consulter `--help` pour les paramètres. `pilot-mock` sert uniquement aux tests
et ne peut jamais alimenter Robin Live comme source réelle.

Les entrées `--cache` portent la provenance immuable `cache-test` et sont
refusées avec `--execute` ou avec PostgreSQL durable. Un `--object-store-root`
local est également refusé pour toute exécution fournisseur et pour tout
replay vers PostgreSQL durable : la lane opérationnelle écrit et relit R2
uniquement. Chaque unité fournisseur est réservée avant l’appel dans le journal
append-only R2 `prospective-deep-budget/prospective-provider-budget-v1`, puis
projetée dans PostgreSQL, afin qu’une erreur de parsing, R2 ou PostgreSQL ne
rende jamais le coût invisible.

Avant chaque transport de données, écrire aussi dans ce journal un guard
immuable `GUARDED_BEFORE_PROVIDER_CALL:<step>` de zéro unité pour chaque
fenêtre et numéro de tentative concernés. Après durabilité du reçu, écrire le
lien `pcc1:<guard_sha256>:<receipt_hash>`, lui aussi append-only
et de zéro unité. Au démarrage d’une reprise, réconcilier d’abord tout guard
dont le reçu R2 est déjà durable, puis contrôler les guards non résolus avant
tout preflight. Une fraîcheur `/fixtures` complétée est réutilisée sans nouvel
appel et le transport profond peut continuer. Seul un guard sans reçu
vérifiable impose `PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED`, avec zéro second
appel et zéro second crédit.

La clé guard est
`pcg1:<provider>:<command>:<f|d>:<scope_sha256>:<step_sha256>:<window_sha256>:aN`
et reste sous 250 caractères ; `pcc1` mesure 134 caractères. Ces deux lignées
sont compatibles avec l’`idempotency_key VARCHAR(250)` PostgreSQL.

La surcharge durable attendue sans retry est de 71 guards et 71 complétions par
fixture, soit une entrée R2 et une lignée SQL de complétion par guard ; elle ne
consomme aucune unité fournisseur.

## Rapports compacts

Le répertoire d’artifact contient :

```text
fixture-registry.json
five-league-registry.json
five-league-expansion-summary.json
scheduler-plan.json
general-capture-report.json
player-capture-report.json
lineup-capture-report.json
odds-capture-report.json
r2-replay-audit.json
gate-report.json
next-due-windows.json
public-evidence-ledger-v3-<sha256>.jsonl
pilot-report.json
```

Le bloc `observatory` est nettoyé et peut alimenter le cockpit si les invariants
production, social et démo sont explicites. Aucun payload brut ni secret n’y
figure.

Le ledger sépare explicitement :

```text
planned_events
capture_attempt_events
physical_capture_events
physical_http_calls
temporal_evidence_events
gate_evaluation_events
```

`physical_capture_events` est dédupliqué par `physical_capture_id`.
API-Football conserve une identité fixture-scoped ; la réponse Odds globale
partage la même identité sur toutes les fixtures qu’elle contient.
`temporal_evidence_events` est dédupliqué par capture physique et fixture, les
familles restant des alias techniques. `physical_http_calls` additionne les
appels attribués aux reçus physiques ; le journal budget reste l’autorité pour
les transports de contrôle sans reçu.

## Ordre d’un pilote

1. estimation signée globale, puis registre borné des cinq ligues, trois appels
   API-Football au maximum par ligue et zéro crédit Odds ;
2. plan du scheduler ;
3. réconciliation des complétions prouvées par reçu R2, puis contrôle des
   guards non résolus avant tout preflight ;
4. publication des fenêtres dues et du coût maximum ;
5. guard R2 zéro unité, puis captures uniquement dues et autorisées ;
6. vérification R2 ;
7. projection PostgreSQL ;
8. replay audit ;
9. gate report et synthèse cinq ligues provider-free ;
10. premier snapshot de périmètre, audit R2/PostgreSQL des identités, puis
    snapshot Robin Live final.

Si `windows_due=0`, publier `CANARY_NOT_DUE_SCHEDULER_READY` avec
`provider_calls=0`, `odds_api_credits=0`, `r2_puts=0` et
`capture_attempts=0`, puis s’arrêter. Une fixture enregistrée sans lineup,
blessure ou cote due est un pilote sain. Le preflight de fraîcheur kickoff
player/lineup n’est exécuté que pour les fixtures effectivement dues.

Une réparation d’intention antérieure peut néanmoins publier
`recovery_r2_puts>0`. Elle rematérialise des objets déjà autorisés sans
fournisseur et reste séparée de `r2_puts`, qui demeure zéro.

Pour API-Football, seul `status.short=NS` est admissible. L’horloge et le cutoff
sont relus avant le preflight, avant chaque transport profond et à réception.
Un cutoff franchi avant transport ne consomme aucune unité ; une réponse reçue
au cutoff ou après reste durable mais porte `TEMPORALITY_FAILED`.

Une réponse vide `INJURY` reçue dans la fenêtre est une preuve négative bornée
et peut produire `NO_INJURY_REPORTED_AT_CAPTURE`. Elle ne signifie jamais
« aucune blessure réelle » et ne devient pas un zéro analytique.

`next-due-report` est strictement provider-free. Il publie dans
`reports/jalon12/next-due-windows.json` la prochaine fenêtre UTC par fixture et
famille, son workflow, son coût maximum et l’état attendu. Il ne transforme pas
une estimation en activation.

Seuls les identifiants v3 exacts de la version métier courante sont
opérationnels. Les fenêtres legacy append-only restent reconstructibles mais
sont toujours exclues de `active_windows` et du choix de la prochaine échéance.
Une génération v2 partielle n’active que ses fenêtres v3 présentes : le
scheduler idempotent la complète sans jamais réactiver le legacy ni autoriser
un second appel fournisseur sur une fenêtre obsolète.

## Robin Live

Rafraîchissement borné :

```powershell
$env:COCKPIT_PROSPECTIVE_ONLY = "1"
$env:PROSPECTIVE_REPORT_ROOT = "<artifact compact>"
python scripts/build_cockpit_snapshot.py
pnpm --dir cockpit test
```

Le builder refuse un rapport sans `PRODUCTION_LOCKED`, avec `real_bets=true`,
publication sociale active, démo active ou décisions non nulles.

`prospective-gate-report.yml` exécute dans le même verrou un replay R2 du
sous-ensemble canari sans fournisseur, puis le gate report et la synthèse par
ligue. Il construit
un premier périmètre, vérifie chaque identité contre le reçu R2 et sa projection
PostgreSQL, reconstruit le snapshot final et teste Robin Experience. Le gate,
les identités et le cockpit sont ainsi liés au même ensemble exact de reçus,
sans réutiliser un artefact d’un run antérieur. Ce mécanisme
n’implique pas un déploiement privé : tant qu’aucune cible privée n’est
explicitement reliée au dépôt, le statut exact reste
`COCKPIT_ARTIFACT_PUBLISHED`, jamais `COCKPIT_PRIVATE_DEPLOYED`.

## Contrôles quotidiens

- fixtures et kickoffs fiables ;
- fenêtres prévues/dues/capturées/manquées ;
- appels, crédits, réserves, retries et erreurs ;
- hashes, octets, lag R2 et suppressions ;
- migration, inserts, doublons et lag PostgreSQL ;
- parité exacte reçus/index/budgets R2 ↔ PostgreSQL ;
- parité de lignes complète pour player status, injuries, lineups, formations
  et odds snapshots ;
- gates et progression H11 ;
- `raw_payloads_in_git=0`.

## Incident

Préserver reçus, payloads R2, tentatives et run id. Ne pas relancer hors fenêtre.
Rejouer depuis R2 pour PostgreSQL. Une panne durable ouvre un incident
explicite ; aucune perte silencieuse ni suppression corrective n’est permise.

Le succès de reconstruction porte `R2_REPLAY_VERIFIED` et
`CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2`. Un index fixture
incomplet porte `R2_REPLAY_PARTIAL_FIXTURE_INDEX` et
`RECONSTRUCTION_INCOMPLETE`, jamais un succès générique.

Lors d’une migration de budget legacy partielle, recopier conditionnellement
chaque ligne SQL absente de R2, puis vérifier l’égalité de toutes les clés et
de tous les champs après reprojection. Ne jamais exiger que le namespace R2
soit vide pour reprendre ce seeding.

## Récupération CI replay-only

Sur la branche de pré-fusion Jalon 12, le marqueur
`[run-j12-replay-only]` autorise uniquement :

1. la vérification de présence des secrets sans affichage ;
2. `alembic upgrade head` jusqu’à `0015_chronos_fail_closed` ;
3. le replay R2 borné par l’autorité canari existante, avec credentials
   fournisseur vides ;
4. les gates, le ledger, le snapshot Robin Live et son artefact.

Les étapes fixture-registry, scheduler et captures doivent apparaître
`skipped`. Le marqueur `[run-j12-pilot]` ne doit jamais être présent sur le
même commit ; le workflow rejette ce double mode avant tout appel.
