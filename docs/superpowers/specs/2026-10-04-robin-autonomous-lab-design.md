# Robin autonomous lab — design

## Outcome

Robin becomes a private personal laboratory that keeps collecting the five
already-supported football leagues and the `h2h,totals` markets without Codex
or the owner's computer. Every observation is stored durably before it is used,
the latest usable result is discoverable through one stable workflow and one
private R2 pointer, and the generated table distinguishes collection health,
data freshness and bookmaker market availability.

This remains an E1 observation system. It performs no betting, backfill,
scientific promotion or automatic edge validation.

## Successor boundary

The one-shot workflows 90 and 91 and their manifests remain immutable history.
A successor mission, runtime and workflow own recurring operation. The successor
starts from merged main `0be96131d1c9c6d7337629f906ead3b282304293` and imports
the verified receipt and private R2 report from run `37153158456` as its seed.
The fifteen existing captures are read and verified, never rewritten.

All real metrics in the new view reference successor claims backed by the
downloaded public receipt and its SHA-256 values. The historical pre-run claims
remain unchanged and superseded.

After authority and accounting integrity checks, the first eligible run verifies
the receipt's canonical digest, the exact private-report key, digest and R2
metadata, then derives one immutable private successor report. The derivation
keeps the historical repository, run, capture and source timestamps, adds only
the deterministic `2026-10-03T20:00:00Z` slot identity to normalized rows and
removes raw-object references from its branch projection. It performs no
provider request and creates no accounting node; the existing CAS latest path
publishes it as the initial stale usable report. Repeated or concurrent
bootstraps converge on the same bytes and cannot double-count the historical
16 requests or 34 credits.

## Cadence and hard budgets

GitHub Actions runs the successor at minute 17 of every second UTC hour. One
slot contains at most one request for each of the five leagues, with both
markets in the same request. A slot therefore reserves at most five requests
and ten credits. There is no provider retry or missed-slot catch-up.

The runtime floors the actual start time to a two-hour UTC slot. R2 keys contain
that slot and sport, so a duplicate, delayed or manually repeated launch reads
the same reservation and cannot create another provider request.

The conservative admission model includes the historical baseline of 16
requests and 34 credits until it naturally leaves both rolling windows. With
schedule jitter, at most thirteen two-hour slots can intersect any 24-hour
window and 361 can intersect 30 days. The resulting hard upper bounds are:

- 81 requests and 164 credits per 24 hours, below 140 and 280;
- 1,821 requests and 3,644 credits per 30 days, below 4,000 and 8,000.

Before any provider dispatch, the runtime reserves the complete five-request,
ten-credit slot in an immutable accounting node. A private accounting-head
object identifies the latest node and is advanced with an R2 `If-Match` compare
and swap (or `If-None-Match: *` for the first successor node). A node contains
its predecessor key, predecessor digest and ETag, the slot, the historical
16-request/34-credit seed, lifetime totals and only those reservation entries
that can still intersect either rolling window. Nodes and their predecessor
hashes are read back before admission; a CAS conflict causes a bounded state
refresh and another accounting-only attempt, never a provider retry.

The reservation head is `OPEN` until an immutable private slot report has been
written and read back. A hash-linked closure node then advances the same CAS
head to `CLOSED` and binds the report key and digest. A newer slot is never
admitted behind an open predecessor. If a later scheduler run finds an older
open slot, it performs offline recovery only from existing reservations and raw
objects, closes that slot if the evidence permits it, and never backfills a
missing provider call. A fixed immutable initialization marker distinguishes a
first launch from a lost mutable head, preventing silent counter reseeding.

The provider call starts only after the new immutable node and its CAS head are
both verified. An unused or ambiguous slot reservation remains conservatively
charged. A head mismatch, broken predecessor chain, ambiguous state write,
unverified provider cost, insufficient observed provider balance or cap
violation stops all new calls fail-closed. Two launches racing at a limit can
therefore produce at most one admitted successor head.

## Data and persistence flow

For every eligible sport in a slot:

1. Write an immutable attempt reservation in R2.
2. Resolve DNS and read the existing provider secret lazily.
3. Send one strict pinned-IP TLS request with no redirect and no retry.
4. Persist the raw envelope immutably in R2.
5. Read the exact object back, verify its digest and normalize only that readback.
6. Preserve branch-local failure while allowing other leagues to continue.

Quota and cost observations are carried to the accounting reconciler even when
raw persistence or readback fails. A cost/quota anomaly opens the shared slot
circuit before another league can call the provider. A reconciliation that
cannot be proven leaves the slot open, so a future slot cannot treat the old
head as safe.

An immutable slot report stores normalized current rows, incidents, market
limitations, quota observations, accounting, lineage and descriptive summaries.
After its readback succeeds and accounting closes, a single-attempt mutable R2
pointer updates the private `latest.json` projection. The pointer contains the
current immutable report reference plus the last verified non-empty usable
report reference. A verified empty response remains the truthful current slot,
while a later incident can still display the last non-empty observations as
explicitly stale. Overwriting the pointer never deletes or rewrites raw or
historical slot data.

If the latest pointer update fails, the immutable slot result remains valid but
the run fails delivery so stale access is explicit. The next run never invents
freshness from that failure.

## State semantics

The output separates three concepts:

- **Collection health**: success, partial branch result, or system failure.
- **Freshness**: fresh only while the latest verified capture is within the
  two-hour cadence plus one-hour tolerance; otherwise stale or unavailable.
- **Market availability**: `RESULT_MARKET_MISSING` for no supplied market,
  `RESULT_MARKET_DUPLICATED` for multiple supplied copies, and explicit legacy
  `RESULT_MARKET_MISSING_OR_DUPLICATED` for the already-preserved seed where the
  historical code cannot distinguish them.

An HTTP 200 response containing an empty event list is a verified empty capture,
not a transport failure and not a missing bookmaker market. It contributes a
capture timestamp and zero rows. It does not overwrite the pointer's last
non-empty usable reference.

An old capture is never relabelled as fresh. A failed branch cannot suppress a
successful sibling league.

## Consultable table and descriptive exploration

The normalized HTML is self-contained and uses no external script or CDN. It
keeps rows as reviewed JSON and renders a bounded page rather than materializing
the whole dataset in the DOM. Controls provide free-text search plus league,
market, bookmaker and status filters, reset, pagination and CSV access.

The opening view shows latest capture/source timestamps, freshness, five-league
coverage, branch incidents, market absences, quota observations and rolling
consumption. It also includes descriptive, non-causal exploration:

- coverage by league and market with explicit denominators;
- bookmaker price distribution by market/outcome;
- matched-offer price changes versus the previous verified slot;
- a clear statement that no edge is validated.

Dates remain UTC and filters apply consistently to metrics and the detail table.
Empty selections, stale data and unavailable branches are visibly distinct from
measured zero.

The rendered freshness badge recomputes its age from the verified capture time
when the page opens and once per minute. Thus a locally retained artifact ages
to `STALE` even if a later workflow artifact never arrives.

The stable access point is the workflow 92 page; every run reuses the existing
GitHub Actions artifact channel to publish normalized, secret-free derivatives
with a predictable prefix and links the current run in its summary. The
repository is public, so this normalized artifact boundary is explicit in the
successor authority; raw envelopes, provider URLs, keys and private reports
remain private in R2. No new public host, bucket or publication channel is
created. R2 `latest.json` is the stable private machine-readable pointer.

## Authority lifetime

The immutable successor manifest expires at `2026-11-03T23:59:59Z`. Runtime
admission checks that timestamp before reserving a slot and fails closed after
it. Continued operation beyond that point requires a separately authorized
successor manifest and source hash committed before expiry; neither the
workflow nor the accounting head can extend its own authority. Expiry is shown
as an operational incident in the last available dashboard and workflow run.

## Operational simplification

The disabled legacy CI file is retained because the active SAFE V2 workflow
reads it directly and repository tests/evidence bind its path; deleting it would
break required CI rather than simplify collection. Every historical
provider-capable workflow is disabled before workflow 92 can make its first live
call, so there is one provider admission route. No historical report or ledger
row is deleted.

New governance evidence is one consolidated successor delta, not a new review
stack per defect. Unchanged transport, storage and scientific safeguards reuse
their prior reviews. Runtime defects discovered during rollout enter the same
work loop and receive targeted tests before a corrective commit.

## Acceptance

The mission is delivered only when:

- targeted runtime, workflow, dashboard and governance tests pass;
- the required exact-head checks pass and the PR is merged normally;
- at least two distinct `schedule`-event runs complete on merged main;
- duplicate/replay behavior is demonstrated without a second provider call;
- a last-capacity race admits one accounting head and zero over-budget calls;
- their immutable reports, latest pointer and artifacts read back successfully;
- the rendered table passes normal/narrow visual checks and representative
  filter/reset/empty-state checks;
- consumption remains below both rolling limits and the observed provider
  balance, with no purchase, bet, backfill, promotion or secret exposure;
- a post-run append-only evidence closure records what actually ran separately
  from code that was merely prepared.
