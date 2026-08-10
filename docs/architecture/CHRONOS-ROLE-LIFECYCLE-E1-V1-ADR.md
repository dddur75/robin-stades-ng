# Chronos Role Lifecycle E1 V1

Status: accepted for implementation after independent design review
Decision: `BOOTSTRAP_OWNED_ROLE_LIFECYCLE`
Date: 2026-08-10
Frozen predecessor: PR #43 at `b942f24f8306fbf96717c2a69dbb80a1ff16d4eb`

## Context

PR #43 delegates role creation to a temporary non-superuser migrator carrying
`CREATEROLE`. PostgreSQL 16 automatically records an administrative membership
when such a principal creates a role. For each scoped runtime LOGIN the observed
edge is:

```text
granted_role = newly created LOGIN
member_role = creating migrator
grantor = cluster bootstrap superuser
admin_option = true
inherit_option = false
set_option = false
```

The behavior was reproduced by the PostgreSQL 16 service in GitHub Actions runs
[31343668450](https://github.com/dddur75/robin-stades-ng/actions/runs/31343668450)
and
[31344137405](https://github.com/dddur75/robin-stades-ng/actions/runs/31344137405).
The corrected reader privilege and seven other contracts pass. The only failing
contract reports the three reverse memberships from
`chronos_authority_runtime_login`, `chronos_effect_runtime_login`, and
`chronos_reader_login` to `robin_ci_migrator`. PostgreSQL logs also report that
the migrator had not itself granted these memberships, so its attempted
`REVOKE <created_login> FROM CURRENT_USER` cannot remove them.

The PostgreSQL 16 role-membership model documents independent `ADMIN`,
`INHERIT`, and `SET` membership options. This decision treats catalog direction
and every option as security-significant; a role name pair alone is not enough.

## Options considered

### A. Migrator `CREATEROLE` plus creator-edge `REVOKE`

Decision: `REJECTED_IMPOSSIBLE_POSTGRESQL16`.

The creator edge is granted by the cluster bootstrap superuser, not by the
non-superuser creator. Retrying the same `REVOKE`, moving it, or spelling the
same path through a helper does not change ownership of the grant. This is the
prohibited architecture:

```text
MIGRATOR_CREATES_RUNTIME_LOGINS = SAME_ARCHITECTURE_PROHIBITED
MIGRATOR_REVOKES_CREATOR_ADMIN_EDGE = IMPOSSIBLE_UNDER_POSTGRESQL_16
```

### B. Bootstrap owner provisions identities; migrator is `NOCREATEROLE`

Decision: `ACCEPTED`.

The offline bootstrap owner is a non-superuser with `CREATEROLE`. It creates or
validates the four NOLOGIN groups, creates a bounded temporary migrator, and
later creates the three runtime LOGIN identities. The migrator performs schema
migration only and cannot create, alter, drop, or administer roles. Automatic
creator edges terminate at the offline bootstrap owner and are classified
explicitly; they do not become runtime-effective because both `INHERIT` and
`SET` are false.

### C. Neon Console, API, or CLI creates scoped runtime LOGIN identities

Decision: `REJECTED_NEON_SUPERUSER_RISK`.

Provider-created identities can acquire provider-managed capabilities such as
`neon_superuser`. Runtime LOGIN identities must therefore be created by SQL in
the bounded bootstrap-owner session, never by the Neon identity API:

```text
NEON_API_CREATES_SCOPED_RUNTIME_LOGINS = REJECTED_NEON_SUPERUSER_RISK
```

The production Neon client has an explicit route-and-method allowlist limited
to the already reviewed project, branch, endpoint, and recovery-point
operations. Every role, user, or identity endpoint is outside the allowlist.
Console/CLI-created identities are never an adoption or resume path. A runtime
identity lacking the pinned bootstrap creator edge, or carrying
`neon_superuser` or any other provider-managed membership, fails closed as
`FORBIDDEN_MEMBERSHIP`.

## Responsibility boundaries

### Bootstrap owner

- non-superuser, offline, `CREATEROLE`, outside runtime;
- runs every lifecycle transaction with
  `SET LOCAL createrole_self_grant = ''` and verifies the setting;
- creates or validates the four exact NOLOGIN group roles;
- creates the temporary LOGIN migrator as `NOINHERIT NOCREATEROLE`;
- creates the three runtime LOGIN identities after migration;
- grants each functional membership with explicit
  `ADMIN FALSE, INHERIT TRUE, SET FALSE` options;
- disables the migrator with `NOLOGIN` after migration;
- retains administrative authority offline only; its credential is removed
  from the operational environment after provisioning.
- audits the complete role graph before any 0014 object ACL is granted and
  again after every lifecycle transition.
- carries a short `VALID UNTIL` bootstrap window and, after successful
  provisioning, terminalizes authentication as `NOLOGIN` while retaining the
  offline `CREATEROLE` authority, clears its password and role settings,
  verifies there are no other bootstrap-owner sessions, and closes the final
  session. Removing a GitHub secret alone is not accepted as credential
  invalidation. A future controlled lifecycle run must install a new password,
  open a new short `VALID UNTIL` window, and only then re-enable LOGIN.
- performs that terminalization on success and on every non-resumable terminal
  failure. A resumable failure emits no PASS, leaves no active bootstrap-owner
  session, and retains credential validity only until the pinned `VALID UNTIL`
  deadline. Cleanup failure overrides any success verdict.
- bounds bootstrap-owner `valid_until` to the earlier of signed-preflight expiry
  and ten minutes after enablement. The migrator window is bounded to the
  five-minute Alembic timeout plus a one-minute cleanup margin. Neither deadline
  may be extended automatically within the same run. Both sessions set local
  `statement_timeout`, `idle_session_timeout`, and
  `idle_in_transaction_session_timeout`; expiry or error leads to `NOLOGIN`, a
  null password, and zero remaining sessions.

### Migrator

- dynamic bounded name and persistent role identity/OID, but only a temporary
  LOGIN capability, `NOINHERIT NOCREATEROLE`;
- owns or receives only the schema and object privileges required by Alembic;
- has no Chronos functional group membership and no membership involving a
  runtime LOGIN;
- cannot create, alter, drop, or grant roles;
- terminates as `NOLOGIN` in an unconditional cleanup path, including after a
  migration or verification failure;
- is reused by exact provenance and role name for downgrade/re-upgrade because
  it owns the 0014 objects and is their object-ACL grantor.

### Alembic migration 0014

- asserts that all four group roles already exist and have exact safe
  attributes;
- creates tables, views, functions, and triggers;
- revokes and grants object privileges only;
- contains no role creation, role deletion, or role-membership mutation;
- downgrade removes only 0014 objects and object ACLs; roles and memberships
  remain byte-for-byte outside Alembic lifecycle.

### Runtime LOGIN identities

- are `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  NOBYPASSRLS`;
- receive exactly one functional group membership;
- cannot `SET ROLE` to another runtime LOGIN, the migrator, or the bootstrap
  owner;
- cannot administer memberships.

## Exact membership classification

The verifier audits both ends of every edge touching a Chronos role, the
migrator, or the bootstrap owner.

`EXPECTED_RUNTIME_GROUP_EDGE` (grantor is exactly the observed bootstrap owner,
not merely any non-superuser):

```text
chronos_authority_executor -> chronos_authority_runtime_login
chronos_runtime_writer -> chronos_effect_runtime_login
chronos_reader -> chronos_reader_login
admin=false, inherit=true, set=false
```

`EXPECTED_BOOTSTRAP_ADMIN_EDGE` (grantor is exactly one pinned, observed
bootstrap-system superuser identity shared by all automatic creator edges):

```text
created Chronos role -> bootstrap owner
grantor is a superuser
admin=true, inherit=false, set=false
runtime_effective=false
```

`EXPECTED_MIGRATOR_ADMIN_EDGE`:

```text
migrator -> bootstrap owner
grantor is the same pinned bootstrap-system superuser identity
admin=true, inherit=false, set=false
runtime_effective=false
```

Every other edge is `FORBIDDEN_MEMBERSHIP`.

The audit predicate covers both directions for Chronos roles, the migrator, and
the bootstrap owner. In particular, it includes both `member_role = bootstrap
owner` and `granted_role = bootstrap owner`; the latter cannot be hidden merely
because it is not runtime-facing and is forbidden. The exact final graph has
eleven edges: three functional edges, seven bootstrap-admin edges for the four
groups plus three runtime LOGIN identities, and one migrator-admin edge. Any
other edge is forbidden.

Stage inventories are exact as well: group provisioning adds four roles and
four admin edges; migrator provisioning adds exactly one persistent role and
one admin edge; final runtime provisioning adds three roles and six edges,
reaching eleven overall. No helper role or alias is permitted, even if its name
contains neither `chronos` nor `migrator`. The migrator is born
`NOCREATEROLE`; no lifecycle statement may alter it or an alias to
`CREATEROLE`. Among lifecycle principals, only the pinned bootstrap owner may
carry `CREATEROLE`.

## Invariants

The rejected `ZERO_BIDIRECTIONAL_MEMBERSHIPS` shorthand is replaced with:

```text
ZERO_MIGRATOR_TO_RUNTIME_MEMBERSHIP
ZERO_RUNTIME_TO_MIGRATOR_MEMBERSHIP
ZERO_UNEXPECTED_RUNTIME_INHERITANCE
ZERO_RUNTIME_ADMIN_OPTION
ZERO_RUNTIME_SET_ROLE_PATH
BOOTSTRAP_ADMIN_EDGES_EXACTLY_CLASSIFIED
```

The activation matrix must always prove:

```text
forbidden_edge_count = 0
runtime_effective_bootstrap_edge_count = 0
migrator_runtime_edge_count = 0
```

`runtime_effective` is computed from PostgreSQL effective-role checks, including
`pg_has_role(..., 'USAGE')` and `pg_has_role(..., 'SET')`, rather than inferred
from a classification label. The matrix also records whether the member can
authenticate and whether the edge is administratively effective. Transitive
paths are tested; no indirect runtime or `SET ROLE` path is allowed.

## Lifecycle and recovery

The only accepted sequence is:

```text
preprovision groups
audit exact group provenance, attributes, grantor and both edge directions
create NOCREATEROLE migrator
assert rolcreaterole=false
upgrade 0013 -> 0014
disable migrator immediately in the Alembic finally path
create runtime LOGIN identities as bootstrap owner
grant explicit functional memberships
audit both directions and connection permissions
```

The PostgreSQL 16 contract cycle provisions the final eleven-edge graph first,
then proves that an empty downgrade 0014 -> 0013 leaves all eight lifecycle role
OIDs and memberships unchanged, and that re-upgrade is idempotent with those
same preprovisioned roles.

Lifecycle operations are resumable without changing role identity:

- a role with the expected bounded name, provenance, attributes, exact
  automatic admin edge, and no forbidden edge is adopted; any mismatch fails
  closed;
- a terminal migrator is re-enabled with a newly generated parameterized
  password only for the migration transaction, then disabled again;
- revision 0013 permits at most one 0014 Alembic dispatch; revision 0014 is
  treated as an already-applied resume point and is verified without a second
  dispatch;
- an existing partially provisioned runtime LOGIN is adopted only after exact
  attribute, provenance, grantor, and bidirectional-edge validation, then its
  password is rotated through a bound parameter;
- migrator cleanup is an unconditional `finally` around the Alembic subprocess,
  occurs before runtime LOGIN provisioning, and a cleanup failure overrides a
  success verdict.

The bounded migrator name is derived from stable database/branch identity stored
in the signed preflight artifact, never from a GitHub run id. A later controlled
run therefore resolves the same role name and OID.

Schema delegation is split deliberately: the migrator receives `USAGE` with
grant option because migration 0014 grants schema usage to groups, while
`CREATE` is granted without grant option. `alembic_version` SELECT is delegated
with grant option, while its required DML is granted without grant option.
Before the migrator becomes `NOLOGIN`, bootstrap revokes schema `CREATE` and
the Alembic-version DML privileges. It deliberately preserves only schema
`USAGE WITH GRANT OPTION` and `alembic_version SELECT WITH GRANT OPTION`: the
0014 grants to functional groups depend on these two grants, and revoking them
with `RESTRICT` would fail. Their exact dormant ACL is audited; LOGIN and the
password are removed and no migrator session may remain.

Parameterized PostgreSQL utility statements (`CREATE ROLE`, `ALTER ROLE`, and
`COMMENT ON ROLE`) use psycopg `ClientCursor`, which performs safe client-side
literal binding because PostgreSQL utility grammar does not accept extended-
protocol `$1` parameters at those positions. The Alembic child receives an
allowlisted environment containing its scoped URL and no Neon key, bootstrap
DSN, runtime secret, or generation nonce.

Adoption checks for every pre-existing group preserve the former 0014
anti-smuggling controls outside Alembic: no role settings, unexpected ACL or
default ACL, unexpected ownership, or forbidden membership may exist. After
0014, object ACLs must match the exact allowlist before runtime LOGIN identities
are provisioned.

## Consequences

- Role lifecycle is no longer transactionally coupled to Alembic schema
  lifecycle.
- Bootstrap administrative edges are expected catalog evidence, not runtime
  privileges; hiding them is a verification failure.
- The bootstrap credential becomes more sensitive but shorter-lived and remains
  outside runtime.
- Production bootstrap requires a pre-existing SQL-capable bootstrap owner; it
  must not use a provider identity-creation API.
- Provider-free canary budgets, effect journaling, replay behavior, workflow
  manual-only guards, revision guards, and secret sentinels remain unchanged.

## E1 constraints

This implementation and its tests perform no Neon API or SQL calls, no R2
operation, no provider call, no Odds credit, no deployment, and no production
mutation. PR #43 remains frozen until the replacement PR has passed its exact
CI and final review.
