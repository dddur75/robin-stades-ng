from __future__ import annotations

from datetime import UTC, datetime, timedelta

from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
)
from robin.prospective_observatory.r2 import (
    InMemoryObjectStore,
    ProspectiveR2Repository,
    StoredCapture,
)
from robin.prospective_observatory.team_identities import (
    build_team_identity_registry,
    canonical_team_key,
    extract_team_identity_evidence,
)

BASE = datetime(2026, 7, 1, 12, tzinfo=UTC)


def _fixture_capture(
    *,
    provider: str = "api-football",
    provider_fixture_id: str = "fixture-1",
    home_team_id: str = "81",
    home_name: str = "Olympique de Marseille",
    away_team_id: str = "95",
    away_name: str = "RC Strasbourg Alsace",
    observed_at: datetime = BASE,
    kickoff_at: datetime | None = None,
) -> StoredCapture:
    kickoff = kickoff_at or observed_at + timedelta(days=30)
    fixture_id = f"{provider}:{provider_fixture_id}"
    context = CaptureContext(
        window_id=None,
        window_label="REGISTRY",
        fixture_id=fixture_id,
        competition="Ligue 1",
        season="2026",
        provider=provider,
        family=CaptureFamily.FIXTURE,
        requested_at=observed_at - timedelta(seconds=2),
        response_received_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at,
        kickoff_at=kickoff,
        cutoff_at=kickoff - timedelta(microseconds=1),
        http_status=200,
        source_endpoint="/fixtures",
        complete=True,
        quality_status=AvailabilityStatus.CAPTURED,
        provider_calls=0,
        code_revision="synthetic-test",
        materialized_at=observed_at,
    )
    payload = {
        "normalized_family_records": [
            {
                "fixture": {
                    "id": provider_fixture_id,
                    "date": kickoff.isoformat(),
                },
                "teams": {
                    "home": {"id": home_team_id, "name": home_name},
                    "away": {"id": away_team_id, "name": away_name},
                },
            }
        ],
        "fixture_contract": {
            "fixture_id": fixture_id,
            "competition": "Ligue 1",
            "season": "2026",
            "phase": "Regular Season - 1",
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "kickoff_at": kickoff.isoformat(),
            "provider": provider,
            "provider_fixture_id": provider_fixture_id,
            "registered_at": observed_at.isoformat(),
            "code_revision": "synthetic-test",
            "cancelled": False,
            "horizon_days": 60,
        },
    }
    return ProspectiveR2Repository(InMemoryObjectStore()).capture(
        payload=payload,
        context=context,
    )


def test_case_a_verified_names_are_extracted_from_fixture_payload() -> None:
    home, away = extract_team_identity_evidence(_fixture_capture())
    assert home.display_name == "Olympique de Marseille"
    assert away.display_name == "RC Strasbourg Alsace"
    assert home.receipt_verified is True
    assert home.source == "R2_FIXTURE_PAYLOAD"


def test_case_c_a_new_team_needs_no_registry_code_change() -> None:
    home, _ = extract_team_identity_evidence(
        _fixture_capture(
            provider_fixture_id="fixture-new",
            home_team_id="newly-promoted-42",
            home_name="Club Promu Synthétique",
        )
    )
    registry = build_team_identity_registry([home])
    assert (
        registry.resolve("api-football", "newly-promoted-42").display_name
        == "Club Promu Synthétique"
    )


def test_case_d_name_changes_are_versioned_with_provenance() -> None:
    old_home, _ = extract_team_identity_evidence(
        _fixture_capture(
            provider_fixture_id="fixture-old-name",
            home_name="Nom Historique Synthétique",
        )
    )
    changed_at = BASE + timedelta(days=365)
    new_home, _ = extract_team_identity_evidence(
        _fixture_capture(
            provider_fixture_id="fixture-new-name",
            home_name="Nom Actuel Synthétique",
            observed_at=changed_at,
        )
    )
    registry = build_team_identity_registry([new_home, old_home, new_home])
    identity = registry.identities[0]
    assert [version.display_name for version in identity.versions] == [
        "Nom Historique Synthétique",
        "Nom Actuel Synthétique",
    ]
    assert identity.versions[0].valid_to == changed_at
    assert identity.aliases == ("Nom Historique Synthétique",)
    assert len(identity.versions[1].sources) == 1


def test_case_e_identical_ids_from_two_providers_never_collide() -> None:
    first, _ = extract_team_identity_evidence(_fixture_capture())
    second, _ = extract_team_identity_evidence(
        _fixture_capture(
            provider="second-provider",
            provider_fixture_id="fixture-2",
            home_name="Autre Club Synthétique",
        )
    )
    registry = build_team_identity_registry([first, second])
    assert len(registry.identities) == 2
    assert canonical_team_key("api-football", "81") != canonical_team_key(
        "second-provider",
        "81",
    )


def test_case_f_postponement_keeps_identity_bound_to_canonical_fixture() -> None:
    before, _ = extract_team_identity_evidence(_fixture_capture())
    after, _ = extract_team_identity_evidence(
        _fixture_capture(
            observed_at=BASE + timedelta(days=1),
            kickoff_at=BASE + timedelta(days=37),
        )
    )
    registry = build_team_identity_registry([before, after])
    identity = registry.identities[0]
    assert len(identity.versions) == 1
    assert len(identity.versions[0].sources) == 2
    assert {source.fixture_id for source in identity.versions[0].sources} == {
        "api-football:fixture-1"
    }


def test_case_g_fixture_order_cannot_change_associations() -> None:
    first = extract_team_identity_evidence(_fixture_capture())
    second = extract_team_identity_evidence(
        _fixture_capture(
            provider_fixture_id="fixture-2",
            home_team_id="200",
            home_name="Domicile Deux Synthétique",
            away_team_id="201",
            away_name="Extérieur Deux Synthétique",
        )
    )
    evidence = [*first, *second]
    assert build_team_identity_registry(evidence).sha256 == (
        build_team_identity_registry(reversed(evidence)).sha256
    )
