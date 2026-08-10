> **Statut historique:** `SUPERSEDED_BY_CHRONOS_PRODUCTION_BOOTSTRAP_V3`.
> Conservé comme preuve; ne pas utiliser comme source d’autorité. Le handoff
> courant est `docs/handoffs/CHRONOS-PRODUCTION-BOOTSTRAP-V3-HANDOFF.md`.

# Next Mission Brief — Chronos Control Plane V2 Review and Controlled Activation

Status: `NOT_EXECUTED`

Reasoning: Very high

## Mandatory pins

```text
repository = dddur75/robin-stades-ng
pr = 41
branch = codex/robin-chronos-control-plane-v2
pr41_head = RESOLVE_EXACTLY_FROM_GITHUB_BEFORE_ANY_ACTION
main_before_merge = b03051d15e741eeb5293e0d3661572b2cb60eeba
migration = 0014_chronos_control_plane_v2
```

The mission must stop if the PR head, base, checks, or file inventory cannot be
resolved exactly. The PR head above is deliberately resolved at execution time because
the final review commit cannot contain its own SHA.

Read the provider-free validation evidence at
`reports/closure/pr41-chronos-control-plane-v2-validation-v1.json`; preserve its
explicit exact-head CI and PostgreSQL 16 proof gates.

## Starting facts to reverify

- PR #39 is closed, not merged, and its remote branch is preserved at
  `ea983c0f42177317a9c8e91f4e49974df2b63525`.
- PR #40 is merged as `b03051d15e741eeb5293e0d3661572b2cb60eeba`; its source
  branch remains at `b4b549b1caf46d69a53a1c1efe7298aab3f6f928`.
- PR #41 must still be draft and unmerged.
- No remote/Neon Chronos migration, live provider call, external R2 operation, or
  GitHub canary was executed by the preceding mission.
- No current workflow uses a protected GitHub Environment.

## Mandatory order

1. Resolve and pin the exact PR #41 head, base, diff, reviews, and CI results.
2. Snapshot the enabled/disabled state of every workflow and inventory all queued or
   in-flight GitHub Actions runs.
3. Disable the 23 automatic workflows below first, in dependency order (downstream
   `workflow_run` consumers before their producers). Then cancel or drain runs under
   the approved policy and re-list until both queued and in-progress counts are zero.
   Preserve each prior state for individual restoration. Do not dispatch any manual
   workflow during this window; hold or administratively lock every manual migration
   path listed below as well.
4. Remove automatic `alembic upgrade head` from all 23 direct and indirect paths in a
   separate reviewed activation change. No legacy workflow may retain a migrator
   credential. After the one controlled migration in step 11, replace stale `0013`
   guards with read-only `0014_chronos_control_plane_v2` checks before any individual
   workflow is re-enabled.
5. Obtain independent `DP6`, `SEC`, `SRE`, `C2`, `RP8`, and `RED` PASS on the exact
   PR head, with zero P0/P1 and score at least 95/100.
6. Create and configure the protected GitHub Environment
   `chronos-control-plane-production`, but keep it disabled and prepare only sealed
   secret slots before migration. The Chronos group roles do not exist yet. Keep the
   existing isolated migrator credential outside every workflow and Environment.
7. Merge PR #41 only after every prior gate is green, every automatic and manual
   migration path is held, and no queued or in-progress run remains.
8. Verify the exact merge SHA on `main`.
9. Generate a new 256-bit generation nonce outside PostgreSQL. Never log or persist
   the nonce in Git, artifacts, reports, or database rows.
10. Revoke the legacy shared `DATABASE_URL`; only the isolated administrative channel
    may retain the migrator credential.
11. Explicitly migrate Neon once with the isolated migrator role:
   `alembic upgrade 0014_chronos_control_plane_v2`.
12. After the migration creates the four `NOLOGIN` group roles with zero usable
    memberships, verify any PostgreSQL 16 migrator links are exactly bootstrap-granted
    ADMIN-only (`INHERIT=false`, `SET=false`) and fail `pg_has_role(...,'USAGE')`. Then
    create fresh and distinct authority, runtime, and reader LOGIN principals. Grant
    each principal exactly its matching group role; never add a usable migrator grant,
    rotate their credentials, and place only those scoped credentials plus the new
    generation nonce in the still-disabled protected Environment. Keep
    `chronos_test_writer` without production membership.
13. Verify revision, tables, append-only triggers, functions, exact LOGIN-to-group
    memberships, absence of cross-membership, effective `pg_has_role(...,'USAGE')`
    identities,
    grants,
    PostgreSQL server epoch, and generation hash.
14. In a separate PR, add a manual-only provider-free canary workflow. It must have
    no `schedule`, `push`, or `workflow_run` trigger and must use the protected
    Environment.
15. Run one exact GitHub run/attempt and one reserved operation. Verify the complete
    hash chain and effect accounting before any further action.
16. Re-enable only workflows individually audited as compatible. Never reactivate all
    23 as a batch.
17. Treat a provider canary as `DEFAULT_DENY` unless a new append-only decision names
    its provider, endpoint, fixture, run identity, expiry, and budgets.
18. Publish a final report with all SHA pins, reviews, role/grant evidence, migration,
    epoch, non-secret generation ID, effect events, budgets, and final workflow states.

## Workflows that must be held before merge

```text
api-football-coverage.yml
collect-fixtures.yml
collect-odds.yml
daily-health.yml
external-validation.yml
feature-factory.yml
historical-backfill.yml
historical-backtesting.yml
historical-market-quality.yml
historical-quality.yml
model-training.yml
post-match-settlement.yml
pre-match-shadow.yml
prequential-prediction.yml
prequential-settlement.yml
prequential-training.yml
prospective-deep-scheduler.yml
prospective-fixture-registry.yml
prospective-gate-report.yml
prospective-lineup-capture.yml
prospective-odds-capture.yml
prospective-player-capture.yml
prospective-r2-replay-audit.yml
```

The indirect migration paths that must also be audited are:

```text
.github/actions/historical-state-persist/action.yml
.github/actions/durable-shadow/action.yml
scripts/neon_bootstrap.py
```

The following manual workflows can also reach migration code and must not be
dispatched during the hold. Disable them or enforce an equivalent administrative lock;
`jalon11-operational-one-shot.yml` is included because it calls
`deep-feature-build.yml`.

```text
critical-gate-backfill.yml
historical-market-ingestion.yml
market-model-validation.yml
strategy-lab-v4.yml
pattern-discovery.yml
pattern-settlement.yml
pattern-validation.yml
shadow-pattern-decisions.yml
deep-feature-build.yml
jalon11-operational-one-shot.yml
```

The old revision guards occur after `alembic upgrade head`; they stop a workload but
cannot stop an automatic Neon migration. Holding every path and removing automatic
upgrades is therefore a merge precondition, not a post-merge cleanup.

## Provider-free canary ceiling

```text
provider_calls = 0
odds_credits = 0
R2_PUT <= 1
R2_GET <= 1, only after a 412 or explicit recovery
R2_LIST = 0
R2_HEAD = 0
R2_DELETE = 0
PostgreSQL = controlled migration and Chronos events only
workflow_dispatch = 1
deployments = 0
purchases = 0
real_bets = 0
promotions = 0
triples = 0
```

Every `PUT_DISPATCHED` consumes one unit, including 412 and ambiguous outcomes. A
GET requires the unique durable `R2_GET_DISPATCHED` permit before network I/O; a crash
or replay never sends a second GET. Old chains restored across an epoch or generation
boundary remain immutable and must not trigger R2 traffic. A
409, SDK retry possibility, lost response, or insufficient attribution stays pending
or conflict. Presence of matching bytes never proves physical creation.

## Provider canary

The provider canary remains locked after the provider-free canary. A later decision may
authorize at most one fixture, one provider request, one possible Odds credit, and one
single-attempt conditional PUT. Without that decision, stop after provider-free review.

## Stop conditions

Stop without merge, migration, or canary for any SHA drift, non-green exact-head CI,
P0/P1, score below 95, workflow not drained, unprotected environment, unsafe role or
grant, leaked nonce, epoch/generation mismatch, R2 ambiguity promoted to created or
preexisting, downgrade weakness, or exceeded budget.

## Superseded historical handoffs

This archive preserves earlier fail-closed contracts; it is not current execution
authority. The troisième architecture and `capability-scoped-evidence-ladder-v2`
handoffs remain superseded and cannot restart E1A or any earlier campaign.
