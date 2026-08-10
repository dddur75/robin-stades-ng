# Next Mission Brief — Chronos Neon Recovery E1 V1

## Mission boundary

This brief starts only after the Draft pull request headed by
`codex/chronos-role-lifecycle-e1-v1` has passed all required checks. The current
mission deliberately performs no Neon API call, no production SQL, no provider
call, no R2 operation, no purchase, and no deployment.

The next mission owns the controlled production activation. It must use very
high reasoning, stop on any failed gate, and preserve the evidence chain.

## Required starting state

- The replacement pull request is open, Draft, mergeable, and green.
- PR #43 is closed without merge and marked
  `SUPERSEDED_BY_CHRONOS_ROLE_LIFECYCLE_E1_V1`.
- Its exact head derives from frozen commit
  `b942f24f8306fbf96717c2a69dbb80a1ff16d4eb`.
- PostgreSQL 16 contracts are 8/8, the migration cycle passes, SSR/visual
  checks pass, and the exact role-edge matrix contains no forbidden edge.
- Existing bootstrap secrets are available through the approved secret store;
  they must never be printed, copied into files, or committed.

## Ordered execution

1. Re-review and merge the replacement pull request. Do not bypass protections.
2. Verify `main` contains the reviewed exact head and rerun the required main
   checks if repository policy requires them.
3. Create a dedicated Neon recovery branch from that exact `main` head.
4. Reuse the existing bootstrap secrets; do not create parallel credentials.
5. Run `PREFLIGHT` and verify its signature, expiry, branch identity, revision
   `0013`, clean role inventory, and zero forbidden membership.
6. Pre-provision the four group roles and the stable NOCREATEROLE migrator with
   the bootstrap owner. Preserve the expected 4→5 edge cardinalities.
7. Migrate exactly once to revision `0014`, then disable the migrator before
   provisioning any runtime LOGIN.
8. Create or exactly adopt the three runtime LOGIN roles with the bootstrap
   owner and grant only the three functional memberships. The final graph must
   contain exactly 11 classified edges.
9. Install the scoped runtime secrets in the approved secret store without
   exposing their values.
10. Run `VERIFY`, including the bidirectional graph audit, grantor/options
    checks, role attributes, object ACLs, revision guard, and zero-session
    terminal state.
11. Run the reusable provider-free canary. It must not call any provider or use
    paid odds credits.
12. Remove or rotate bootstrap secret material according to the runbook, while
    retaining the dormant bootstrap owner as `NOLOGIN CREATEROLE`, password
    NULL, settings reset, and zero sessions.

## Stop conditions

Stop without repair-in-place if any of these is observed: an unexpected role or
membership, a mismatched grantor or option, revision other than `0013` at
preflight, an expired artifact, more than one Alembic dispatch, a runtime role
created through Neon identity APIs, a migrator with CREATEROLE, an effective
runtime path to a bootstrap-admin role, a provider call, or an unbounded secret.

Any recovery must begin from a newly reviewed plan and preserve the same stable
migrator identity/OID contract.

## Completion evidence

Record exact commit and workflow run identifiers, preflight/verify artifact
hashes, migration revision, 8/8 PostgreSQL contracts, the observed 11-edge
matrix, canary result, secret-cleanup result, zero forbidden edges, zero active
bootstrap/migrator sessions, and explicit zero counts for external-cost and
provider operations.

## Historical compatibility archive — no authority

The frozen literals `troisième architecture` and
`capability-scoped-evidence-ladder-v2` identify a superseded handoff only.
They do not authorize restarting that campaign and do not alter this brief.
