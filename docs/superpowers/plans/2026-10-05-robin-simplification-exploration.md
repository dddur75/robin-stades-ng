# Robin simplification and autonomous exploration — implementation plan

**Spec:** `docs/superpowers/specs/2026-10-05-robin-simplification-exploration-design.md`

**Goal:** Deliver the eight frozen acceptance criteria with a real-data explorer,
safe automatic refresh, reproducible descriptive experiment, and materially faster
CI while preserving every scientific and operational guard.

**Global constraints:** C0 is the only writer. Specialists and final reviewers are
read-only. Use targeted tests during development, one repository-wide suite before
merge, no provider calls, no full-corpus replay, no raw payloads in Git, and append
Council decisions before every commit.

### Task 1: Freeze governance, measurements, and evidence inputs

**Files:** create the mission manifest, extend agent schema/matrix, add targeted
governance tests, record the architecture/operations/performance/science/UX/QA
reports, baseline claim IDs, and the first append-only Council authorization.

**Interfaces:** Produces immutable mission authority, the exact allowed path set,
baseline claims, frozen capture identities, and R1–R8 acceptance table consumed by
all later tasks.

**Steps:** add failing governance tests; run and observe failure; add the minimal
manifest/schema/matrix/reports/claims/ledger records; run targeted Council tests;
lint changed JSON and Python tests.

**Completion test:** `python -m pytest -q tests/council/test_robin_simplification_exploration_governance.py tests/council/test_robin_council_os_v3.py`

### Task 2: Build the shared two-acquisition descriptive model

**Files:** `src/robin/capture/real_data_dashboard.py`, targeted dashboard tests.

**Interfaces:** Consumes normalized rows and acquisition metadata; produces one
comparison model for UI/export/experiment with exclusions and breakdowns.

**Steps:** write tests for exact h2h/totals identities, duplicates, invalid prices,
temporal ordering, appeared/non-observed/excluded rows, directions, denominator and
breakdowns; observe RED; implement the smallest pure model; observe GREEN; verify
the existing dashboard tests.

**Completion test:** `python -m pytest -q tests/capture/test_real_data_dashboard.py`

### Task 3: Deliver the real-data explorer and exact exports

**Files:** dashboard renderer, CLI integration, targeted tests and browser evidence.

**Interfaces:** Consumes Task 2 model; embeds a versioned explorer payload and uses
one client-side selection for table, counters, CSV and JSON.

**Steps:** add failing DOM/contract tests for every filter, numeric sort, reset,
pagination-independent export, comparison columns, acquisition selector, states and
provenance; implement; generate from the frozen artifacts; measure 30 repetitions at
1366/390; exercise via browser and capture evidence.

**Completion test:** `python -m pytest -q tests/capture/test_real_data_dashboard.py tests/capture/test_run_recurring_real_data_cli.py`

### Task 4: Add validated atomic local refresh and durable launcher

**Files:** local explorer service module, launcher/install scripts, runbook and tests.

**Interfaces:** Consumes GitHub artifact receipts through `gh`; produces immutable
version directories plus an atomically switched pointer and last-known-good service.

**Steps:** test corrupted hashes/schema, interrupted staging, auth failure, old late
artifact, latest refresh, pinned history, stop/restart and browser-secret absence;
observe RED; implement with stdlib; install the durable Windows launcher; prove one
natural artifact appears without copy/command/Codex intervention.

**Completion test:** targeted explorer-service and installation tests plus a live
localhost acceptance script against downloaded real artifacts.

### Task 5: Execute and independently verify the descriptive experiment

**Files:** experiment CLI/report, frozen public receipts, evidence claims and tests.

**Interfaces:** Consumes the exact 08:00Z/10:00Z artifacts validated in Task 1 and
Task 2 output; produces a reproducible report, export, three sourced descriptive
findings and an independent QA reconciliation.

**Steps:** test the report schema and independent calculator; validate hashes and
branch order; run the bounded experiment; reconcile every total/breakdown and sampled
row; state exposure, missing provenance fields and no causal/edge interpretation.

**Completion test:** targeted experiment plus dashboard/export reconciliation tests.

### Task 6: Simplify SAFE V2 while preserving every gate

**Files:** `.github/workflows/ci-safe-v2.yml`, workflow contract tests, CI evidence.

**Interfaces:** Consumes Task 1 frozen CI baseline; produces a parallel DAG with one
explicit final gate and no duplicate full-suite domain reruns.

**Steps:** add failing structural tests for true artifact dependencies, parallel
jobs, required final results and absence of redundant pytest calls; implement the
minimal DAG; run workflow/domain tests; map each moved/removed control to retained
evidence.

**Completion test:** targeted workflow tests, YAML parse, relevant lint/security
checks; measure three new comparable green PR runs without synthetic reruns.

### Task 7: Review, integrate, and prove the deployed path

**Files:** final review report, evidence graph, Council ledger, runbook/checkpoint.

**Interfaces:** Consumes all task proofs; produces one reviewed candidate, normal PR
and merge, post-merge path verification, R1 observation checkpoint and live explorer.

**Steps:** run domain suites then the single repository-wide suite; assemble the
review package; obtain one fresh independent whole-branch review; fix Critical and
Important findings once under RED→GREEN; append pre-commit ledger; commit/push/PR;
wait for exact-head checks, measure CI, merge normally, verify main and launcher.

**Completion test:** required exact-head and post-merge checks green, local service
serves the merged commit and the final reviewer reports zero P0/P1.

### Task 8: Close R1–R8 after passive continuity observation

**Files:** final acceptance report, continuity reconciliation, evidence claims and
Council decision.

**Interfaces:** Consumes the unchanged collector's continuous 24-hour run history
and the deployed explorer's refresh observations; produces final PASS/FAIL status for
each frozen criterion.

**Steps:** create a quiet heartbeat checkpoint; reconcile every expected slot over a
continuous 24-hour interval; verify repeated captures and zero-call replay; verify
the local latest view advanced and historical view stayed pinned; re-run the bounded
acceptance path and experiment QA; append final evidence and decision. Never lower a
target after observing the result.

**Completion test:** all R1–R8 are PASS with consultable claim IDs and the delivered
commit remains within rolling provider ceilings. Otherwise retain PARTIAL and name
only the material blocker allowed by §8.

## Review focus

Deliberately challenge duplicate offer identities, totals thresholds, renamed
outcomes, out-of-order branches, invalid hashes, partial multi-file publication,
stale/late GitHub artifacts, pinned-history drift, browser token leakage, branch
protection compatibility, missing final-gate dependencies, and contamination of a
prospective validation by exposed descriptive data.

