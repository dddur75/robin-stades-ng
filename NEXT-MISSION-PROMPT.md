# Next Mission Prompt — Review, Merge and Preflight Dual-Principal Chronos

Read `NEXT-MISSION-BRIEF.md`, the dual-principal ADR and runbook, the new draft
PR, and its complete exact-head CI evidence before changing remote state.

First review the PR. Merge it only if every protection and required check is
green, then verify the reviewed result on `main`. After that, perform only the
read-only capability preflight for the real `NEON_BOOTSTRAP_DATABASE_URL`.

Prove the external principal's PostgreSQL identity and role-management
capabilities, advisory-lock support, required privileged-catalog visibility,
current revision, and sanitized existing Chronos role graph. Never print or
persist a secret or complete database URL. Stop on any missing capability,
unknown role, unknown membership or catalog ambiguity.

Do not run Alembic, create or alter a role, create a Neon recovery branch, call
R2 or a provider, deploy, purchase, bet or promote in this first phase. The
capability result requires a separate explicit activation decision.

Return exact Git and CI identifiers, the capability matrix, sanitized catalog
evidence, current revision, and explicit external-effect counters.

## Historical compatibility marker

The predecessor handoff was
`SUPERSEDED_BEFORE_EXECUTION`.

This literal is retained exclusively to satisfy the closed historical contract.
It does not supersede this current handoff, does not authorize execution, and
does not modify the current mission state.

Historical freeze: Ne lancer ni E1A ni la
`capability-scoped-evidence-ladder-v2`. The following strings preserve the
closed V1 contract and do not grant execution authority for this mission:

- `MODÈLE = GPT-5.6 Sol`
- `RAISONNEMENT = Très élevé`
- `DURÉE = 20 à 50 heures utiles`
- `r2_read_budget = 10000 GET`
- `r2_write_budget = 0`
- `api_football_budget = 0`
- `sql_read_budget = 0`
- `TRIPLE_SEARCH_LOCKED`

Ne jamais lancer de triple depuis ce handoff.
