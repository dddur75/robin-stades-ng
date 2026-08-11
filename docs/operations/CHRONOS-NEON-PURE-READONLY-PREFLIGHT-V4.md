# Chronos Neon Pure Read-Only Preflight V4

## Purpose

This workflow proves whether the existing Neon production state is compatible
with a separately authorized Chronos migration. It does not authorize or run a
migration. A GO verdict is evidence for a later Council decision only.

The workflow must be dispatched from the exact `main` revision and only after
all other Actions runs are complete. A rerun (`GITHUB_RUN_ATTEMPT != 1`) fails
closed. Never dispatch the workflow twice for the same mission.

## Protected execution

- workflow: `.github/workflows/chronos-neon-pure-readonly-preflight-v4.yml`;
- trigger: `workflow_dispatch` only;
- environment: `chronos-control-plane-production`;
- permissions: `contents: read`;
- required secrets: `NEON_API_KEY`, `NEON_BOOTSTRAP_DATABASE_URL`;
- optional repository variable: `NEON_PROJECT_ID` (recommended to remove any
  multi-project ambiguity).

The queue and dispatch-history checks use the public GitHub Actions read
endpoint without a token. They add no permission beyond `contents: read` and
make three requests. The exact-main workflow history must contain this dispatch
exactly once, which closes both reruns and a second distinct dispatch.

The script accepts only a direct PostgreSQL URL with TLS required and exactly
one query parameter, `sslmode`. URL fragments, path parameters and libpq
overrides such as `host`, `hostaddr`, `port`, `user` or `dbname` fail before
any network request. Pooled, localhost, passwordless, non-PostgreSQL and
non-Neon targets fail closed.
The workflow installs a dedicated hash-locked runtime with no Alembic, boto3,
S3 or SQLAlchemy package.

## Read-only envelope

The Neon client exposes `GET` only. It has no generic HTTP request method and a
hard ceiling of 25 calls; the bounded multi-project path performs at most 24.
It lists existing projects, branches and endpoints and reads one matched
project detail. It does not create, modify, suspend, start, restore or delete a
resource.

PostgreSQL is opened with:

```text
default_transaction_read_only=on
statement_timeout=15000
lock_timeout=3000
```

The first explicit statement is `BEGIN READ ONLY`, the last is `ROLLBACK`, and
the source contains at most 25 statements. The current implementation uses 14.
Only transaction control, `SHOW` and `SELECT` are accepted by the static gate.

The inspection reads:

- database and PostgreSQL version;
- actual TLS state;
- current Alembic revision;
- lifecycle-admin role capabilities and privileged catalog visibility;
- existing `chronos_%` roles and memberships;
- existing Chronos relations and functions.

The endpoint must already be `active`. An `idle` endpoint produces
`DIRECT_ENDPOINT_NOT_PROVEN` before PostgreSQL connection, so the preflight
cannot implicitly wake or start a compute. The Alembic table must contain
exactly one row and that row must be the expected revision; zero or multiple
heads fail closed.

It does not execute Alembic and performs no `CREATE`, `ALTER`, `DROP`, `GRANT`,
`REVOKE`, `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` statement.

## Recovery feasibility

No recovery branch is created. Feasibility requires all of the following
read-only evidence:

- the exact production branch is bound to the direct DSN endpoint;
- the branch is ready or active;
- project history retention is positive;
- the bounded project inventory is complete and has a single owner scope;
- every branch inventory is unpaginated and complete;
- the owner-wide current branch count is strictly below the documented
  `project.owner.branches_limit` allowance;
- the GitHub Actions queue and in-progress counts are zero after excluding the
  preflight itself.

If the allowance would be exceeded, the exact reason is `PURCHASE_REQUIRED`.
No purchase is attempted.

## Sanitized artifact

The uploaded JSON contains hashes of project, branch (including its name),
endpoint, database and role identifiers. It never contains the API key, DSN,
password, endpoint host or raw provider response. Stable counters prove zero
Neon mutation, zero SQL write, zero R2 operation, zero provider call, zero
migration and zero purchase.

The expected revision is exactly:

```text
0013_historical_evidence_index
```

Any other value produces `UNEXPECTED_DATABASE_REVISION` and no mutation.

## Verdicts

GO is exactly:

```text
CHRONOS_NEON_MIGRATION_READY_FOR_SEPARATE_AUTHORIZATION
```

NO-GO is exactly:

```text
CHRONOS_NEON_MIGRATION_NOT_AUTHORIZED
```

with one approved reason:

```text
NEON_PROJECT_IDENTITY_AMBIGUOUS
NEON_PRODUCTION_BRANCH_AMBIGUOUS
DIRECT_ENDPOINT_NOT_PROVEN
UNEXPECTED_DATABASE_REVISION
BOOTSTRAP_AUTHORITY_INSUFFICIENT
RECOVERY_BRANCH_NOT_FEASIBLE
PURCHASE_REQUIRED
SECRET_MISSING
```

Even after GO, recovery branch creation, role creation, migration `0014`,
runtime credential installation, provider-free canary, R2 and provider calls
remain prohibited and require a separate authorization.
