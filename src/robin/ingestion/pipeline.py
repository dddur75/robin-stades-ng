"""État transactionnel et idempotent des exécutions de pipeline."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from robin.domain.temporal import require_utc
from robin.storage.models import PipelineRun


def start_pipeline_run(
    session: Session,
    *,
    pipeline_name: str,
    idempotency_key: str,
    source_version: str,
    started_at: datetime,
) -> tuple[PipelineRun, bool]:
    existing = session.scalar(
        select(PipelineRun).where(PipelineRun.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing, False
    run = PipelineRun(
        id=str(uuid4()),
        idempotency_key=idempotency_key,
        pipeline_name=pipeline_name,
        started_at=require_utc(started_at, "started_at"),
        finished_at=None,
        status="IN_PROGRESS",
        source_version=source_version,
        error_message=None,
    )
    session.add(run)
    session.flush()
    return run, True
