from datetime import UTC, datetime

from sqlalchemy import func, select

from robin.ingestion.pipeline import start_pipeline_run
from robin.storage.database import build_engine, transaction
from robin.storage.models import Base, PipelineRun


def test_deux_executions_de_meme_cle_ne_creent_pas_de_doublon() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 24, 12, tzinfo=UTC)

    with transaction(engine) as session:
        first, created_first = start_pipeline_run(
            session,
            pipeline_name="mock-odds",
            idempotency_key="mock-odds:2026-07-24T12:00Z",
            source_version="mock-v1",
            started_at=now,
        )
        second, created_second = start_pipeline_run(
            session,
            pipeline_name="mock-odds",
            idempotency_key="mock-odds:2026-07-24T12:00Z",
            source_version="mock-v1",
            started_at=now,
        )

        assert first.id == second.id
        assert created_first
        assert not created_second
        assert session.scalar(select(func.count()).select_from(PipelineRun)) == 1

