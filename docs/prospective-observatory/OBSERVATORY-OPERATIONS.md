# Exploitation de l’Observatoire

## Workflows

| Workflow | Cadence/rôle |
|---|---|
| `prospective-fixture-registry.yml` | quotidien, fixtures futures |
| `prospective-deep-scheduler.yml` | horaire, sélection des fenêtres dues |
| `prospective-player-capture.yml` | joueurs, squads, statuts et blessures |
| `prospective-lineup-capture.yml` | lineups et formations proches du kickoff |
| `prospective-odds-capture.yml` | snapshots 1X2 et O/U 2,5 bornés |
| `prospective-r2-replay-audit.yml` | replay sans fournisseur |
| `prospective-gate-report.yml` | couverture, temporalité et cockpit |

Tous utilisent `prospective-deep-state`, sans `historical-state` ni
`shadow-state`. Les schedules GitHub ne descendent pas sous une heure.
La configuration partagée est
`configs/prospective_observatory_v1.json`.

## CLI

```text
scripts/run_prospective_observatory.py fixture-registry
scripts/run_prospective_observatory.py scheduler
scripts/run_prospective_observatory.py capture-player
scripts/run_prospective_observatory.py capture-lineup
scripts/run_prospective_observatory.py capture-odds
scripts/run_prospective_observatory.py replay-audit
scripts/run_prospective_observatory.py gate-report
```

Consulter `--help` pour les paramètres. `pilot-mock` sert uniquement aux tests
et ne peut jamais alimenter Robin Live comme source réelle.

## Rapports compacts

Le répertoire d’artifact contient :

```text
fixture-registry.json
scheduler-plan.json
general-capture-report.json
player-capture-report.json
lineup-capture-report.json
odds-capture-report.json
r2-replay-audit.json
gate-report.json
public-evidence-ledger-v3-<sha256>.jsonl
pilot-report.json
```

Le bloc `observatory` est nettoyé et peut alimenter le cockpit si les invariants
production, social et démo sont explicites. Aucun payload brut ni secret n’y
figure.

## Ordre d’un pilote

1. registre Ligue 1 ;
2. plan du scheduler ;
3. publication des fenêtres dues et du coût maximum ;
4. captures uniquement dues et autorisées ;
5. vérification R2 ;
6. projection PostgreSQL ;
7. replay audit ;
8. gate report ;
9. snapshot Robin Live.

Si `windows_due=0`, s’arrêter sans appel. Une fixture enregistrée sans lineup,
blessure ou cote due est un pilote sain.

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

`prospective-gate-report.yml` reconstruit et teste ce snapshot, puis publie
l’état Robin Live et le ledger V3 dans un artefact compact. Ce mécanisme
n’implique pas un déploiement privé : tant qu’aucune cible privée n’est
explicitement reliée au dépôt, le statut exact reste
`COCKPIT_ARTIFACT_PUBLISHED`, jamais `COCKPIT_PRIVATE_DEPLOYED`.

## Contrôles quotidiens

- fixtures et kickoffs fiables ;
- fenêtres prévues/dues/capturées/manquées ;
- appels, crédits, réserves, retries et erreurs ;
- hashes, octets, lag R2 et suppressions ;
- migration, inserts, doublons et lag PostgreSQL ;
- gates et progression H11 ;
- `raw_payloads_in_git=0`.

## Incident

Préserver reçus, payloads R2, tentatives et run id. Ne pas relancer hors fenêtre.
Rejouer depuis R2 pour PostgreSQL. Une panne durable ouvre un incident
explicite ; aucune perte silencieuse ni suppression corrective n’est permise.

## Récupération CI replay-only

Sur la branche de pré-fusion Jalon 12, le marqueur
`[run-j12-replay-only]` autorise uniquement :

1. la vérification de présence des secrets sans affichage ;
2. `alembic upgrade head` jusqu’à `0009_jalon12_observatory` ;
3. le replay intégral R2 avec credentials fournisseur vides ;
4. les gates, le ledger, le snapshot Robin Live et son artefact.

Les étapes fixture-registry, scheduler et captures doivent apparaître
`skipped`. Le marqueur `[run-j12-pilot]` ne doit jamais être présent sur le
même commit ; le workflow rejette ce double mode avant tout appel.
