"""Append-only projections for the Universal Football Hypothesis Genome V2."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from robin.storage.models import Base


class FootballPropertyDefinitionModel(Base):
    __tablename__ = "football_property_definitions"
    __table_args__ = (
        UniqueConstraint(
            "property_id",
            "version",
            name="uq_football_property_definition_version",
        ),
        CheckConstraint(
            "length(property_hash) = 64 AND append_only = true",
            name="ck_football_property_definition_integrity",
        ),
        Index(
            "ix_football_property_family_status",
            "family",
            "availability_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40))
    family: Mapped[str] = mapped_column(String(120))
    subfamily: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(120))
    data_type: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(200))
    source_field: Mapped[str] = mapped_column(String(300))
    availability_status: Mapped[str] = mapped_column(String(80))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    property_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisCampaignModel(Base):
    __tablename__ = "hypothesis_campaigns"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "revision",
            name="uq_hypothesis_campaign_revision",
        ),
        CheckConstraint(
            "length(campaign_hash) = 64 AND promotion_locked = true AND append_only = true",
            name="ck_hypothesis_campaign_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(160))
    revision: Mapped[str] = mapped_column(String(40))
    multiplicity_family: Mapped[str] = mapped_column(String(160))
    data_gate: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    campaign_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promotion_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisTreeNodeModel(Base):
    __tablename__ = "hypothesis_tree_nodes"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "canonical_fingerprint",
            name="uq_hypothesis_tree_node_campaign_fingerprint",
        ),
        CheckConstraint(
            "depth >= 1 AND length(canonical_fingerprint) = 64 "
            "AND length(payload_hash) = 64 AND promotion_locked = true "
            "AND append_only = true",
            name="ck_hypothesis_tree_node_integrity",
        ),
        Index(
            "ix_hypothesis_tree_node_navigation",
            "campaign_id",
            "tree_id",
            "depth",
            "materialization_disposition",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(160))
    tree_id: Mapped[str] = mapped_column(String(160))
    parent_node_id: Mapped[str | None] = mapped_column(String(180))
    parent_ids: Mapped[list[str]] = mapped_column(JSON)
    ancestor_ids: Mapped[list[str]] = mapped_column(JSON)
    depth: Mapped[int] = mapped_column(Integer)
    family: Mapped[str] = mapped_column(String(120))
    subfamily: Mapped[str] = mapped_column(String(120))
    tags: Mapped[list[str]] = mapped_column(JSON)
    canonical_fingerprint: Mapped[str] = mapped_column(String(64))
    materialization_disposition: Mapped[str] = mapped_column(String(80))
    scientific_status: Mapped[str] = mapped_column(String(80))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    promotion_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class HypothesisDerivationEdgeModel(Base):
    __tablename__ = "hypothesis_derivation_edges"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "parent_node_id",
            "child_node_id",
            name="uq_hypothesis_derivation_edge",
        ),
        CheckConstraint(
            "length(edge_hash) = 64 AND append_only = true",
            name="ck_hypothesis_derivation_edge_integrity",
        ),
        Index(
            "ix_hypothesis_derivation_child",
            "campaign_id",
            "child_node_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(160))
    parent_node_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_tree_nodes.id", ondelete="RESTRICT")
    )
    child_node_id: Mapped[str] = mapped_column(
        ForeignKey("hypothesis_tree_nodes.id", ondelete="RESTRICT")
    )
    derivation_kind: Mapped[str] = mapped_column(String(100))
    edge_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceFieldClassificationModel(Base):
    __tablename__ = "source_field_classifications"
    __table_args__ = (
        UniqueConstraint(
            "source_schema_hash",
            "source_field",
            name="uq_source_field_classification",
        ),
        CheckConstraint(
            "length(source_schema_hash) = 64 "
            "AND classification IN ('PROPERTY','BLOCKED','PROVENANCE','UNUSED') "
            "AND append_only = true",
            name="ck_source_field_classification_integrity",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    source: Mapped[str] = mapped_column(String(160))
    source_schema_hash: Mapped[str] = mapped_column(String(64))
    source_field: Mapped[str] = mapped_column(String(300))
    classification: Mapped[str] = mapped_column(String(40))
    property_id: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    append_only: Mapped[bool] = mapped_column(Boolean, default=True)


UNIVERSAL_GENOME_TABLES = frozenset(
    {
        "football_property_definitions",
        "hypothesis_campaigns",
        "hypothesis_tree_nodes",
        "hypothesis_derivation_edges",
        "source_field_classifications",
    }
)


__all__ = [
    "UNIVERSAL_GENOME_TABLES",
    "FootballPropertyDefinitionModel",
    "HypothesisCampaignModel",
    "HypothesisDerivationEdgeModel",
    "HypothesisTreeNodeModel",
    "SourceFieldClassificationModel",
]
