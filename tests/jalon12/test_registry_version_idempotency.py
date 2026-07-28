from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, func, select

from robin.prospective_observatory.contracts import CaptureFamily
from robin.prospective_observatory.r2 import ProspectiveR2Repository
from robin.storage.database import build_engine
from scripts.run_prospective_observatory import (
    DirectoryObjectStore,
    MemoryOperationalState,
    ObservatoryPolicy,
    SQLAlchemyOperationalState,
    _active_windows,
    _due_windows,
    _filter_fixtures,
    run_fixture_registry,
    run_scheduler,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _cache(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [
                    {
                        "fixture": {
                            "id": 9001,
                            "date": (NOW + timedelta(hours=2)).isoformat(),
                            "status": {"short": "NS"},
                        },
                        "league": {
                            "id": 61,
                            "name": "Ligue 1",
                            "season": 2026,
                            "round": "Regular Season - 1",
                        },
                        "teams": {
                            "home": {"id": 1, "name": "Paris"},
                            "away": {"id": 2, "name": "Lyon"},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _fixture_record(
    *,
    status: str = "NS",
    phase: str = "Regular Season - 1",
    kickoff: str | None = None,
) -> dict[str, object]:
    return {
        "fixture": {
            "id": 9001,
            "date": kickoff or (NOW + timedelta(hours=2)).isoformat(),
            "status": {"short": status},
        },
        "league": {
            "id": 61,
            "name": "Ligue 1",
            "season": 2026,
            "round": phase,
        },
        "teams": {
            "home": {"id": 1, "name": "Paris"},
            "away": {"id": 2, "name": "Lyon"},
        },
    }


def _args(
    *,
    output: Path,
    cache: Path,
    store: Path,
    now: datetime,
    revision: str,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="fixture-registry",
        policy=POLICY,
        output=output,
        now=now.isoformat(),
        code_revision=revision,
        cache=cache,
        object_store_root=store,
        estimate=False,
        execute=False,
        estimate_file=None,
        competition="Ligue 1",
        max_attempts=1,
        max_objects=250,
    )


def _register_twice(
    *,
    state: MemoryOperationalState,
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    cache = _cache(tmp_path / "fixtures.json")
    store_root = tmp_path / "objects"
    repository = ProspectiveR2Repository(DirectoryObjectStore(store_root))
    first = run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store_root,
            now=NOW,
            revision="revision-a",
        ),
        state=state,
        repository=repository,
    )
    second = run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store_root,
            now=NOW + timedelta(minutes=5),
            revision="revision-b",
        ),
        state=state,
        repository=repository,
    )
    return first, second


def test_registry_reobservation_is_not_a_new_memory_business_version(
    tmp_path: Path,
) -> None:
    state = MemoryOperationalState()
    first, second = _register_twice(state=state, tmp_path=tmp_path)

    assert first["fixtures_inserted"] == 1
    assert second["fixtures_inserted"] == 0
    assert second["duplicates_avoided"] == 1
    assert len(state.fixtures()) == 1


def test_registry_reobservation_is_not_a_new_sql_business_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{(tmp_path / 'state.db').as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = build_engine(url)
    state = SQLAlchemyOperationalState(engine)

    first, second = _register_twice(state=state, tmp_path=tmp_path)

    fixture_table = Table("prospective_fixtures", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        count = connection.execute(
            select(func.count()).select_from(fixture_table)
        ).scalar_one()
    assert first["fixtures_inserted"] == 1
    assert second["fixtures_inserted"] == 0
    assert second["duplicates_avoided"] == 1
    assert count == 1


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_fixture_record(status="TBD"), "unreliable_status"),
        (_fixture_record(phase="TBD"), "unverified_phase"),
        (
            _fixture_record(kickoff="2026-08-01T14:00:00"),
            "non_utc_kickoff",
        ),
    ],
)
def test_registry_excludes_unreliable_provider_fixtures(
    record: dict[str, object],
    reason: str,
) -> None:
    selected = _filter_fixtures(
        [record],
        policy=ObservatoryPolicy.load(POLICY),
        competition="Ligue 1",
        now=NOW,
        code_revision=f"test-{reason}",
        expected_season=2026,
    )
    assert selected == ()


def test_cancellation_tombstone_deactivates_previously_scheduled_windows(
    tmp_path: Path,
) -> None:
    state = MemoryOperationalState()
    cache = _cache(tmp_path / "fixtures.json")
    store = tmp_path / "objects"
    repository = ProspectiveR2Repository(DirectoryObjectStore(store))
    first_args = _args(
        output=tmp_path / "reports",
        cache=cache,
        store=store,
        now=NOW,
        revision="active",
    )
    run_fixture_registry(first_args, state=state, repository=repository)
    scheduler_args = argparse.Namespace(**vars(first_args))
    scheduler_args.command = "scheduler"
    run_scheduler(scheduler_args, state=state)
    assert state.fixtures()

    cache.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [_fixture_record(status="CANC")],
            }
        ),
        encoding="utf-8",
    )
    cancelled_args = _args(
        output=tmp_path / "reports",
        cache=cache,
        store=store,
        now=NOW + timedelta(minutes=5),
        revision="cancelled",
    )
    cancelled = run_fixture_registry(
        cancelled_args,
        state=state,
        repository=repository,
    )

    assert cancelled["fixtures_inserted"] == 1
    assert state.fixtures() == ()
    assert (
        _due_windows(
            state,
            families=tuple(CaptureFamily),
            now=NOW + timedelta(minutes=5),
        )
        == ()
    )


def test_cancellation_tombstone_survives_sql_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{(tmp_path / 'cancelled.db').as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = build_engine(url)
    state = SQLAlchemyOperationalState(engine)
    cache = _cache(tmp_path / "fixtures.json")
    store = tmp_path / "objects"
    repository = ProspectiveR2Repository(DirectoryObjectStore(store))
    run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store,
            now=NOW,
            revision="active",
        ),
        state=state,
        repository=repository,
    )
    cache.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [_fixture_record(status="PST")],
            }
        ),
        encoding="utf-8",
    )
    run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store,
            now=NOW + timedelta(minutes=5),
            revision="postponed",
        ),
        state=state,
        repository=repository,
    )
    engine.dispose()

    restarted = SQLAlchemyOperationalState(build_engine(url))
    assert restarted.fixtures() == ()


def test_same_kickoff_reactivation_is_append_only_and_survives_sql_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"sqlite:///{(tmp_path / 'reactivated.db').as_posix()}"
    monkeypatch.setenv("ROBIN_DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    engine = build_engine(url)
    state = SQLAlchemyOperationalState(engine)
    cache = _cache(tmp_path / "fixtures.json")
    store = tmp_path / "objects"
    repository = ProspectiveR2Repository(DirectoryObjectStore(store))

    active_args = _args(
        output=tmp_path / "reports",
        cache=cache,
        store=store,
        now=NOW,
        revision="active-v1",
    )
    run_fixture_registry(active_args, state=state, repository=repository)
    scheduler_args = argparse.Namespace(**vars(active_args))
    scheduler_args.command = "scheduler"
    run_scheduler(scheduler_args, state=state)
    original_window_ids = {window.window_id for window in state.windows()}
    original_hash = state.fixtures()[0].registry_hash

    cache.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [_fixture_record(status="TBD")],
            }
        ),
        encoding="utf-8",
    )
    run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store,
            now=NOW + timedelta(minutes=5),
            revision="tombstone",
        ),
        state=state,
        repository=repository,
    )
    engine.dispose()

    tombstoned = SQLAlchemyOperationalState(build_engine(url))
    assert tombstoned.fixtures() == ()
    cache.write_text(
        json.dumps(
            {
                "current_season": 2026,
                "fixtures": [_fixture_record(status="NS")],
            }
        ),
        encoding="utf-8",
    )
    reactivation_args = _args(
        output=tmp_path / "reports",
        cache=cache,
        store=store,
        now=NOW + timedelta(minutes=10),
        revision="active-v2",
    )
    reactivated = run_fixture_registry(
        reactivation_args,
        state=tombstoned,
        repository=repository,
    )
    scheduler_args = argparse.Namespace(**vars(reactivation_args))
    scheduler_args.command = "scheduler"
    scheduled = run_scheduler(scheduler_args, state=tombstoned)

    active = tombstoned.fixtures()
    assert reactivated["fixtures_inserted"] == 1
    assert len(active) == 1
    assert active[0].kickoff_at == NOW + timedelta(hours=2)
    assert active[0].registry_hash != original_hash
    assert scheduled["windows_inserted"] > 0
    reactivated_window_ids = {
        window.window_id for window in _active_windows(tombstoned)
    }
    assert reactivated_window_ids
    assert original_window_ids.isdisjoint(reactivated_window_ids)

    repeated = run_fixture_registry(
        _args(
            output=tmp_path / "reports",
            cache=cache,
            store=store,
            now=NOW + timedelta(minutes=15),
            revision="active-v2-reobserved",
        ),
        state=tombstoned,
        repository=repository,
    )
    assert repeated["fixtures_inserted"] == 0
    assert repeated["duplicates_avoided"] == 1
    tombstoned.engine.dispose()

    restored = SQLAlchemyOperationalState(build_engine(url))
    assert len(restored.fixtures()) == 1
    assert restored.fixtures()[0].registry_hash == active[0].registry_hash
    fixture_table = Table(
        "prospective_fixtures",
        MetaData(),
        autoload_with=restored.engine,
    )
    with restored.engine.connect() as connection:
        versions = connection.execute(
            select(
                fixture_table.c.registry_hash,
                fixture_table.c.cancelled,
            ).order_by(fixture_table.c.registered_at)
        ).all()
    assert len(versions) == 3
    assert [bool(row.cancelled) for row in versions] == [
        False,
        True,
        False,
    ]
    assert len({str(row.registry_hash) for row in versions}) == 3
