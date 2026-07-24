"""Pagination générique, reprenable et consciente du quota."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from robin.domain.enums import DataAvailability
from robin.providers.contracts import ProviderResult, TransientProviderError


class PaginationError(RuntimeError):
    pass


class PageEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int
    rows: int
    payload_hash: str | None
    raw_observation_id: str | None
    quota_remaining: int | None
    received_at: datetime


class PaginationManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: str
    parameters_hash: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    next_page: int = 1
    expected_total_pages: int | None = None
    pages: tuple[PageEvidence, ...] = ()
    calls: int = 0
    rows: int = 0
    error_code: str | None = None
    replayed: bool = False


@dataclass(frozen=True)
class PaginationOutcome:
    manifest: PaginationManifest
    records: tuple[dict[str, object], ...]


def _write_checkpoint(path: Path | None, manifest: PaginationManifest) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_checkpoint(path: Path | None) -> PaginationManifest | None:
    if path is None or not path.exists():
        return None
    return PaginationManifest.model_validate(json.loads(path.read_text("utf-8")))


def iterate_pages(
    *,
    endpoint: str,
    parameters_hash: str,
    fetch_page: Callable[[int], ProviderResult],
    checkpoint_path: Path | None = None,
    max_pages: int = 500,
    quota_reserve: int = 10,
) -> PaginationOutcome:
    """Parcourir toutes les pages sans rappeler un run déjà terminé."""

    checkpoint = _load_checkpoint(checkpoint_path)
    if (
        checkpoint is not None
        and checkpoint.status == "COMPLETED"
        and checkpoint.endpoint == endpoint
        and checkpoint.parameters_hash == parameters_hash
    ):
        replay = checkpoint.model_copy(update={"replayed": True})
        return PaginationOutcome(replay, ())

    now = datetime.now(UTC)
    if checkpoint is None or (
        checkpoint.endpoint != endpoint
        or checkpoint.parameters_hash != parameters_hash
    ):
        manifest = PaginationManifest(
            endpoint=endpoint,
            parameters_hash=parameters_hash,
            status="RUNNING",
            started_at=now,
        )
    else:
        manifest = checkpoint.model_copy(
            update={"status": "RUNNING", "error_code": None, "replayed": False}
        )

    evidences = list(manifest.pages)
    records: list[dict[str, object]] = []
    seen_hashes = {
        evidence.payload_hash
        for evidence in evidences
        if evidence.payload_hash is not None and evidence.rows > 0
    }
    page = manifest.next_page
    calls = manifest.calls
    total_rows = manifest.rows
    total_pages = manifest.expected_total_pages

    while page <= max_pages:
        try:
            result = fetch_page(page)
        except TransientProviderError:
            failed = manifest.model_copy(
                update={
                    "status": "RETRYABLE",
                    "next_page": page,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": "TRANSIENT_PROVIDER_ERROR",
                }
            )
            _write_checkpoint(checkpoint_path, failed)
            return PaginationOutcome(failed, tuple(records))

        calls += 1
        if result.availability == DataAvailability.ERROR:
            failed = manifest.model_copy(
                update={
                    "status": "FAILED",
                    "finished_at": datetime.now(UTC),
                    "next_page": page,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": f"HTTP_{result.http_status or 'ERROR'}",
                }
            )
            _write_checkpoint(checkpoint_path, failed)
            return PaginationOutcome(failed, tuple(records))

        if (
            result.paging_current != page
            or result.paging_total < result.paging_current
            or result.paging_total < 1
        ):
            failed = manifest.model_copy(
                update={
                    "status": "FAILED",
                    "finished_at": datetime.now(UTC),
                    "next_page": page,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": "INCONSISTENT_PAGINATION",
                }
            )
            _write_checkpoint(checkpoint_path, failed)
            return PaginationOutcome(failed, tuple(records))

        if total_pages is None:
            total_pages = result.paging_total
        elif total_pages != result.paging_total:
            failed = manifest.model_copy(
                update={
                    "status": "FAILED",
                    "finished_at": datetime.now(UTC),
                    "next_page": page,
                    "expected_total_pages": total_pages,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": "TOTAL_PAGES_CHANGED",
                }
            )
            _write_checkpoint(checkpoint_path, failed)
            return PaginationOutcome(failed, tuple(records))

        page_rows = len(result.records)
        if (
            page_rows > 0
            and result.raw_payload_hash is not None
            and result.raw_payload_hash in seen_hashes
        ):
            failed = manifest.model_copy(
                update={
                    "status": "FAILED",
                    "finished_at": datetime.now(UTC),
                    "next_page": page,
                    "expected_total_pages": total_pages,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": "DUPLICATE_PAGE_PAYLOAD",
                }
            )
            _write_checkpoint(checkpoint_path, failed)
            return PaginationOutcome(failed, tuple(records))

        received = result.received_at or result.observed_at
        evidences.append(
            PageEvidence(
                page=page,
                rows=page_rows,
                payload_hash=result.raw_payload_hash,
                raw_observation_id=result.raw_observation_id,
                quota_remaining=result.quota.remaining,
                received_at=received,
            )
        )
        if result.raw_payload_hash is not None and page_rows > 0:
            seen_hashes.add(result.raw_payload_hash)
        records.extend(result.records)
        total_rows += page_rows

        if page_rows == 0 and page < result.paging_total:
            partial = manifest.model_copy(
                update={
                    "status": "PARTIAL",
                    "finished_at": datetime.now(UTC),
                    "next_page": page,
                    "expected_total_pages": total_pages,
                    "pages": tuple(evidences),
                    "calls": calls,
                    "rows": total_rows,
                    "error_code": "EMPTY_INTERMEDIATE_PAGE",
                }
            )
            _write_checkpoint(checkpoint_path, partial)
            return PaginationOutcome(partial, tuple(records))

        next_page = page + 1
        running = manifest.model_copy(
            update={
                "status": "RUNNING",
                "next_page": next_page,
                "expected_total_pages": total_pages,
                "pages": tuple(evidences),
                "calls": calls,
                "rows": total_rows,
            }
        )
        _write_checkpoint(checkpoint_path, running)

        remaining = result.quota.remaining
        if remaining is not None and remaining <= quota_reserve and page < total_pages:
            paused = running.model_copy(
                update={
                    "status": "PAUSED_QUOTA",
                    "finished_at": datetime.now(UTC),
                    "error_code": "QUOTA_RESERVE_REACHED",
                }
            )
            _write_checkpoint(checkpoint_path, paused)
            return PaginationOutcome(paused, tuple(records))

        if page >= result.paging_total:
            completed = running.model_copy(
                update={
                    "status": "COMPLETED",
                    "finished_at": datetime.now(UTC),
                    "error_code": None,
                }
            )
            _write_checkpoint(checkpoint_path, completed)
            return PaginationOutcome(completed, tuple(records))
        page = next_page

    exceeded = manifest.model_copy(
        update={
            "status": "FAILED",
            "finished_at": datetime.now(UTC),
            "next_page": page,
            "expected_total_pages": total_pages,
            "pages": tuple(evidences),
            "calls": calls,
            "rows": total_rows,
            "error_code": "MAX_PAGES_EXCEEDED",
        }
    )
    _write_checkpoint(checkpoint_path, exceeded)
    return PaginationOutcome(exceeded, tuple(records))
