# Chronos PostgreSQL — Restore and Authority Runbook V1

## Purpose

This runbook prevents a PostgreSQL restore, PITR, Neon branch swap, compute restart or
credential rollback from silently reviving an old Chronos authority. It applies only to
the Chronos Control Plane V2 tables and roles.

It does not authorize a canary, a provider call, an R2 operation, a deployment or a
scientific workflow dispatch.

## Safety invariant

A restored or restarted control plane is quarantined until all of these are new and
proven together:

```text
control-plane generation nonce
runtime and authority credentials
GitHub run identity
authority ticket
authority claim
PostgreSQL server epoch
```

Expected rejection for a snapshot containing an old authority:

```text
AUTHORITY_REJECTED_AFTER_RESTORE
```

## Roles

| Role | Purpose | Prohibited |
|---|---|---|
| `chronos_reader` | Read audit tables and accounting views | DML, functions that mutate |
| `chronos_test_writer` | Local/CI test surfaces only | Production CONNECT/USAGE/EXECUTE |
| `chronos_runtime_writer` | Claim authority and append validated transitions | Direct table DML, DDL, issue authority |
| `chronos_authority_executor` | Issue short-lived authority | Runtime transitions, direct DML |
| migration owner | Apply the reviewed migration | Scientific runtime use |

Use distinct connection strings for migrator, authority, runtime and reader. Never put
the migrator credential in a scientific workflow.

Migration `0014` creates the four Chronos roles as `NOLOGIN` groups and requires zero
usable memberships while the schema is installed or reinstalled. PostgreSQL 16 gives a
non-superuser `CREATEROLE` migrator an unavoidable ADMIN-only link to each role. The
migration accepts only that exact system topology: bootstrap grantor, `ADMIN=true`,
`INHERIT=false`, `SET=false`; production gates test `USAGE`, so this link conveys no
runtime authority. Any other membership fails closed. After migration, an administrator
may create three fresh LOGIN principals and grant each exactly one group: authority
executor, runtime writer, or reader. Do not create a production member for
`chronos_test_writer`, and reject cross-memberships. Verify catalog topology and
effective `pg_has_role(login, group, 'USAGE')` before enabling the Environment. Before
any later downgrade or reapplication of `0014`, freeze workflows and revoke these LOGIN
memberships first; retain only the audited ADMIN-only migrator links.

Upgrade, downgrade to `0013_historical_evidence_index`, and reapplication of revision
`0014` must use the same isolated PostgreSQL `current_user`: the migrator that owns the
revision objects and directly granted its reviewed ACLs. Only after that migrator has
completed the `0014 -> 0013` boundary may the legacy migration owner downgrade older
revisions. A different administrator is not a substitute for the original ACL grantor.

## External generation

The generation is a random 256-bit nonce created outside PostgreSQL.

- Keep the nonce only in a protected GitHub environment.
- Store only its SHA-256 in PostgreSQL authority rows.
- Never derive it from a database row, database timestamp, branch ID or other
  restorable value.
- Treat the nonce and all old runtime/authority credentials as compromised after a
  restore boundary until rotated.
- Record a non-secret generation ID and the target Neon project/branch/endpoint in the
  external incident record.

A public hash is not a generation credential.

## Events that require quarantine

Run this procedure after any of the following:

- Neon restore or PITR;
- Neon branch restore, branch swap or endpoint reassignment;
- compute rotation or unexpected PostgreSQL restart;
- migration rollback involving the Chronos schema;
- suspected credential or generation rollback;
- clone of production data into another target;
- failure to prove the current `pg_postmaster_start_time()`.

A normal application retry without any of these events does not rotate generation; it
reuses the same `operation_id` and reads its durable state.

## Phase 1 — Freeze before restore

1. Disable the GitHub protected environment that exposes authority/runtime credentials.
2. Revoke or disable the Chronos runtime and authority login credentials.
3. Disable the R2 writer credential associated with the target.
4. Record the exact source and destination:
   - Neon project;
   - branch;
   - endpoint;
   - database;
   - requested restore point;
   - current GitHub run ID and attempt;
   - current non-secret generation ID.
5. Confirm there is no active Chronos job.
6. Do not dispatch a replacement workflow.
7. Do not LIST, HEAD, GET or PUT R2 during the database restore itself.

If credentials cannot be revoked, stop. Do not reconnect the restored target.

## Phase 2 — Restore into isolation

1. Restore into a target that is not reachable by the runtime credential.
2. Keep provider and R2 secrets absent.
3. Use only the migration/administrative identity required for verification.
4. Confirm the database target independently; never trust a restored label alone.
5. Capture, without changing data:
   - migration revision;
   - table and function inventory;
   - role memberships and grants;
   - `pg_postmaster_start_time()`;
   - counts of authorities and effect events;
   - operations whose latest state is `PUT_DISPATCHED`,
     `R2_GET_DISPATCHED`,
     `PUT_COMMITTED_ACTUAL_PENDING` or
     `RECOVERY_OBSERVED_MATCHING_OBJECT`.
6. Do not claim, reserve or append an event with an old authority.

A restored hash chain may be internally valid and still be truncated. The external
generation fence is what prevents that truncated history from becoming authoritative.

## Phase 3 — Rotate the security boundary

Perform these steps while the target remains quarantined:

1. Generate a new random 256-bit generation nonce outside PostgreSQL.
2. Assign a new non-secret generation ID.
3. Rotate the authority login.
4. Rotate the runtime login.
5. Rotate the R2 writer credential if it could have been shared with the old runtime.
6. Update the protected GitHub environment with the new credentials and nonce.
7. Remove old secrets from that environment.
8. Verify that local shells and unprotected jobs cannot read the new values.
9. Record the target project/branch/endpoint alongside the new generation ID.

Do not copy the old generation nonce into the restored target for compatibility.

## Phase 4 — Verify schema and privilege fences

Using the migration/administrative identity, verify:

- both Chronos tables exist at the reviewed revision;
- UPDATE and DELETE triggers exist and are enabled;
- `PUBLIC` has no rights on Chronos tables or functions;
- `chronos_runtime_writer` has EXECUTE only on claim/transition functions;
- `chronos_authority_executor` has EXECUTE only on authority issuance;
- `chronos_test_writer` has no production function execution;
- no application role is a migration owner or can disable triggers;
- functions are `SECURITY DEFINER` with a pinned `search_path`;
- `clock_timestamp()` and `pg_postmaster_start_time()` are used by the production
  functions;
- no production function accepts `now`, `test_now`, `fake_now` or an injected
  clock;
- the server epoch differs from every authority issued before the compute boundary.

Any mismatch keeps the target quarantined.

## Phase 5 — Negative authority test

Before issuing a new authority, use the protected runtime path to attempt a claim of an
old ticket with:

- the old run identity, if available;
- the current run identity;
- the new generation nonce.

Every attempt must fail. Accepted rejection codes include:

```text
CHRONOS_SERVER_EPOCH_MISMATCH
CHRONOS_CONTROL_PLANE_GENERATION_MISMATCH
CHRONOS_GITHUB_RUN_IDENTITY_MISMATCH
CHRONOS_AUTHORITY_NOT_ACTIVE
```

Record the combined drill verdict as:

```text
AUTHORITY_REJECTED_AFTER_RESTORE
```

If any old authority succeeds, revoke the new logins and stop.

## Phase 6 — New run and authority

Only after the negative test passes:

1. Start a new GitHub run.
2. Use its exact:
   - `github_run_id`;
   - `github_run_attempt`;
   - `github_sha`;
   - `github_workflow_ref`;
   - `github_workflow_sha`;
   - `github_repository`;
   - `github_ref`.
3. Issue a short-lived authority using the authority credential.
4. Claim it using the runtime credential and the new generation nonce.
5. Verify the returned:
   - authority ID;
   - DB-authorized timestamp;
   - half-open expiry;
   - PostgreSQL server epoch;
   - authority receipt hash.
6. Do not reuse a ticket from a previous run attempt.

This phase proves only the control plane. It does not authorize R2 or provider traffic
unless a later mission explicitly does so.

## Phase 7 — Pending-effect reconciliation

Restored operation chains are immutable evidence. Their `operation_id` binds the old
run and attempt, so a new recovery authority cannot append to them and must not try.
Do not issue R2 GET/LIST/HEAD requests for an old chain after restore; retain its last
state as pending and record it in the incident report. A future cross-generation
reconciliation ledger requires a separate reviewed decision.

For a pending operation created after the new boundary, recovery is allowed only while
the original authority still matches the current server epoch, generation, run and
attempt:

1. Confirm its canonical key and payload hash.
2. Commit the unique `R2_GET_DISPATCHED` permit before the exact-key GET.
3. If the permit already exists, do not send another GET.
4. If no object or no response is obtained, retain unknown attribution.
5. If exact bytes exist, append `RECOVERY_OBSERVED_MATCHING_OBJECT`.
6. If bytes differ, append `INTEGRITY_CONFLICT`.
7. Never turn matching bytes into `CREATED_CONFIRMED`.
8. Promote only if a future R2 metadata contract proves author, atomic persistence,
   immutability and writer isolation.

An ETag alone is not proof of bytes or author. A request ID lost before durable
recording is not recoverable evidence.

## Phase 8 — Re-enable

Re-enable access only when all gates are present:

```text
schema verified
roles verified
append-only triggers verified
old authority rejected
new generation anchored externally
new credentials active
new run identity captured
new authority claimed
pending operations classified honestly
```

Restore the protected environment first. Do not expose credentials to local commands.
Enable only the workflow explicitly authorized by the later mission.

## Compute restart without restore

A compute restart changes `pg_postmaster_start_time()`. Therefore:

1. let in-flight jobs fail closed;
2. revoke the old authority;
3. start a new GitHub run;
4. issue a new authority against the new epoch;
5. treat any operation after `PUT_DISPATCHED` and before a final event as pending.

A restart must never be hidden by accepting the old authority.

## Rollback and downgrade

The migration downgrade is fail-closed:

- if any authority or effect event exists, downgrade raises an error;
- the same isolated migrator identity must cross the `0014 -> 0013` boundary;
- the legacy migration owner may continue from `0013` only after that boundary succeeds;
- operators must export and review evidence under a separate retention procedure;
- no row may be deleted merely to make downgrade pass;
- roles are not silently broadened to support an older runtime.

## Evidence to retain

Retain locally or in the approved operational record:

- incident/restore identifier;
- source and target project/branch/endpoint;
- old and new non-secret generation IDs;
- credential rotation timestamps, not secret values;
- old-authority negative-test results;
- old and new server epochs;
- new GitHub run identity;
- new authority receipt hash;
- pending-operation inventory and classifications;
- reviewer sign-off.

Never store the generation nonce, connection strings or provider/R2 secret values in
Git.

## Abort conditions

Stop and keep the target quarantined if:

- target identity is ambiguous;
- an old login still works unexpectedly;
- an old authority can be claimed;
- the server epoch cannot be proven;
- the new generation is derived from restored data;
- PUBLIC or the test role can execute production functions;
- append-only triggers are missing or disabled;
- R2 authorship would require inference from object presence;
- a provider or scientific workflow would need to run to validate the restore.
