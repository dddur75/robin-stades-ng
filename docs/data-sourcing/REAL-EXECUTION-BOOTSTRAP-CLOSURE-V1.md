# Real Execution Bootstrap Closure V1

## Outcome

This capability closes the five preparation gaps that previously made a first
real provider capture impossible to authorize honestly. It remains default deny:
the delivery, bootstrap, DNS preparation, and owner-review pack do not authorize
or perform a provider HTTP request, read `THE_ODDS_API_KEY`, create a real batch,
or create a real snapshot.

Historical V1 contracts and replay bytes remain supported. New real executions
must enter through the additive V2 authority and executor path.

## Causal boundary

The successor separates information available before dispatch from information
that can exist only after a response:

```text
official schedule evidence
→ OfficialFixtureTargetV1
→ FixtureTargetSetV1
→ complete five-league H24/H2/H1 candidate universe
→ deterministic CampaignWindowSelectionV1 winner
→ durable DNS claim bound to that exact winner
→ OwnerAuthorizationV2 / ActivationEnvelopeV2 / LivePlanV2 / LivePlanItemV2
→ one direct response
→ raw SHA-256
→ durable intake receipt
→ durable content-addressed raw bytes
→ deterministic exact fixture mapping
→ durable post-capture mapping evidence
→ mapped-only scientific projection
```

No pre-dispatch V2 artifact contains a provider event ID or
`fixture_mappings_sha256`. Exact sport, UTC kickoff, home role, and away role are
matched after raw durability using one versioned Unicode NFKC, casefold, and
Unicode-whitespace normalization rule. There is no alias table, edit distance,
fuzzy match, or home/away reversal. Non-bijective relationships are ambiguous;
unproven targets never enter normalized science.

Capture success and scientific admission are distinct. V2 lineage records
`FULL`, `PARTIAL`, or `NONE` over the frozen target set. Extra provider events do
not reduce target coverage. Replay rehashes the raw bytes and binds the complete
mapping artifact and target-set hash, including unmatched targets.

## Network preparation boundary

`prepare_provider_network_binding_v1.py` performs one injected or operating-system
`getaddrinfo` operation for the literal hostname `api.the-odds-api.com`. It does
not import a provider client, inspect a provider secret, open a TCP connection, or
send HTTP. It rejects the complete resolution if any address is malformed or is
not global unicast. The fail-closed policy explicitly denies every prefix in the
IANA IPv4 and IPv6 Special-Purpose Address Registries as revised 2025-10-09,
including entries that the Python standard library labels globally reachable,
plus deprecated IPv6 site-local space. It canonicalizes and deduplicates the
remaining set, orders IPv4 before IPv6 by packed bytes, and selects the first
address. There is no retry, random choice, or failover.

Before calling the resolver, the tool atomically creates a deterministic
mission-global claim in the receipt-bound owner execution registry at
`<Windows Profile>\RDS\RobinGlobalClaimsV2` and then mirrors the
`ProviderNetworkResolutionClaimV1` into the fingerprint-verified control-temp
root. The global marker is keyed by the exact tracked mission-manifest hash, so a
second independently verified runtime workspace cannot reset the budget. It
permanently consumes the mission's one DNS attempt, including when resolution or
output persistence later fails. A second invocation, even with another workspace
or output filename, stops before resolution. The claim binds the verified
workspace, tracked mission manifest, complete campaign-selection hash, and exact
winning target-set hash. Mission expiry, workspace identity, and the still-current
unique campaign winner are checked again before the observed resolver boundary.
After the final clock sample, the no-callback composite barrier also re-reads the
historical marker and binds its exact path, authority-manifest hash, raw bytes,
ACL expectation, and V2/legacy root identities alongside the current global and
local claims; no mutation callback runs between that assertion and the sole
resolver operation.
The resolver derives one common runtime parent from the receipt's repository,
control-temp, and capture roots, then proves its physical parent is the current
Windows profile's `RDS` boundary using canonical path, volume, device/file ID,
filesystem, synchronization, reparse, cloud, and ACL facts. It verifies the
parent before creating only the versioned child and re-inspects the exact child
before use. `%LOCALAPPDATA%\RobinRealExecutionMissionClaimsV1` is retained solely
as a read-only compatibility source: both roots are inspected before a new claim,
equal dual markers are accepted as already consumed, unequal markers fail closed,
and no legacy directory, ACL, or marker is created, repaired, moved, or deleted.
The rejected LocalAppData boundary had real non-exclusive ACL authority
(`ACL_REAL_NON_EXCLUSIVITY=TRUE`, `ACL_POLICY_FALSE_POSITIVE=FALSE`); this design
therefore preserves the security policy and changes neither LocalAppData nor RDS
ACLs.

The 23,127-byte owner delivery directive dated 2026-08-28 (SHA-256
`2d30511e1ae2ab9e49ba97fcd0e57d48a93212c96ab5f75b2cf3b8386c09e368`) is a
new, exact one-time delivery authority for this twelve-path correction. It
supersedes the older mission-matrix path allowlist only for those twelve named
paths; it does not replace or expand the unchanged V5 runtime manifest whose
source hash is `204e4323d0b99fdfa8c655cdc3a08a8d2b3c82ac0a784f9a97982c90ab3a7312`.
The directive is strictly narrower at runtime: it permits the post-merge
official pre-DNS preparation but requires provider DNS, transport, secret access,
Owner Review Pack creation, OwnerAuthorization, and C0 to remain at zero.

The recorded expiry is explicitly a local binding-policy TTL (maximum fifteen
minutes). In the one-shot campaign path it is shortened to the earliest of the
requested TTL, mission expiry, selected campaign usable expiry, and five minutes
before the earliest target kickoff. It therefore never outlives the activation
that the pack can issue. At least two minutes must remain both before the durable
DNS claim and immediately before resolution. The operating-system stub interface
does not expose an authoritative DNS RR TTL or a definitive upstream resolver
server, so the artifact makes no such claim. Runtime DNS remains zero. The V2
executor and transport revalidate the full binding before preflight, before the
secret boundary, after a secret read, before dispatch, and inside the direct
socket-connect path. Owner-pack preparation checks the binding again after every
artifact is written and returns `NETWORK_BINDING_EXPIRED` if it expired during
completion; it never prints a ready result in that state.

## Git and local workspace boundary

`prepare_real_capture_workspace_v1.py` supports `CREATE`, `VERIFY`, and `INSPECT`.
The Windows production inspector rejects UNC/network paths, non-fixed or
non-ACL-capable filesystems, registered synchronization roots, cloud recall and
offline attributes, reparse points, root overlap, and non-exclusive ACLs.
When `CREATE` has no explicit root, it discovers deterministic fixed-volume
candidates and prefers the current user's local application-data boundary. An
explicit or discovered candidate's existing parent is inspected before the first
directory is created. ACL decisions compare stable SIDs rather than localized
account names.

`CREATE` makes sibling repository, control-temp, and capture roots, uses a small
sanitized Git environment and an empty template, obtains a complete public clone,
checks out the exact merged main detached, and rejects submodules, symlinks,
shallow/partial/shared object state, alternates, replacement objects, hooks,
unsafe config, dirty/untracked files, and hidden index flags. It runs
`git fsck --full --strict` and emits an immutable sanitized creation receipt. That
receipt is explicitly not authority-eligible. The tool must then be invoked again
in `VERIFY` mode from the new standalone clone itself; only this in-clone
verification receipt is accepted by schedule freeze, campaign selection, DNS, or
owner-pack preparation. A `.git` file or linked worktree is never valid for V2.
The receipt independently records the repository owning the actual entrypoint
and the repository owning the imported `robin.capture` package. Both must be the
verified standalone clone. Every downstream preparation CLI rechecks those
loaded-code paths, the three root fingerprints, pristine exact Git state, and the
Git executable before proceeding. The receipt also binds and rechecks each root's
ACL security-descriptor hash. All review artifacts (schedule, selection, the
control-root DNS-claim mirror, network binding, and owner pack) are confined to
the receipt-bound control-temp root, so preparation cannot dirty the verified
repository. The sole exception is the sanitized mission-global reservation
marker described above. Provider resolution claims and First-C0 preparation-cycle
reservations share the same untracked, deterministic V2 registry beneath the
verified owner execution boundary, so separately verified workspaces cannot each
spend the same mission opportunity. Read-only inspection never creates the V2 or
legacy directory. New writes target V2 exclusively and use create-exclusive
semantics after a final dual-root consumption check; the legacy root is never a
write target. Machine-local paths are not committed as execution artifacts.
Cross-workspace, dual-root, and exact failure-class regressions use injected
resolver and fetch counters and prove that every rejected boundary reaches zero
provider DNS, TCP, HTTP, secret, Owner Review Pack, and C0 effects.

Owner authorization binds both the canonical Git executable path and its freshly
computed SHA-256. V2 repository inspection checks both around local Git use; the
same bytes at a different path fail closed.

## Owner review and later approval

`select_campaign_window_v1.py` requires fresh post-bootstrap official target sets
for all five live sport keys, each declaring an owner-reviewed complete official
fixture horizon with exact count and source-bytes hash, plus a hash-bound
corpus-coverage snapshot. It enumerates every distinct active interval clique,
so a greedy partition cannot omit a higher-coverage one-call group. H24 and H2
retain their exact frozen PR57 role bindings. H1 remains visible with the
repository's exact
`STRICT_CONVERGENCE_GUARD_PROPOSED_FROM_FROZEN_5_MIN_TOLERANCE` authority and
lower-bound caveat, but is explicitly non-admitting until a separate scientific
amendment. Expired groups are retained as `MISSED_NOT_BACKDATED`; future,
non-admitting, and insufficient-margin groups are explicit. The unique best
remaining H24/H2 winner is ranked by fixture coverage, protocol-role binding
count, a required positive margin, underrepresented-league corpus value,
earliest operational readiness, and only then a stable group hash. A future
winner is bound with an exact not-before time; DNS and pack preparation stop
until it is open, and the entire official/corpus universe must still be no more
than thirty minutes old. Reloading or current-use validation regenerates the
complete universe and winner.

`build_owner_review_pack_v1.py` consumes the authority-eligible verification
receipt, one current network binding, the tracked unexpired mission manifest, and
that exact campaign selection. It derives the target set and request from the
winner; neither can be supplied separately. It enforces workspace → fresh official
schedules → selection → durable DNS claim → observed resolution → pack generation
order. The review window is derived as the earliest of the binding expiry, mission
expiry, selected campaign close, and earliest kickoff minus five minutes, with at
least two minutes left. It emits only review candidates and zero-effect counters.
A review candidate is not executable.

A later, separate mission may create an `OWNER_AUTHORIZED` V2 artifact only after
an explicit owner decision. That artifact must name the exact reviewed candidate
hash in `review_candidate_sha256`; the contract recomputes and verifies the parent
candidate identity. This prevents an approval from being transferred to changed
Git, network, target, request, time, or budget material.
The pack projects and records the exact canonical hash that this sole valid
promotion will have without creating an authorized artifact. Its activation is
bound to that projected hash, so the reviewed activation, plan, and item remain
byte-identical after valid owner promotion; any scope change invalidates the
entire chain.
The V2 runtime must load that exact review-candidate artifact as well as the later
authorized artifact and tracked mission manifest; a caller-supplied self-pin is
not accepted. Campaign selection, DNS, pack preparation, and V2 runtime all load
the manifest only from
`configs/execution/real-execution-bootstrap-closure-v1.json` inside the exact
verified standalone repository. An alternate rehashed copy or later expiry is
rejected.

## Required operational order

1. Merge this capability with a merge commit only after exact-head CI and the
   required read-only reviews accept it; then require post-merge `main` CI to be
   green at that exact merge SHA.
2. Create a clean source stage at the exact merge SHA. From that source, invoke
   workspace `CREATE` at most once to provision a new standalone runtime; its
   receipt remains non-authoritative.
3. Load the bootstrap tool and package from that exact standalone clone and
   invoke `VERIFY` at most once. Only the resulting authority-eligible receipt
   may be used downstream. Never reuse, repair, clean, or advance an older
   runtime for this sequence.
4. Before consuming a preparation cycle, derive the owner boundary from the
   three verified receipt roots, prove it is the same physical
   `<Windows Profile>\RDS` object, inspect the V2 child and legacy root read-only,
   and write an untracked `global-claim-boundary-v2-receipt.json` in control-temp.
   This inspection must create no claim or cycle and must record canonical paths,
   volume/device/file identities, ACL hashes, the workspace-receipt hash, the
   merge SHA, the legacy `FORBIDDEN` write policy, and a canonical receipt hash.
5. From the verified runtime, enter only the First-C0 preparation path. Reserve
   the mission-global V2 cycle before its local reservation and before any
   official public schedule read. Start with La Liga; refresh or use the
   Bundesliga fallback only when the preceding immutable receipt authorizes that
   exact transition. Never backfill a gap or repeat an identical source. Stop at
   three cycles or twelve physical official reads.
6. Freeze the resulting official evidence and produce the immutable pre-DNS
   bundle. A governed `CANARY_READY_NOW`, `PREFETCHED_FUTURE_WINDOW`, or
   `CANARY_FUTURE_WINDOW` is a successful preparation outcome; source failure,
   no valid window, or mission expiry is a governed stop and never authorizes an
   invented fallback.
7. If a governed bundle exists, build untracked
   `first-c0-owner-launch-kit-v2.json` and `.md` in control-temp from the actual
   receipt, manifest, boundary receipt, bundle, optional prefetch handoff,
   selected candidate/window, historical marker hashes, and exact file paths.
   Include the recommended owner start in UTC and Europe/Paris and display the
   exact future `run_first_c0_owner_pack_atomic_v1.py` command with both
   `--execute` and `--owner-present-for-at-least-20-minutes` gates.
8. Stop after publishing that launch kit. The displayed command belongs to a
   later explicit owner authorization and is not executed by this preparation
   sequence. Provider `getaddrinfo`, provider DNS/TCP/HTTP, the DNS claim,
   network binding, secret access, Owner Review Pack creation, owner
   authorization, and C0 all remain exactly zero.

If any ordering, freshness, path, hash, target, identity, or evidence gate fails,
stop. Do not alter `%LOCALAPPDATA%` or RDS ACLs, write the legacy root, backdate,
guess an IP, invent a provider fixture ID, silently retry, or reuse an expired or
consumed artifact.
