from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from robin.domain.enums import EntityType, QualityStatus
from robin.domain.identity import ProviderIdentity
from robin.domain.temporal import FeatureRecord, TemporalInstants, known_strictly_before
from robin.identity.service import IdentityService
from robin.storage.database import build_engine, transaction
from robin.storage.models import Base


def utc(hour: int) -> datetime:
    return datetime(2026, 7, 24, hour, tzinfo=UTC)


def test_feature_refuse_observation_future_et_instant_naif() -> None:
    with pytest.raises(ValidationError):
        FeatureRecord(
            feature_name="referee_card_rate",
            entity_id="ref-1",
            fixture_id="fixture-1",
            value=4.2,
            as_of_time=utc(12),
            calculated_at=utc(12),
            source_version="raw:abc",
            feature_version="1",
            quality_status=QualityStatus.DERIVED,
            observation_times=(utc(12),),
        )

    with pytest.raises(ValidationError):
        FeatureRecord(
            feature_name="form",
            entity_id="team-1",
            fixture_id="fixture-1",
            value=0.5,
            as_of_time=datetime(2026, 7, 24, 12),
            calculated_at=utc(12),
            source_version="raw:abc",
            feature_version="1",
            quality_status=QualityStatus.DERIVED,
        )


def test_instant_prediction_impose_observation_strictement_anterieure() -> None:
    with pytest.raises(ValidationError):
        TemporalInstants(
            fixture_created_at=utc(8),
            fixture_kickoff_at=utc(18),
            data_observed_at=utc(12),
            data_ingested_at=utc(12) + timedelta(minutes=1),
            prediction_generated_at=utc(12),
        )
    assert known_strictly_before(utc(11), utc(12))
    assert not known_strictly_before(utc(12), utc(12))


def test_identite_est_stable_par_cle_fournisseur_sans_fusion_par_nom() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    observed_at = utc(10)

    with transaction(engine) as session:
        service = IdentityService(session)
        first = ProviderIdentity(
            entity_type=EntityType.TEAM,
            provider_name="provider-a",
            provider_entity_id="club-001",
            observed_name="Racing Club",
            valid_from=observed_at,
        )
        same_name_other_id = first.model_copy(update={"provider_entity_id": "club-002"})
        internal_first = service.resolve_or_create(first)
        assert service.resolve_or_create(first) == internal_first
        assert service.resolve_or_create(same_name_other_id) != internal_first


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_tous_les_types_d_identite_sont_operationnels(entity_type: EntityType) -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with transaction(engine) as session:
        service = IdentityService(session)
        reference = ProviderIdentity(
            entity_type=entity_type,
            provider_name="fixture-provider",
            provider_entity_id=f"{entity_type.value}-42",
            observed_name="Nom non déterminant",
            valid_from=utc(9),
        )
        assert service.resolve_or_create(reference)


def test_deux_fournisseurs_ne_sont_fusionnes_que_par_lien_explicite() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with transaction(engine) as session:
        service = IdentityService(session)
        source_a = ProviderIdentity(
            entity_type=EntityType.PLAYER,
            provider_name="provider-a",
            provider_entity_id="p-7",
            observed_name="Alex Martin",
            valid_from=utc(9),
        )
        source_b = source_a.model_copy(
            update={"provider_name": "provider-b", "provider_entity_id": "99"}
        )
        internal_id = service.resolve_or_create(source_a)
        assert service.resolve(source_b) is None
        service.link_provider(internal_id, source_b)
        assert service.resolve(source_b) == internal_id

