# Robin real-data result mission — design

## Outcome

Deliver real The Odds API data through the existing strict transport and R2
storage to a directly consultable HTML/CSV table. Prove three distinct programmed
cycles over the five already-supported football league endpoints and the
`h2h,totals` markets, while preserving partial branch results.

Authority is capped at `E3B` only to permit the five league endpoints; the
collection itself is held at `E1`/`PASS_AND_HOLD`. This operational snapshot
performs no E1→E2/E3 transition. Five endpoint captures are not evidence of a
season, 100 fixtures, or any scientific promotion.

## Reused components

- `StrictHttpsTransport`: pinned-IP TLS, absolute deadline, no redirects or
  retries, response-secret rejection and sanitized quota headers.
- Existing environment secret reader and public DNS resolution.
- Existing Chronos/R2 client and immutable conditional writes.
- Existing replay principle: normalize only bytes read back from the durable
  object and compare deterministic digests.
- Existing normalized HTML/CSV rendering and pinned GitHub artifact upload.

The successor workflow deliberately does not depend on API-Football or a live
PostgreSQL fixture registry. Those components are not required to display the
provider's own event identifiers, teams, commencement times, bookmakers and
prices, and would make an unavailable branch stop unrelated branches.

## Socket repair

`http.client` closes its connection after parsing `Connection: close`, while
the returned `HTTPResponse` still owns a buffered reader over the same socket.
`_DeadlineSocketAdapter.makefile()` therefore grants a file lease. Adapter
close records an owner-close request and closes the TLS socket only after the
last lease is released. Closing `_DeadlineSocketRaw` releases that lease once.
Both transport versions close the response before the connection in `finally`,
retry a transient close once, and fail with a redacted `CONNECTION_CLOSE`
diagnostic if successful response processing cannot be followed by confirmed
cleanup. A post-handshake failure closes the TLS wrapper that owns the socket,
not the superseded raw object. The existing timeout refresh before every
`recv_into`, certificate validation, SNI and peer pinning remain unchanged.

## Redacted diagnostics

A diagnostic contains only an allowlisted stage, stable code, exception class,
integer errno and HTTP status in 100–599. It never serializes exception text,
tracebacks, request targets, URLs, headers, secrets or payloads. Diagnostics are
attached to failed branch receipts and the normalized report.

## Cycles and budgets

One post-merge workflow execution schedules three cycles at distinct UTC times.
Each cycle independently attempts five sport branches, one request per branch,
requesting both supported markets. A reservation receipt is written before
every request. Thus the planned successor maximum is 15 provider requests and
30 credits, counted conservatively at two credits per request. With the prior
attempt and four reserved prior credits, the mission accounts for at most 16 of
40 requests and 34 of 60 credits.

Provider slot keys contain mission, cycle and sport identifiers but deliberately
exclude the GitHub run so a later authorized dispatch observes the same fixed 15
slots and cannot repeat a reserved request. Raw envelopes retain the capture run
and repository SHA. Cycle receipts and the normalized report additionally use a
run-specific prefix. The workflow has no automatic provider retry. Two matching
failures stop only that sport branch; other sports continue. The first successful
branch must pass conditional persistence, exact-key readback, hash verification
and deterministic replay before later branches proceed.

Before any provider access, the runtime inventories the immutable reservation
for all 15 slots. Existing raw envelopes and their verified quota evidence are
therefore known, replayed and counted even when a low-quota or branch stop governs
new calls; a data replay failure does not discard an independently valid quota
header. DNS and the provider secret are initialized lazily only when an
unreserved slot is eligible for a new call, so a complete R2 replay needs neither.
The bounded inventory/readback path permits at most 34 exact-key R2 GETs per
dispatch (15 reservations, 15 raw objects or new-capture readbacks, three cycle
receipts and one final report).

## Delivery

The normalized report contains cycle/branch status, capture and source timestamps,
coverage, quota observations, request/credit accounting, replay hashes and
redacted diagnostics. The HTML and CSV expose normalized event and outcome rows.
Raw payloads remain private in R2 and never enter Git or the artifact. The
normalized plaintext HTML/CSV/JSON artifact is deliberately consultable from the
workflow run of this public repository; it contains odds but no secret, API-key
URL or raw provider envelope. The workflow summary contains aggregated counts.
This authorized normalized artifact is neither a social publication nor a
scientific promotion.

## Stop conditions

Fail closed before a new provider request if authority, main SHA, expiry, locks,
secret, network binding, R2 reservation or remaining budget cannot be proved.
Inventory and replay of already durable slots precede new-call quota and branch
stops. Stop the mission on the global ceiling, missing required access, purchase
requirement or destructive operation. Branch-local provider/data failures remain
explicit and do not stop other branches.
