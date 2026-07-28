"""Verified, provider-scoped team identities extracted from fixture captures."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast

from robin.prospective_observatory.contracts import (
    CaptureFamily,
    canonical_sha256,
)
from robin.prospective_observatory.r2 import StoredCapture

IdentitySide = Literal["home", "away"]


def canonical_team_key(provider: str, provider_team_id: str) -> str:
    """Return a collision-free key without assuming anything about provider IDs."""

    clean_provider = provider.strip()
    clean_identifier = provider_team_id.strip()
    if not clean_provider or not clean_identifier:
        raise ValueError("TEAM_IDENTITY_CANONICAL_KEY_INVALID")
    return f"{clean_provider}:{clean_identifier}"


@dataclass(frozen=True, slots=True)
class TeamIdentityEvidence:
    provider: str
    provider_team_id: str
    canonical_team_id: str
    display_name: str
    short_name: str | None
    competition: str
    season: str
    fixture_id: str
    side: IdentitySide
    captured_at: datetime
    source_payload_sha256: str
    source_receipt_id: str
    source_payload_r2_key: str
    source_receipt_r2_key: str
    receipt_verified: bool = True
    source: str = "R2_FIXTURE_PAYLOAD"
    identity_status: str = "VERIFIED"

    def __post_init__(self) -> None:
        if (
            self.canonical_team_id
            != canonical_team_key(self.provider, self.provider_team_id)
            or not self.display_name.strip()
            or len(self.source_payload_sha256) != 64
            or len(self.source_receipt_id) != 64
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
            or not self.receipt_verified
            or self.source != "R2_FIXTURE_PAYLOAD"
            or self.identity_status != "VERIFIED"
        ):
            raise ValueError("TEAM_IDENTITY_EVIDENCE_INVALID")

    def public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "provider_team_id": self.provider_team_id,
            "canonical_team_id": self.canonical_team_id,
            "display_name": self.display_name,
            "short_name": self.short_name,
            "competition": self.competition,
            "season": self.season,
            "fixture_id": self.fixture_id,
            "side": self.side,
            "captured_at": self.captured_at.astimezone(UTC).isoformat(),
            "source": self.source,
            "payload_sha256": self.source_payload_sha256,
            "receipt_id": self.source_receipt_id,
            "payload_r2_key": self.source_payload_r2_key,
            "receipt_r2_key": self.source_receipt_r2_key,
            "receipt_verified": self.receipt_verified,
            "identity_status": self.identity_status,
        }


@dataclass(frozen=True, slots=True)
class TeamIdentitySource:
    fixture_id: str
    side: IdentitySide
    competition: str
    season: str
    captured_at: datetime
    payload_sha256: str
    receipt_id: str

    def public_dict(self) -> dict[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "side": self.side,
            "competition": self.competition,
            "season": self.season,
            "captured_at": self.captured_at.astimezone(UTC).isoformat(),
            "payload_sha256": self.payload_sha256,
            "receipt_id": self.receipt_id,
        }


@dataclass(frozen=True, slots=True)
class TeamIdentityVersion:
    display_name: str
    short_name: str | None
    valid_from: datetime
    valid_to: datetime | None
    sources: tuple[TeamIdentitySource, ...]
    status: str = "VERIFIED"

    def public_dict(self) -> dict[str, object]:
        return {
            "display_name": self.display_name,
            "short_name": self.short_name,
            "valid_from": self.valid_from.astimezone(UTC).isoformat(),
            "valid_to": (
                self.valid_to.astimezone(UTC).isoformat()
                if self.valid_to is not None
                else None
            ),
            "sources": [source.public_dict() for source in self.sources],
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RegisteredTeamIdentity:
    provider: str
    provider_team_id: str
    canonical_team_id: str
    versions: tuple[TeamIdentityVersion, ...]

    @property
    def aliases(self) -> tuple[str, ...]:
        current = self.versions[-1].display_name
        return tuple(
            dict.fromkeys(
                version.display_name
                for version in self.versions
                if version.display_name != current
            )
        )

    def resolve(self, *, at: datetime | None = None) -> TeamIdentityVersion:
        if at is None:
            return self.versions[-1]
        instant = at.astimezone(UTC)
        matches = [
            version
            for version in self.versions
            if version.valid_from <= instant
            and (version.valid_to is None or instant < version.valid_to)
        ]
        if len(matches) != 1:
            raise LookupError("TEAM_IDENTITY_VERSION_UNRESOLVED")
        return matches[0]

    def public_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "provider_team_id": self.provider_team_id,
            "canonical_team_id": self.canonical_team_id,
            "display_name": self.versions[-1].display_name,
            "short_name": self.versions[-1].short_name,
            "aliases": list(self.aliases),
            "versions": [version.public_dict() for version in self.versions],
            "status": "VERIFIED",
        }


@dataclass(frozen=True, slots=True)
class TeamIdentityRegistry:
    identities: tuple[RegisteredTeamIdentity, ...]
    schema_version: str = "team-identity-registry-v1"

    def resolve(
        self,
        provider: str,
        provider_team_id: str,
        *,
        at: datetime | None = None,
    ) -> TeamIdentityVersion:
        key = canonical_team_key(provider, provider_team_id)
        matches = [
            identity for identity in self.identities if identity.canonical_team_id == key
        ]
        if len(matches) != 1:
            raise LookupError("TEAM_IDENTITY_UNRESOLVED")
        return matches[0].resolve(at=at)

    def public_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "key_policy": "provider:provider_team_id",
            "mutation_policy": "APPEND_VERSION_ON_VERIFIED_NAME_CHANGE",
            "identities": [
                identity.public_dict()
                for identity in sorted(
                    self.identities,
                    key=lambda item: item.canonical_team_id,
                )
            ],
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.public_dict())


def _mapping(value: object, *, error: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(error)
    return cast(Mapping[str, object], value)


def _identity_name(team: Mapping[str, object]) -> str:
    name = str(team.get("name", "")).strip()
    if not name:
        raise ValueError("TEAM_IDENTITY_NAME_MISSING")
    return name


def _verified_short_name(team: Mapping[str, object]) -> str | None:
    for field in ("short_name", "shortName"):
        value = team.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_team_identity_evidence(
    capture: StoredCapture,
) -> tuple[TeamIdentityEvidence, TeamIdentityEvidence]:
    """Extract two identities after `read_capture` verified receipt and payload bytes."""

    receipt = capture.receipt
    if (
        receipt.family is not CaptureFamily.FIXTURE
        or receipt.window_label != "REGISTRY"
        or not receipt.complete
    ):
        raise ValueError("TEAM_IDENTITY_FIXTURE_CAPTURE_REQUIRED")
    payload = _mapping(capture.payload, error="TEAM_IDENTITY_PAYLOAD_INVALID")
    normalized = payload.get("normalized_family_records")
    raw: object = (
        normalized[0]
        if isinstance(normalized, list) and len(normalized) == 1
        else payload.get("provider_payload")
    )
    record = _mapping(raw, error="TEAM_IDENTITY_FIXTURE_RECORD_INVALID")
    fixture = _mapping(
        record.get("fixture"),
        error="TEAM_IDENTITY_FIXTURE_PROVIDER_CONTRACT_INVALID",
    )
    teams = _mapping(record.get("teams"), error="TEAM_IDENTITY_TEAMS_INVALID")
    contract = _mapping(
        payload.get("fixture_contract"),
        error="TEAM_IDENTITY_FIXTURE_CONTRACT_MISSING",
    )

    contract_fixture_id = str(contract.get("fixture_id", "")).strip()
    contract_provider = str(contract.get("provider", "")).strip()
    provider_fixture_id = str(contract.get("provider_fixture_id", "")).strip()
    raw_fixture_id = str(fixture.get("id", "")).strip()
    if (
        contract_fixture_id != receipt.fixture_id
        or contract_provider != receipt.provider
        or provider_fixture_id != raw_fixture_id
        or receipt.fixture_id != f"{receipt.provider}:{provider_fixture_id}"
        or str(contract.get("competition", "")).strip() != receipt.competition
        or str(contract.get("season", "")).strip() != receipt.season
    ):
        raise ValueError("TEAM_IDENTITY_FIXTURE_PROVENANCE_MISMATCH")

    result: list[TeamIdentityEvidence] = []
    sides: tuple[IdentitySide, IdentitySide] = ("home", "away")
    for side in sides:
        team = _mapping(
            teams.get(side),
            error=f"TEAM_IDENTITY_{side.upper()}_INVALID",
        )
        provider_team_id = str(team.get("id", "")).strip()
        contract_team_id = str(contract.get(f"{side}_team_id", "")).strip()
        if not provider_team_id or provider_team_id != contract_team_id:
            raise ValueError("TEAM_IDENTITY_TEAM_PROVENANCE_MISMATCH")
        result.append(
            TeamIdentityEvidence(
                provider=receipt.provider,
                provider_team_id=provider_team_id,
                canonical_team_id=canonical_team_key(
                    receipt.provider,
                    provider_team_id,
                ),
                display_name=_identity_name(team),
                short_name=_verified_short_name(team),
                competition=receipt.competition,
                season=receipt.season,
                fixture_id=receipt.fixture_id,
                side=side,
                captured_at=receipt.observed_at,
                source_payload_sha256=receipt.payload_sha256,
                source_receipt_id=receipt.receipt_hash,
                source_payload_r2_key=receipt.r2_key,
                source_receipt_r2_key=receipt.receipt_r2_key,
            )
        )
    return result[0], result[1]


def build_team_identity_registry(
    evidence: Iterable[TeamIdentityEvidence],
) -> TeamIdentityRegistry:
    """Build deterministic temporal versions; repeated evidence is idempotent."""

    grouped: dict[str, list[TeamIdentityEvidence]] = defaultdict(list)
    seen: set[tuple[str, str, datetime, str]] = set()
    for item in evidence:
        unique_key = (
            item.canonical_team_id,
            item.display_name,
            item.captured_at,
            item.source_receipt_id,
        )
        if unique_key not in seen:
            grouped[item.canonical_team_id].append(item)
            seen.add(unique_key)

    identities: list[RegisteredTeamIdentity] = []
    for key, rows in sorted(grouped.items()):
        ordered = sorted(
            rows,
            key=lambda item: (
                item.captured_at,
                item.source_receipt_id,
                item.fixture_id,
                item.side,
            ),
        )
        versions: list[TeamIdentityVersion] = []
        for row in ordered:
            source = TeamIdentitySource(
                fixture_id=row.fixture_id,
                side=row.side,
                competition=row.competition,
                season=row.season,
                captured_at=row.captured_at,
                payload_sha256=row.source_payload_sha256,
                receipt_id=row.source_receipt_id,
            )
            if (
                versions
                and versions[-1].display_name == row.display_name
                and versions[-1].short_name == row.short_name
            ):
                current = versions[-1]
                if source not in current.sources:
                    versions[-1] = replace(
                        current,
                        sources=tuple(
                            sorted(
                                (*current.sources, source),
                                key=lambda item: (
                                    item.captured_at,
                                    item.receipt_id,
                                    item.fixture_id,
                                ),
                            )
                        ),
                    )
                continue
            if versions:
                versions[-1] = replace(
                    versions[-1],
                    valid_to=row.captured_at,
                )
            versions.append(
                TeamIdentityVersion(
                    display_name=row.display_name,
                    short_name=row.short_name,
                    valid_from=row.captured_at,
                    valid_to=None,
                    sources=(source,),
                )
            )
        first = ordered[0]
        identities.append(
            RegisteredTeamIdentity(
                provider=first.provider,
                provider_team_id=first.provider_team_id,
                canonical_team_id=key,
                versions=tuple(versions),
            )
        )
    return TeamIdentityRegistry(identities=tuple(identities))


def fixture_identity_scope_sha256(
    fixtures: Iterable[Mapping[str, object]],
) -> str:
    """Hash only stable fixture/team linkage, never presentation timestamps."""

    scoped: list[dict[str, str]] = []
    for fixture in fixtures:
        def clean(field: str) -> str:
            value = fixture.get(field)
            return value.strip() if isinstance(value, str) else ""

        row = {
            "fixture_id": clean("fixture_id"),
            "provider": clean("provider"),
            "provider_fixture_id": clean("provider_fixture_id"),
            "home_team_id": clean("home_team_id"),
            "away_team_id": clean("away_team_id"),
            "competition": clean("competition"),
            "season": clean("season"),
        }
        required = {key: value for key, value in row.items() if key != "season"}
        if (
            not all(required.values())
            or row["home_team_id"] == row["away_team_id"]
        ):
            raise ValueError("TEAM_IDENTITY_FIXTURE_SCOPE_INVALID")
        scoped.append(row)
    return canonical_sha256(
        sorted(scoped, key=lambda item: item["fixture_id"])
    )
