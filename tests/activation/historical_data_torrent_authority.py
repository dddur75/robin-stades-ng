"""Explicit historical authority clock for legacy activation scenarios only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import robin.chronos_production as production_contract

DATA_TORRENT_AUTHORITY_NOT_BEFORE = datetime(2026, 8, 30, 6, 36, tzinfo=UTC)
DATA_TORRENT_AUTHORITY_ADMISSION_CLOSE = datetime(2026, 9, 1, 22, 0, tzinfo=UTC)

_REAL_VALIDATE_DATA_TORRENT_AUTHORITY = production_contract.validate_data_torrent_authority


def validate_historical_data_torrent_authority(
    *,
    now: datetime,
    repository_root: Path | None = None,
) -> datetime:
    """Run the real authority contract at the instant owned by the scenario."""

    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError("historical authority instant must be UTC")
    if not DATA_TORRENT_AUTHORITY_NOT_BEFORE <= now < DATA_TORRENT_AUTHORITY_ADMISSION_CLOSE:
        raise ValueError("historical authority instant must be inside the active window")
    return _REAL_VALIDATE_DATA_TORRENT_AUTHORITY(
        now=now,
        repository_root=repository_root,
    )


def bind_historical_data_torrent_authority(
    monkeypatch: Any,
    *modules: Any,
    now: datetime,
) -> None:
    """Bind only scenario-local imported aliases; never freeze the global clock."""

    def validate_at_scenario_instant(
        *,
        now: datetime | None = None,
        repository_root: Path | None = None,
    ) -> datetime:
        return validate_historical_data_torrent_authority(
            now=now if now is not None else scenario_now,
            repository_root=repository_root,
        )

    scenario_now = now
    for module in modules:
        monkeypatch.setattr(
            module,
            "validate_data_torrent_authority",
            validate_at_scenario_instant,
        )


def install_subprocess_historical_data_torrent_authority(*, now: datetime) -> None:
    """Install the same real, explicit clock inside one test-owned subprocess."""

    def validate_at_scenario_instant(
        *,
        now: datetime | None = None,
        repository_root: Path | None = None,
    ) -> datetime:
        return validate_historical_data_torrent_authority(
            now=now if now is not None else scenario_now,
            repository_root=repository_root,
        )

    scenario_now = now
    production_contract.validate_data_torrent_authority = validate_at_scenario_instant
