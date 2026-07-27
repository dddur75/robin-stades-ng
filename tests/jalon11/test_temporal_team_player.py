from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from robin.deep_football.availability import (
    AbsenceObservation,
    absence_known_before,
    count_unavailable_roles,
    infer_absence_from_non_selection,
)
from robin.deep_football.player_features import (
    PlayerAppearance,
    baseline_centre_back_before,
    player_form_before,
    prior_appearances,
    usual_starter_before,
)
from robin.deep_football.team_features import (
    CoachObservation,
    TeamMatch,
    build_team_prematch_features,
    coach_tenure_before,
)
from robin.deep_football.temporal import (
    TemporalInput,
    assert_feature_allowlist,
    assert_input_available_strictly_before_cutoff,
    assert_market_alignment,
)

TARGET = datetime(2026, 7, 27, 18, tzinfo=UTC)


def _temporal_input(
    *,
    available_at: datetime | None = None,
    lineage_hash: str = "a" * 64,
    source: str = "API_FOOTBALL",
) -> TemporalInput:
    return TemporalInput(
        input_id="input-1",
        available_at=available_at or TARGET - timedelta(minutes=1),
        cutoff_at=TARGET,
        lineage_hash=lineage_hash,
        source=source,
    )


def _appearance(
    offset_days: int,
    *,
    fixture_id: str | None = None,
    player_id: str = "p1",
    minutes: int | None = 90,
    started: bool | None = True,
    goals: int | None = 0,
    assists: int | None = 0,
    shots: int | None = 1,
    observed_delta: timedelta = timedelta(hours=3),
    position: str | None = "centre-back",
) -> PlayerAppearance:
    kickoff = TARGET - timedelta(days=offset_days)
    return PlayerAppearance(
        fixture_id=fixture_id or f"f-{offset_days}",
        player_id=player_id,
        team_id="team-a",
        kickoff_at=kickoff,
        minutes=minutes,
        started=started,
        goals=goals,
        assists=assists,
        shots=shots,
        observed_at=kickoff + observed_delta,
        position=position,
    )


def _absence(
    player_id: str,
    *,
    role_start: datetime | None = None,
    observed_at: datetime | None = None,
    unavailable_until: datetime | None = None,
    confidence: float = 1.0,
    team_id: str = "team-a",
) -> AbsenceObservation:
    return AbsenceObservation(
        player_id=player_id,
        team_id=team_id,
        observed_at=observed_at or TARGET - timedelta(days=2),
        unavailable_from=role_start or TARGET - timedelta(days=3),
        unavailable_until=unavailable_until,
        source="TIMESTAMPED_SOURCE",
        reason="injury",
        identity_confidence=confidence,
    )


def test_cutoff_is_strict_and_requires_lineage_and_source() -> None:
    assert_input_available_strictly_before_cutoff([_temporal_input()])

    with pytest.raises(ValueError, match="INPUT_NOT_STRICTLY_BEFORE_CUTOFF"):
        assert_input_available_strictly_before_cutoff(
            [_temporal_input(available_at=TARGET)]
        )
    with pytest.raises(ValueError, match="INPUT_LINEAGE_HASH_INVALID"):
        assert_input_available_strictly_before_cutoff(
            [_temporal_input(lineage_hash="not-a-hash")]
        )
    with pytest.raises(ValueError, match="INPUT_SOURCE_MISSING"):
        assert_input_available_strictly_before_cutoff(
            [_temporal_input(source="")]
        )
    with pytest.raises(ValueError, match="TEMPORAL_INPUTS_REQUIRED"):
        assert_input_available_strictly_before_cutoff([])


def test_feature_allowlist_preserves_missing_and_rejects_targets() -> None:
    row = {
        "elo": "1510.5",
        "rest_days": None,
        "target_home_goals": 4,
    }
    assert assert_feature_allowlist(row, ["elo", "rest_days"]) == (1510.5, None)

    with pytest.raises(ValueError, match="TARGET_FIELD_IN_FEATURE_ALLOWLIST"):
        assert_feature_allowlist(row, ["target_home_goals"])
    with pytest.raises(ValueError, match="NON_NUMERIC_FEATURE"):
        assert_feature_allowlist({"formation": "4-3-3"}, ["formation"])


def test_market_alignment_requires_fixture_and_exact_live_timestamp() -> None:
    assert_market_alignment(
        feature_fixture_id="fixture-1",
        market_fixture_id="fixture-1",
        market_available_at=TARGET - timedelta(seconds=1),
        cutoff_at=TARGET,
        require_exact_observed_at=True,
    )
    assert_market_alignment(
        feature_fixture_id="fixture-1",
        market_fixture_id="fixture-1",
        market_available_at=None,
        cutoff_at=TARGET,
        require_exact_observed_at=False,
    )

    with pytest.raises(ValueError, match="MARKET_FIXTURE_ID_MISMATCH"):
        assert_market_alignment(
            feature_fixture_id="fixture-1",
            market_fixture_id="fixture-2",
            market_available_at=TARGET - timedelta(minutes=1),
            cutoff_at=TARGET,
            require_exact_observed_at=True,
        )
    with pytest.raises(ValueError, match="MARKET_EXACT_OBSERVED_AT_REQUIRED"):
        assert_market_alignment(
            feature_fixture_id="fixture-1",
            market_fixture_id="fixture-1",
            market_available_at=None,
            cutoff_at=TARGET,
            require_exact_observed_at=True,
        )
    with pytest.raises(ValueError, match="FUTURE_MARKET_PRICE_FORBIDDEN"):
        assert_market_alignment(
            feature_fixture_id="fixture-1",
            market_fixture_id="fixture-1",
            market_available_at=TARGET,
            cutoff_at=TARGET,
            require_exact_observed_at=True,
        )


def test_team_rolling_windows_are_built_before_target_result() -> None:
    start = datetime(2026, 1, 1, 18, tzinfo=UTC)
    matches = [
        TeamMatch(
            fixture_id=f"f-{index}",
            kickoff_at=start + timedelta(days=7 * index),
            home_team="A",
            away_team=f"B-{index}",
            home_goals=index % 3,
            away_goals=0,
        )
        for index in range(11)
    ]
    rows = build_team_prematch_features(matches)
    first = rows[0]
    target = rows[-1]

    assert first["home_points_3"] is None
    assert first["home_goals_for_10"] is None
    assert target["home_points_3"] == 7
    assert target["home_points_5"] == 11
    assert target["home_points_10"] == 22
    assert target["home_goals_for_3"] == pytest.approx(1.0)
    assert target["home_goals_for_5"] == pytest.approx(1.0)
    assert target["home_goals_for_10"] == pytest.approx(0.9)
    assert target["feature_cutoff"] == "STRICTLY_BEFORE_TARGET_KICKOFF"


def test_calendar_congestion_and_rest_are_strictly_historical() -> None:
    matches = [
        TeamMatch("old", TARGET - timedelta(days=20), "A", "B", 1, 0),
        TeamMatch("recent", TARGET - timedelta(days=6), "A", "C", 0, 0),
        TeamMatch("target", TARGET, "A", "D", 9, 0),
    ]
    target = build_team_prematch_features(matches)[-1]

    assert target["home_rest_days"] == 6.0
    assert target["home_matches_7d"] == 1
    assert target["home_matches_14d"] == 1
    assert target["home_matches_21d"] == 2
    assert target["home_goals_for_3"] == pytest.approx(0.5)


def test_team_feature_builder_rejects_invalid_windows_and_simultaneous_history() -> None:
    with pytest.raises(ValueError, match="TEAM_WINDOWS_MUST_BE_SORTED"):
        build_team_prematch_features([], windows=(5, 3))

    simultaneous = [
        TeamMatch("f-1", TARGET, "A", "B", 1, 0),
        TeamMatch("f-2", TARGET, "A", "C", 2, 0),
    ]
    with pytest.raises(ValueError, match="TEAM_HISTORY_NOT_STRICTLY_BEFORE_TARGET"):
        build_team_prematch_features(simultaneous)


def test_coach_tenure_uses_only_observations_known_before_target() -> None:
    observations = [
        CoachObservation(
            "A",
            "coach-old",
            TARGET - timedelta(days=100),
            TARGET - timedelta(days=100),
        ),
        CoachObservation(
            "A",
            "coach-current",
            TARGET - timedelta(days=20),
            TARGET - timedelta(days=19),
        ),
        CoachObservation(
            "A",
            "future-coach",
            TARGET - timedelta(days=1),
            TARGET + timedelta(minutes=1),
        ),
    ]
    matches = [
        TeamMatch(
            f"f-{index}",
            TARGET - timedelta(days=18 - index * 3),
            "A",
            f"B-{index}",
            1,
            0,
        )
        for index in range(5)
    ]
    result = coach_tenure_before(
        observations,
        matches,
        team_id="A",
        target_kickoff=TARGET,
    )

    assert result == {
        "coach_id": "coach-current",
        "matches_since_change": 5,
        "recent_change": True,
    }


def test_unknown_coach_remains_missing() -> None:
    result = coach_tenure_before(
        [],
        [],
        team_id="A",
        target_kickoff=TARGET,
    )
    assert result == {
        "coach_id": None,
        "matches_since_change": None,
        "recent_change": None,
    }


def test_prior_appearances_excludes_target_future_and_unused_bench() -> None:
    appearances = [
        _appearance(5),
        _appearance(4, minutes=0),
        _appearance(3, minutes=None),
        _appearance(2, fixture_id="target"),
        _appearance(
            1,
            observed_delta=timedelta(days=2),
        ),
        _appearance(-1),
    ]
    previous = prior_appearances(
        appearances,
        player_id="p1",
        target_fixture_id="target",
        target_kickoff=TARGET,
        count=3,
    )
    assert tuple(item.fixture_id for item in previous) == ("f-5",)


def test_player_form_uses_appearances_and_never_turns_missing_into_zero() -> None:
    appearances = [
        _appearance(3, goals=1, assists=0, shots=2),
        _appearance(2, goals=None, assists=0, shots=None),
        _appearance(1, goals=1, assists=1, shots=3),
    ]
    form = player_form_before(
        appearances,
        player_id="p1",
        target_fixture_id="target",
        target_kickoff=TARGET,
    )

    assert form["history_status"] == "SUFFICIENT_HISTORY"
    assert form["appearances"] == 3
    assert form["minutes"] == 270
    assert form["starts"] == 3
    assert form["goals"] is None
    assert form["goal_involvements"] is None
    assert form["shots"] is None
    assert form["target_fixture_excluded"] is True


def test_player_without_appearances_is_explicitly_insufficient() -> None:
    form = player_form_before(
        [],
        player_id="p1",
        target_fixture_id="target",
        target_kickoff=TARGET,
    )
    assert form["history_status"] == "INSUFFICIENT_HISTORY"
    assert form["appearances"] == 0
    assert form["minutes"] is None
    assert form["goals"] is None


def test_usual_starter_requires_support_and_observed_starter_flags() -> None:
    regular = [
        _appearance(index, started=index <= 5)
        for index in range(8, 0, -1)
    ]
    assert (
        usual_starter_before(
            regular,
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is True
    )
    assert (
        usual_starter_before(
            regular[:3],
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is None
    )
    with_missing_flag = [*regular[:-1], _appearance(1, started=None)]
    assert (
        usual_starter_before(
            with_missing_flag,
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is None
    )


def test_baseline_centre_back_requires_observed_role_and_four_starts() -> None:
    centre_back = [_appearance(index) for index in range(8, 0, -1)]
    assert (
        baseline_centre_back_before(
            centre_back,
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is True
    )

    midfielder = [
        _appearance(index, position="M", started=True)
        for index in range(8, 0, -1)
    ]
    assert (
        baseline_centre_back_before(
            midfielder,
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is False
    )
    unknown_role = [*centre_back[:-1], _appearance(1, position=None)]
    assert (
        baseline_centre_back_before(
            unknown_role,
            player_id="p1",
            target_fixture_id="target",
            target_kickoff=TARGET,
        )
        is None
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"observed_at": TARGET}, False),
        ({"confidence": 0.98}, False),
        ({"role_start": TARGET}, False),
        ({"unavailable_until": TARGET - timedelta(seconds=1)}, False),
        ({}, True),
    ],
)
def test_absence_must_be_point_in_time(
    changes: dict[str, object],
    expected: bool,
) -> None:
    assert absence_known_before(
        _absence("p1", **changes),
        cutoff=TARGET,
    ) is expected


def test_absence_roles_count_goalkeeper_and_two_centre_backs_once() -> None:
    observations = [
        _absence("cb-1"),
        _absence("cb-1"),
        _absence("cb-2"),
        _absence("gk-1"),
        _absence("other"),
        _absence("opponent", team_id="team-b"),
    ]
    roles = {
        "cb-1": "CENTRE_BACK",
        "cb-2": "CENTRE_BACK",
        "gk-1": "GOALKEEPER",
    }
    assert count_unavailable_roles(
        observations,
        roles,
        team_id="team-a",
        cutoff=TARGET,
    ) == {
        "CENTRE_BACK": 2,
        "GOALKEEPER": 1,
        "OTHER": 1,
    }


@pytest.mark.parametrize("selected", [True, False])
def test_non_selection_can_never_define_an_absence(selected: bool) -> None:
    with pytest.raises(ValueError, match="NON_SELECTION_CANNOT_DEFINE_ABSENCE"):
        infer_absence_from_non_selection(selected=selected)
