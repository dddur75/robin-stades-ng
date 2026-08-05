from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "configs/data/historical-coverage-denominator-contract-v1.json"
UPSTREAM_PATH = ROOT / "configs/historical-deep-data-harvest-v1.json"
CALENDAR_PATH = ROOT / "configs/data/calendar-fatigue-property-gates-v1.json"
PACKS_PATH = ROOT / "configs/data/coverage-scale-pack-manifests-v1.json"
GRAIN_CATALOG_PATH = ROOT / "configs/data/football-grain-catalog-v1.json"
GATES_PATH = ROOT / "configs/data/p0-readiness-gates-v1.json"
PR26_REVIEW_PATH = ROOT / "reports/evidence/pr26-final-review-v1.json"
PROPERTY_ROLES_PATH = ROOT / "reports/hypothesis-genome/property-semantic-roles.json"


class DenominatorError(ValueError):
    """A denominator proof would violate the fail-closed contract."""


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_contract() -> dict[str, Any]:
    return load_json(CONTRACT_PATH)


def load_grain_catalog() -> dict[str, Any]:
    return load_json(GRAIN_CATALOG_PATH)


def verify_grain_catalog(
    contract: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    reference = contract["grain_catalog"]
    if not reference["authoritative"]:
        raise DenominatorError("GRAIN_CATALOG_NOT_AUTHORITATIVE")
    if catalog["schema_version"] != reference["schema_version"]:
        raise DenominatorError("GRAIN_CATALOG_SCHEMA_MISMATCH")
    p0_scope = catalog["scopes"]["P0_2020_2025"]
    if p0_scope["competitions"] != contract["grid"]["competitions"]:
        raise DenominatorError("GRAIN_CATALOG_COMPETITIONS_MISMATCH")
    if p0_scope["seasons"] != contract["grid"]["seasons"]:
        raise DenominatorError("GRAIN_CATALOG_SEASONS_MISMATCH")
    bindings = catalog["family_bindings"]
    if set(bindings) != set(contract["grid"]["families"]):
        raise DenominatorError("GRAIN_CATALOG_FAMILIES_MISMATCH")
    required = {
        "grain",
        "distinct_key",
        "source",
        "temporal_class",
        "null_policy",
        "duplicate_policy",
        "expected_denominator",
        "authorized_uses",
    }
    for binding in bindings.values():
        grain = catalog["grains"][binding["grain_id"]]
        if not required <= set(grain):
            raise DenominatorError("GRAIN_CATALOG_FIELDS_MISSING")
    return catalog


def verify_upstream_contract(contract: dict[str, Any]) -> dict[str, Any]:
    upstream = load_json(UPSTREAM_PATH)
    expected = contract["upstream_contract"]
    if canonical_file_hash(UPSTREAM_PATH) != expected["file_sha256_lf"]:
        raise DenominatorError("UPSTREAM_FILE_HASH_MISMATCH")
    if canonical_hash(upstream) != expected["canonical_sha256"]:
        raise DenominatorError("UPSTREAM_CANONICAL_HASH_MISMATCH")
    grid = contract["grid"]
    if grid["competitions"] != [item["canonical_key"] for item in upstream["competitions"]]:
        raise DenominatorError("UPSTREAM_COMPETITIONS_MISMATCH")
    if grid["seasons"] != upstream["season_priorities"]["P0"]:
        raise DenominatorError("UPSTREAM_SEASONS_MISMATCH")
    if grid["families"] != upstream["families"]["P0"]:
        raise DenominatorError("UPSTREAM_FAMILIES_MISMATCH")
    return upstream


def make_rate(
    numerator: int | None,
    denominator: int | None,
    *,
    grain: str,
    complete_scope: bool = False,
    not_applicable: bool = False,
) -> dict[str, object]:
    if not grain:
        raise DenominatorError("RATE_GRAIN_REQUIRED")
    if not_applicable:
        return {
            "numerator": None,
            "denominator": None,
            "value": None,
            "status": "NOT_APPLICABLE",
            "grain": grain,
        }
    if numerator is None or denominator is None:
        if numerator is not None or denominator is not None:
            raise DenominatorError("RATE_PARTIAL_TRIPLET_FORBIDDEN")
        return {
            "numerator": None,
            "denominator": None,
            "value": None,
            "status": "UNKNOWN",
            "grain": grain,
        }
    if numerator < 0 or denominator < 0:
        raise DenominatorError("RATE_NEGATIVE_COUNT")
    if numerator > denominator:
        raise DenominatorError("RATE_NUMERATOR_EXCEEDS_DENOMINATOR")
    if denominator == 0:
        if numerator != 0 or not complete_scope:
            raise DenominatorError("RATE_ZERO_DENOMINATOR_NOT_PROVEN_EMPTY")
        return {
            "numerator": 0,
            "denominator": 0,
            "value": None,
            "status": "EMPTY_VALID",
            "grain": grain,
        }
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator,
        "status": "KNOWN",
        "grain": grain,
    }


def aggregate_weighted_rate(rates: list[dict[str, object]]) -> dict[str, object]:
    if not rates:
        raise DenominatorError("WEIGHTED_RATE_INPUT_REQUIRED")
    applicable = [rate for rate in rates if rate["status"] != "NOT_APPLICABLE"]
    if not applicable:
        return make_rate(None, None, grain="weighted expected denominator", not_applicable=True)
    if any(rate["status"] == "UNKNOWN" for rate in applicable):
        return make_rate(None, None, grain="weighted expected denominator")
    if any(rate["status"] not in {"KNOWN", "EMPTY_VALID"} for rate in applicable):
        raise DenominatorError("WEIGHTED_RATE_STATUS_INVALID")
    numerator = sum(int(rate["numerator"] or 0) for rate in applicable)
    denominator = sum(int(rate["denominator"] or 0) for rate in applicable)
    return make_rate(
        numerator,
        denominator,
        grain="weighted expected denominator",
        complete_scope=True,
    )


def _definition(
    contract: dict[str, Any],
    catalog: dict[str, Any],
    competition: str,
    season: int,
    family: str,
) -> dict[str, object]:
    rule_version = contract["absence_partition_rule"]["version"]
    binding = catalog["family_bindings"][family]
    grain = catalog["grains"][binding["grain_id"]]
    base = {
        "contract_id": contract["contract_id"],
        "scope": "P0_2020_2025",
        "competition": competition,
        "season": season,
        "family": family,
        "grain_binding": binding,
        "grain_definition": grain,
        "rule_version": rule_version,
    }
    return {
        "cell_id": canonical_hash(
            {
                "competition": competition,
                "season": season,
                "family": family,
                "contract_id": contract["contract_id"],
                "grain_catalog": catalog["catalog_id"],
                "rule_version": rule_version,
            }
        ),
        "definition_hash": canonical_hash(base),
        "scope": "P0_2020_2025",
        "competition": competition,
        "season": season,
        "family": family,
        "grain": binding["grain_id"],
        "distinct_key": grain["distinct_key"],
    }


def build_p0_cells(contract: dict[str, Any]) -> list[dict[str, object]]:
    verify_upstream_contract(contract)
    catalog = verify_grain_catalog(contract, load_grain_catalog())
    grid = contract["grid"]
    lineage_hash = canonical_hash(
        {
            "contract": contract,
            "grain_catalog": catalog,
            "upstream": contract["upstream_contract"],
            "population_kind": "P0_FULL",
            "evaluation_level": "E0",
        }
    )
    cells: list[dict[str, object]] = []
    for competition in grid["competitions"]:
        for season in grid["seasons"]:
            for family in grid["families"]:
                cell = _definition(contract, catalog, competition, season, family)
                binding = catalog["family_bindings"][family]
                grain = catalog["grains"][binding["grain_id"]]
                cell.update(
                    {
                        "population_kind": "P0_FULL",
                        "evaluation_level": "E0",
                        "closure_state": "OPEN_NOT_EVALUATED",
                        "reason_codes": [
                            "E0_DEFINITION_ONLY",
                            "NO_AUTHORITATIVE_CENSUS_EVIDENCE",
                        ],
                        "advertised_coverage": None,
                        "expected_count": None,
                        "received_count": None,
                        "empty_valid_count": None,
                        "invalid_count": None,
                        "coverage_percent": None,
                        "null_rate": None,
                        "source_endpoint": grain["source"],
                        "payload_hash": None,
                        "receipt_hash": None,
                        "temporal_class": grain["temporal_class"],
                        "gate": "BLOCKED_BY_COVERAGE",
                        "gate_reason": "CENSUS_DENOMINATOR_NOT_MATERIALIZED",
                        "rates": {
                            "scope_completion": make_rate(
                                None, None, grain=f"scope:{family}"
                            ),
                            "normalization_integrity": make_rate(
                                None,
                                None,
                                grain=" + ".join(grain["distinct_key"]),
                            ),
                            "content_presence": make_rate(
                                None,
                                None,
                                grain=binding["expected_count_formula"],
                            ),
                        },
                        "diagnostics": {
                            "linked_empirical_observations": 0,
                            "census_evidence": False,
                            "provider_calls": 0,
                        },
                        "lineage_hash": lineage_hash,
                    }
                )
                cell["cell_hash"] = canonical_hash(cell)
                cells.append(cell)
    if len(cells) != grid["expected_cells"]:
        raise DenominatorError("P0_GRID_CELL_COUNT_MISMATCH")
    return cells


def partition_observations_by_scope(
    observations: list[dict[str, object]], contract: dict[str, Any]
) -> dict[str, list[dict[str, object]]]:
    grid = contract["grid"]
    p0_dimensions = {
        (competition, season, family)
        for competition in grid["competitions"]
        for season in grid["seasons"]
        for family in grid["families"]
    }
    p0: list[dict[str, object]] = []
    extended: list[dict[str, object]] = []
    seen: dict[tuple[object, object, object], dict[str, object]] = {}
    for observation in observations:
        dimension = (
            observation.get("competition"),
            observation.get("season"),
            observation.get("family"),
        )
        prior = seen.get(dimension)
        if prior is not None:
            if canonical_hash(prior) != canonical_hash(observation):
                raise DenominatorError("OPEN_CONFLICTING_DUPLICATE")
            continue
        seen[dimension] = observation
        explicitly_partial = observation.get("explicitly_partial") is True
        scope_incomplete = observation.get("scope_complete") is False
        if dimension in p0_dimensions and not (explicitly_partial or scope_incomplete):
            p0.append(observation)
        else:
            extended.append(observation)
    return {"P0_2020_2025": p0, "EXTENDED_ALL_AVAILABLE": extended}


def validate_cell_closure(
    cell: dict[str, Any], *, authorizations: dict[str, bool] | None = None
) -> None:
    if cell["closure_state"] != "DENOMINATOR_CLOSED_FULL_SCOPE":
        return
    if cell["evaluation_level"] not in {"E3", "E4"}:
        raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_E3_OR_E4")
    authorizations = authorizations or {}
    if not authorizations.get(cell["evaluation_level"], False):
        raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_LEVEL_AUTHORIZATION")
    if cell["population_kind"] not in {"FULL_SCOPE", "P0_FULL"}:
        raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_FULL_SCOPE")
    if any(cell.get(key) is None for key in ("expected_count", "received_count")):
        raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_COUNTS")
    expected = cell["expected_count"]
    received = cell["received_count"]
    empty_valid = cell.get("empty_valid_count") or 0
    if expected < 0 or received + empty_valid > expected:
        raise DenominatorError("REAL_CELL_CLOSURE_COUNTS_INVALID")
    if expected == 0:
        if received != 0 or empty_valid != 0 or cell.get("coverage_percent") is not None:
            raise DenominatorError("REAL_CELL_CLOSURE_EMPTY_COUNTS_INVALID")
    elif cell.get("coverage_percent") != (received + empty_valid) / expected:
        raise DenominatorError("REAL_CELL_CLOSURE_COVERAGE_RATE_INVALID")
    for rate_name in ("scope_completion", "normalization_integrity"):
        rate = cell["rates"][rate_name]
        complete_known = rate["status"] == "KNOWN" and rate["value"] == 1.0
        complete_empty = (
            rate["status"] == "EMPTY_VALID"
            and rate["numerator"] == 0
            and rate["denominator"] == 0
            and rate["value"] is None
        )
        if not (complete_known or complete_empty):
            raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_COMPLETE_RATES")
    if not cell.get("payload_hash") or not cell.get("receipt_hash"):
        raise DenominatorError("REAL_CELL_CLOSURE_REQUIRES_LINEAGE")


def closure_counts(cells: list[dict[str, Any]]) -> dict[str, int]:
    for cell in cells:
        validate_cell_closure(cell)
    closed = sum(
        cell["closure_state"] == "DENOMINATOR_CLOSED_FULL_SCOPE" for cell in cells
    )
    return {"closed": closed, "open": len(cells) - closed}


def verify_pr26_census_source(contract: dict[str, Any]) -> dict[str, Any]:
    review = load_json(PR26_REVIEW_PATH)
    if artifact_proof_hash(review) != review["proof_hash"]:
        raise DenominatorError("PR26_REVIEW_PROOF_HASH_INVALID")
    if review["proof_hash"] != contract["census_evidence"]["source_review_proof_hash"]:
        raise DenominatorError("PR26_REVIEW_PROOF_HASH_MISMATCH")
    coverage = review["coverage"]
    if coverage["coverage_count"] != contract["census_evidence"]["observed_union_cells"]:
        raise DenominatorError("PR26_OBSERVED_UNION_COUNT_MISMATCH")
    if coverage["census_evidence_cells"] != 0:
        raise DenominatorError("PR26_CENSUS_EVIDENCE_EXPECTED_ABSENT")
    return review


def canonical_calendar_property_ids() -> set[str]:
    roles = load_json(PROPERTY_ROLES_PATH)
    prefix = "football:calendar_fatigue:"
    return {
        item["property_id"].removeprefix(prefix)
        for item in roles["items"]
        if item["family"] == "CALENDAR_FATIGUE"
    }


def calendar_ready_properties() -> list[dict[str, Any]]:
    calendar = load_json(CALENDAR_PATH)
    configured = {item["id"] for item in calendar["properties"]}
    if configured != canonical_calendar_property_ids():
        raise DenominatorError("CALENDAR_PROPERTY_CATALOG_MISMATCH")
    ready = [item for item in calendar["properties"] if item["status"].startswith("READY")]
    if len(ready) != calendar["current_ready_properties"]:
        raise DenominatorError("CALENDAR_READY_COUNT_MISMATCH")
    return ready


def grid_invariants(cells: list[dict[str, object]]) -> dict[str, object]:
    dimensions = [
        (cell["competition"], cell["season"], cell["family"]) for cell in cells
    ]
    return {
        "unique": len(dimensions) == len(set(dimensions)),
        "by_competition": dict(Counter(cell["competition"] for cell in cells)),
        "by_season": {
            str(key): value for key, value in Counter(cell["season"] for cell in cells).items()
        },
        "by_family": dict(Counter(cell["family"] for cell in cells)),
    }


def artifact_proof_hash(artifact: dict[str, Any]) -> str:
    payload = dict(artifact)
    payload.pop("proof_hash", None)
    return canonical_hash(payload)


def seal_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(artifact)
    sealed["proof_hash"] = artifact_proof_hash(sealed)
    return sealed


def classify_fixture_status(status: str) -> str:
    contract = load_contract()["fixture_applicability"]
    normalized = status.strip().upper() if status else "UNKNOWN"
    if normalized in contract["applicable_terminal"]:
        return "APPLICABLE"
    if normalized in contract["not_applicable"]:
        return "NOT_APPLICABLE"
    return "BLOCKING"


def _absence_text(record: dict[str, object]) -> str:
    return " ".join(str(record.get(key) or "") for key in ("type", "reason", "description"))


def classify_absence(record: dict[str, object]) -> str:
    rules = load_contract()["absence_partition_rule"]
    text = _absence_text(record).strip()
    if not text:
        return "UNCLASSIFIABLE"
    if re.search(rules["suspension_regex"], text, flags=re.IGNORECASE):
        return "SUSPENSION"
    if re.search(rules["injury_regex"], text, flags=re.IGNORECASE):
        return "INJURY"
    return "UNCLASSIFIABLE"


def _absence_natural_key(record: dict[str, object]) -> tuple[object, ...]:
    fields = load_contract()["absence_partition_rule"]["natural_key"]
    return tuple(record.get(field) for field in fields)


def reconcile_absences(
    records: list[dict[str, object]], *, pages_complete: bool
) -> dict[str, object]:
    if not pages_complete:
        raise DenominatorError("OPEN_MISSING_SCOPE")
    distinct: dict[tuple[object, ...], dict[str, object]] = {}
    for record in records:
        key = _absence_natural_key(record)
        existing = distinct.get(key)
        if existing is None:
            distinct[key] = record
        elif canonical_hash(existing) != canonical_hash(record):
            raise DenominatorError("OPEN_CONFLICTING_DUPLICATE")
    counts = Counter(classify_absence(record) for record in distinct.values())
    total = len(distinct)
    if sum(counts.values()) != total:
        raise DenominatorError("ABSENCE_PARTITION_INVARIANT_FAILED")
    classified = total - counts["UNCLASSIFIABLE"]
    return {
        "source_records_distinct": total,
        "injuries": counts["INJURY"],
        "suspensions": counts["SUSPENSION"],
        "unclassifiable": counts["UNCLASSIFIABLE"],
        "duplicates_ignored": len(records) - total,
        "absence_scope_completion_rate": make_rate(
            1, 1, grain="complete injuries pagination"
        ),
        "absence_classification_integrity_rate": make_rate(
            classified,
            total,
            grain="classified distinct absence / distinct source absence",
            complete_scope=True,
        ),
        "classification_state": (
            "DENOMINATOR_CLASSIFICATION_READY"
            if counts["UNCLASSIFIABLE"] == 0
            else "OPEN_CLASSIFICATION_AMBIGUOUS"
        ),
    }


def calendar_family_status(ready_properties: int) -> str:
    total = len(load_json(CALENDAR_PATH)["properties"])
    if ready_properties < 0 or ready_properties > total:
        raise DenominatorError("CALENDAR_READY_PROPERTY_COUNT_INVALID")
    if ready_properties == 0:
        return "CLOSED"
    if ready_properties == total:
        return "READY_STRICT"
    return "PARTIAL_OPEN_SCOPED"


def initial_level_states() -> dict[str, str]:
    levels = load_json(PACKS_PATH)["levels"]
    return {level: item["result"] for level, item in levels.items()}


def run_golden_pack(pack: dict[str, Any]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for scenario in pack["scenarios"]:
        status = "PASS"
        observed: object
        try:
            kind = scenario["kind"]
            if kind == "fixture_status":
                observed = classify_fixture_status(scenario["status"])
            elif kind == "absence_partition":
                observed = reconcile_absences(
                    scenario["records"], pages_complete=scenario["pages_complete"]
                )
            elif kind == "rate":
                observed = make_rate(
                    scenario.get("numerator"),
                    scenario.get("denominator"),
                    grain=scenario["grain"],
                    complete_scope=scenario.get("complete_scope", False),
                )
            elif kind == "ignored_block":
                observed = "IGNORED_NO_DENOMINATOR_EFFECT"
            else:
                raise DenominatorError("GOLDEN_SCENARIO_KIND_UNKNOWN")
            expected = scenario["expected"]
            if isinstance(expected, dict):
                for key, value in expected.items():
                    if not isinstance(observed, dict) or observed.get(key) != value:
                        status = "FAIL"
            elif observed != expected:
                status = "FAIL"
        except DenominatorError as exc:
            observed = str(exc)
            if observed != scenario["expected"]:
                status = "FAIL"
        results.append(
            {
                "scenario_id": scenario["id"],
                "status": status,
                "observed": observed,
                "expected": scenario["expected"],
            }
        )
    return results
