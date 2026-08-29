"""Sanitized human and machine reports derived only from the captured batch."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from robin.data_torrent.contracts import canonical_json_bytes, utc_text


def _data_type(values: list[object]) -> str:
    non_null = [value for value in values if value is not None]
    types = {type(value) for value in non_null}
    if not types:
        return "null"
    if types <= {int}:
        return "integer"
    if types <= {int, float}:
        return "number"
    if types == {bool}:
        return "boolean"
    if types == {str}:
        return "string"
    if types == {list}:
        return "array"
    if types == {dict}:
        return "object"
    return "mixed"


def field_dictionary(
    *,
    mission_id: str,
    generated_at: datetime,
    canonical_dataset_sha256: str,
    records: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    record_types = sorted({str(item["record_type"]) for item in records})
    fields: list[dict[str, Any]] = []
    for record_type in record_types:
        typed_records = [item for item in records if item["record_type"] == record_type]
        names = sorted({name for item in typed_records for name in item})
        for name in names:
            values = [item.get(name) for item in typed_records]
            is_time = name.endswith("_utc")
            fields.append(
                {
                    "record_type": record_type,
                    "field_name": name,
                    "data_type": _data_type(values),
                    "nullable": any(value is None for value in values),
                    "allowed_values": (
                        sorted({value for value in values if isinstance(value, str)})
                        if name in {"record_type", "market_key", "temporal_role"}
                        else []
                    ),
                    "unit": "UTC" if is_time else None,
                    "description": f"Observed {name} field for {record_type} records.",
                    "source_family": ("OFFICIAL" if record_type == "OFFICIAL_FIXTURE" else "ODDS"),
                    "source_path": name,
                    "semantic_role": (
                        "EVENT_TIME"
                        if name == "kickoff_utc"
                        else "KNOWN_TIME"
                        if name
                        in {
                            "known_at_utc",
                            "retrieved_at_utc",
                            "bookmaker_last_update_utc",
                            "market_last_update_utc",
                        }
                        else "LINEAGE"
                        if name.startswith("source_")
                        else "MEASURE",
                    ),
                    "canonicalization": "ROBIN_CANONICAL_JSON_LINES_V1",
                    "temporal_semantics": {
                        "event_time_field": "kickoff_utc",
                        "known_at_field": (
                            "known_at_utc"
                            if record_type == "OFFICIAL_FIXTURE"
                            else "market_last_update_utc"
                        ),
                        "retrieved_at_field": (
                            "known_at_utc"
                            if record_type == "OFFICIAL_FIXTURE"
                            else "retrieved_at_utc"
                        ),
                        "safe_pre_event_use": True,
                        "leakage_rule": "known/update <= retrieved < kickoff",
                    },
                }
            )
    return {
        "schema_version": "robin-hypothesis-ready-field-dictionary-v1",
        "mission_id": mission_id,
        "generated_at_utc": utc_text(generated_at),
        "canonical_dataset_sha256": canonical_dataset_sha256,
        "record_types": record_types,
        "fields": fields,
        "quality_guards": [
            "TIMEZONE_REQUIRED",
            "KNOWN_OR_UPDATE_NOT_AFTER_RETRIEVAL",
            "RETRIEVAL_STRICTLY_BEFORE_KICKOFF",
            "RAW_SHA256_LINEAGE_REQUIRED",
            "NO_FUZZY_FIXTURE_MAPPING",
        ],
    }


def hypothesis_backlog(
    *,
    canonical_dataset_sha256: str,
    coverage: tuple[dict[str, Any], ...],
    records: tuple[dict[str, Any], ...],
    rejects: tuple[dict[str, Any], ...],
) -> str:
    sections = [
        "# Hypothesis backlog from real data V1",
        "",
        f"Dataset SHA-256: `{canonical_dataset_sha256}`",
        "",
        "All hypotheses are NOT_TESTED. They are factual research prompts, not edge claims.",
        "",
    ]
    for index, cell in enumerate(coverage, start=1):
        sections.extend(
            [
                f"## HYP-{index:03d}",
                "",
                "Status: NOT_TESTED",
                "",
                (
                    "Observation: "
                    f"{cell['league']} / {cell['market']} contains "
                    f"{cell['records_normalized']} accepted outcomes across "
                    f"{cell['fixtures_captured']} of {cell['fixtures_available']} "
                    "official fixtures."
                ),
                "",
                (
                    "Hypothesis: availability and dispersion for this league-market "
                    "cell may differ systematically from the other observed cells."
                ),
                "",
                (
                    f"Evidence: dataset `{canonical_dataset_sha256}`, coverage cell "
                    f"`{cell['sport_key']}:{cell['market']}`."
                ),
                "",
                "Test: pre-register a cross-cell coverage and price-dispersion comparison.",
                "",
                "Temporal guard: use only observations retrieved before kickoff.",
                "",
                "Edge promotion: NO",
                "",
            ]
        )
    type_counts = Counter(str(item["record_type"]) for item in records)
    reject_counts = Counter(str(item["reason"]) for item in rejects)
    additional = (
        (
            "The ratio of official fixture rows to mapped odds outcomes may predict "
            "where coverage controls need strengthening.",
            f"record type counts {dict(sorted(type_counts.items()))}",
            "compare coverage ratios without evaluating sporting outcomes",
        ),
        (
            "Observed reject reasons may cluster by source contract or league.",
            f"reject reason counts {dict(sorted(reject_counts.items()))}",
            "compare reject proportions with exact Wilson intervals",
        ),
    )
    for offset, (hypothesis, evidence, test) in enumerate(additional, start=len(coverage) + 1):
        sections.extend(
            [
                f"## HYP-{offset:03d}",
                "",
                "Status: NOT_TESTED",
                "",
                f"Observation: {evidence}.",
                "",
                f"Hypothesis: {hypothesis}",
                "",
                f"Evidence: dataset `{canonical_dataset_sha256}`.",
                "",
                f"Test: {test}.",
                "",
                "Temporal guard: preserve the captured known-at boundary.",
                "",
                "Edge promotion: NO",
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def load_replay_markdown(report: dict[str, Any]) -> str:
    return (
        "# Torrent load replay V1\n\n"
        "## Identity\n\n"
        f"Mission: `{report['mission_id']}`; status: **{report['status']}**.\n\n"
        "## Input\n\n"
        f"Raw bytes/iteration: {report['input']['raw_bytes_per_iteration']}; "
        f"records/iteration: {report['input']['normalized_records_per_iteration']}.\n\n"
        "## Normal required throughput\n\n"
        f"{report['normal_required_throughput']['records_per_second']:.4f} records/s; "
        f"{report['normal_required_throughput']['bytes_per_second']:.4f} bytes/s.\n\n"
        "## Replay volume\n\n"
        f"Multiplier: {report['replay']['multiplier']}×; equivalent records: "
        f"{report['replay']['equivalent_normalized_records']}.\n\n"
        "## Performance\n\n"
        f"{report['measurement']['records_per_second']:.4f} records/s; "
        f"p50 {report['measurement']['p50_latency_ms']:.4f} ms; "
        f"p95 {report['measurement']['p95_latency_ms']:.4f} ms; peak memory "
        f"{report['measurement']['peak_memory_bytes']} bytes.\n\n"
        "## Data integrity\n\n"
        f"Canonical equality: {report['acceptance']['canonical_equality_pass']}; "
        f"silent losses: {report['measurement']['silent_losses']}; duplicates: "
        f"{report['measurement']['duplicates']}.\n\n"
        "## External-effect delta\n\n"
        f"`{report['external_effects_delta']}`\n\n"
        "## Acceptance\n\n"
        f"Minimum throughput ratio: {report['throughput']['minimum_ratio']:.4f}; "
        f"accepted: {report['status'] == 'PASS'}.\n"
    )


_QA_SCHEMA_VERSION = "robin-data-torrent-qa-acceptance-matrix-v1"
_QA_PROOF_ALGORITHM = "SHA-256"
_QA_ERROR = "DATA_TORRENT_QA_PROOF_INVALID"
_QA_FILE = "torrent-qa-acceptance-matrix-v1.json"

_QA_GATE_SPECS: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "baseline_identity",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/run_identity",
                "EXACT_RUN_AND_WORKFLOW_IDENTITY",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/post_merge_ci_proof",
                "EXACT_POST_MERGE_CI_IDENTITY",
            ),
        ),
    ),
    (
        "cross_run_claim",
        "P0",
        (
            (
                "torrent-opportunity-claim-receipt-v1.json",
                "",
                "DURABLE_WINNER_CLAIM",
            ),
            (
                "torrent-opportunity-claim-receipt-v1.json",
                "/cross_run_contract_proof",
                "CROSS_RUN_CI_CONTRACT",
            ),
            (
                "torrent-control-plane-event-chain-v1.json",
                "/events/external_sources",
                "CLAIM_BEFORE_SOURCE_PERMITS",
            ),
        ),
    ),
    (
        "loser_replay_no_reads",
        "P0",
        (
            (
                "torrent-load-replay-report-v1.json",
                "/external_effects_delta",
                "REPLAY_ZERO_EXTERNAL_EFFECTS",
            ),
            (
                "torrent-load-replay-report-v1.json",
                "/cross_run_loser_contract_proof",
                "CROSS_RUN_LOSER_ZERO_PERMITS",
            ),
        ),
    ),
    (
        "migration_rbac",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/production/database_revision",
                "EXACT_PRODUCTION_DATABASE_REVISION",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/chronos_release_chain_proof",
                "ATTESTED_MIGRATION_RBAC_RELEASE_CHAIN",
            ),
        ),
    ),
    (
        "production_bindings",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/production/runtime_bindings_present",
                "SCOPED_RUNTIME_BINDING_ATTESTATION",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/run_identity",
                "SCOPED_BINDING_RUN_IDENTITY",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/chronos_release_chain_proof/database_target",
                "SIGNED_SCOPED_DATABASE_TARGET",
            ),
        ),
    ),
    (
        "ordering_one_shot",
        "P0",
        (
            (
                "torrent-opportunity-claim-receipt-v1.json",
                "/claim_before_first_external_effect",
                "CLAIM_PRECEDES_FIRST_EFFECT",
            ),
            (
                "torrent-control-plane-event-chain-v1.json",
                "/events/external_sources",
                "SOURCE_EFFECT_SEQUENCE_AND_TERMINALS",
            ),
        ),
    ),
    (
        "ledger_caps",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/effect_summary/actual",
                "TOTAL_EFFECTS_OBSERVED",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/effect_summary/limits",
                "TOTAL_EFFECT_LIMITS",
            ),
            (
                "torrent-control-plane-event-chain-v1.json",
                "/events",
                "PER_OPERATION_EFFECT_LEDGER",
            ),
            (
                "torrent-r2-inventory-v1.json",
                "/counters",
                "R2_EFFECTS_OBSERVED",
            ),
            (
                "torrent-r2-inventory-v1.json",
                "/limits",
                "R2_EFFECT_LIMITS",
            ),
        ),
    ),
    (
        "forbidden_effects",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/execution",
                "ONE_SHOT_AND_ZERO_RETRY_ATTESTATION",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/effect_summary",
                "ZERO_FORBIDDEN_EFFECT_TOTALS",
            ),
            (
                "torrent-real-batch-quality-report-v1.json",
                "/external_effects",
                "ZERO_UNACCOUNTED_EFFECTS",
            ),
            (
                "torrent-r2-inventory-v1.json",
                "/counters",
                "ZERO_DELETE_AND_OVERWRITE_EFFECTS",
            ),
        ),
    ),
    (
        "secret_safety",
        "P0",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/artifacts",
                "POST_SCAN_SANITIZED_ARTIFACT_HASH_INVENTORY",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/schema_version",
                "POST_SCAN_MANIFEST_SELF_WITNESS",
            ),
        ),
    ),
    (
        "temporal_safety",
        "P0",
        (
            (
                "torrent-real-batch-quality-report-v1.json",
                "/temporal",
                "ZERO_TEMPORAL_LEAKAGE",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/horizon/no_backfill",
                "NO_BACKFILL",
            ),
        ),
    ),
    (
        "scope_horizon",
        "P1",
        (("torrent-real-batch-manifest-v1.json", "/horizon", "LIVE_HORIZON"),),
    ),
    (
        "official_breadth",
        "P1",
        (
            (
                "torrent-official-read-receipts-v1.json",
                "/reads",
                "ALL_ENABLED_LEAGUE_READS",
            ),
            (
                "torrent-official-read-receipts-v1.json",
                "/total_physical_reads",
                "OFFICIAL_READS_OBSERVED",
            ),
            (
                "torrent-official-read-receipts-v1.json",
                "/maximum_physical_reads",
                "OFFICIAL_READS_REQUIRED_MAXIMUM",
            ),
        ),
    ),
    (
        "odds_breadth",
        "P1",
        (
            (
                "torrent-provider-credit-receipt-v1.json",
                "/credit_transitions",
                "ALL_ENABLED_LEAGUE_CREDIT_TRANSITIONS",
            ),
            (
                "torrent-provider-credit-receipt-v1.json",
                "/provider_requests",
                "ODDS_REQUESTS_OBSERVED",
            ),
            (
                "torrent-provider-credit-receipt-v1.json",
                "/credits_used",
                "ODDS_CREDITS_OBSERVED",
            ),
            (
                "torrent-provider-credit-receipt-v1.json",
                "/maximum_credits",
                "ODDS_CREDITS_REQUIRED_MAXIMUM",
            ),
        ),
    ),
    (
        "raw_durability",
        "P1",
        (
            ("torrent-r2-inventory-v1.json", "/objects/0", "RAW_OBJECT_TERMINAL_RECEIPT"),
            (
                "torrent-real-batch-raw-index-v1.json",
                "/totals/accounted_responses",
                "RAW_RESPONSE_ACCOUNTING",
            ),
        ),
    ),
    (
        "normalization_lineage",
        "P1",
        (
            (
                "torrent-raw-to-normalized-lineage-v1.json",
                "/summary",
                "RAW_RESPONSE_LINEAGE_CLOSURE",
            ),
            (
                "torrent-real-batch-quality-report-v1.json",
                "/source_unit_accounting",
                "SOURCE_UNIT_ACCOUNTING_CLOSURE",
            ),
        ),
    ),
    (
        "fixture_mapping_coverage",
        "P1",
        (
            (
                "torrent-real-batch-coverage-matrix-v1.csv",
                "",
                "LEAGUE_MARKET_COVERAGE_ROWS",
            ),
        ),
    ),
    (
        "replay",
        "P1",
        (
            (
                "torrent-load-replay-report-v1.json",
                "/acceptance",
                "REPLAY_ACCEPTANCE",
            ),
            (
                "torrent-canonical-dataset-hash-v1.json",
                "/equality",
                "CANONICAL_HASH_EQUALITY",
            ),
        ),
    ),
    (
        "load",
        "P1",
        (
            (
                "torrent-load-replay-report-v1.json",
                "/throughput",
                "MEASURED_TO_REQUIRED_THROUGHPUT",
            ),
            (
                "torrent-load-replay-report-v1.json",
                "/measurement",
                "LOAD_MEASUREMENT",
            ),
        ),
    ),
    (
        "artifact_closure",
        "P2",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/artifacts",
                "FINAL_ARTIFACT_HASH_INVENTORY_EXCLUDING_MANIFEST_SELF",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/schema_version",
                "MANIFEST_SELF_WITNESS",
            ),
        ),
    ),
    (
        "ops_recovery_science",
        "P2",
        (
            (
                "hypothesis-ready-field-dictionary-v1.json",
                "/fields",
                "NONEMPTY_FIELD_DICTIONARY",
            ),
            (
                "hypothesis-backlog-from-real-data-v1.md",
                "",
                "FACTUAL_HYPOTHESIS_BACKLOG",
            ),
            (
                "robin-data-torrent-operations-pack-v1.md",
                "",
                "OPERATIONS_RUNBOOK",
            ),
            (
                "robin-data-torrent-recovery-pack-v1.md",
                "",
                "RECOVERY_RUNBOOK",
            ),
        ),
    ),
    (
        "ci_merge_postmerge",
        "P2",
        (
            (
                "torrent-real-batch-manifest-v1.json",
                "/post_merge_ci_proof",
                "EXACT_HEAD_POST_MERGE_CI_SUCCESS",
            ),
            (
                "torrent-real-batch-manifest-v1.json",
                "/chronos_release_chain_proof",
                "ATTESTED_PREFLIGHT_MIGRATE_VERIFY_SUCCESSION",
            ),
        ),
    ),
)

_QA_TERMINAL_EVIDENCE = tuple(
    (_QA_FILE, f"/gates/{index}/proof_sha256", "PRIOR_GATE_PROOF")
    for index in range(len(_QA_GATE_SPECS))
)

_QA_DEBT = (
    "D: official public page schemas may drift after this evidenced run",
    "D: GitHub runner performance varies; measured environment is attributed",
    "D: a zero-effect process crash after claim keeps the one-shot opportunity closed",
)


def _qa_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _qa_evidence(
    specs: tuple[tuple[str, str, str], ...],
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for file_name, pointer, role in specs:
        binding = {
            "evidence_file": file_name,
            "evidence_pointer": pointer,
            "evidence_role": role,
        }
        evidence.append({**binding, "binding_sha256": _qa_hash(binding)})
    return evidence


def _qa_gate_row(
    *,
    gate_id: str,
    priority: str,
    observed: bool,
    evidence_specs: tuple[tuple[str, str, str], ...],
    dependency_proofs: tuple[str, ...] = (),
) -> dict[str, Any]:
    evidence = _qa_evidence(evidence_specs)
    proof = {
        "gate_id": gate_id,
        "priority": priority,
        "predicate_id": f"{gate_id}-boolean-equality-v1",
        "comparison": "BOOLEAN_EQUALS",
        "observed": observed,
        "required": True,
        "evidence_file": evidence[0]["evidence_file"],
        "evidence_pointer": evidence[0]["evidence_pointer"],
        "evidence": evidence,
        "dependency_proof_sha256": list(dependency_proofs),
    }
    return {
        **proof,
        "status": "PASS" if observed is True else "FAIL",
        "proof_sha256": _qa_hash(proof),
    }


def _qa_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    failed_priorities = Counter(str(row["priority"]) for row in rows if row["status"] == "FAIL")
    passed = sum(row["status"] == "PASS" for row in rows)
    total = len(rows)
    return {
        "passed": passed,
        "total": total,
        "qa_acceptance_percent": int(100 * passed / total),
        "p0": failed_priorities["P0"],
        "p1": failed_priorities["P1"],
        "p2": failed_priorities["P2"],
        "open_threads": total - passed,
    }


def _qa_document(
    *,
    generated_at_utc: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = _qa_summary(rows)
    debt = list(_QA_DEBT)
    matrix_proof = {
        "schema_version": _QA_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "gate_proof_sha256": [str(row["proof_sha256"]) for row in rows],
        "summary": summary,
        "remaining_non_blocking_debt": debt,
    }
    return {
        "schema_version": _QA_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc,
        "proof_hash_algorithm": _QA_PROOF_ALGORITHM,
        "gates": rows,
        "summary": summary,
        "remaining_non_blocking_debt": debt,
        "matrix_proof_sha256": _qa_hash(matrix_proof),
    }


def verify_qa_matrix(document: Mapping[str, Any]) -> None:
    """Reconstruct every QA result and proof, failing closed on any mismatch."""

    generated_at = document.get("generated_at_utc")
    raw_rows = document.get("gates")
    if type(generated_at) is not str or type(raw_rows) is not list:
        raise ValueError(_QA_ERROR)
    rows = cast(list[object], raw_rows)
    if len(rows) != len(_QA_GATE_SPECS) + 1:
        raise ValueError(_QA_ERROR)

    reconstructed: list[dict[str, Any]] = []
    for raw_row, (gate_id, priority, evidence_specs) in zip(rows[:-1], _QA_GATE_SPECS, strict=True):
        if type(raw_row) is not dict:
            raise ValueError(_QA_ERROR)
        row = cast(dict[str, object], raw_row)
        observed = row.get("observed")
        if type(observed) is not bool:
            raise ValueError(_QA_ERROR)
        expected = _qa_gate_row(
            gate_id=gate_id,
            priority=priority,
            observed=observed,
            evidence_specs=evidence_specs,
        )
        if canonical_json_bytes(row) != canonical_json_bytes(expected):
            raise ValueError(_QA_ERROR)
        reconstructed.append(expected)

    raw_terminal = rows[-1]
    if type(raw_terminal) is not dict:
        raise ValueError(_QA_ERROR)
    dependency_proofs = tuple(str(row["proof_sha256"]) for row in reconstructed)
    terminal = _qa_gate_row(
        gate_id="qa_terminal",
        priority="P2",
        observed=all(row["status"] == "PASS" for row in reconstructed),
        evidence_specs=_QA_TERMINAL_EVIDENCE,
        dependency_proofs=dependency_proofs,
    )
    if canonical_json_bytes(cast(dict[str, object], raw_terminal)) != canonical_json_bytes(
        terminal
    ):
        raise ValueError(_QA_ERROR)
    reconstructed.append(terminal)

    expected_document = _qa_document(
        generated_at_utc=generated_at,
        rows=reconstructed,
    )
    if canonical_json_bytes(dict(document)) != canonical_json_bytes(expected_document):
        raise ValueError(_QA_ERROR)


def qa_matrix(
    *,
    generated_at: datetime,
    statuses: Mapping[str, bool],
) -> dict[str, Any]:
    expected = {gate_id for gate_id, _priority, _evidence in _QA_GATE_SPECS}
    if set(statuses) != expected or any(type(value) is not bool for value in statuses.values()):
        raise ValueError("DATA_TORRENT_QA_EVIDENCE_INVALID")

    rows = [
        _qa_gate_row(
            gate_id=gate_id,
            priority=priority,
            observed=statuses[gate_id],
            evidence_specs=evidence_specs,
        )
        for gate_id, priority, evidence_specs in _QA_GATE_SPECS
    ]
    rows.append(
        _qa_gate_row(
            gate_id="qa_terminal",
            priority="P2",
            observed=all(row["status"] == "PASS" for row in rows),
            evidence_specs=_QA_TERMINAL_EVIDENCE,
            dependency_proofs=tuple(str(row["proof_sha256"]) for row in rows),
        )
    )
    document = _qa_document(generated_at_utc=utc_text(generated_at), rows=rows)
    verify_qa_matrix(document)
    return document


def operations_pack() -> str:
    return """# Robin data torrent operations pack V1

## Identity
Run only the exact merged main SHA and tracked workflow SHA on Ubuntu.

## Preconditions
Require green exact-main post-merge CI, attested PREFLIGHT/MIGRATE/VERIFY succession,
production revision 0015, the four scoped Chronos bindings, Odds and R2 credentials.

## Secret bindings
Read values only in the secret-bearing runtime step; never emit values or connection URLs.

## Budgets
Official 50 reads; Odds 5 requests/1000 credits; R2 P20/G20/L2/D0; automatic retries 0.

## Claim
Acquire the stable PostgreSQL opportunity before DNS, HTTP or R2. A loser exits with zero effects.

## One-shot dispatch
Run attempt must be 1. Never rerun or request an identical snapshot.

## Artifacts
R2 is authoritative for raw and normalized archives; GitHub receives sanitized evidence only.

## Validation
Require exact canonical replay equality, ratio >=5, zero silent loss/leakage/duplicates/unaccounted effects.

## Abort
Stop on ambiguity, budget risk, generation mismatch or any non-additive production state.
"""


def recovery_pack() -> str:
    return """# Robin data torrent recovery pack V1

## State classification
Classify from PostgreSQL permits/events and exact R2 keys; never infer from a process exit code alone.

## Claim loser
Do not read official sources, resolve the provider, consume credits or touch R2.

## Pre-dispatch failure
A proven FAILED_BEFORE_DISPATCH has zero external effects, but the one-shot opportunity remains closed.

## Official/odds effect ambiguity
Do not retry. Preserve any captured bytes and escalate as an owner-only consumed-effect hard stop.

## R2 ambiguity
Use only the Chronos-authorized exact-key GET path; never LIST, overwrite or DELETE.

## No-retry rule
No workflow rerun and no second identical snapshot. Replay operates exclusively from durable raw bytes.

## Branch/migration limits
At most two recovery branches and three additive migrations; destructive migration is forbidden.

## Owner-only hard stop
Escalate only permissions/secrets, paid capacity, destructive-only recovery, or a consumed ambiguous one-shot.
"""


__all__ = [
    "field_dictionary",
    "hypothesis_backlog",
    "load_replay_markdown",
    "operations_pack",
    "qa_matrix",
    "recovery_pack",
    "verify_qa_matrix",
]
