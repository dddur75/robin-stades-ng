# Robin Autonomous Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a recurring, budget-safe real-data collection with durable idempotence, a stable latest projection and a usable descriptive dashboard.

**Architecture:** A successor workflow invokes a focused recurring runtime for one deterministic two-hour slot. Immutable R2 reservations/raw reports provide truth; an immutable hash-linked accounting node plus an R2 ETag compare-and-swap head enforces atomic admission before provider dispatch. A mutable private pointer names the latest verified immutable report. A separate renderer produces the filtered HTML and descriptive summaries from verified normalized rows.

**Tech Stack:** Python 3.12, `http.client` strict transport, boto3/R2, GitHub Actions, pytest, Ruff, mypy, self-contained HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-04-robin-autonomous-lab-design.md`

## Global Constraints

- C0 is the sole Git writer; all independent agents remain read-only.
- Preserve raw R2 objects and the fifteen captures from run `37153158456`.
- Maximum 140 requests/280 credits per rolling 24 hours and 4,000/8,000 per rolling 30 days.
- No provider retry, catch-up, purchase, bet, backfill, promotion, new public publication channel or secret-bearing output. Normalized artifacts reuse the existing GitHub Actions channel explicitly authorized by the successor manifest.
- Keep all immutable safety locks and Council vetoes.
- Targeted tests during implementation and one repository-wide suite before merge.

## Review Focus

- A delayed or duplicate scheduler launch must map to an existing slot and issue zero duplicate requests.
- A reservation without a raw envelope must count conservatively and never be retried.
- Missing predecessor accounting or an unavailable latest pointer must make staleness explicit and stop unsafe calls.
- A missing bookmaker market must not be reported as a transport incident or a duplicated market.
- Dashboard filtering must recompute visible counts and represent an empty selection without inventing zero-source observations.
- The manifest expires at `2026-11-03T23:59:59Z`; only a separately authorized successor may continue beyond it.

---

### Task 1: Successor authority and verified seed

**Files:**
- Create: `docs/data-sourcing/ROBIN-AUTONOMOUS-LAB-2026-10-04.md`
- Create: `configs/execution/robin-autonomous-lab-20261004.json`
- Create: `reports/evidence/robin-real-data-result-run-37153158456-public-receipt.json`
- Modify: `configs/agents/agent-report-schema-v3.json`
- Modify: `configs/agents/mission-activation-matrix-v3.json`
- Modify: `reports/evidence/evidence-graph.json`
- Test: `tests/council/test_robin_autonomous_lab_governance.py`

**Interfaces:**
- Consumes: merged run 37153158456 receipt and hashes.
- Produces: immutable mission ID `ROBIN_AUTONOMOUS_LAB_20261004` and verified seed claims.

- [ ] Write failing governance tests for the eight-field manifest, successor claims and unchanged historical claims.
- [ ] Add the source mandate, manifest, receipt and matrix/schema bindings.
- [ ] Append successor seed claims and their authorization decision in the same append-only projection without rewriting old nodes.
- [ ] Run the focused Council test and verify it passes.

### Task 2: R2 latest projection surface

**Files:**
- Modify: `src/robin/prospective_observatory/chronos_r2.py`
- Test: `tests/chronos/test_chronos_r2_effects_v2.py`

**Interfaces:**
- Produces: `get_latest_projection(key)` and `put_latest_projection(key, data, metadata, on_dispatch, expected_etag)` with one SDK attempt, ETag CAS and exact readback.

- [ ] Write failing tests for single-attempt overwrite, first-head creation, ETag CAS, conflict/readback, redacted failures and no delete/list surface.
- [ ] Implement the smallest normalized-pointer methods without changing immutable raw writes.
- [ ] Run the focused R2 tests.

### Task 3: Recurring slot runtime

**Files:**
- Create: `src/robin/capture/recurring_real_data.py`
- Modify: `src/robin/capture/real_data_result.py`
- Test: `tests/capture/test_recurring_real_data.py`

**Interfaces:**
- Consumes: strict transport, secret reader, conditional R2 store, verified seed report.
- Produces: `RecurringConfig`, `run_recurring_real_data(...)`, immutable slot report and public receipt.

- [ ] Write failing tests for two-hour slot identity, five-league capture and exact readback.
- [ ] Write boundary tests for rolling 24-hour/30-day request and credit admission.
- [ ] Write duplicate, concurrent-reservation, ambiguous-attempt, stale-predecessor and quota-failure tests, including two adjacent-slot runs racing for the last allowed capacity.
- [ ] Split market-missing and market-duplicated limitation codes with regression coverage for the legacy combined code.
- [ ] Implement immutable bounded accounting nodes and a CAS head; reserve the whole slot before the first provider call.
- [ ] Verify branch isolation, seed preservation, zero retry and safety locks.

### Task 4: Dashboard and descriptive exploration

**Files:**
- Create: `src/robin/capture/real_data_dashboard.py`
- Test: `tests/capture/test_real_data_dashboard.py`

**Interfaces:**
- Consumes: current verified rows, previous verified rows, branches, accounting and generation time.
- Produces: reviewed dashboard snapshot and self-contained paginated HTML.

- [ ] Write failing tests for freshness/health/market-availability separation.
- [ ] Write calculation tests for coverage denominators, price quantiles and matched-offer movements.
- [ ] Write markup tests for search, filters, reset, pagination, UTC dates, incidents and no-edge disclosure.
- [ ] Implement a bounded-DOM renderer with safe embedded JSON and CSV link.
- [ ] Verify empty, partial and stale states.

### Task 5: CLI and scheduled workflow

**Files:**
- Create: `scripts/run_recurring_real_data.py`
- Create: `.github/workflows/92-robin-autonomous-lab.yml`
- Test: `tests/capture/test_run_recurring_real_data_cli.py`
- Test: `tests/capture/test_recurring_real_data_workflow.py`

**Interfaces:**
- Consumes: mission token, manifest, GitHub scheduled context and existing secrets.
- Produces: four normalized files, R2 latest pointer, workflow summary and artifact.

- [ ] Write failing CLI tests for scheduled context, redacted diagnostics and exact exit states.
- [ ] Write failing workflow tests for `17 */2 * * *`, exact pinned actions, permissions, concurrency and normalized-only upload.
- [ ] Implement the CLI and workflow with schedule-only live calls and run-attempt-one enforcement.
- [ ] Run the targeted CLI/workflow tests and static validation.

### Task 5A: Release-blocking recurring recovery and quota circuit

**Files:**
- Modify: `src/robin/capture/recurring_real_data.py`
- Modify: `src/robin/capture/real_data_dashboard.py`
- Modify: `src/robin/prospective_observatory/chronos_r2.py`
- Test: `tests/capture/test_recurring_real_data.py`
- Test: `tests/capture/test_real_data_dashboard.py`
- Test: `tests/chronos/test_chronos_r2_effects_v2.py`

**Interfaces:**
- Consumes: an admitted slot, immutable per-sport reservations, observed quota headers and the prior latest pointer.
- Produces: crash-safe replay, a durable quota circuit, one cached DNS/secret outcome and a failed-attempt view that preserves the last usable observations as stale.

- [ ] Reproduce quota/cost anomalies, accounting slot regression, restart after admission, storage exceptions and cached access failures.
- [ ] Reserve each sport before DNS or secret access and recover verified raw envelopes without another provider call.
- [ ] Stop sibling calls after a quota/cost anomaly and reconcile the durable provider floor before any possible next call.
- [ ] Preserve the current incident and last usable report in the latest projection; render fallback observations explicitly stale.
- [ ] Run the targeted runtime, dashboard and R2 adapter tests plus static validation.

### Task 6: Resolve operational duplication without breaking CI

**Files:**
- Inspect: `.github/workflows/ci.yml`
- Inspect: `.github/workflows/ci-safe-v2.yml`
- Inspect: tests and evidence that bind the legacy path.

**Interfaces:**
- Consumes: proof that `ci.yml` is disabled and differs from active `ci-safe-v2.yml` only by name, plus the active SAFE V2 dependency on the legacy file.
- Produces: an evidence-backed retention decision; no refactor unrelated to recurring collection.

- [ ] Verify the required-context producer and all references to the legacy path.
- [ ] Preserve `ci.yml` because SAFE V2 reads it and repository evidence/tests bind it; deletion would break active CI.
- [ ] Record that provider-route simplification is instead achieved by keeping all eleven historical provider workflows disabled before workflow 92 runs.

### Task 7: Candidate verification and delivery

**Files:**
- Modify: `reports/council/decision-ledger.jsonl`
- Modify: `reports/evidence/evidence-graph.json`

**Interfaces:**
- Produces: one C0 commit, PR, exact-head checks and normal merge.

- [ ] Run focused runtime/dashboard/workflow/governance tests, Ruff, mypy and `git diff --check`.
- [ ] Run the Golden Synthetic Pack and one repository-wide suite.
- [ ] Obtain consolidated independent review and fix only verified findings.
- [ ] Append `MISSION_AUTHORIZED`, seed evidence links and the pre-commit ledger record in the same candidate projection with worktree, branch, HEAD, PR, writer, files, tests and reused evidence.
- [ ] Commit, push, open the PR, attach it, wait for required checks and merge normally.

### Task 8: Scheduled activation and observation

**Files:** none unless a verified rollout defect requires a corrective PR.

**Interfaces:**
- Produces: at least two distinct schedule-event runs and verified artifacts.

- [ ] Verify merged main, existing secrets by name only and seed quota available; disable every historical provider-capable workflow before enabling the successor's first live call.
- [ ] Wait passively for scheduled runs; do not dispatch provider work manually.
- [ ] For each run, verify event type, SHA, slot, reservations, R2 readback, latest pointer, rows, incidents and consumption.
- [ ] Download the newest artifact and perform normal/narrow rendered checks plus filter/reset/empty-state interactions.
- [ ] Keep historical provider workflows disabled while the successor owns the sole live admission route.

### Task 9: Post-run evidence closure

**Files:**
- Modify: `reports/council/decision-ledger.jsonl`
- Modify: `reports/evidence/evidence-graph.json`
- Test: `tests/council/test_robin_autonomous_lab_governance.py`

**Interfaces:**
- Consumes: exact scheduled run receipts and artifact hashes.
- Produces: append-only claims distinguishing actual execution from prepared code.

- [ ] Add scheduled-run capture, view and consumption claims linked to their receipts.
- [ ] Run the affected governance checks and one delta review.
- [ ] Deliver through a small closure PR if repository evidence changed.
- [ ] Return stable links, observed coverage, incidents, descriptive findings and exact consumption.

### Task 10: Scheduler non-materialization redesign

**Observed after the original merge:** workflow 92 remained active on exact
`main`, every historical provider route remained disabled, and GitHub created
no run for the natural 10:17, 12:17 or 14:17 UTC occurrences. A disable/enable
registration refresh between the second and third occurrence did not change
that outcome. Because no job existed, this failure caused no secret read,
provider request, credit reservation or R2 effect.

**Smallest successor delta:** preserve the immutable parent authority, runtime,
R2 namespace and accounting family. Add a schedule-only overlay authorizing an
hourly trigger at minute 37 while retaining the two-hour data-slot identity.
The second hourly opportunity in a closed slot must replay before DNS, secret
access or transport and leave every provider counter unchanged.

- [x] Reproduce the missing-run boundary and record `FAIL_AND_REDESIGN` at E1.
- [x] Add the immutable scheduling overlay, matrix/schema bindings and an exact
  double-manifest workflow gate.
- [x] Add a test whose two launches occur in different clock hours but the same
  two-hour slot, with one raw/report hash and five total provider requests.
- [ ] Obtain C2/A2 review, run the single full pre-merge suite and exact-head CI,
  then merge normally.
- [ ] Observe, without dispatch, one captured slot, one same-slot zero-provider
  replay and a capture in a second data slot before calling the result delivered.
