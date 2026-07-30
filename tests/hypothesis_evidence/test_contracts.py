from __future__ import annotations

import json

from robin.hypothesis_evidence.contracts import (
    AUTHORITATIVE_HISTORICAL_REVISION,
    BYTE_IDENTICAL_REPLICA_REVISIONS,
    HISTORICAL_PARQUET_TREE,
    TOP_RULE_IDS,
    canonical_json,
    canonical_sha256,
    hypothesis_id,
    schema_contract,
)

EXPECTED_TABLES = {
    "historical_fixture_evidence": {
        "grain": "one frozen historical market source record per fixture",
        "primary_key": ["source_dataset_hash", "canonical_match_id"],
        "required_fields": {
            "canonical_match_id",
            "provider_fixture_id",
            "competition_key",
            "competition_name",
            "season",
            "round",
            "kickoff_at",
            "home_team_id",
            "home_team_name",
            "away_team_id",
            "away_team_name",
            "home_goals",
            "away_goals",
            "final_status",
            "source_dataset_hash",
            "source_row_hash",
        },
    },
    "hypothesis_fixture_membership": {
        "grain": "one strict eligible settled fixture per J10 rule",
        "primary_key": ["dataset_hash", "rule_hash", "canonical_match_id"],
        "required_fields": {
            "hypothesis_id",
            "hypothesis_version",
            "rule_hash",
            "canonical_match_id",
            "market",
            "selection",
            "price_class",
            "observed_odds",
            "market_margin",
            "stake_units",
            "won",
            "lost",
            "void",
            "profit_units",
            "cumulative_profit_units",
            "chronological_fold",
            "statistical_group",
            "eligibility_reason",
            "membership_hash",
        },
    },
    "hypothesis_historical_evidence_summary": {
        "grain": "one aggregate historical evidence record per J10 rule",
        "primary_key": ["dataset_hash", "rule_hash"],
        "required_fields": {
            "occurrences",
            "settled_occurrences",
            "wins",
            "losses",
            "voids",
            "hit_rate",
            "average_odds",
            "median_odds",
            "total_staked_units",
            "gross_returns_units",
            "profit_units",
            "roi",
            "maximum_drawdown_units",
            "longest_losing_streak",
            "confidence_interval",
            "positive_folds",
            "eligible_folds",
            "distinct_seasons",
            "distinct_teams",
            "statistical_groups",
            "p_value",
            "q_value",
        },
    },
}


def test_schema_contract_exposes_the_three_normalized_public_models() -> None:
    contract = schema_contract()
    tables = contract["tables"]
    assert isinstance(tables, dict)
    assert set(tables) == set(EXPECTED_TABLES)

    for table_name, expected in EXPECTED_TABLES.items():
        table = tables[table_name]
        assert isinstance(table, dict)
        assert table["grain"] == expected["grain"]
        assert table["primary_key"] == expected["primary_key"]
        fields = table["fields"]
        assert isinstance(fields, list)
        field_names: set[str] = {
            str(field["name"])
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("name"), str)
        }
        assert set(expected["required_fields"]) <= field_names
        assert len(field_names) == len(fields)


def test_historical_source_pin_and_byte_identical_replicas_are_explicit() -> None:
    assert AUTHORITATIVE_HISTORICAL_REVISION == (
        "5c85cf20b932df44dca8665de00e52e3f1e02236"
    )
    assert BYTE_IDENTICAL_REPLICA_REVISIONS == (
        "518cb4b708b214f550e38c519d1226a0d34f1e38",
        "4678a30a72bc1cbe138508c4f5881275d97e9b47",
    )
    assert HISTORICAL_PARQUET_TREE == (
        "986010a776cb7c0f4948098660febea9577f159e"
    )


def test_hypothesis_ids_preserve_the_public_top_three_and_stable_fallback() -> None:
    expected = {
        "293f3a6d5e635389abc272e8b6579b5e95df58836cd2e1355737df96c52f4867": (
            "J10-M001"
        ),
        "a82c917853baf22ec85eea189eb2efde72022b0271e1e0eadffb2f851d0623a2": (
            "J10-M002"
        ),
        "561b8a16908ab9bb8cb477c77af343779d20485d959b40ea7ed2a2e60535ec20": (
            "J10-M003"
        ),
    }
    assert TOP_RULE_IDS == expected
    assert {hypothesis_id(rule_hash) for rule_hash in expected} == {
        "J10-M001",
        "J10-M002",
        "J10-M003",
    }
    assert hypothesis_id("0123456789abcdef" + "f" * 48) == (
        "J10-0123456789ABCDEF"
    )


def test_schema_contract_serialization_is_canonical_and_deterministic() -> None:
    first = schema_contract()
    second = json.loads(json.dumps(first))
    assert first is not second
    assert canonical_json(first) == canonical_json(second)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert canonical_sha256(first) == (
        "e203c7fd87ba0a72f1e51383ef06749961c0b66a75852c5f7d926184fde45ca2"
    )
    assert canonical_json({"z": 1, "a": 2}) == '{"a":2,"z":1}'
