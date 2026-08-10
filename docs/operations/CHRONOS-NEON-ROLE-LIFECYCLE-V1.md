# Chronos Neon Role Lifecycle V1

Status: implementation contract; production execution is not authorized by this
document.

## Identity rule

Chronos runtime LOGIN identities are created by SQL in the bounded bootstrap
owner session. They are never created or adopted through Neon Console, Neon API,
Neon CLI, or any provider-managed identity endpoint. A runtime role carrying
`neon_superuser`, any other provider membership, or no exact bootstrap creator
edge fails closed.

The Neon client is allowlisted to the reviewed project, branch, endpoint, and
recovery-point routes. Role, user, and identity routes are forbidden.

## Bootstrap owner

The bootstrap owner is a non-superuser `CREATEROLE` authority available only
during provisioning. Each lifecycle transaction executes and verifies:

```sql
SET LOCAL createrole_self_grant = '';
```

Its authentication window is no later than the signed preflight expiry and ten
minutes after enablement. On success it finishes `NOLOGIN`, retains dormant
offline `CREATEROLE`, has a null password and no role settings, and has no other
active session. Deleting a GitHub secret does not replace database credential
invalidation.

PostgreSQL 16 automatic ADMIN edges from every role created by this owner are
expected catalog state. They must have `ADMIN=true`, `INHERIT=false`,
`SET=false`, one pinned bootstrap-system superuser grantor, and no effective
runtime `USAGE` or `SET` path.

## Schema migrator

The persistent bounded migrator role is a temporary LOGIN only while Alembic is
running. It is born and remains:

```text
NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
```

Before Alembic, `rolcreaterole=false` is asserted. The migrator receives schema
`CREATE` without grant option, schema `USAGE` and `alembic_version` SELECT only
with the grant options needed by migration 0014, and bounded DML on
`alembic_version`. Its six-minute maximum LOGIN window includes Alembic timeout
and cleanup margin.

The `finally` path revokes only schema `CREATE` and Alembic-version DML, clears
the password, verifies zero sessions, and sets `NOLOGIN` before any runtime
LOGIN is created. Schema `USAGE WITH GRANT OPTION` and revision-table `SELECT
WITH GRANT OPTION` remain as the exact dormant ACL because 0014 group grants
depend on them. The same role name and OID are reused for an authorized
downgrade/re-upgrade cycle because the migrator owns the 0014 objects.

## Alembic 0014

Migration 0014 asserts that the four exact NOLOGIN groups already exist. It
creates schema objects and applies object ACLs. It contains no `CREATE ROLE`,
`DROP ROLE`, `ALTER ROLE`, or role-membership GRANT/REVOKE. Downgrade removes
only 0014 objects and their object ACLs; roles and memberships remain unchanged.

## Runtime identities

After migration and migrator cleanup, the bootstrap owner creates:

```text
chronos_authority_runtime_login -> chronos_authority_executor
chronos_effect_runtime_login    -> chronos_runtime_writer
chronos_reader_login            -> chronos_reader
```

Each LOGIN is `NOINHERIT` and has no elevated role attributes. Each functional
edge is granted explicitly with `ADMIN FALSE, INHERIT TRUE, SET FALSE`. Passwords
are bound driver parameters, never SQL-interpolated or emitted in artifacts.

## Verification and recovery

The final graph contains exactly eleven edges: seven bootstrap ADMIN edges for
groups and runtime identities, one migrator ADMIN edge, and three functional
edges. Every other edge is `FORBIDDEN_MEMBERSHIP`.

The activation matrix must always show:

```text
forbidden_edge_count = 0
runtime_effective_bootstrap_edge_count = 0
migrator_runtime_edge_count = 0
```

An empty `0014 -> 0013 -> 0014` cycle must preserve the complete role and
membership snapshot and the migrator OID. An already-applied 0014 is a verified
resume point and never causes a second Alembic dispatch. A new signed preflight
may be issued at 0014 after the schema, ownership, ACL, marker inventory and
partial/final graph all pass exact verification.

## Secret retirement

After production provisioning is independently verified, remove the bootstrap
credential from the protected execution environment. The database owner must
already be `NOLOGIN` with a null password and zero active sessions. Scoped
runtime URLs remain separately protected and are used only by their designated
authority, effect, and reader sessions.
