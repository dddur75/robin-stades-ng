from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from robin.deep_football.contracts import ResearchMode
from robin.deep_football.datasets import (
    checkpoint_key,
    deterministic_dataset_hash,
    exact_pairing,
    row_key,
)
from robin.deep_football.footedness import (
    FootednessObservation,
    footedness_coverage,
    infer_foot_from_position,
    observed_foot,
)
from robin.deep_football.formations import normalize_formation
from robin.deep_football.lineups import (
    LineupObservation,
    centre_back_pair_continuity,
    lineup_continuity,
    observed_centre_backs,
    validate_lineup,
)

KICKOFF = datetime(2026, 7, 27, 18, tzinfo=UTC)
CUTOFF = KICKOFF - timedelta(minutes=5)


def _lineup(
    *,
    players: tuple[str, ...] = tuple(f"p-{index}" for index in range(1, 12)),
    observed_at: datetime = KICKOFF - timedelta(minutes=10),
    complete: bool = True,
) -> LineupObservation:
    return LineupObservation(
        fixture_id="fixture-1",
        team_id="team-a",
        player_ids=players,
        observed_at=observed_at,
        kickoff_at=KICKOFF,
        formation_raw="4-3-3",
        complete=complete,
    )


def _paired_row(
    fixture_id: str,
    *,
    probability_home: float = 0.5,
) -> dict[str, object]:
    return {
        "competition": "Ligue 1",
        "fixture_id": fixture_id,
        "kickoff_at": KICKOFF.isoformat(),
        "research_mode": "PRE_LINEUP",
        "feature_cutoff": CUTOFF.isoformat(),
        "market_source": "FOOTBALL_DATA",
        "market_record_hash": "a" * 64,
        "p_home": probability_home,
    }


def _defenders(count: int) -> list[dict[str, object]]:
    return [
        {
            "player_id": f"defender-{slot}",
            "position": "D",
            "grid": f"2:{slot}",
        }
        for slot in range(1, count + 1)
    ]


def test_confirmed_lineup_is_forbidden_in_pre_lineup_mode() -> None:
    with pytest.raises(
        ValueError,
        match="CONFIRMED_LINEUP_FORBIDDEN_IN_PRE_LINEUP_MODE",
    ):
        validate_lineup(
            _lineup(),
            mode=ResearchMode.PRE_LINEUP,
            cutoff=CUTOFF,
        )


def test_post_lineup_requires_eleven_unique_players_before_cutoff() -> None:
    validate_lineup(
        _lineup(),
        mode=ResearchMode.POST_LINEUP,
        cutoff=CUTOFF,
    )

    with pytest.raises(ValueError, match="LINEUP_NOT_AVAILABLE_AT_CUTOFF"):
        validate_lineup(
            _lineup(observed_at=CUTOFF),
            mode=ResearchMode.POST_LINEUP,
            cutoff=CUTOFF,
        )
    with pytest.raises(ValueError, match="LINEUP_INCOMPLETE"):
        validate_lineup(
            _lineup(complete=False),
            mode=ResearchMode.POST_LINEUP,
            cutoff=CUTOFF,
        )
    with pytest.raises(ValueError, match="LINEUP_MUST_HAVE_ELEVEN_UNIQUE"):
        validate_lineup(
            _lineup(players=("p-1",) * 11),
            mode=ResearchMode.POST_LINEUP,
            cutoff=CUTOFF,
        )


def test_lineup_continuity_is_actual_overlap_not_resolution_rate() -> None:
    previous = tuple(f"p-{index}" for index in range(1, 12))
    current = (*previous[:9], "new-1", "new-2")
    assert lineup_continuity(current, previous) == pytest.approx(9 / 11)
    assert lineup_continuity(current[:10], previous) is None
    assert lineup_continuity(("p-1",) * 11, previous) is None


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        (("a", "b"), ("b", "a"), "SAME_PAIR"),
        (("a", "c"), ("a", "b"), "ONE_NEW_CENTRE_BACK"),
        (("c", "d"), ("a", "b"), "TWO_NEW_CENTRE_BACKS"),
        (("a",), ("a", "b"), "UNKNOWN"),
    ],
)
def test_centre_back_pair_states(
    current: tuple[str, ...],
    previous: tuple[str, ...],
    expected: str,
) -> None:
    assert centre_back_pair_continuity(current, previous) == expected


def test_centre_backs_are_selected_from_observed_grid_not_names() -> None:
    players = [
        {"player_id": "keeper", "position": "G", "grid": "1:1"},
        *_defenders(4),
        {"player_id": "central-by-name", "position": "M", "grid": "3:1"},
    ]
    assert observed_centre_backs(players, expected_back_line=4) == (
        "defender-2",
        "defender-3",
    )


def test_centre_back_grid_fails_closed_on_mismatch_or_invalid_shape() -> None:
    with pytest.raises(ValueError, match="FORMATION_DEFENDER_COUNT_MISMATCH"):
        observed_centre_backs(_defenders(3), expected_back_line=4)
    with pytest.raises(ValueError, match="BACK_LINE_SIZE_INVALID"):
        observed_centre_backs(_defenders(2), expected_back_line=2)
    with pytest.raises(ValueError, match="LINEUP_GRID_INVALID"):
        observed_centre_backs(
            [
                {"player_id": "a", "position": "D", "grid": "2:x"},
                *_defenders(3),
            ],
            expected_back_line=4,
        )


@pytest.mark.parametrize(
    ("raw", "normalized", "confidence"),
    [
        ("4-3-3", "4-3-3", 1.0),
        (" 4 – 3 – 3 ", "4-3-3", 1.0),
        ("4/4/2", "4-4-2", 1.0),
        ("4-2-3-1", "4-2-3-1", 1.0),
    ],
)
def test_formation_normalization_preserves_raw_and_confidence(
    raw: str,
    normalized: str,
    confidence: float,
) -> None:
    formation = normalize_formation(raw)
    assert formation.raw == raw
    assert formation.normalized == normalized
    assert formation.confidence == confidence
    assert formation.ambiguous is False


def test_formation_families_are_explicit() -> None:
    assert normalize_formation("4-3-3").families == (
        "BACK_FOUR",
        "MIDFIELD_THREE",
        "FRONT_THREE",
    )
    assert normalize_formation("3-5-2").families == (
        "BACK_THREE",
        "FRONT_TWO",
    )
    assert normalize_formation("5-4-1").families == (
        "BACK_FIVE",
        "MIDFIELD_FOUR",
        "SINGLE_STRIKER",
    )


@pytest.mark.parametrize("raw", [None, "", "4-2-4", "unknown"])
def test_missing_or_unsupported_formation_remains_ambiguous(
    raw: str | None,
) -> None:
    formation = normalize_formation(raw)
    assert formation.normalized is None
    assert formation.confidence == 0.0
    assert formation.ambiguous is True
    assert formation.families == ()


def test_footedness_requires_observed_source_and_supported_value() -> None:
    valid = FootednessObservation("p-1", " left ", "SCOUT", "preferred_foot")
    assert observed_foot(valid) == "LEFT"
    assert observed_foot(
        FootednessObservation("p-2", "RIGHT", None, "preferred_foot")
    ) is None
    assert observed_foot(
        FootednessObservation("p-3", "UNKNOWN", "SCOUT", "preferred_foot")
    ) is None


def test_footedness_coverage_is_measured_on_relevant_players_only() -> None:
    observations = [
        FootednessObservation("p-1", "LEFT", "SCOUT", "preferred_foot"),
        FootednessObservation("p-2", None, "SCOUT", "preferred_foot"),
        FootednessObservation("irrelevant", "RIGHT", "SCOUT", "preferred_foot"),
    ]
    assert footedness_coverage(observations, ["p-1", "p-2"]) == 0.5
    assert footedness_coverage(observations, []) == 0.0


def test_footedness_is_never_inferred_from_position() -> None:
    with pytest.raises(
        ValueError,
        match="FOOTEDNESS_HEURISTIC_INFERENCE_FORBIDDEN",
    ):
        infer_foot_from_position(position="left-back")


def test_exact_pairing_is_order_independent_and_preserves_exact_keys() -> None:
    left = [_paired_row("fixture-2"), _paired_row("fixture-1")]
    right = [_paired_row("fixture-1", probability_home=0.6), _paired_row("fixture-2")]
    paired = exact_pairing(left, right)

    assert len(paired.keys) == 2
    assert tuple(row["fixture_id"] for row in paired.left) == (
        "fixture-1",
        "fixture-2",
    )
    assert tuple(row["fixture_id"] for row in paired.right) == (
        "fixture-1",
        "fixture-2",
    )
    assert paired.attrition_left == 0
    assert paired.attrition_right == 0


def test_pairing_rejects_attrition_duplicates_and_missing_dimensions() -> None:
    with pytest.raises(ValueError, match="PAIRED_SAMPLE_KEYSET_MISMATCH"):
        exact_pairing([_paired_row("fixture-1")], [_paired_row("fixture-2")])
    with pytest.raises(ValueError, match="PAIRED_SAMPLE_DUPLICATE"):
        exact_pairing(
            [_paired_row("fixture-1"), _paired_row("fixture-1")],
            [_paired_row("fixture-1")],
        )
    incomplete = _paired_row("fixture-1")
    del incomplete["market_record_hash"]
    with pytest.raises(ValueError, match="PAIRING_FIELD_MISSING"):
        row_key(incomplete)


def test_dataset_hash_and_replay_are_deterministic_and_order_independent() -> None:
    rows = [_paired_row("fixture-1"), _paired_row("fixture-2")]
    first = deterministic_dataset_hash(rows)
    replay = deterministic_dataset_hash(list(reversed(rows)))
    changed = deterministic_dataset_hash(
        [{**rows[0], "p_home": 0.51}, rows[1]]
    )

    assert first == replay
    assert len(first) == 64
    assert changed != first


def test_checkpoint_key_freezes_campaign_dataset_hypotheses_and_seed() -> None:
    first = checkpoint_key(
        campaign="11A",
        dataset_hash="a" * 64,
        hypothesis_ids=["H11-002", "H11-001"],
        seed=11,
    )
    reordered = checkpoint_key(
        campaign="11A",
        dataset_hash="a" * 64,
        hypothesis_ids=["H11-001", "H11-002"],
        seed=11,
    )
    different_seed = checkpoint_key(
        campaign="11A",
        dataset_hash="a" * 64,
        hypothesis_ids=["H11-001", "H11-002"],
        seed=12,
    )
    assert first == reordered
    assert different_seed != first
