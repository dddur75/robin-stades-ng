# Chronos Dual-Principal Lifecycle V1

This runbook describes the accepted lifecycle. It does not authorize a Neon or
production execution.

## Preconditions

- The reviewed draft PR and its exact-head CI are green.
- The external database URL resolves to a direct PostgreSQL 16 endpoint.
- A capability preflight proves that the external principal is a LOGIN and is
  either superuser or `CREATEROLE`, can inspect the required privileged
  `pg_authid.rolpassword` catalog column, can use advisory locks, and can create
  and delete the bounded roles.
- The current revision is `0013` or an exactly validated `0014` recovery state.
- No unknown executor and no concurrent lifecycle lock exists.

Stop before mutation when any capability is missing. Do not weaken the
authority to `LOGIN` and do not use a runtime identity as lifecycle admin.

## Ordered lifecycle

1. Open the external lifecycle-admin connection and acquire the Chronos
   advisory lock.
2. Create or exactly adopt `chronos_bootstrap_authority` as permanent
   `NOLOGIN CREATEROLE`; record its OID and prove its NULL password.
3. Clean one exact stale executor if it has no active session. Refuse unknown or
   multiple executors.
4. Generate a new executor name and password in memory. Create it with one
   connection and a deadline no later than ten minutes.
5. Commit creation separately, then grant the authority with exactly `SET TRUE,
   INHERIT FALSE, ADMIN FALSE` and commit again.
6. Connect as executor. Prove exact catalog state, exact memberships,
   `rolcreaterole = false`, no effective schema/table/column/sequence/function
   privilege from direct ACLs or `PUBLIC`, and failed `CREATE ROLE` with
   SQLSTATE `42501`.
7. Execute `SET ROLE chronos_bootstrap_authority`; prove `session_user` is the
   executor and `current_user` is the authority.
8. Create/adopt group roles, activate the stable migrator with only `LOGIN`,
   `PASSWORD`, and `VALID UNTIL`, and dispatch in-process Alembic only when a
   revision reread under the advisory lock proves 0013.
9. Deactivate the migrator with only `NOLOGIN PASSWORD NULL`; assert its full
   role state, ACLs, ownership, revision and zero sessions.
10. Create/adopt runtime logins and exact functional memberships, then run the
    final active graph audit.
11. Execute `RESET ROLE`, close the executor connection, and refresh the
    PostgreSQL statistics snapshot.
12. From the external connection, prove zero executor sessions, revoke the
    temporary grant, execute `ALTER ROLE <executor> NOLOGIN PASSWORD NULL`, and
    drop the executor.
13. Prove the terminal authority, migrator, graph, OIDs and password state, then
    release the lock and close the lifecycle-admin connection.

Never log or serialize the executor password or its URL. A retry always creates
a fresh credential and fresh role name.

## Recovery matrix

| Last committed point | Recovery action |
| --- | --- |
| authority created | adopt exact authority and same OID |
| executor created | validate, neutralize and drop it; create a fresh executor |
| temporary grant committed | validate exact options, clean it, then create fresh executor |
| after `SET ROLE` | the lost session ends; external admin cleans the old executor |
| during migration | require zero surviving backend, inspect revision and objects, then disable migrator before any resume |
| migrator disabled | keep its OID and do not rotate attributes unnecessarily |
| before executor deletion | close any executor session, then external cleanup and terminal audit |

If revision 0014 and its objects are exact, do not dispatch Alembic again.
Unrelated role drift from the signed preflight remains a hard failure.

## Fail-closed checks

Reject an executor with direct `CREATEROLE`, `INHERIT TRUE`, `ADMIN TRUE`, no
`SET TRUE`, another membership, a hidden alias, an active session, an expired
window, an unknown name or a second concurrent executor. Reject any runtime
`SET ROLE` path to the authority or lifecycle admin. Reject any nonminimal
migrator `ALTER ROLE` and every attempt by the authority to alter its own LOGIN
state.

Also reject a non-NULL adopted authority password, any hidden or effective
authority membership, any same-name executor replacement, an active or still
LOGIN migrator, and every effective `PUBLIC` table, column or mutation
privilege on Chronos objects or `public.alembic_version`.

## Terminal checklist

- authority: same OID, `NOLOGIN CREATEROLE`, password NULL, no session;
- migrator: same OID, `NOLOGIN NOCREATEROLE`, password NULL, no session;
- executor roles and executor memberships: zero;
- runtime-to-authority and runtime-to-lifecycle-admin paths: zero;
- migrator/runtime, forbidden and hidden edges: zero;
- revision 0014 and objects/ACLs: exact;
- provider, R2, paid credit, purchase, deployment and betting effects: zero
  unless a later separately authorized mission explicitly changes the boundary.
