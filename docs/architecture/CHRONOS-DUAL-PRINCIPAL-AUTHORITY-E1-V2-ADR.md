# Chronos Dual-Principal Bootstrap Authority E1 V2

Status: accepted for PostgreSQL 16 review; production activation remains prohibited.

## Decision

Chronos role provisioning uses three distinct principals:

1. an external lifecycle administrator, used only to create, fence, inspect and
   clean lifecycle roles;
2. the permanent `chronos_bootstrap_authority`, created `NOLOGIN NOINHERIT
   CREATEROLE` with a NULL password and never made authenticatable;
3. a fresh `chronos_bootstrap_executor_<suffix>`, created `LOGIN NOINHERIT
   NOCREATEROLE`, limited to one connection and at most ten minutes.

The lifecycle administrator grants the authority to the executor with exactly
`SET TRUE, INHERIT FALSE, ADMIN FALSE`. The executor proves that `CREATE ROLE`
fails with SQLSTATE `42501`, then executes `SET ROLE
chronos_bootstrap_authority`. `session_user` remains the executor while
`current_user` becomes the permanent authority.

The lifecycle administrator holds a session-level advisory lock for the whole
attempt. After `RESET ROLE` and closure of the executor connection, it proves
zero executor sessions, revokes the temporary membership, neutralizes the
credential, drops the executor, and audits the terminal graph.

Before any executor is created, the administrator proves direct visibility of
`pg_authid.rolpassword`, a NULL authority password, and the absence of hidden
or transitively effective authority memberships. Before `SET ROLE`, the
executor is checked for table, column, sequence, function and schema
privileges, including privileges inherited through `PUBLIC` on Chronos objects
and `public.alembic_version`.

## Options considered

- Self-terminalizing bootstrap owner: rejected. PostgreSQL 16 does not give a
  non-superuser role administrative authority over itself; `ALTER ROLE
  <current authority> NOLOGIN` fails with SQLSTATE `42501`.
- Use the external administrator directly for every Chronos operation:
  rejected. It couples object provenance and functional provisioning to an
  infrastructure identity and removes the bounded `SET ROLE` proof.
- Permanent NOLOGIN authority plus ephemeral executor: accepted. It separates
  authentication from authority and leaves no authenticatable administrative
  Chronos principal in terminal state.

## Exact role states

The permanent authority is always `NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
CREATEROLE NOREPLICATION NOBYPASSRLS`, with `rolconfig IS NULL`,
`rolvaliduntil IS NULL`, a NULL password, no owned object and no session.

The executor is `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 1`, has a generated in-memory
password, and has `VALID UNTIL` no later than ten minutes. A lost or expired
executor credential is never replaced on the same role. Recovery deletes that
role and creates a new name and secret.

The stable migrator remains `NOCREATEROLE`. Reactivation changes only `LOGIN`,
`PASSWORD` and `VALID UNTIL`; deactivation changes only `NOLOGIN` and
`PASSWORD NULL`. Revision 0014 contains objects and ACLs only.

## Graph classification

PostgreSQL 16 creates visible creator edges. Their exact number depends on the
external administrator profile:

| Profile | Final with executor | Terminal | Profile-specific edges |
| --- | ---: | ---: | --- |
| superuser lifecycle admin | 12 | 11 | one temporary authority-to-executor SET edge |
| non-superuser `CREATEROLE` lifecycle admin | 14 | 12 | permanent authority-to-admin creator edge, temporary executor-to-admin creator edge, and SET edge |

Both terminal graphs retain the eleven functional/bootstrap edges produced by
the superuser profile. The non-superuser profile also retains the legitimate
permanent authority-to-lifecycle-admin creator edge. It is classified, never
hidden. Both profiles require zero executor role or membership, zero runtime
path to the authority or lifecycle admin, zero migrator/runtime edge, and zero
forbidden edge.

## Crash and recovery decision

Recovery is proven after authority creation, executor creation, temporary
grant, `SET ROLE`, migration dispatch, migrator deactivation, and immediately
before executor deletion. The permanent authority and migrator keep stable
OIDs. Revision `0014` suppresses a second Alembic dispatch. Unknown, multiple,
malformed, expired, connected or secretly related executors fail closed.

Catalog drift is handled in two layers: a signed preflight snapshot continues
to fence every unrelated role, while exact managed crash residue is validated
and cleaned by the lifecycle state machine. A strict whole-inventory hash is
not used to make a legitimate recovery impossible after a committed lifecycle
mutation.

Production Alembic runs in the same process that owns the advisory-lock
connection, with a SQLAlchemy connection injected into Alembic. A retry refuses
an active migrator backend and disables a surviving LOGIN migrator before any
new credential. The crash proof waits for an ungranted relation lock on
`public.alembic_version`, terminates that exact PostgreSQL backend, and proves
zero sessions before recovery.

## PostgreSQL 16 evidence

PostgreSQL 16.14 isolated experiments A, B and C passed. Fresh clusters passed
both administrator profiles, the seven-point crash matrix, the negative matrix,
the cycle `0013 → 0014 → 0013 → 0014`, stable authority and migrator OIDs, and
the eight existing database contracts.

The negative matrix contains 23 fail-closed controls, including authority
password and membership adoption, same-name executor reuse, active/LOGIN
migrator recovery, and table-, column- and revision-table privileges granted
through `PUBLIC`. The full local evidence artifacts are source-bound to the
runner, lifecycle, in-process Alembic adapter, environment and revisions 0013
and 0014; their SHA-256 summaries are versioned under `reports/evidence/`.

No Neon API, production PostgreSQL, R2, provider, purchase, deployment, bet or
promotion action is part of this decision. Actual
`NEON_BOOTSTRAP_DATABASE_URL` capabilities are a mandatory preflight in the
next mission.
