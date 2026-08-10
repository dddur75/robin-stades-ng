# Next Mission Brief — Chronos Dual-Principal Neon Capability Preflight

## Starting boundary

The next mission starts only after the draft PR for
`codex/chronos-dual-principal-authority-e1-v2` has green exact-head CI. This
mission produced no Neon API call, production PostgreSQL read or write, R2
operation, provider call, purchase, deployment, real bet or promotion.

The accepted architecture is documented in
`docs/architecture/CHRONOS-DUAL-PRINCIPAL-AUTHORITY-E1-V2-ADR.md`; its lifecycle
is documented in `docs/operations/CHRONOS-DUAL-PRINCIPAL-LIFECYCLE-V1.md`.

## Mandatory first phase

Perform only these steps, in order:

1. review the new draft PR, its exact diff and all exact-head CI evidence;
2. merge it only if repository protections, reviews and all required checks are
   satisfied;
3. verify `main` contains the reviewed merge result and remains green;
4. run a read-only capability preflight for the real
   `NEON_BOOTSTRAP_DATABASE_URL` principal.

The capability preflight must establish the direct endpoint identity,
PostgreSQL version, `session_user = current_user`, LOGIN, superuser or
`CREATEROLE`, advisory-lock support, visibility of the privileged password
catalog needed by the terminal proof, role-management semantics, and exact
current revision. It must also inventory existing Chronos authority, executor,
migrator, runtime roles and memberships without printing a URL or secret.

If any required capability is absent or any unknown lifecycle residue exists,
stop with a capability report. Do not alter a role, run Alembic, create a
recovery branch or improvise a weaker proof.

## Activation remains separately gated

The preflight result does not itself authorize activation. A later explicit
decision must bind the reviewed `main` SHA, signed preflight, recovery point,
current revision and exact role inventory before any database mutation.

If separately authorized after the capability review, activation must use the
permanent NOLOGIN authority and a fresh ephemeral executor. It must never make
the authority LOGIN, reuse an expired executor, issue a second Alembic dispatch
at proven revision 0014, or leave an executor in terminal state.

## Evidence to return

Return the draft PR and merge identifiers, exact `main` SHA, CI run identifiers,
capability matrix, sanitized role/membership inventory, current revision,
advisory-lock result, privileged-catalog visibility result, and explicit counts
for every external action. Secret values and complete database URLs must never
appear in output or artifacts.

## Historical campaign freeze

The earlier « troisième architecture » and its
`capability-scoped-evidence-ladder-v2` remain historical, closed evidence. This
handoff cannot restart that V1 campaign or reinterpret its budgets.
