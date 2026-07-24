"""Service transactionnel d'identité stable."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from robin.domain.identity import ProviderIdentity
from robin.storage.models import InternalEntity, ProviderMapping


class IdentityConflictError(RuntimeError):
    """Le fournisseur attribue une même identité active à plusieurs entités."""


class IdentityService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, reference: ProviderIdentity) -> str | None:
        statement = select(ProviderMapping).where(
            ProviderMapping.provider_name == reference.provider_name,
            ProviderMapping.entity_type == reference.entity_type.value,
            ProviderMapping.provider_entity_id == reference.provider_entity_id,
            ProviderMapping.valid_from <= reference.valid_from,
            (ProviderMapping.valid_to.is_(None))
            | (ProviderMapping.valid_to > reference.valid_from),
        )
        matches = list(self.session.scalars(statement))
        ids = {match.internal_entity_id for match in matches}
        if len(ids) > 1:
            raise IdentityConflictError("plusieurs identités internes actives pour la même clé")
        return next(iter(ids), None)

    def resolve_or_create(self, reference: ProviderIdentity) -> str:
        existing = self.resolve(reference)
        if existing is not None:
            return existing
        internal_id = str(uuid4())
        now = datetime.now(UTC)
        self.session.add(
            InternalEntity(
                id=internal_id,
                entity_type=reference.entity_type.value,
                display_name=reference.observed_name,
                attributes={},
                created_at=now,
            )
        )
        self.session.add(
            ProviderMapping(
                id=str(uuid4()),
                internal_entity_id=internal_id,
                entity_type=reference.entity_type.value,
                provider_name=reference.provider_name,
                provider_entity_id=reference.provider_entity_id,
                observed_name=reference.observed_name,
                valid_from=reference.valid_from,
                valid_to=reference.valid_to,
                mapping_status=reference.mapping_status.value,
                mapping_confidence=reference.mapping_confidence,
                mapping_method=reference.mapping_method,
                review_status=reference.review_status.value,
            )
        )
        self.session.flush()
        return internal_id

    def link_provider(
        self,
        internal_entity_id: str,
        reference: ProviderIdentity,
    ) -> None:
        """Ajouter explicitement un fournisseur à une identité déjà établie."""
        if self.resolve(reference) is not None:
            raise IdentityConflictError("cette identité fournisseur est déjà liée")
        entity = self.session.get(InternalEntity, internal_entity_id)
        if entity is None or entity.entity_type != reference.entity_type.value:
            raise IdentityConflictError("entité interne absente ou de type incompatible")
        self.session.add(
            ProviderMapping(
                id=str(uuid4()),
                internal_entity_id=internal_entity_id,
                entity_type=reference.entity_type.value,
                provider_name=reference.provider_name,
                provider_entity_id=reference.provider_entity_id,
                observed_name=reference.observed_name,
                valid_from=reference.valid_from,
                valid_to=reference.valid_to,
                mapping_status=reference.mapping_status.value,
                mapping_confidence=reference.mapping_confidence,
                mapping_method=reference.mapping_method,
                review_status=reference.review_status.value,
            )
        )
        self.session.flush()
