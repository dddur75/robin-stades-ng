from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from robin.prospective_observatory.chronos import (
    BOOKMAKER_ALLOWLIST,
    CANONICAL_TAG_IDS_HASH,
    CANONICAL_TAG_REGISTRY_HASH,
    PRICE_CONTRACT_HASH,
    ChronosMarket,
    ChronosSelection,
    KnownAtFact,
    LineageIndex,
    LineageNode,
    LineageNodeKind,
    ScientificRole,
    TagState,
    TemporalClass,
    aggregate_market_snapshot,
    build_known_at_fact,
    build_lineage_edge,
    build_price_observation,
    derive_complete_book_markets,
    freeze_tag_snapshot,
    power_floor,
    strict_fact_view,
    temporal_classification,
)
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureFamily,
    CaptureReceipt,
    canonical_sha256,
    receipt_scope_sha256,
)

NOW = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)
HASH = "a" * 64
CONTRACT_HASH = "b" * 64
TAG_REGISTRY = json.loads(
    Path("configs/hypothesis-tags/canonical-tag-registry-v2.json").read_text(
        encoding="utf-8"
    )
)
TAG_IDS = tuple(sorted(tag["tag_id"] for tag in TAG_REGISTRY["tags"]))


def _receipt(
    *,
    response_received_at: datetime = NOW,
    cutoff_at: datetime = NOW + timedelta(hours=1),
    kickoff_at: datetime = NOW + timedelta(hours=2),
) -> CaptureReceipt:
    window_id = "prospective-window-v3:test"
    scope = receipt_scope_sha256(
        window_id=window_id,
        window_label="NEAR_KICKOFF",
    )
    return CaptureReceipt(
        window_id=window_id,
        window_label="NEAR_KICKOFF",
        fixture_id="fixture-1",
        competition="Ligue 1",
        season="2026",
        provider="the-odds-api",
        family=CaptureFamily.ODDS,
        requested_at=response_received_at - timedelta(seconds=1),
        response_received_at=response_received_at,
        observed_at=response_received_at,
        kickoff_at=kickoff_at,
        cutoff_at=cutoff_at,
        seconds_before_kickoff=int(
            (kickoff_at - response_received_at).total_seconds()
        ),
        http_status=200,
        payload_sha256=HASH,
        payload_bytes=123,
        stored_bytes=90,
        r2_key=f"prospective-deep-data/schema-v1/payload-{HASH}.json.gz",
        receipt_r2_key=(
            "prospective-deep-data/schema-v1/"
            f"receipt-{scope}-{HASH}.json"
        ),
        source_endpoint="/sports/soccer_france_ligue_one/odds",
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=1,
        code_revision="test-revision",
        materialized_at=response_received_at + timedelta(seconds=1),
    )


@pytest.mark.parametrize(
    ("known_at", "expected"),
    [
        (NOW, TemporalClass.ON_TIME),
        (NOW + timedelta(hours=1), TemporalClass.ON_TIME),
        (NOW + timedelta(hours=1, microseconds=1), TemporalClass.LATE_FOR_CUTOFF),
        (NOW + timedelta(hours=2), TemporalClass.POST_KICKOFF_ONLY),
        (None, TemporalClass.KNOWN_AT_UNKNOWN),
    ],
)
def test_temporal_classification_is_inclusive_at_cutoff(
    known_at: datetime | None,
    expected: TemporalClass,
) -> None:
    assert temporal_classification(
        known_at=known_at,
        cutoff_at=NOW + timedelta(hours=1),
        kickoff_at=NOW + timedelta(hours=2),
    ) is expected


def test_known_at_fact_never_uses_provider_timestamp_to_backdate() -> None:
    fact = build_known_at_fact(
        receipt=_receipt(),
        entity_id="bookmaker:betclic_fr",
        normalized_value={"available": True},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    assert fact.known_at == NOW
    assert fact.temporal_class is TemporalClass.ON_TIME
    assert strict_fact_view((fact,)) == (fact,)


def test_restrictive_evidence_can_only_delay_known_at() -> None:
    with pytest.raises(ValueError, match="CHRONOS_RESTRICTIVE_PROOF_BACKDATED"):
        build_known_at_fact(
            receipt=_receipt(),
            entity_id="entity",
            normalized_value={"value": 1},
            cutoff_id="NEAR_KICKOFF",
            request_contract_hash=CONTRACT_HASH,
            scientific_role=ScientificRole.STRICT_KNOWN_AT,
            normalizer_version="test-v1",
            code_revision="test-revision",
            restrictive_available_at=NOW - timedelta(seconds=1),
        )


def test_known_at_unknown_rejects_partial_timestamp_evidence() -> None:
    fact = build_known_at_fact(
        receipt=_receipt(),
        entity_id="entity",
        normalized_value={"value": 1},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    values = fact.model_dump()
    values.update(
        {
            "requested_at": None,
            "known_at": None,
            "temporal_class": "KNOWN_AT_UNKNOWN",
        }
    )
    with pytest.raises(ValueError, match="CHRONOS_UNKNOWN_TIMESTAMPS_MUST_BE_NULL"):
        KnownAtFact.model_validate(values)


def test_fact_supersession_rejects_cross_fixture_predecessor() -> None:
    predecessor = build_known_at_fact(
        receipt=_receipt(),
        entity_id="entity",
        normalized_value={"value": 1},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    successor_receipt = _receipt().model_copy(update={"fixture_id": "fixture-2"})
    with pytest.raises(ValueError, match="CHRONOS_FACT_SUPERSESSION_SCOPE_MISMATCH"):
        build_known_at_fact(
            receipt=successor_receipt,
            entity_id="entity",
            normalized_value={"value": 2},
            cutoff_id="NEAR_KICKOFF",
            request_contract_hash=CONTRACT_HASH,
            scientific_role=ScientificRole.STRICT_KNOWN_AT,
            normalizer_version="test-v1",
            code_revision="test-revision",
            supersedes_fact=predecessor,
        )


def test_future_provider_timestamp_excludes_fact_from_strict_view() -> None:
    receipt = _receipt().model_copy(
        update={"provider_updated_at": NOW + timedelta(seconds=1)}
    )
    fact = build_known_at_fact(
        receipt=receipt,
        entity_id="entity",
        normalized_value={"value": 1},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    assert fact.quality_status.value == "PROVIDER_TIMESTAMP_INCONSISTENT"
    assert strict_fact_view((fact,)) == ()


def _price_observations(bookmakers: tuple[str, ...]) -> tuple[object, ...]:
    observations = []
    for bookmaker in bookmakers:
        for selection, odds in (
            (ChronosSelection.HOME, Decimal("2.10")),
            (ChronosSelection.DRAW, Decimal("3.40")),
            (ChronosSelection.AWAY, Decimal("3.70")),
        ):
            observations.append(
                build_price_observation(
                    receipt=_receipt(),
                    bookmaker=bookmaker,
                    market=ChronosMarket.MATCH_RESULT_90M,
                    selection=selection,
                    line=None,
                    odds_decimal=odds,
                    cutoff_id="NEAR_KICKOFF",
                    request_contract_hash=CONTRACT_HASH,
                    price_contract_hash=PRICE_CONTRACT_HASH,
                    code_revision="test-revision",
                    provider_updated_at=NOW - timedelta(seconds=30),
                    max_age_seconds=600,
                )
            )
    return tuple(observations)


def test_complete_market_devig_and_five_book_consensus() -> None:
    derivations = derive_complete_book_markets(_price_observations(BOOKMAKER_ALLOWLIST))
    assert len(derivations) == 15
    for bookmaker in BOOKMAKER_ALLOWLIST:
        total = sum(
            (
                row.devigged_probability
                for row in derivations
                if row.bookmaker == bookmaker
            ),
            Decimal(0),
        )
        assert total == Decimal(1)
    snapshot = aggregate_market_snapshot(derivations)
    assert snapshot.confirmatory_admissible is True
    assert sum(snapshot.selection_probabilities.values(), Decimal(0)) == Decimal(1)


def test_incomplete_market_is_no_price_not_an_estimate() -> None:
    observations = _price_observations((BOOKMAKER_ALLOWLIST[0],))[:-1]
    assert derive_complete_book_markets(observations) == ()


def test_price_timestamp_and_freshness_fail_closed() -> None:
    missing = build_price_observation(
        receipt=_receipt(),
        bookmaker=BOOKMAKER_ALLOWLIST[0],
        market=ChronosMarket.MATCH_RESULT_90M,
        selection=ChronosSelection.HOME,
        line=None,
        odds_decimal=Decimal("2.1"),
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        price_contract_hash=PRICE_CONTRACT_HASH,
        code_revision="test-revision",
    )
    stale = build_price_observation(
        receipt=_receipt(),
        bookmaker=BOOKMAKER_ALLOWLIST[0],
        market=ChronosMarket.MATCH_RESULT_90M,
        selection=ChronosSelection.HOME,
        line=None,
        odds_decimal=Decimal("2.1"),
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        price_contract_hash=PRICE_CONTRACT_HASH,
        code_revision="test-revision",
        provider_updated_at=NOW - timedelta(seconds=601),
        max_age_seconds=600,
    )
    future = build_price_observation(
        receipt=_receipt(),
        bookmaker=BOOKMAKER_ALLOWLIST[0],
        market=ChronosMarket.MATCH_RESULT_90M,
        selection=ChronosSelection.HOME,
        line=None,
        odds_decimal=Decimal("2.1"),
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        price_contract_hash=PRICE_CONTRACT_HASH,
        code_revision="test-revision",
        provider_updated_at=NOW + timedelta(seconds=1),
        max_age_seconds=600,
    )
    assert missing.quality_status.value == "NO_PRICE"
    assert stale.quality_status.value == "NO_PRICE"
    assert future.quality_status.value == "PROVIDER_TIMESTAMP_INCONSISTENT"
    assert missing.receipt_hash == _receipt().receipt_hash


def test_price_observation_requires_exact_frozen_contract() -> None:
    with pytest.raises(ValueError, match="CHRONOS_PRICE_CONTRACT_MISMATCH"):
        build_price_observation(
            receipt=_receipt(),
            bookmaker=BOOKMAKER_ALLOWLIST[0],
            market=ChronosMarket.MATCH_RESULT_90M,
            selection=ChronosSelection.HOME,
            line=None,
            odds_decimal=Decimal("2.1"),
            cutoff_id="NEAR_KICKOFF",
            request_contract_hash=CONTRACT_HASH,
            price_contract_hash="c" * 64,
            code_revision="test-revision",
            provider_updated_at=NOW - timedelta(seconds=30),
            max_age_seconds=600,
        )


def test_market_overround_outside_bound_is_not_derived() -> None:
    observations = tuple(
        build_price_observation(
            receipt=_receipt(),
            bookmaker=BOOKMAKER_ALLOWLIST[0],
            market=ChronosMarket.MATCH_RESULT_90M,
            selection=selection,
            line=None,
            odds_decimal=Decimal("1.50"),
            cutoff_id="NEAR_KICKOFF",
            request_contract_hash=CONTRACT_HASH,
            price_contract_hash=PRICE_CONTRACT_HASH,
            code_revision="test-revision",
            provider_updated_at=NOW - timedelta(seconds=30),
            max_age_seconds=600,
        )
        for selection in (
            ChronosSelection.HOME,
            ChronosSelection.DRAW,
            ChronosSelection.AWAY,
        )
    )
    assert derive_complete_book_markets(observations) == ()


def test_total_line_must_be_exactly_two_point_five() -> None:
    with pytest.raises(ValueError, match="CHRONOS_TOTAL_2_5_SELECTION_INVALID"):
        build_price_observation(
            receipt=_receipt(),
            bookmaker=BOOKMAKER_ALLOWLIST[0],
            market=ChronosMarket.TOTAL_GOALS_2_5_90M,
            selection=ChronosSelection.OVER_2_5,
            line=Decimal("3.5"),
            odds_decimal=Decimal("1.9"),
            cutoff_id="H2",
            request_contract_hash=CONTRACT_HASH,
            price_contract_hash=PRICE_CONTRACT_HASH,
            code_revision="test-revision",
        )


def test_late_fact_cannot_enter_tag_snapshot() -> None:
    on_time = build_known_at_fact(
        receipt=_receipt(),
        entity_id="entity:on-time",
        normalized_value={"value": 1},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    late = build_known_at_fact(
        receipt=_receipt(
            response_received_at=NOW + timedelta(hours=1, minutes=1),
        ),
        entity_id="entity:late",
        normalized_value={"value": 2},
        cutoff_id="NEAR_KICKOFF",
        request_contract_hash=CONTRACT_HASH,
        scientific_role=ScientificRole.STRICT_KNOWN_AT,
        normalizer_version="test-v1",
        code_revision="test-revision",
    )
    snapshot = freeze_tag_snapshot(
        fixture_id="fixture-1",
        cutoff_id="NEAR_KICKOFF",
        cutoff_at=NOW + timedelta(hours=1),
        kickoff_at=NOW + timedelta(hours=2),
        tag_registry_hash=CANONICAL_TAG_REGISTRY_HASH,
        facts=(late, on_time),
        tag_states={
            tag_id: (TagState.TRUE if tag_id == TAG_IDS[0] else TagState.UNKNOWN)
            for tag_id in TAG_IDS
        },
        tag_fact_ids={
            tag_id: ((on_time.fact_id,) if tag_id == TAG_IDS[0] else ())
            for tag_id in TAG_IDS
        },
        expected_tag_ids=TAG_IDS,
    )
    assert snapshot.facts_used == (on_time.fact_id,)
    assert (snapshot.true_count, snapshot.false_count, snapshot.unknown_count) == (
        1,
        0,
        149,
    )


def test_tag_snapshot_rejects_arbitrary_150_id_registry() -> None:
    arbitrary = tuple(f"arbitrary-{index:03d}" for index in range(150))
    with pytest.raises(ValueError, match="CHRONOS_TAG_REGISTRY_NOT_CANONICAL"):
        freeze_tag_snapshot(
            fixture_id="fixture-1",
            cutoff_id="NEAR_KICKOFF",
            cutoff_at=NOW + timedelta(hours=1),
            kickoff_at=NOW + timedelta(hours=2),
            tag_registry_hash="c" * 64,
            facts=(),
            tag_states={tag_id: TagState.UNKNOWN for tag_id in arbitrary},
            tag_fact_ids={tag_id: () for tag_id in arbitrary},
            expected_tag_ids=arbitrary,
        )


def test_lineage_is_append_only_and_bidirectional() -> None:
    edge = build_lineage_edge(
        upstream_kind=LineageNodeKind.RAW_OBJECT,
        upstream_id="raw-1",
        upstream_hash=HASH,
        downstream_kind=LineageNodeKind.KNOWN_AT_FACT,
        downstream_id="fact-1",
        downstream_hash=CONTRACT_HASH,
        relation="DERIVED_FROM",
        contract_hash=HASH,
        code_revision="test-revision",
    )
    index = LineageIndex()
    index.add_node(
        LineageNode(
            node_id=edge.upstream_id,
            node_kind=edge.upstream_kind,
            content_hash=edge.upstream_hash,
        )
    )
    index.add_node(
        LineageNode(
            node_id=edge.downstream_id,
            node_kind=edge.downstream_kind,
            content_hash=edge.downstream_hash,
        )
    )
    assert index.append(edge) is True
    assert index.append(edge) is False
    assert index.downstream("raw-1") == (edge,)
    assert index.upstream("fact-1") == (edge,)


def test_lineage_rejects_multi_hop_cycle() -> None:
    index = LineageIndex()
    for upstream, downstream in (("a", "b"), ("b", "c")):
        edge = build_lineage_edge(
            upstream_kind=LineageNodeKind.NORMALIZED_FACT,
            upstream_id=upstream,
            upstream_hash=HASH,
            downstream_kind=LineageNodeKind.NORMALIZED_FACT,
            downstream_id=downstream,
            downstream_hash=HASH,
            relation="DERIVED_FROM",
            contract_hash=HASH,
            code_revision="test-revision",
        )
        index.add_node(
            LineageNode(
                node_id=edge.upstream_id,
                node_kind=edge.upstream_kind,
                content_hash=edge.upstream_hash,
            )
        )
        index.add_node(
            LineageNode(
                node_id=edge.downstream_id,
                node_kind=edge.downstream_kind,
                content_hash=edge.downstream_hash,
            )
        )
        index.append(edge)
    with pytest.raises(ValueError, match="CHRONOS_LINEAGE_CYCLE"):
        index.append(
            build_lineage_edge(
                upstream_kind=LineageNodeKind.NORMALIZED_FACT,
                upstream_id="c",
                upstream_hash=HASH,
                downstream_kind=LineageNodeKind.NORMALIZED_FACT,
                downstream_id="a",
                downstream_hash=HASH,
                relation="DERIVED_FROM",
                contract_hash=HASH,
                code_revision="test-revision",
            )
        )


def test_lineage_rejects_edge_with_unregistered_node() -> None:
    edge = build_lineage_edge(
        upstream_kind=LineageNodeKind.RAW_OBJECT,
        upstream_id="raw-missing",
        upstream_hash=HASH,
        downstream_kind=LineageNodeKind.KNOWN_AT_FACT,
        downstream_id="fact-missing",
        downstream_hash=CONTRACT_HASH,
        relation="DERIVED_FROM",
        contract_hash=HASH,
        code_revision="test-revision",
    )
    with pytest.raises(ValueError, match="CHRONOS_LINEAGE_NODE_MISSING_OR_MISMATCH"):
        LineageIndex().append(edge)


def test_v3_power_floor_is_frozen_and_not_thirty() -> None:
    assert power_floor(standardized_effect=Decimal("0.20")) == 675
    assert power_floor(standardized_effect=Decimal("0.10"), power="0.90") == 3176
    assert canonical_sha256({"tests": 7480}) != HASH


def test_foundation_artifacts_are_utf8_json_and_hash_bound() -> None:
    paths = (
        Path("configs/hypothesis-campaigns/market-residual-campaign-v3-draft.json"),
        Path("configs/hypothesis-tags/point-in-time-tag-snapshot-contract-v1.json"),
        Path("configs/lineage/chronos-lineage-contract-v1.json"),
        Path("configs/prices/point-in-time-price-contract-v1.json"),
        Path("configs/temporal/known-at-fact-contract-v1.json"),
        Path("docs/hypothesis-intelligence/MARKET-RESIDUAL-CAMPAIGN-V3-DRAFT.md"),
        Path("docs/prices/POINT-IN-TIME-PRICE-CONTRACT-V1.md"),
        Path("docs/temporal/KNOWN-AT-FACT-CONTRACT-V1.md"),
        Path("reports/data-quality/blocked-property-gap-analysis-v1.json"),
        Path("reports/data-sources/known-at-and-price-source-capability-matrix-v1.json"),
        Path("reports/prices/historical-price-source-audit-v1.json"),
    )
    payloads: dict[Path, object] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="strict")
        assert text
        if path.suffix == ".json":
            payloads[path] = json.loads(text)

    price_path = Path("configs/prices/point-in-time-price-contract-v1.json")
    tag_path = Path(
        "configs/hypothesis-tags/point-in-time-tag-snapshot-contract-v1.json"
    )
    tag_contract = payloads[tag_path]
    assert isinstance(tag_contract, dict)
    assert canonical_sha256(payloads[price_path]) == PRICE_CONTRACT_HASH
    assert TAG_REGISTRY["registry_hash"] == CANONICAL_TAG_REGISTRY_HASH
    assert canonical_sha256(TAG_REGISTRY["tags"]) == CANONICAL_TAG_REGISTRY_HASH
    assert canonical_sha256(TAG_IDS) == CANONICAL_TAG_IDS_HASH
    assert tag_contract["tag_registry_hash"] == CANONICAL_TAG_REGISTRY_HASH
    assert tag_contract["tag_count"] == len(TAG_IDS) == 150
