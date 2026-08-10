# Next Mission Prompt — Execute Chronos Neon Recovery E1 V1

Work at very high reasoning. Read `NEXT-MISSION-BRIEF.md`, the accepted Chronos
role-lifecycle ADR, the operations runbook, the replacement Draft pull request,
and its complete CI evidence before changing any remote state.

Your mission is to review and merge the green replacement pull request, verify
the resulting `main`, create a dedicated Neon recovery branch, reuse the
existing bootstrap secrets, run signed `PREFLIGHT`, pre-provision the
bootstrap-owned PostgreSQL roles, migrate exactly once to revision `0014`,
disable the stable NOCREATEROLE migrator, provision the three runtime LOGIN
roles through the bootstrap owner, install scoped secrets, run bidirectional
`VERIFY`, execute the provider-free canary, and clean bootstrap secret material.

Apply the gates in the brief in order. Do not print or persist secret values. Do
not use Neon role/user/identity API routes. Do not accept an unexpected role,
membership, grantor, membership option, revision, role OID, or effective
runtime path. Stop on the first failed gate and report evidence; do not improvise
a production repair.

Return a durable report containing exact Git and CI identifiers, signed
artifact hashes, migration-cycle evidence, the observed 11-edge matrix, scoped
connection checks, provider-free canary result, cleanup evidence, and explicit
zero counts for Neon identity API calls, provider calls, R2 operations, paid
credits, purchases, voluntary deployments outside this activation, real bets,
and promotions.

## Historical handoff archive — no authority

The following literals are retained only because repository preflight contracts
freeze the superseded Phase-C handoff. They are not the budgets or execution
authority of the Chronos recovery mission above.

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
Ne lancer ni E1A ni capability-scoped-evidence-ladder-v2.
```
