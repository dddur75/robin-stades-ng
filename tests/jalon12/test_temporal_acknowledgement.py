from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureContext,
    CaptureFamily,
    CaptureWindow,
    ProspectiveFixture,
    RetryDisposition,
)
from robin.prospective_observatory.gates import (
    GateObservation,
    GateStatus,
    evaluate_fixture_gates,
)
from robin.prospective_observatory.r2 import (
    InMemoryObjectStore,
    ProspectiveR2Repository,
)
from robin.prospective_observatory.temporal import (
    CAPTURE_POLICIES,
    LEGACY_VERSIONED_WINDOW_ID_PREFIXES,
    VERSIONED_WINDOW_ID_PREFIX,
    VERSIONED_WINDOW_ID_PREFIXES,
    WINDOW_POLICY_VERSION,
    classify_window,
    is_versioned_window_id,
    retry_disposition,
    schedule_windows,
)
from scripts.run_prospective_observatory import _capture_estimated_units

KICKOFF = datetime(2026, 8, 15, 19, tzinfo=UTC)
SCHEDULED_AT = datetime(2026, 7, 20, 12, tzinfo=UTC)


def _fixture(
    *,
    fixture_id: str = "ligue1-2026-001",
    kickoff_at: datetime = KICKOFF,
) -> ProspectiveFixture:
    return ProspectiveFixture(
        fixture_id=fixture_id,
        competition="Ligue 1",
        season="2026",
        phase="Regular Season",
        home_team_id="team-home",
        away_team_id="team-away",
        kickoff_at=kickoff_at,
        provider="api-football",
        provider_fixture_id="123456",
        registered_at=SCHEDULED_AT,
        code_revision="revision-j12-temporal-v2",
    )


def _windows_by_family(
    fixture: ProspectiveFixture,
) -> dict[CaptureFamily, tuple[CaptureWindow, ...]]:
    return {
        family: schedule_windows(
            fixture,
            family,
            scheduled_at=SCHEDULED_AT,
        )
        for family in CaptureFamily
    }


def test_policy_v2_has_49_non_overlapping_windows_per_fixture() -> None:
    fixture = _fixture()
    windows_by_family = _windows_by_family(fixture)

    assert WINDOW_POLICY_VERSION == "prospective-capture-window-v2"
    assert VERSIONED_WINDOW_ID_PREFIX == "prospective-window-v3:"
    assert len(VERSIONED_WINDOW_ID_PREFIXES) == len(
        set(VERSIONED_WINDOW_ID_PREFIXES)
    )
    assert VERSIONED_WINDOW_ID_PREFIXES[-1] == VERSIONED_WINDOW_ID_PREFIX
    assert "prospective-window-v2:" in LEGACY_VERSIONED_WINDOW_ID_PREFIXES
    assert all(
        is_versioned_window_id(f"{prefix}immutable-id")
        for prefix in VERSIONED_WINDOW_ID_PREFIXES
    )

    assert sum(len(windows) for windows in windows_by_family.values()) == 49
    assert sum(
        len(windows)
        for index in range(9)
        for windows in _windows_by_family(
            _fixture(fixture_id=f"ligue1-2026-{index:03d}")
        ).values()
    ) == 441

    for family, windows in windows_by_family.items():
        assert len(windows) == len(CAPTURE_POLICIES[family])
        for left_index, left in enumerate(windows):
            assert left.window_id.startswith(VERSIONED_WINDOW_ID_PREFIX)
            for right in windows[left_index + 1 :]:
                assert (
                    left.cutoff_at <= right.opens_at
                    or right.cutoff_at <= left.opens_at
                ), (family, left.label, right.label)


def test_h2_and_near_kickoff_are_adjacent_canonical_buckets() -> None:
    for family in (
        CaptureFamily.FIXTURE,
        CaptureFamily.TEAM,
        CaptureFamily.PLAYER_STATUS,
        CaptureFamily.INJURY,
        CaptureFamily.LINEUP,
        CaptureFamily.FORMATION,
        CaptureFamily.ODDS,
        CaptureFamily.EVENT_STATUS,
    ):
        windows = schedule_windows(
            _fixture(),
            family,
            scheduled_at=SCHEDULED_AT,
        )
        h2 = next(window for window in windows if window.label == "H-2")
        near = next(
            window for window in windows if window.label == "NEAR_KICKOFF"
        )

        assert (h2.opens_at, h2.cutoff_at) == (
            KICKOFF - timedelta(hours=3),
            KICKOFF - timedelta(hours=1),
        )
        assert (near.opens_at, near.cutoff_at) == (
            KICKOFF - timedelta(hours=1),
            KICKOFF - timedelta(microseconds=1),
        )
        assert h2.cutoff_at == near.opens_at


@pytest.mark.parametrize(
    ("delta", "expected_label"),
    (
        (timedelta(hours=2, minutes=30), "H-2"),
        (timedelta(hours=2), "H-2"),
        (timedelta(hours=1, minutes=30), "H-2"),
        (timedelta(hours=1), "NEAR_KICKOFF"),
        (timedelta(minutes=50), "NEAR_KICKOFF"),
        (timedelta(minutes=45), "NEAR_KICKOFF"),
        (timedelta(minutes=37), "NEAR_KICKOFF"),
        (timedelta(minutes=30), "NEAR_KICKOFF"),
        (timedelta(minutes=17), "NEAR_KICKOFF"),
        (timedelta(minutes=15), "NEAR_KICKOFF"),
        (timedelta(minutes=5), "NEAR_KICKOFF"),
        (-timedelta(minutes=1), None),
        (-timedelta(hours=1), None),
    ),
)
def test_frozen_clock_matrix_has_one_canonical_due_window(
    delta: timedelta,
    expected_label: str | None,
) -> None:
    now = KICKOFF - delta
    for family, windows in _windows_by_family(_fixture()).items():
        due_labels = {
            window.label
            for window in windows
            if classify_window(window, now=now) is AvailabilityStatus.DUE
        }
        if family is CaptureFamily.SQUAD:
            assert due_labels == set()
        elif expected_label is None:
            assert due_labels == set()
        else:
            assert due_labels == {expected_label}


@pytest.mark.parametrize(
    ("delta", "work_expected"),
    (
        (timedelta(hours=2, minutes=30), True),
        (timedelta(hours=2), True),
        (timedelta(hours=1, minutes=30), True),
        (timedelta(hours=1), True),
        (timedelta(minutes=50), True),
        (timedelta(minutes=45), True),
        (timedelta(minutes=37), True),
        (timedelta(minutes=30), True),
        (timedelta(minutes=17), True),
        (timedelta(minutes=15), True),
        (timedelta(minutes=5), True),
        (-timedelta(minutes=1), False),
        (-timedelta(hours=1), False),
    ),
)
def test_frozen_clock_matrix_has_bounded_operational_outcome(
    delta: timedelta,
    work_expected: bool,
) -> None:
    fixture = _fixture()
    now = KICKOFF - delta
    by_family = _windows_by_family(fixture)
    due_by_family = {
        family: tuple(
            window
            for window in windows
            if classify_window(window, now=now) is AvailabilityStatus.DUE
        )
        for family, windows in by_family.items()
    }
    commands = {
        "capture-general": (
            CaptureFamily.FIXTURE,
            CaptureFamily.TEAM,
            CaptureFamily.EVENT_STATUS,
        ),
        "capture-player": (
            CaptureFamily.SQUAD,
            CaptureFamily.PLAYER_STATUS,
            CaptureFamily.INJURY,
        ),
        "capture-lineup": (
            CaptureFamily.LINEUP,
            CaptureFamily.FORMATION,
        ),
        "capture-odds": (CaptureFamily.ODDS,),
    }
    estimated_units = {
        command: _capture_estimated_units(
            command,
            tuple(
                window
                for family in families
                for window in due_by_family[family]
            ),
        )[1]
        for command, families in commands.items()
    }

    if not work_expected:
        assert estimated_units == {
            "capture-general": 0,
            "capture-player": 0,
            "capture-lineup": 0,
            "capture-odds": 0,
        }
        near = next(
            window
            for window in by_family[CaptureFamily.LINEUP]
            if window.label == "NEAR_KICKOFF"
        )
        assert classify_window(near, now=now) is (
            AvailabilityStatus.MISSED_WINDOW
        )
        assert retry_disposition(
            window=near,
            now=now,
            attempts=1,
        ) is RetryDisposition.LATE_RETRY
        return

    assert estimated_units == {
        "capture-general": 2,
        "capture-player": 3,
        "capture-lineup": 3,
        "capture-odds": 2,
    }
    assert all(
        len(windows) <= 1 for windows in due_by_family.values()
    )
    lineup_window = due_by_family[CaptureFamily.LINEUP][0]
    stored = ProspectiveR2Repository(InMemoryObjectStore()).capture(
        payload={"lineups": "validated-by-projection-contract"},
        context=CaptureContext(
            window_id=lineup_window.window_id,
            window_label=lineup_window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="api-football",
            family=CaptureFamily.LINEUP,
            requested_at=now,
            response_received_at=now,
            observed_at=now,
            kickoff_at=fixture.kickoff_at,
            cutoff_at=lineup_window.cutoff_at,
            http_status=200,
            source_endpoint="/fixtures/lineups",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision=fixture.code_revision,
            materialized_at=now,
        ),
    )
    observations = tuple(
        GateObservation(
            receipt=stored.receipt,
            projection={
                "team_id": team,
                "starters": [f"{team}-{index}" for index in range(11)],
            },
        )
        for team in ("home", "away")
    )
    lineup_gate = evaluate_fixture_gates(
        fixture.fixture_id,
        observations,
    )[2]
    assert stored.receipt.temporally_admissible
    assert lineup_gate.status is GateStatus.PASSED
    assert lineup_gate.observations == 1
    assert retry_disposition(
        window=lineup_window,
        now=now,
        attempts=1,
    ) is RetryDisposition.RETRY_PENDING


def test_kickoff_change_generates_a_disjoint_window_generation() -> None:
    original = _fixture()
    delayed = original.model_copy(
        update={"kickoff_at": original.kickoff_at + timedelta(minutes=30)}
    )
    original_ids = {
        window.window_id
        for windows in _windows_by_family(original).values()
        for window in windows
    }
    delayed_ids = {
        window.window_id
        for windows in _windows_by_family(delayed).values()
        for window in windows
    }

    assert len(original_ids) == 49
    assert len(delayed_ids) == 49
    assert original_ids.isdisjoint(delayed_ids)


def test_response_before_window_opening_is_never_temporal_evidence() -> None:
    fixture = _fixture()
    window = next(
        item
        for item in schedule_windows(
            fixture,
            CaptureFamily.LINEUP,
            scheduled_at=SCHEDULED_AT,
        )
        if item.label == "H-2"
    )
    received_at = window.opens_at - timedelta(seconds=1)
    stored = ProspectiveR2Repository(InMemoryObjectStore()).capture(
        payload={"lineups": []},
        context=CaptureContext(
            window_id=window.window_id,
            window_label=window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider="api-football",
            family=window.family,
            requested_at=received_at - timedelta(seconds=1),
            response_received_at=received_at,
            observed_at=received_at,
            kickoff_at=fixture.kickoff_at,
            cutoff_at=window.cutoff_at,
            http_status=200,
            source_endpoint="/fixtures/lineups",
            complete=True,
            quality_status=AvailabilityStatus.CAPTURED,
            provider_calls=1,
            code_revision=fixture.code_revision,
            materialized_at=received_at,
        ),
    )

    assert not stored.receipt.temporally_admissible
