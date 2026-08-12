# Chronos Neon Controlled Idle Wake + Read-Only Database Preflight V1

## Decision

This contract separates endpoint identity from endpoint execution state. A
project-scoped positive ownership witness may complete while the endpoint is
`idle`. Only after project, default branch, direct endpoint, secure DSN,
Scale-to-Zero, exact-SHA dispatch uniqueness, and Actions quiescence are proven
may the workflow attempt one direct PostgreSQL connection.

The connection attempt is an explicit external compute lifecycle effect. It is
recorded as `compute_wake_events <= 1`; it is not a Neon control-plane mutation.
No `/start`, `/restart`, `/suspend`, POST, PUT, PATCH, or DELETE call is allowed.

## Official Neon contract reviewed

- [Scale to Zero](https://neon.com/docs/introduction/scale-to-zero): an inactive
  compute suspends automatically and a later query reactivates it.
- [Manage computes](https://neon.com/docs/manage/endpoints/): an idle compute can
  be woken by a query; after activity stops, the existing Scale-to-Zero policy
  returns it to idle.
- [Connection errors](https://neon.com/docs/connect/connection-errors): connecting
  to an idle compute automatically activates it; the primary lifecycle states are
  `active` and `idle`.
- [Retrieve compute endpoint details](https://api-docs.neon.tech/reference/getprojectendpoint)
  and the [OpenAPI V2 specification](https://neon.com/api_spec/release/v2.json):
  `EndpointState` is `init | active | idle`; `idle` means scaled to zero.
  `suspend_timeout_seconds=-1` disables suspension, `0` uses the plan default,
  and a positive value is a finite inactivity timeout.
- [Connection pooling](https://neon.com/docs/connect/connection-pooling): a pooled
  hostname contains `-pooler`; this mission requires the already-reviewed direct
  hostname and rejects pooled access.

The reviewed default for `suspend_timeout_seconds=0` is 300 seconds. The new
workflow has a hard live-script ceiling of 120 seconds. A positive finite timeout
must be at least 300 seconds for this mission, so the operation occupies no more
than 40% of the proven inactivity window. An always-active value (`-1`), missing
field, malformed value, or shorter window fails before connection.

## Ordered gates

1. Exact new `main` SHA, run attempt 1, dispatch count 1, global Actions queue 0.
2. `NEON_PROJECT_ID` remains absent; secure direct DSN is validated without
   exposing it.
3. Candidate-first project and endpoint inventory by exact normalized DSN host.
4. Endpoint detail, project detail, default branch, and branch-scoped endpoint
   concordance complete while `active` or `idle`.
5. Endpoint must be direct, `read_write`, unpooled, enabled, and in the supported
   `active | idle` lifecycle set.
6. Existing Scale-to-Zero configuration proves automatic return to idle.
7. Read-only startup options and first explicit SQL `BEGIN READ ONLY` are proven.
8. At most one `psycopg.connect`; no retry or reconnect.
9. Bounded read-only inspection proves SSL, read-only transaction, timeouts,
   Alembic revision, bootstrap authority, and recovery feasibility.
10. Cursor and connection close; no explicit suspend and no polling for idle.

## Budgets and effects

- Neon GET: at most 25. Worst case remains 3 project pages + 16 candidate
  endpoint inventories + endpoint detail + project detail + 3 branch pages +
  branch endpoint inventory = 25.
- Neon mutations: 0; no automatic API retry.
- Production PostgreSQL connection attempts: at most 1; no retry.
- SQL statements: at most 25, allowlisted to `BEGIN READ ONLY`, `SHOW`, `SELECT`,
  and `ROLLBACK`; writes: 0.
- Compute wake events: 0 if already active; 1 if an idle endpoint receives the
  single connection attempt. A failed attempt is conservatively reported with
  upper bound 1 and indeterminate outcome.
- Branch, role, secret, variable, migration, R2, provider, and purchase effects: 0.

## Reviews

- DP5 / Platform-SRE: PASS 99. Wrong-endpoint wake, pre-identity wake, reconnect,
  and persistent configuration change are unreachable.
- DP6 / Evidence-DBA: PASS 99. Startup read-only mode precedes connection; first
  explicit SQL is `BEGIN READ ONLY`; allowlist and revision refusal are strict.
- C4 / Security-Red: PASS 98. Host redirection, idle identity bypass, second wake,
  control-plane start, raw identity leakage, and cursor-guard bypass are refused.

P0 = 0. P1 = 0. Migration authority remains separate.
