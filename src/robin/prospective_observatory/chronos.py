"""Robin Chronos V1 point-in-time contracts and deterministic derivations.

This module is deliberately provider-free.  It turns already captured receipts
into immutable facts, price observations, tag snapshots and lineage records.
Provider access remains in the existing prospective observatory.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal, getcontext
from enum import StrEnum
from statistics import median
from typing import Literal, Self, cast

from pydantic import Field, model_validator

from robin.prospective_observatory.contracts import (
    CaptureFamily,
    CaptureReceipt,
    FrozenContract,
    canonical_sha256,
    ensure_utc,
)

CHRONOS_SCHEMA_VERSION = "robin-chronos-v1"
PRICE_CONTRACT_VERSION = "point-in-time-price-contract-v1"
TAG_SNAPSHOT_VERSION = "point-in-time-tag-snapshot-v1"
CANONICAL_TAG_COUNT = 150
MAX_MARKET_OVERROUND = Decimal("0.06")
PROPORTIONAL_METHOD_ID = "PROPORTIONAL_COMPLETE_MARKET_V1"
PROPORTIONAL_METHOD_VERSION = "1.0.0"
REGION_ALLOWLIST = ("fr",)
BOOKMAKER_ALLOWLIST = (
    "betclic_fr",
    "netbet_fr",
    "pmu_fr",
    "unibet_fr",
    "winamax_fr",
)


class TemporalClass(StrEnum):
    """Classification relative to one exact scientific cutoff."""

    ON_TIME = "ON_TIME"
    LATE_FOR_CUTOFF = "LATE_FOR_CUTOFF"
    POST_KICKOFF_ONLY = "POST_KICKOFF_ONLY"
    KNOWN_AT_UNKNOWN = "KNOWN_AT_UNKNOWN"


class ScientificRole(StrEnum):
    STRICT_KNOWN_AT = "STRICT_KNOWN_AT"
    KNOWN_AT_WITH_LIMITATION = "KNOWN_AT_WITH_LIMITATION"
    RECONSTRUCTED_POST_MATCH = "RECONSTRUCTED_POST_MATCH"
    TARGET_ONLY = "TARGET_ONLY"
    IDENTITY_ONLY = "IDENTITY_ONLY"
    QUALITY_ONLY = "QUALITY_ONLY"
    UNKNOWN = "UNKNOWN"


class QualityStatus(StrEnum):
    VALID = "VALID"
    BOUNDED_NEGATIVE_EVIDENCE = "BOUNDED_NEGATIVE_EVIDENCE"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    IDENTITY_FAILED = "IDENTITY_FAILED"
    PROVIDER_TIMESTAMP_INCONSISTENT = "PROVIDER_TIMESTAMP_INCONSISTENT"
    CLOCK_SKEW_EXCEEDED = "CLOCK_SKEW_EXCEEDED"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NO_PRICE = "NO_PRICE"


class ChronosMarket(StrEnum):
    MATCH_RESULT_90M = "MATCH_RESULT_90M"
    TOTAL_GOALS_2_5_90M = "TOTAL_GOALS_2_5_90M"


class ChronosSelection(StrEnum):
    HOME = "HOME"
    DRAW = "DRAW"
    AWAY = "AWAY"
    OVER_2_5 = "OVER_2_5"
    UNDER_2_5 = "UNDER_2_5"


class TagState(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


def temporal_classification(
    *,
    known_at: datetime | None,
    cutoff_at: datetime,
    kickoff_at: datetime,
) -> TemporalClass:
    """Classify with the mission's inclusive known-at scientific cutoff.

    Capture-window membership remains half-open in the legacy scheduler.  This
    function answers the separate scientific question: was the fact known by
    the exact decision cutoff?  Equality is therefore admissible.
    """

    cutoff = ensure_utc(cutoff_at, field="cutoff_at")
    kickoff = ensure_utc(kickoff_at, field="kickoff_at")
    if cutoff >= kickoff:
        raise ValueError("CHRONOS_CUTOFF_MUST_PRECEDE_KICKOFF")
    if known_at is None:
        return TemporalClass.KNOWN_AT_UNKNOWN
    known = ensure_utc(known_at, field="known_at")
    if known >= kickoff:
        return TemporalClass.POST_KICKOFF_ONLY
    if known > cutoff:
        return TemporalClass.LATE_FOR_CUTOFF
    return TemporalClass.ON_TIME


class KnownAtFact(FrozenContract):
    schema_version: Literal["known-at-fact-v1"] = "known-at-fact-v1"
    fact_id: str = Field(pattern=r"^known-at-fact:[0-9a-f]{64}$")
    normalized_fact_id: str = Field(pattern=r"^normalized-fact:[0-9a-f]{64}$")
    fixture_id: str = Field(min_length=1, max_length=120)
    entity_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=120)
    family: CaptureFamily
    source_object_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    requested_at: datetime | None
    response_received_at: datetime | None
    provider_updated_at: datetime | None
    effective_at: datetime | None
    known_at: datetime | None
    known_at_basis: str = Field(min_length=1, max_length=80)
    cutoff_id: str = Field(min_length=1, max_length=250)
    cutoff_at: datetime
    kickoff_at: datetime
    temporal_class: TemporalClass
    scientific_role: ScientificRole
    quality_status: QualityStatus
    value_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalizer_version: str = Field(min_length=1, max_length=80)
    code_revision: str = Field(min_length=1, max_length=80)
    supersedes_fact_id: str | None = Field(
        default=None,
        pattern=r"^known-at-fact:[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_temporality(self) -> Self:
        for name in (
            "requested_at",
            "response_received_at",
            "provider_updated_at",
            "effective_at",
            "known_at",
        ):
            value = getattr(self, name)
            if value is not None:
                ensure_utc(value, field=name)
        if (
            self.requested_at is not None
            and self.response_received_at is not None
            and self.requested_at > self.response_received_at
        ):
            raise ValueError("CHRONOS_REQUEST_AFTER_RESPONSE")
        if (
            self.response_received_at is not None
            and self.known_at is not None
            and self.known_at < self.response_received_at
        ):
            raise ValueError("CHRONOS_KNOWN_AT_BACKDATED")
        if (
            self.provider_updated_at is not None
            and self.known_at is not None
            and self.provider_updated_at > self.known_at
            and self.quality_status
            is not QualityStatus.PROVIDER_TIMESTAMP_INCONSISTENT
        ):
            raise ValueError("CHRONOS_PROVIDER_TIMESTAMP_NOT_FAIL_CLOSED")
        if self.supersedes_fact_id == self.fact_id:
            raise ValueError("CHRONOS_FACT_SELF_SUPERSESSION")
        expected = temporal_classification(
            known_at=self.known_at,
            cutoff_at=self.cutoff_at,
            kickoff_at=self.kickoff_at,
        )
        if self.temporal_class is not expected:
            raise ValueError("CHRONOS_TEMPORAL_CLASS_MISMATCH")
        return self


def build_known_at_fact(
    *,
    receipt: CaptureReceipt,
    entity_id: str,
    normalized_value: Mapping[str, object],
    cutoff_id: str,
    request_contract_hash: str,
    scientific_role: ScientificRole,
    normalizer_version: str,
    code_revision: str,
    restrictive_available_at: datetime | None = None,
    effective_at: datetime | None = None,
    quality_status: QualityStatus = QualityStatus.VALID,
    supersedes_fact_id: str | None = None,
) -> KnownAtFact:
    """Build a fact without accepting a caller-provided ``known_at`` value."""

    response = ensure_utc(
        receipt.response_received_at,
        field="response_received_at",
    )
    known = response
    basis = "RESPONSE_RECEIVED_AT"
    if restrictive_available_at is not None:
        restrictive = ensure_utc(
            restrictive_available_at,
            field="restrictive_available_at",
        )
        if restrictive < response:
            raise ValueError("CHRONOS_RESTRICTIVE_PROOF_BACKDATED")
        known = restrictive
        basis = "RESTRICTIVE_AVAILABLE_AT"
    normalized_hash = canonical_sha256(normalized_value)
    normalized_fact_id = "normalized-fact:" + canonical_sha256(
        {
            "source_object_hash": receipt.payload_sha256,
            "normalizer_version": normalizer_version,
            "family": receipt.family.value,
            "entity_id": entity_id,
            "value_hash": normalized_hash,
        }
    )
    temporal_class = temporal_classification(
        known_at=known,
        cutoff_at=receipt.cutoff_at,
        kickoff_at=receipt.kickoff_at,
    )
    provider_updated = receipt.provider_updated_at
    if (
        provider_updated is not None
        and ensure_utc(provider_updated, field="provider_updated_at") > known
    ):
        quality_status = QualityStatus.PROVIDER_TIMESTAMP_INCONSISTENT
    identity = {
        "fixture_id": receipt.fixture_id,
        "normalized_fact_id": normalized_fact_id,
        "cutoff_id": cutoff_id,
        "source": receipt.provider,
        "family": receipt.family.value,
        "request_contract_hash": request_contract_hash,
        "known_at": known.isoformat(),
        "temporal_class": temporal_class.value,
        "scientific_role": scientific_role.value,
        "quality_status": quality_status.value,
        "supersedes_fact_id": supersedes_fact_id,
    }
    return KnownAtFact(
        fact_id="known-at-fact:" + canonical_sha256(identity),
        normalized_fact_id=normalized_fact_id,
        fixture_id=receipt.fixture_id,
        entity_id=entity_id,
        source=receipt.provider,
        family=receipt.family,
        source_object_hash=receipt.payload_sha256,
        receipt_hash=receipt.receipt_hash,
        requested_at=receipt.requested_at,
        response_received_at=response,
        provider_updated_at=receipt.provider_updated_at,
        effective_at=effective_at,
        known_at=known,
        known_at_basis=basis,
        cutoff_id=cutoff_id,
        cutoff_at=receipt.cutoff_at,
        kickoff_at=receipt.kickoff_at,
        temporal_class=temporal_class,
        scientific_role=scientific_role,
        quality_status=quality_status,
        value_hash=normalized_hash,
        request_contract_hash=request_contract_hash,
        normalizer_version=normalizer_version,
        code_revision=code_revision,
        supersedes_fact_id=supersedes_fact_id,
    )


def strict_fact_view(facts: Iterable[KnownAtFact]) -> tuple[KnownAtFact, ...]:
    return tuple(
        sorted(
            (
                fact
                for fact in facts
                if fact.temporal_class is TemporalClass.ON_TIME
                and fact.scientific_role is ScientificRole.STRICT_KNOWN_AT
                and fact.quality_status in {
                    QualityStatus.VALID,
                    QualityStatus.BOUNDED_NEGATIVE_EVIDENCE,
                }
            ),
            key=lambda fact: fact.fact_id,
        )
    )


class PriceObservation(FrozenContract):
    schema_version: Literal["point-in-time-price-observation-v1"] = (
        "point-in-time-price-observation-v1"
    )
    price_snapshot_id: str = Field(pattern=r"^price-observation:[0-9a-f]{64}$")
    fixture_id: str
    provider: Literal["the-odds-api"] = "the-odds-api"
    bookmaker: str
    region: str
    market: ChronosMarket
    selection: ChronosSelection
    line: Decimal | None
    odds_decimal: Decimal = Field(gt=Decimal("1"))
    requested_at: datetime
    response_received_at: datetime
    provider_updated_at: datetime | None
    price_age_seconds: int | None = Field(default=None, ge=0)
    known_at: datetime
    cutoff_id: str
    cutoff_at: datetime
    kickoff_at: datetime
    raw_object_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    temporal_class: TemporalClass
    quality_status: QualityStatus
    code_revision: str

    @model_validator(mode="after")
    def validate_price(self) -> Self:
        requested = ensure_utc(self.requested_at, field="requested_at")
        response = ensure_utc(
            self.response_received_at,
            field="response_received_at",
        )
        known = ensure_utc(self.known_at, field="known_at")
        if requested > response or known != response:
            raise ValueError("CHRONOS_PRICE_KNOWN_AT_INVALID")
        if self.provider_updated_at is not None:
            provider_updated = ensure_utc(
                self.provider_updated_at,
                field="provider_updated_at",
            )
            expected_age = int((known - provider_updated).total_seconds())
            if expected_age < 0:
                if (
                    self.quality_status
                    is not QualityStatus.PROVIDER_TIMESTAMP_INCONSISTENT
                    or self.price_age_seconds is not None
                ):
                    raise ValueError("CHRONOS_PRICE_PROVIDER_TIMESTAMP_INVALID")
            elif self.price_age_seconds != expected_age:
                raise ValueError("CHRONOS_PRICE_AGE_MISMATCH")
        elif (
            self.quality_status is not QualityStatus.NO_PRICE
            or self.price_age_seconds is not None
        ):
            raise ValueError("CHRONOS_PRICE_PROVIDER_TIMESTAMP_REQUIRED")
        if self.bookmaker not in BOOKMAKER_ALLOWLIST:
            raise ValueError("CHRONOS_BOOKMAKER_NOT_ALLOWED")
        if self.region not in REGION_ALLOWLIST:
            raise ValueError("CHRONOS_REGION_NOT_ALLOWED")
        if self.market is ChronosMarket.MATCH_RESULT_90M:
            if self.selection not in {
                ChronosSelection.HOME,
                ChronosSelection.DRAW,
                ChronosSelection.AWAY,
            } or self.line is not None:
                raise ValueError("CHRONOS_MATCH_RESULT_SELECTION_INVALID")
        elif self.selection not in {
            ChronosSelection.OVER_2_5,
            ChronosSelection.UNDER_2_5,
        } or self.line != Decimal("2.5"):
            raise ValueError("CHRONOS_TOTAL_2_5_SELECTION_INVALID")
        expected = temporal_classification(
            known_at=known,
            cutoff_at=self.cutoff_at,
            kickoff_at=self.kickoff_at,
        )
        if expected is not self.temporal_class:
            raise ValueError("CHRONOS_PRICE_TEMPORAL_CLASS_MISMATCH")
        return self

    @property
    def observation_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json"))


def build_price_observation(
    *,
    receipt: CaptureReceipt,
    bookmaker: str,
    market: ChronosMarket,
    selection: ChronosSelection,
    line: Decimal | None,
    odds_decimal: Decimal,
    cutoff_id: str,
    request_contract_hash: str,
    code_revision: str,
    provider_updated_at: datetime | None = None,
    max_age_seconds: int = 3600,
) -> PriceObservation:
    known = ensure_utc(
        receipt.response_received_at,
        field="response_received_at",
    )
    temporal_class = temporal_classification(
        known_at=known,
        cutoff_at=receipt.cutoff_at,
        kickoff_at=receipt.kickoff_at,
    )
    identity = {
        "fixture_id": receipt.fixture_id,
        "receipt_hash": receipt.receipt_hash,
        "bookmaker": bookmaker,
        "market": market.value,
        "selection": selection.value,
        "line": str(line) if line is not None else None,
        "odds_decimal": str(odds_decimal),
        "cutoff_id": cutoff_id,
        "request_contract_hash": request_contract_hash,
    }
    provider_updated = provider_updated_at
    price_age_seconds: int | None = None
    if provider_updated is None:
        quality_status = QualityStatus.NO_PRICE
    else:
        updated = ensure_utc(provider_updated, field="provider_updated_at")
        age = int((known - updated).total_seconds())
        if age < 0:
            quality_status = QualityStatus.PROVIDER_TIMESTAMP_INCONSISTENT
        else:
            price_age_seconds = age
            quality_status = (
                QualityStatus.VALID
                if age <= max_age_seconds
                else QualityStatus.NO_PRICE
            )
    return PriceObservation(
        price_snapshot_id="price-observation:" + canonical_sha256(identity),
        fixture_id=receipt.fixture_id,
        bookmaker=bookmaker,
        region="fr",
        market=market,
        selection=selection,
        line=line,
        odds_decimal=odds_decimal,
        requested_at=receipt.requested_at,
        response_received_at=known,
        provider_updated_at=provider_updated,
        price_age_seconds=price_age_seconds,
        known_at=known,
        cutoff_id=cutoff_id,
        cutoff_at=receipt.cutoff_at,
        kickoff_at=receipt.kickoff_at,
        raw_object_hash=receipt.payload_sha256,
        receipt_hash=receipt.receipt_hash,
        request_contract_hash=request_contract_hash,
        temporal_class=temporal_class,
        quality_status=quality_status,
        code_revision=code_revision,
    )


class PriceDerivation(FrozenContract):
    derivation_id: str = Field(pattern=r"^price-derivation:[0-9a-f]{64}$")
    fixture_id: str
    cutoff_id: str
    bookmaker: str
    market: ChronosMarket
    selection: ChronosSelection
    line: Decimal | None
    source_price_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_id: Literal["PROPORTIONAL_COMPLETE_MARKET_V1"] = (
        "PROPORTIONAL_COMPLETE_MARKET_V1"
    )
    method_version: Literal["1.0.0"] = "1.0.0"
    definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    implied_probability: Decimal
    market_overround: Decimal
    devigged_probability: Decimal
    price_age_seconds: int = Field(ge=0)


def _required_selections(market: ChronosMarket) -> tuple[ChronosSelection, ...]:
    if market is ChronosMarket.MATCH_RESULT_90M:
        return (
            ChronosSelection.HOME,
            ChronosSelection.DRAW,
            ChronosSelection.AWAY,
        )
    return (ChronosSelection.OVER_2_5, ChronosSelection.UNDER_2_5)


def derive_complete_book_markets(
    observations: Iterable[PriceObservation],
) -> tuple[PriceDerivation, ...]:
    """Devig complete same-receipt markets; incomplete markets remain NO_PRICE."""

    getcontext().prec = 28
    grouped: dict[
        tuple[str, str, ChronosMarket, Decimal | None, str],
        dict[ChronosSelection, PriceObservation],
    ] = defaultdict(dict)
    for observation in observations:
        if (
            observation.temporal_class is not TemporalClass.ON_TIME
            or observation.quality_status is not QualityStatus.VALID
        ):
            continue
        key = (
            observation.fixture_id,
            observation.bookmaker,
            observation.market,
            observation.line,
            observation.receipt_hash,
        )
        existing = grouped[key].get(observation.selection)
        if existing is None or observation.observation_hash < existing.observation_hash:
            grouped[key][observation.selection] = observation
    result: list[PriceDerivation] = []
    definition_hash = canonical_sha256(
        {
            "method_id": PROPORTIONAL_METHOD_ID,
            "version": PROPORTIONAL_METHOD_VERSION,
            "formula": "p_s=(1/odds_s)/sum(1/odds)",
        }
    )
    for key, selection_map in sorted(grouped.items(), key=lambda item: str(item[0])):
        fixture_id, bookmaker, market, line, _ = key
        required = _required_selections(market)
        if set(selection_map) != set(required):
            continue
        ordered = tuple(selection_map[selection] for selection in required)
        source_hash = canonical_sha256(
            [observation.observation_hash for observation in ordered]
        )
        implied = tuple(Decimal(1) / observation.odds_decimal for observation in ordered)
        total = sum(implied, Decimal(0))
        overround = total - Decimal(1)
        if overround <= Decimal(0) or overround > MAX_MARKET_OVERROUND:
            continue
        for observation, unscaled in zip(ordered, implied, strict=True):
            devigged = unscaled / total
            identity = {
                "source_price_set_hash": source_hash,
                "selection": observation.selection.value,
                "definition_hash": definition_hash,
            }
            result.append(
                PriceDerivation(
                    derivation_id="price-derivation:" + canonical_sha256(identity),
                    fixture_id=fixture_id,
                    cutoff_id=observation.cutoff_id,
                    bookmaker=bookmaker,
                    market=market,
                    selection=observation.selection,
                    line=line,
                    source_price_set_hash=source_hash,
                    definition_hash=definition_hash,
                    implied_probability=unscaled,
                    market_overround=overround,
                    devigged_probability=devigged,
                    price_age_seconds=cast(int, observation.price_age_seconds),
                )
            )
    return tuple(result)


class AggregatedMarketSnapshot(FrozenContract):
    snapshot_id: str = Field(pattern=r"^market-snapshot:[0-9a-f]{64}$")
    fixture_id: str
    cutoff_id: str
    market: ChronosMarket
    line: Decimal | None
    bookmakers: tuple[str, ...]
    selection_probabilities: dict[ChronosSelection, Decimal]
    input_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmatory_admissible: bool
    quality_status: QualityStatus


def aggregate_market_snapshot(
    derivations: Iterable[PriceDerivation],
) -> AggregatedMarketSnapshot:
    rows = tuple(derivations)
    if not rows:
        raise ValueError("CHRONOS_NO_COMPLETE_MARKET")
    identity_keys = {(row.fixture_id, row.cutoff_id, row.market, row.line) for row in rows}
    if len(identity_keys) != 1:
        raise ValueError("CHRONOS_MARKET_AGGREGATION_SCOPE_MIXED")
    fixture_id, cutoff_id, market, line = identity_keys.pop()
    by_selection: dict[ChronosSelection, list[Decimal]] = defaultdict(list)
    by_bookmaker: dict[str, set[ChronosSelection]] = defaultdict(set)
    for row in rows:
        by_selection[row.selection].append(row.devigged_probability)
        by_bookmaker[row.bookmaker].add(row.selection)
    required = set(_required_selections(market))
    complete_books = tuple(
        sorted(book for book, selections in by_bookmaker.items() if selections == required)
    )
    if not complete_books or set(by_selection) != required:
        raise ValueError("CHRONOS_NO_COMPLETE_MARKET")
    medians = {
        selection: Decimal(str(median(values)))
        for selection, values in by_selection.items()
    }
    normalizer = sum(medians.values(), Decimal(0))
    probabilities = {
        selection: value / normalizer for selection, value in medians.items()
    }
    input_hash = canonical_sha256(sorted(row.derivation_id for row in rows))
    confirmatory = complete_books == tuple(sorted(BOOKMAKER_ALLOWLIST))
    identity = {
        "fixture_id": fixture_id,
        "cutoff_id": cutoff_id,
        "market": market.value,
        "line": str(line) if line is not None else None,
        "bookmakers": complete_books,
        "probabilities": {
            selection.value: str(value)
            for selection, value in sorted(
                probabilities.items(),
                key=lambda item: item[0].value,
            )
        },
        "input_set_hash": input_hash,
    }
    return AggregatedMarketSnapshot(
        snapshot_id="market-snapshot:" + canonical_sha256(identity),
        fixture_id=fixture_id,
        cutoff_id=cutoff_id,
        market=market,
        line=line,
        bookmakers=complete_books,
        selection_probabilities=probabilities,
        input_set_hash=input_hash,
        confirmatory_admissible=confirmatory,
        quality_status=(QualityStatus.VALID if confirmatory else QualityStatus.NO_PRICE),
    )


class PointInTimeTagSnapshot(FrozenContract):
    schema_version: Literal["point-in-time-tag-snapshot-v1"] = (
        "point-in-time-tag-snapshot-v1"
    )
    fixture_id: str
    cutoff_id: str
    cutoff_at: datetime
    kickoff_at: datetime
    tag_registry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts_used: tuple[str, ...]
    fact_hashes: dict[str, str]
    tag_states: dict[str, TagState]
    tag_fact_ids: dict[str, tuple[str, ...]]
    known_count: int = Field(ge=0)
    true_count: int = Field(ge=0)
    false_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    tag_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_tag_snapshot_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.cutoff_at >= self.kickoff_at:
            raise ValueError("CHRONOS_TAG_CUTOFF_INVALID")
        if self.facts_used != tuple(sorted(self.fact_hashes)):
            raise ValueError("CHRONOS_TAG_FACT_MANIFEST_INVALID")
        if set(self.tag_fact_ids) != set(self.tag_states) or self.facts_used != tuple(
            sorted(
                {
                    fact_id
                    for fact_ids in self.tag_fact_ids.values()
                    for fact_id in fact_ids
                }
            )
        ):
            raise ValueError("CHRONOS_TAG_FACT_REFERENCES_INVALID")
        if self.known_count != self.true_count + self.false_count:
            raise ValueError("CHRONOS_TAG_KNOWN_COUNT_INVALID")
        if self.known_count + self.unknown_count != len(self.tag_states):
            raise ValueError("CHRONOS_TAG_TOTAL_COUNT_INVALID")
        if len(self.tag_states) != CANONICAL_TAG_COUNT:
            raise ValueError("CHRONOS_TAG_COUNT_NOT_150")
        if self.supersedes_tag_snapshot_hash == self.tag_snapshot_hash:
            raise ValueError("CHRONOS_TAG_SELF_SUPERSESSION")
        return self


def freeze_tag_snapshot(
    *,
    fixture_id: str,
    cutoff_id: str,
    cutoff_at: datetime,
    kickoff_at: datetime,
    tag_registry_hash: str,
    facts: Iterable[KnownAtFact],
    tag_states: Mapping[str, TagState],
    tag_fact_ids: Mapping[str, Sequence[str]],
    expected_tag_ids: Sequence[str],
    supersedes_tag_snapshot_hash: str | None = None,
) -> PointInTimeTagSnapshot:
    expected = tuple(sorted(expected_tag_ids))
    if len(expected) != CANONICAL_TAG_COUNT or len(set(expected)) != len(expected):
        raise ValueError("CHRONOS_TAG_REGISTRY_NOT_150")
    ordered_states = dict(sorted(tag_states.items()))
    if tuple(ordered_states) != expected or set(tag_fact_ids) != set(expected):
        raise ValueError("CHRONOS_TAG_REGISTRY_SCOPE_MISMATCH")
    strict = {fact.fact_id: fact for fact in strict_fact_view(facts)}
    cutoff = ensure_utc(cutoff_at, field="cutoff_at")
    kickoff = ensure_utc(kickoff_at, field="kickoff_at")
    for fact in strict.values():
        if (
            fact.fixture_id != fixture_id
            or fact.cutoff_id != cutoff_id
            or fact.cutoff_at != cutoff
            or fact.kickoff_at != kickoff
        ):
            raise ValueError("CHRONOS_TAG_FACT_SCOPE_MISMATCH")
    used_ids: set[str] = set()
    for tag_id, state in ordered_states.items():
        referenced = tuple(sorted(set(tag_fact_ids[tag_id])))
        if state is TagState.UNKNOWN:
            if referenced:
                raise ValueError("CHRONOS_UNKNOWN_TAG_REFERENCES_FACT")
            continue
        if not referenced or any(fact_id not in strict for fact_id in referenced):
            raise ValueError("CHRONOS_KNOWN_TAG_WITHOUT_ADMISSIBLE_FACT")
        used_ids.update(referenced)
    fact_hashes = {
        fact_id: canonical_sha256(strict[fact_id].model_dump(mode="json"))
        for fact_id in sorted(used_ids)
    }
    true_count = sum(state is TagState.TRUE for state in ordered_states.values())
    false_count = sum(state is TagState.FALSE for state in ordered_states.values())
    unknown_count = sum(state is TagState.UNKNOWN for state in ordered_states.values())
    identity = {
        "fixture_id": fixture_id,
        "cutoff_id": cutoff_id,
        "cutoff_at": ensure_utc(cutoff_at, field="cutoff_at").isoformat(),
        "kickoff_at": ensure_utc(kickoff_at, field="kickoff_at").isoformat(),
        "tag_registry_hash": tag_registry_hash,
        "fact_hashes": fact_hashes,
        "tag_states": {key: value.value for key, value in ordered_states.items()},
        "tag_fact_ids": {
            key: tuple(sorted(set(tag_fact_ids[key]))) for key in expected
        },
        "supersedes_tag_snapshot_hash": supersedes_tag_snapshot_hash,
    }
    return PointInTimeTagSnapshot(
        fixture_id=fixture_id,
        cutoff_id=cutoff_id,
        cutoff_at=cutoff_at,
        kickoff_at=kickoff_at,
        tag_registry_hash=tag_registry_hash,
        facts_used=tuple(sorted(fact_hashes)),
        fact_hashes=fact_hashes,
        tag_states=ordered_states,
        tag_fact_ids={
            key: tuple(sorted(set(tag_fact_ids[key]))) for key in expected
        },
        known_count=true_count + false_count,
        true_count=true_count,
        false_count=false_count,
        unknown_count=unknown_count,
        tag_snapshot_hash=canonical_sha256(identity),
        supersedes_tag_snapshot_hash=supersedes_tag_snapshot_hash,
    )


class LineageNodeKind(StrEnum):
    RAW_OBJECT = "RAW_OBJECT"
    NORMALIZED_FACT = "NORMALIZED_FACT"
    KNOWN_AT_FACT = "KNOWN_AT_FACT"
    TAG_SNAPSHOT = "TAG_SNAPSHOT"
    PRICE_SNAPSHOT = "PRICE_SNAPSHOT"
    HYPOTHESIS_VERSION = "HYPOTHESIS_VERSION"
    STRATEGY_VERSION = "STRATEGY_VERSION"
    DECISION = "DECISION"
    SETTLEMENT = "SETTLEMENT"


class LineageEdge(FrozenContract):
    edge_id: str = Field(pattern=r"^chronos-edge:[0-9a-f]{64}$")
    upstream_kind: LineageNodeKind
    upstream_id: str
    upstream_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    downstream_kind: LineageNodeKind
    downstream_id: str
    downstream_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    relation: str
    contract_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_revision: str


def build_lineage_edge(
    *,
    upstream_kind: LineageNodeKind,
    upstream_id: str,
    upstream_hash: str,
    downstream_kind: LineageNodeKind,
    downstream_id: str,
    downstream_hash: str,
    relation: str,
    contract_hash: str,
    code_revision: str,
) -> LineageEdge:
    identity = {
        "upstream_kind": upstream_kind.value,
        "upstream_id": upstream_id,
        "upstream_hash": upstream_hash,
        "downstream_kind": downstream_kind.value,
        "downstream_id": downstream_id,
        "downstream_hash": downstream_hash,
        "relation": relation,
        "contract_hash": contract_hash,
        "code_revision": code_revision,
    }
    return LineageEdge(
        edge_id="chronos-edge:" + canonical_sha256(identity),
        upstream_kind=upstream_kind,
        upstream_id=upstream_id,
        upstream_hash=upstream_hash,
        downstream_kind=downstream_kind,
        downstream_id=downstream_id,
        downstream_hash=downstream_hash,
        relation=relation,
        contract_hash=contract_hash,
        code_revision=code_revision,
    )


class LineageIndex:
    """Small append-only bidirectional lineage index used by replay and tests."""

    def __init__(self) -> None:
        self._edges: dict[str, LineageEdge] = {}

    def append(self, edge: LineageEdge) -> bool:
        existing = self._edges.get(edge.edge_id)
        if existing is not None:
            if existing != edge:
                raise ValueError("CHRONOS_LINEAGE_EDGE_CONFLICT")
            return False
        if edge.upstream_id == edge.downstream_id:
            raise ValueError("CHRONOS_LINEAGE_SELF_CYCLE")
        pending = [edge.downstream_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == edge.upstream_id:
                raise ValueError("CHRONOS_LINEAGE_CYCLE")
            if current in visited:
                continue
            visited.add(current)
            pending.extend(
                candidate.downstream_id
                for candidate in self._edges.values()
                if candidate.upstream_id == current
            )
        self._edges[edge.edge_id] = edge
        return True

    def upstream(self, node_id: str) -> tuple[LineageEdge, ...]:
        return tuple(
            sorted(
                (edge for edge in self._edges.values() if edge.downstream_id == node_id),
                key=lambda edge: edge.edge_id,
            )
        )

    def downstream(self, node_id: str) -> tuple[LineageEdge, ...]:
        return tuple(
            sorted(
                (edge for edge in self._edges.values() if edge.upstream_id == node_id),
                key=lambda edge: edge.edge_id,
            )
        )


class CanaryBudget(FrozenContract):
    max_fixtures: int = Field(default=5, ge=0, le=5)
    max_technical_attempts: int = Field(default=2, ge=1, le=2)
    api_football_calls_max: int = Field(default=50, ge=0, le=50)
    odds_credits_max: int = Field(default=20, ge=0, le=100)
    r2_object_writes_max: int = Field(default=2000, ge=0, le=2000)
    postgresql_rows_max: int = Field(default=10000, ge=0, le=10000)
    new_purchase_allowed: Literal[False] = False
    r2_deletes: Literal[0] = 0
    destructive_sql: Literal[0] = 0

    def authorize(
        self,
        *,
        fixtures: int,
        attempts: int,
        api_football_calls: int,
        odds_credits: int,
        r2_object_writes: int,
        postgresql_rows: int,
        provider_remaining_after: int,
        provider_reserve: int,
    ) -> None:
        checks = (
            (fixtures, self.max_fixtures, "FIXTURES"),
            (attempts, self.max_technical_attempts, "ATTEMPTS"),
            (api_football_calls, self.api_football_calls_max, "API_CALLS"),
            (odds_credits, self.odds_credits_max, "ODDS_CREDITS"),
            (r2_object_writes, self.r2_object_writes_max, "R2_WRITES"),
            (postgresql_rows, self.postgresql_rows_max, "POSTGRESQL_ROWS"),
        )
        for actual, maximum, label in checks:
            if actual < 0 or actual > maximum:
                raise ValueError(f"CHRONOS_CANARY_{label}_LIMIT")
        if provider_remaining_after < provider_reserve:
            raise ValueError("CHRONOS_CANARY_PROVIDER_RESERVE")


def deterministic_fixture_canary(
    fixture_ids_by_league: Mapping[str, Sequence[str]],
    *,
    maximum: int = 5,
) -> tuple[str, ...]:
    """Select at most one due fixture per league, deterministically."""

    if maximum < 0 or maximum > 5:
        raise ValueError("CHRONOS_CANARY_FIXTURE_LIMIT_INVALID")
    return tuple(
        sorted(values)[0]
        for _, values in sorted(fixture_ids_by_league.items())
        if values
    )[:maximum]


def power_floor(
    *,
    standardized_effect: Decimal,
    power: Literal["0.80", "0.90"] = "0.80",
) -> int:
    """Frozen conservative Bonferroni planning values for 7,480 tests."""

    table = {
        "0.80": {
            Decimal("0.20"): 675,
            Decimal("0.15"): 1200,
            Decimal("0.10"): 2699,
        },
        "0.90": {
            Decimal("0.20"): 794,
            Decimal("0.15"): 1412,
            Decimal("0.10"): 3176,
        },
    }
    try:
        return table[power][standardized_effect]
    except KeyError as error:
        raise ValueError("CHRONOS_POWER_EFFECT_NOT_PREREGISTERED") from error


__all__ = [
    "AggregatedMarketSnapshot",
    "BOOKMAKER_ALLOWLIST",
    "CANONICAL_TAG_COUNT",
    "CanaryBudget",
    "ChronosMarket",
    "ChronosSelection",
    "KnownAtFact",
    "LineageEdge",
    "LineageIndex",
    "LineageNodeKind",
    "PointInTimeTagSnapshot",
    "PriceDerivation",
    "PriceObservation",
    "QualityStatus",
    "REGION_ALLOWLIST",
    "ScientificRole",
    "TagState",
    "TemporalClass",
    "aggregate_market_snapshot",
    "build_known_at_fact",
    "build_lineage_edge",
    "build_price_observation",
    "derive_complete_book_markets",
    "deterministic_fixture_canary",
    "freeze_tag_snapshot",
    "power_floor",
    "strict_fact_view",
    "temporal_classification",
]
