> **Statut historique:** `SUPERSEDED_BY_CHRONOS_PRODUCTION_BOOTSTRAP_V3`.
> Conservé comme preuve; ne pas exécuter. Utiliser le handoff V3 courant.

# Prompt — Chronos Control Plane V2 Controlled Review and Activation

Work in very-high reasoning mode. Read `NEXT-MISSION-BRIEF.md`, the E1 ADR, the
adversarial review, the restore runbook, and
`reports/closure/pr41-chronos-control-plane-v2-validation-v1.json`. Resolve the exact
PR head from GitHub before taking any action; never trust an unverified branch name or
stale report.

Follow the brief in order. Before merging PR #41, snapshot workflow state, disable the
downstream and upstream automatic migration paths, then drain or cancel existing runs
until queued and in-progress counts are both zero. Preserve prior states. Do not
dispatch any manual migration path. Remove automatic `alembic upgrade head` from all
direct and indirect paths in a separate reviewed activation change; the stale `0013`
guards occur too late to prevent migration. Require exact-head CI plus independent DP6,
SEC, SRE, C2, RP8, and RED PASS, zero P0/P1, and score at least 95/100.

Create the protected GitHub Environment before merge but keep it disabled with sealed
secret slots only. The migrator credential stays outside every workflow and Environment.
Merge only after those controls exist, revoke the legacy shared database credential,
then migrate exactly once and explicitly to `0014_chronos_control_plane_v2`. Only after
the migration creates the `NOLOGIN` group roles may you create distinct authority,
runtime, and reader LOGIN principals, grant each exactly one matching group membership,
rotate their credentials and the external 256-bit nonce, and populate the protected
Environment. Accept only PostgreSQL 16's bootstrap-granted ADMIN-only migrator links
with `INHERIT=false`, `SET=false`, and failed `USAGE`; never add a usable migrator grant
or give `chronos_test_writer` a production member. Verify effective `USAGE` identities
and absence of cross-membership. Replace old revision guards with read-only `0014` checks before
re-enabling any workflow individually.

The first canary is provider-free, manual-only, and bounded to one run/attempt and one
operation. A lost response, SDK retry possibility, 409, or insufficient proof remains
pending or conflict; never infer `CREATED_CONFIRMED` or `PREEXISTING_CONFIRMED` from
matching bytes alone. The provider canary stays `DEFAULT_DENY` without a separate exact
append-only authorization.

Commit `R2_GET_DISPATCHED` before the sole exact-key GET. Never read twice after a
crash/replay and never reconcile an old restored chain with a new run authority.

Do not reactivate workflows in bulk. End with a factual report giving all SHA pins,
reviews, migration and grant evidence, epoch, non-secret generation ID, event hash
chain, accounting, provider/R2/SQL budgets, and the final state of every workflow.

## Superseded historical handoff archive

The following literals preserve fail-closed evidence for old missions only. They are
`SUPERSEDED_BEFORE_EXECUTION`, are not current budgets, and confer no authority:

```text
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
DURÉE = 20 à 50 heures utiles
r2_read_budget = 10000 GET
r2_write_budget = 0
api_football_budget = 0
sql_read_budget = 0
TRIPLE_SEARCH_LOCKED
Ne jamais lancer de triple.
Ne lancer ni E1A ni une campagne antérieure.
capability-scoped-evidence-ladder-v2
```
