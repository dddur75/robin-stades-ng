"""Pure target-blind Phase C V2 feature, mask and pair-space engine."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

FOLDS = (
    ("F1", 703, 929, "2024-12-14"),
    ("F2", 929, 1133, "2025-01-19"),
    ("F3", 1133, 1345, "2025-02-17"),
    ("F4", 1345, 1547, "2025-03-30"),
    ("F5", 1547, 1756, "2025-04-27"),
)
TARGET_BLIND_SUPPORT_START = 303
TARGET_BLIND_TRAIN_END = 703
TARGET_BLIND_SUPPORT_MIN_KNOWN = 320
TARGET_BLIND_SUPPORT_MIN_TRUE = 40
PAIR_SHARD_COUNT = 64


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def object_hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("PHASE_C_V2_NAIVE_DATETIME_REJECTED")
    return parsed.astimezone(UTC)


def quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True, slots=True)
class Fixture:
    fixture_key: str
    competition_key: str
    kickoff: datetime
    status: str


@dataclass(frozen=True, slots=True)
class TeamFact:
    fixture_key: str
    competition_key: str
    team_key: str
    opponent_key: str
    side: str
    kickoff: datetime
    available_at: datetime
    settlement_status: str
    result: str
    points: int
    goals_for: int
    goals_against: int
    substitutions: int | None
    substitutions_status: str
    legacy_generic_cards: int | None
    legacy_generic_cards_status: str
    generic_cards: int | None
    generic_cards_status: str
    yellow_cards: int | None
    dismissals: int | None
    cards_status: str
    formation: str | None
    formation_status: str


@dataclass(frozen=True, slots=True)
class Observation:
    known: bool
    value: float | str | bool | None
    forced_false: bool = False

    def __post_init__(self) -> None:
        if not self.known and (self.value is not None or self.forced_false):
            raise ValueError("PHASE_C_V2_UNKNOWN_OBSERVATION_HAS_VALUE")


@dataclass(frozen=True, slots=True)
class FeatureInputs:
    fixtures: tuple[Fixture, ...]
    facts: tuple[TeamFact, ...]
    facts_by_fixture: Mapping[str, Mapping[str, TeamFact]]
    history_by_team: Mapping[str, tuple[TeamFact, ...]]


@dataclass(frozen=True, slots=True)
class FoldTagState:
    fold_id: str
    train_end: int
    validation_end: int
    states: tuple[bool | None, ...]
    thresholds: Mapping[str, float]
    threshold_hash: str


@dataclass(frozen=True, slots=True)
class TargetSpec:
    target_id: str
    label_key: str
    categories: tuple[str, ...]


def _read_gzip(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"PHASE_C_V2_JSON_OBJECT_REQUIRED:{path}")
    return value


def load_feature_inputs(bundle_root: Path) -> FeatureInputs:
    universe_payload = _read_gzip(bundle_root / "fixture-universe-v2.json.gz")
    universe_rows = universe_payload.get("records")
    if not isinstance(universe_rows, list) or len(universe_rows) != 1_756:
        raise RuntimeError("PHASE_C_V2_FIXTURE_UNIVERSE_MISMATCH")
    fixtures = tuple(
        Fixture(
            fixture_key=str(row["fixture_key"]),
            competition_key=str(row["competition_key"]),
            kickoff=parse_utc(str(row["kickoff_utc"])),
            status=str(row["status"]),
        )
        for row in universe_rows
    )
    if tuple(row.fixture_key for row in fixtures) != tuple(
        f"fixture:{index:04d}" for index in range(1, 1_757)
    ):
        raise RuntimeError("PHASE_C_V2_FIXTURE_ORDINAL_MISMATCH")
    if tuple(sorted(fixtures, key=lambda row: (row.kickoff, row.fixture_key))) != fixtures:
        raise RuntimeError("PHASE_C_V2_FIXTURE_TEMPORAL_ORDER_MISMATCH")

    facts: list[TeamFact] = []
    for path in sorted(bundle_root.glob("team-match-facts-competition-*-v2.json.gz")):
        payload = _read_gzip(path)
        rows = payload.get("records")
        if not isinstance(rows, list):
            raise RuntimeError(f"PHASE_C_V2_TEAM_FACT_ROWS_REQUIRED:{path.name}")
        for row in rows:
            facts.append(
                TeamFact(
                    fixture_key=str(row["fixture_key"]),
                    competition_key=str(row["competition_key"]),
                    team_key=str(row["team_key"]),
                    opponent_key=str(row["opponent_key"]),
                    side=str(row["side"]),
                    kickoff=parse_utc(str(row["kickoff_utc"])),
                    available_at=parse_utc(str(row["availability_proxy_at"])),
                    settlement_status=str(row["settlement_status"]),
                    result=str(row["result"]),
                    points=int(row["points"]),
                    goals_for=int(row["goals_for"]),
                    goals_against=int(row["goals_against"]),
                    substitutions=(
                        int(row["substitutions"])
                        if row["substitutions"] is not None
                        else None
                    ),
                    substitutions_status=str(row["substitutions_status"]),
                    legacy_generic_cards=(
                        int(row["legacy_generic_cards"])
                        if row["legacy_generic_cards"] is not None
                        else None
                    ),
                    legacy_generic_cards_status=str(row["legacy_generic_cards_status"]),
                    generic_cards=(
                        int(row["generic_cards"])
                        if row["generic_cards"] is not None
                        else None
                    ),
                    generic_cards_status=str(row["generic_cards_status"]),
                    yellow_cards=(
                        int(row["yellow_cards"])
                        if row["yellow_cards"] is not None
                        else None
                    ),
                    dismissals=(
                        int(row["dismissals"])
                        if row["dismissals"] is not None
                        else None
                    ),
                    cards_status=str(row["cards_status"]),
                    formation=(
                        str(row["formation"]) if row["formation"] is not None else None
                    ),
                    formation_status=str(row["formation_status"]),
                )
            )
    if len(facts) != 3_512:
        raise RuntimeError("PHASE_C_V2_TEAM_FACT_COUNT_MISMATCH")
    facts.sort(key=lambda row: (row.kickoff, row.fixture_key, row.side))
    facts_by_fixture: dict[str, dict[str, TeamFact]] = defaultdict(dict)
    history_by_team: dict[str, list[TeamFact]] = defaultdict(list)
    for fact in facts:
        if fact.side not in {"HOME", "AWAY"} or fact.side in facts_by_fixture[fact.fixture_key]:
            raise RuntimeError("PHASE_C_V2_TEAM_FACT_GRAIN_MISMATCH")
        facts_by_fixture[fact.fixture_key][fact.side] = fact
        history_by_team[fact.team_key].append(fact)
    if any(set(sides) != {"HOME", "AWAY"} for sides in facts_by_fixture.values()):
        raise RuntimeError("PHASE_C_V2_TEAM_FACT_SIDE_COVERAGE_MISMATCH")
    return FeatureInputs(
        fixtures=fixtures,
        facts=tuple(facts),
        facts_by_fixture={key: dict(value) for key, value in facts_by_fixture.items()},
        history_by_team={key: tuple(value) for key, value in history_by_team.items()},
    )


def load_target_labels(bundle_root: Path) -> tuple[dict[str, str], ...]:
    rows = _read_gzip(bundle_root / "target-labels-v2.json.gz").get("records")
    if not isinstance(rows, list) or len(rows) != 1_756:
        raise RuntimeError("PHASE_C_V2_TARGET_LABEL_COUNT_MISMATCH")
    return tuple({str(key): str(value) for key, value in row.items()} for row in rows)


def eligible_history(
    history: Sequence[TeamFact], target: Fixture
) -> tuple[TeamFact, ...]:
    return tuple(
        fact
        for fact in history
        if fact.fixture_key != target.fixture_key
        and fact.settlement_status in {"FT", "AET"}
        and fact.available_at < target.kickoff
    )


def _window(history: Sequence[TeamFact], window: str) -> tuple[TeamFact, ...] | None:
    if window == "SEASON_TO_DATE":
        return tuple(history) if len(history) >= 3 else None
    if window.startswith("L") and window[1:].isdigit():
        count = int(window[1:])
        return tuple(history[-count:]) if len(history) >= count else None
    raise KeyError(window)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _numeric_history_observation(
    metric: str, window: str, history: Sequence[TeamFact]
) -> Observation:
    selected = _window(history, window)
    if selected is None:
        return Observation(False, None)
    if metric in {"substitutions_mean", "generic_cards", "yellow_cards_mean", "dismissals_mean"}:
        values: list[int | None]
        if metric == "substitutions_mean":
            values = [row.substitutions for row in selected]
            statuses = [row.substitutions_status for row in selected]
        elif metric == "generic_cards":
            values = [row.legacy_generic_cards for row in selected]
            statuses = [row.legacy_generic_cards_status for row in selected]
        elif metric == "yellow_cards_mean":
            values = [row.yellow_cards for row in selected]
            statuses = [row.cards_status for row in selected]
        else:
            values = [row.dismissals for row in selected]
            statuses = [row.cards_status for row in selected]
        if any(not status.startswith("KNOWN") for status in statuses) or any(
            value is None for value in values
        ):
            return Observation(False, None)
        return Observation(True, _mean([float(value) for value in values if value is not None]))
    numeric_values: list[float]
    if metric == "points_per_match":
        numeric_values = [float(row.points) for row in selected]
    elif metric == "win_rate":
        numeric_values = [float(row.result == "WIN") for row in selected]
    elif metric == "draw_rate":
        numeric_values = [float(row.result == "DRAW") for row in selected]
    elif metric == "goals_for":
        numeric_values = [float(row.goals_for) for row in selected]
    elif metric == "goals_against":
        numeric_values = [float(row.goals_against) for row in selected]
    elif metric == "over_2_5_rate":
        numeric_values = [float(row.goals_for + row.goals_against > 2) for row in selected]
    elif metric == "clean_sheet_rate":
        numeric_values = [float(row.goals_against == 0) for row in selected]
    elif metric == "failed_to_score_rate":
        numeric_values = [float(row.goals_for == 0) for row in selected]
    elif metric == "points_volatility":
        if len(selected) < 2:
            return Observation(False, None)
        return Observation(True, statistics.pstdev(row.points for row in selected))
    elif metric == "same_orientation_points_per_match":
        numeric_values = [float(row.points) for row in selected]
    elif metric == "weighted_points_hl5":
        weights = [2 ** (-age / 5) for age in reversed(range(len(selected)))]
        denominator = sum(weights)
        return Observation(
            True,
            sum(float(row.points) * weight for row, weight in zip(selected, weights, strict=True))
            / denominator,
        )
    else:
        raise KeyError(metric)
    return Observation(True, _mean(numeric_values))


def _ranking_observation(
    inputs: FeatureInputs, target: Fixture, target_team: str
) -> Observation:
    prior = [
        fact
        for fact in inputs.facts
        if fact.competition_key == target.competition_key
        and fact.available_at < target.kickoff
        and fact.fixture_key != target.fixture_key
        and fact.settlement_status in {"FT", "AET"}
    ]
    table: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for fact in prior:
        values = table[fact.team_key]
        values[0] += fact.points
        values[1] += fact.goals_for - fact.goals_against
        values[2] += fact.goals_for
        values[3] += 1
    if target_team not in table or table[target_team][3] < 3 or len(table) < 2:
        return Observation(False, None)
    ranked = sorted(
        ((team, values) for team, values in table.items()),
        key=lambda row: (-row[1][0], -row[1][1], -row[1][2]),
    )
    target_values = table[target_team][:3]
    positions = [
        index
        for index, (_, values) in enumerate(ranked, 1)
        if values[:3] == target_values
    ]
    midrank = _mean([float(position) for position in positions])
    return Observation(True, 1 - (midrank - 1) / (len(ranked) - 1))


def observation_for_tag(
    tag: Mapping[str, Any], target: Fixture, inputs: FeatureInputs
) -> Observation:
    side = str(tag["orientation"])
    target_fact = inputs.facts_by_fixture[target.fixture_key][side]
    history = eligible_history(inputs.history_by_team[target_fact.team_key], target)
    metric = str(tag["metric"])
    window = str(tag["temporal_window"])
    if metric == "last_prior_formation":
        if not history:
            return Observation(False, None)
        latest = history[-1]
        if not latest.formation_status.startswith("KNOWN") or latest.formation is None:
            return Observation(False, None)
        return Observation(True, latest.formation)
    if metric.startswith("after_") and metric.endswith("_points_per_match"):
        category = str(tag["category_value"])
        if not history:
            return Observation(False, None)
        if history[-1].result != category:
            return Observation(True, False, forced_false=True)
        transitions = [
            float(destination.points)
            for source, destination in zip(history[:-1], history[1:], strict=True)
            if source.result == category
        ]
        if len(transitions) < 3:
            return Observation(False, None)
        return Observation(True, _mean(transitions))
    if metric.startswith("current_") and metric.endswith("_streak"):
        category = str(tag["category_value"])
        if not history:
            return Observation(False, None)
        streak = 0
        for fact in reversed(history):
            if fact.result != category:
                break
            streak += 1
        return Observation(True, float(streak))
    if metric == "reconstructed_table_strength_percentile":
        return _ranking_observation(inputs, target, target_fact.team_key)
    selected_history = history
    if metric == "same_orientation_points_per_match":
        selected_history = tuple(row for row in history if row.side == side)
    return _numeric_history_observation(metric, window, selected_history)


def build_observations(
    registry: Mapping[str, Any], inputs: FeatureInputs
) -> dict[str, tuple[Observation, ...]]:
    tags = registry.get("tags")
    if not isinstance(tags, list) or len(tags) != 150:
        raise RuntimeError("PHASE_C_V2_REGISTRY_TAG_COUNT_MISMATCH")
    result: dict[str, tuple[Observation, ...]] = {}
    for tag in tags:
        tag_id = str(tag["tag_id"])
        result[tag_id] = tuple(
            observation_for_tag(tag, fixture, inputs) for fixture in inputs.fixtures
        )
    return result


def _thresholds(
    tag: Mapping[str, Any],
    observations: Sequence[Observation],
    fixtures: Sequence[Fixture],
    indices: Sequence[int],
) -> dict[str, float]:
    if tag["threshold_origin"] != "TRAIN_QUANTILE_Q67_LINEAR_PER_LEAGUE_AND_FOLD":
        return {}
    thresholds: dict[str, float] = {}
    competitions = sorted({fixtures[index].competition_key for index in indices})
    for competition in competitions:
        values: list[float] = []
        for index in indices:
            observation = observations[index]
            if (
                fixtures[index].competition_key == competition
                and observation.known
                and not observation.forced_false
                and isinstance(observation.value, (int, float))
            ):
                values.append(float(observation.value))
        threshold = quantile(values, 0.67)
        if threshold is not None:
            thresholds[competition] = threshold
    return thresholds


def tag_states(
    tag: Mapping[str, Any],
    observations: Sequence[Observation],
    fixtures: Sequence[Fixture],
    train_indices: Sequence[int],
    end: int,
) -> tuple[tuple[bool | None, ...], dict[str, float]]:
    thresholds = _thresholds(tag, observations, fixtures, train_indices)
    states: list[bool | None] = []
    for index in range(end):
        observation = observations[index]
        if not observation.known:
            states.append(None)
            continue
        if observation.forced_false:
            states.append(False)
            continue
        origin = str(tag["threshold_origin"])
        if origin == "ONTOLOGY_FIXED":
            states.append(observation.value == tag["category_value"])
        elif origin == "FIXED_ZERO":
            states.append(
                float(observation.value) > 0
                if isinstance(observation.value, (int, float))
                else None
            )
        elif origin == "FIXED_TWO":
            states.append(
                float(observation.value) >= 2
                if isinstance(observation.value, (int, float))
                else None
            )
        else:
            threshold = thresholds.get(fixtures[index].competition_key)
            states.append(
                None
                if threshold is None or not isinstance(observation.value, (int, float))
                else float(observation.value) >= threshold
            )
    return tuple(states), thresholds


def mask_int(states: Sequence[bool | None]) -> tuple[int, int]:
    known = 0
    true = 0
    for index, state in enumerate(states):
        if state is None:
            continue
        known |= 1 << index
        if state:
            true |= 1 << index
    if true & ~known:
        raise RuntimeError("PHASE_C_V2_MASK_TRUE_NOT_SUBSET_KNOWN")
    return known, true


def build_structural_masks(
    registry: Mapping[str, Any],
    inputs: FeatureInputs,
    observations: Mapping[str, Sequence[Observation]],
) -> tuple[dict[str, tuple[int, int]], dict[str, dict[str, float]]]:
    masks: dict[str, tuple[int, int]] = {}
    threshold_rows: dict[str, dict[str, float]] = {}
    train_indices = tuple(range(TARGET_BLIND_TRAIN_END))
    for tag in registry["tags"]:
        tag_id = str(tag["tag_id"])
        states, thresholds = tag_states(
            tag, observations[tag_id], inputs.fixtures, train_indices, len(inputs.fixtures)
        )
        masks[tag_id] = mask_int(states)
        threshold_rows[tag_id] = thresholds
    return masks, threshold_rows


def canonical_pair_id(tag_a: str, tag_b: str) -> str:
    left, right = sorted((tag_a, tag_b))
    return "pair:" + hashlib.sha256((left + "\0" + right).encode("utf-8")).hexdigest()


def enumerate_pair_census(
    registry: Mapping[str, Any], masks: Mapping[str, tuple[int, int]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tags = sorted(masks)
    property_by_tag = {
        str(row["tag_id"]): str(row["property_id"]) for row in registry["tags"]
    }
    support_mask = ((1 << TARGET_BLIND_TRAIN_END) - 1) ^ (
        (1 << TARGET_BLIND_SUPPORT_START) - 1
    )
    census: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for tag_a, tag_b in combinations(tags, 2):
        pair_id = canonical_pair_id(tag_a, tag_b)
        property_a = property_by_tag[tag_a]
        property_b = property_by_tag[tag_b]
        known = masks[tag_a][0] & masks[tag_b][0] & support_mask
        true = masks[tag_a][1] & masks[tag_b][1] & support_mask
        union = (masks[tag_a][1] | masks[tag_b][1]) & support_mask
        known_count = known.bit_count()
        true_count = true.bit_count()
        jaccard = true_count / union.bit_count() if union else 1.0
        if property_a == property_b:
            disposition, reason = "PRUNED", "SAME_PROPERTY_REDUNDANCY"
        elif known_count < TARGET_BLIND_SUPPORT_MIN_KNOWN:
            disposition, reason = "PRUNED", "TARGET_BLIND_KNOWN_LT_320"
        elif true_count < TARGET_BLIND_SUPPORT_MIN_TRUE:
            disposition, reason = "PRUNED", "TARGET_BLIND_INTERSECTION_TRUE_LT_40"
        elif jaccard >= 0.98:
            disposition, reason = "PRUNED", "QUASI_IDENTICAL_MASKS_GTE_0_98"
        else:
            disposition, reason = "ELIGIBLE", "TARGET_BLIND_STRUCTURAL_AND_SUPPORT_PASS"
        row = {
            "pair_id": pair_id,
            "parent_a": tag_a,
            "parent_b": tag_b,
            "parent_property_a": property_a,
            "parent_property_b": property_b,
            "known_count_blind_slice": known_count,
            "true_count_blind_slice": true_count,
            "jaccard_blind_slice": round(jaccard, 10),
            "disposition": disposition,
            "reason": reason,
            "shard_id": int(hashlib.sha256(pair_id.encode("utf-8")).hexdigest()[:16], 16)
            % PAIR_SHARD_COUNT,
        }
        census.append(row)
        if disposition == "ELIGIBLE":
            eligible.append(row)
    if len(census) != 11_175 or len({row["pair_id"] for row in census}) != 11_175:
        raise RuntimeError("PHASE_C_V2_PAIR_CENSUS_CARDINALITY_MISMATCH")
    same_property = sum(row["reason"] == "SAME_PROPERTY_REDUNDANCY" for row in census)
    if same_property != 763:
        raise RuntimeError(f"PHASE_C_V2_SAME_PROPERTY_COUNT_MISMATCH:{same_property}")
    return census, eligible


TARGET_SPECS = (
    TargetSpec(
        target_id="MATCH_RESULT_90M",
        label_key="match_result_90m",
        categories=("HOME_WIN", "DRAW", "AWAY_WIN"),
    ),
    TargetSpec(
        target_id="TOTAL_GOALS_2_5_90M",
        label_key="total_goals_2_5_90m",
        categories=("OVER", "UNDER"),
    ),
)
OOF_COUNT = sum(validation_end - train_end for _, train_end, validation_end, _ in FOLDS)
PAIR_COMPARATORS = ("PARENT_A", "PARENT_B", "ADDITIVE")


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def arithmetic_mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def category_count(labels: Iterable[str], categories: Sequence[str]) -> dict[str, int]:
    count = Counter(labels)
    return {category: count[category] for category in categories}


def smoothed_probs(
    counts: Mapping[str, int],
    categories: Sequence[str],
    prior: Mapping[str, float] | None = None,
    strength: float = 0.5,
) -> dict[str, float]:
    if prior is None:
        numerators = {category: counts.get(category, 0) + strength for category in categories}
    else:
        numerators = {
            category: counts.get(category, 0) + strength * prior[category]
            for category in categories
        }
    denominator = sum(numerators.values())
    return {category: numerators[category] / denominator for category in categories}


def form_buckets(
    registry: Mapping[str, Any], observations: Mapping[str, Sequence[Observation]]
) -> tuple[str, ...]:
    points_tags: dict[str, str] = {}
    for tag in registry["tags"]:
        if tag["metric"] == "points_per_match" and tag["temporal_window"] == "L5":
            points_tags[str(tag["orientation"])] = str(tag["tag_id"])
    if set(points_tags) != {"HOME", "AWAY"}:
        raise RuntimeError("PHASE_C_V2_FORM_BUCKET_INPUTS_MISSING")
    result: list[str] = []
    for home, away in zip(
        observations[points_tags["HOME"]], observations[points_tags["AWAY"]], strict=True
    ):
        if (
            not home.known
            or not away.known
            or not isinstance(home.value, (int, float))
            or not isinstance(away.value, (int, float))
        ):
            result.append("UNKNOWN")
            continue
        delta = float(home.value) - float(away.value)
        result.append(
            "HOME_EDGE" if delta > 0.25 else ("AWAY_EDGE" if delta < -0.25 else "BALANCED")
        )
    return tuple(result)


def simple_predictions(
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    fixtures: Sequence[Fixture],
    buckets: Sequence[str],
    labels: Sequence[str],
    categories: Sequence[str],
) -> tuple[dict[str, float], dict[int, dict[str, float]]]:
    global_counts = category_count((labels[index] for index in train_indices), categories)
    global_probs = smoothed_probs(global_counts, categories)
    groups: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for index in train_indices:
        groups[(fixtures[index].competition_key, buckets[index])][labels[index]] += 1
    predictions: dict[int, dict[str, float]] = {}
    for index in validation_indices:
        key = (fixtures[index].competition_key, buckets[index])
        predictions[index] = smoothed_probs(groups[key], categories, global_probs, 20.0)
    return global_probs, predictions


def league_predictions(
    train_indices: Sequence[int],
    validation_indices: Sequence[int],
    fixtures: Sequence[Fixture],
    labels: Sequence[str],
    categories: Sequence[str],
    global_probs: Mapping[str, float],
) -> dict[int, dict[str, float]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for index in train_indices:
        groups[fixtures[index].competition_key][labels[index]] += 1
    return {
        index: smoothed_probs(
            groups[fixtures[index].competition_key], categories, global_probs, 20.0
        )
        for index in validation_indices
    }


def conditional_probs(
    indices: Sequence[int],
    labels: Sequence[str],
    states: Sequence[bool | None],
    categories: Sequence[str],
    global_probs: Mapping[str, float],
) -> dict[bool, dict[str, float]]:
    counts: dict[bool, Counter[str]] = {True: Counter(), False: Counter()}
    for index in indices:
        state = states[index]
        if state is not None:
            counts[state][labels[index]] += 1
    return {
        state: smoothed_probs(counts[state], categories, global_probs, 10.0)
        for state in (False, True)
    }


def adjusted_probs(
    base: Mapping[str, float],
    conditional: Mapping[str, float],
    global_probs: Mapping[str, float],
    categories: Sequence[str],
) -> dict[str, float]:
    raw = {
        category: max(1e-12, base[category])
        * max(1e-12, conditional[category])
        / max(1e-12, global_probs[category])
        for category in categories
    }
    denominator = sum(raw.values())
    return {category: raw[category] / denominator for category in categories}


def combine_adjustments(
    base: Mapping[str, float],
    conditional_a: Mapping[str, float],
    conditional_b: Mapping[str, float],
    global_probs: Mapping[str, float],
    categories: Sequence[str],
) -> dict[str, float]:
    raw = {
        category: base[category]
        * conditional_a[category]
        * conditional_b[category]
        / max(1e-12, global_probs[category] ** 2)
        for category in categories
    }
    denominator = sum(raw.values())
    return {category: raw[category] / denominator for category in categories}


def log_loss(probabilities: Mapping[str, float], label: str) -> float:
    return -math.log(max(1e-12, min(1 - 1e-12, probabilities[label])))


def brier_loss(
    probabilities: Mapping[str, float], label: str, categories: Sequence[str]
) -> float:
    return sum(
        (probabilities[category] - int(category == label)) ** 2 for category in categories
    ) / len(categories)


def ece(
    rows: Sequence[tuple[Mapping[str, float], str]], categories: Sequence[str]
) -> float | None:
    if not rows:
        return None
    total = 0.0
    for category in categories:
        for lower_index in range(10):
            lower, upper = lower_index / 10, (lower_index + 1) / 10
            group = [
                row
                for row in rows
                if lower <= row[0][category] < upper
                or (upper == 1 and row[0][category] == 1)
            ]
            if not group:
                continue
            confidence = sum(row[0][category] for row in group) / len(group)
            observed = sum(int(row[1] == category) for row in group) / len(group)
            total += len(group) / (len(rows) * len(categories)) * abs(confidence - observed)
    return round(total, 8)


def one_sided_cluster_p(
    differences: Sequence[float], dates: Sequence[str]
) -> tuple[float, int]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for value, date in zip(differences, dates, strict=True):
        clusters[date].append(value)
    cluster_means = [sum(values) / len(values) for _, values in sorted(clusters.items())]
    if len(cluster_means) < 2:
        return 1.0, len(cluster_means)
    average = sum(cluster_means) / len(cluster_means)
    standard_deviation = statistics.stdev(cluster_means)
    if standard_deviation == 0:
        return (0.0 if average > 0 else 1.0), len(cluster_means)
    statistic = average / (standard_deviation / math.sqrt(len(cluster_means)))
    return round(0.5 * math.erfc(statistic / math.sqrt(2)), 10), len(cluster_means)


def bh_adjust(rows: Sequence[tuple[str, float]]) -> dict[str, float]:
    ordered = sorted(rows, key=lambda row: (row[1], row[0]))
    result: dict[str, float] = {}
    running = 1.0
    total = len(ordered)
    for reverse_index in range(total - 1, -1, -1):
        key, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * total / rank)
        result[key] = round(min(1.0, running), 10)
    return result


def build_fold_states(
    registry: Mapping[str, Any],
    inputs: FeatureInputs,
    observations: Mapping[str, Sequence[Observation]],
) -> dict[str, tuple[FoldTagState, ...]]:
    result: dict[str, tuple[FoldTagState, ...]] = {}
    for tag in registry["tags"]:
        tag_id = str(tag["tag_id"])
        snapshots: list[FoldTagState] = []
        for fold_id, train_end, validation_end, expected_start in FOLDS:
            actual_start = inputs.fixtures[train_end].kickoff.date().isoformat()
            if actual_start != expected_start:
                raise RuntimeError(
                    f"PHASE_C_V2_FOLD_BOUNDARY_MISMATCH:{fold_id}:{actual_start}"
                )
            states, thresholds = tag_states(
                tag,
                observations[tag_id],
                inputs.fixtures,
                tuple(range(train_end)),
                validation_end,
            )
            threshold_mapping = dict(sorted(thresholds.items()))
            snapshots.append(
                FoldTagState(
                    fold_id=fold_id,
                    train_end=train_end,
                    validation_end=validation_end,
                    states=states,
                    thresholds=threshold_mapping,
                    threshold_hash=object_hash(threshold_mapping),
                )
            )
        result[tag_id] = tuple(snapshots)
    return result


def build_baselines(
    registry: Mapping[str, Any],
    inputs: FeatureInputs,
    observations: Mapping[str, Sequence[Observation]],
    labels: Sequence[Mapping[str, str]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    buckets = form_buckets(registry, observations)
    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for target in TARGET_SPECS:
        target_labels = [row[target.label_key] for row in labels]
        fold_rows: list[dict[str, Any]] = []
        for fold_id, train_end, validation_end, _ in FOLDS:
            train_indices = tuple(range(train_end))
            validation_indices = tuple(range(train_end, validation_end))
            global_probs, simple = simple_predictions(
                train_indices,
                validation_indices,
                inputs.fixtures,
                buckets,
                target_labels,
                target.categories,
            )
            fold_rows.append(
                {
                    "fold_id": fold_id,
                    "global_probs": global_probs,
                    "simple": simple,
                    "league": league_predictions(
                        train_indices,
                        validation_indices,
                        inputs.fixtures,
                        target_labels,
                        target.categories,
                        global_probs,
                    ),
                }
            )
        result[target.target_id] = tuple(fold_rows)
    return result


def _stability_summary(
    differences: Sequence[float],
    indices: Sequence[int],
    fold_ids: Sequence[str],
    team_keys: Sequence[tuple[str, ...]],
    inputs: FeatureInputs,
) -> dict[str, Any]:
    def exclude_group(groups: Sequence[str]) -> dict[str, Any]:
        values: list[tuple[str, float]] = []
        for group in sorted(set(groups)):
            remaining = [
                value
                for value, row_group in zip(differences, groups, strict=True)
                if row_group != group
            ]
            if remaining:
                values.append((group, sum(remaining) / len(remaining)))
        return {
            "group_count": len(values),
            "positive_count": sum(value > 0 for _, value in values),
            "minimum_delta": round(min((value for _, value in values), default=0.0), 8),
            "values_hash": object_hash(
                [[group, round(value, 10)] for group, value in values]
            ),
        }

    competitions = [inputs.fixtures[index].competition_key for index in indices]
    team_universe = sorted({team for keys in team_keys for team in keys})
    team_removed_sum: dict[str, float] = defaultdict(float)
    team_removed_count: Counter[str] = Counter()
    total_sum = sum(differences)
    total_count = len(differences)
    for value, keys in zip(differences, team_keys, strict=True):
        for team in set(keys):
            team_removed_sum[team] += value
            team_removed_count[team] += 1
    team_values: list[tuple[str, float]] = []
    for team in team_universe:
        remaining_count = total_count - team_removed_count[team]
        if remaining_count:
            team_values.append(
                (team, (total_sum - team_removed_sum[team]) / remaining_count)
            )
    return {
        "leave_one_league_out": exclude_group(competitions),
        "leave_one_period_out": exclude_group(fold_ids),
        "leave_one_team_out": {
            "group_count": len(team_values),
            "positive_count": sum(value > 0 for _, value in team_values),
            "minimum_delta": round(
                min((value for _, value in team_values), default=0.0), 8
            ),
            "values_hash": object_hash(
                [[team, round(value, 10)] for team, value in team_values]
            ),
        },
    }


def _status_atomic(metric: Mapping[str, Any]) -> tuple[str, list[str]]:
    fold_deltas = [
        float(fold["delta_log_loss"])
        for fold in metric["folds"]
        if fold["delta_log_loss"] is not None
    ]
    support_gate = bool(metric["pre_multiple_testing_gate"]["passed"])
    stability_gate = (
        len(fold_deltas) == 5
        and sum(value > 0 for value in fold_deltas) >= 4
        and fold_deltas[-1] > 0
    )
    positive_increment = (
        float(metric["delta_log_loss"] or 0) > 0
        and float(metric["delta_brier"] or 0) > 0
    )
    if float(metric["q_value"]) <= 0.05 and support_gate and positive_increment:
        status = "SURVIVED_MULTIPLE_TESTING"
        if (
            stability_gate
            and float(metric["delta_log_loss"] or 0) >= 0.005
            and float(metric["delta_brier"] or 0) >= 0.002
        ):
            status = "SURVIVED_TEMPORAL_VALIDATION"
    elif support_gate:
        status = "RAW_HISTORICAL_SIGNAL"
    else:
        status = "LONG_TAIL_DEFERRED"
    suspicious: list[str] = []
    if int(metric["true_oof"]) < 80:
        suspicious.append("LOW_SUPPORT")
    if float(metric["dominant_league_share"] or 0) > 0.5:
        suspicious.append("LEAGUE_CONCENTRATION")
    if status.startswith("SURVIVED_"):
        suspicious.append("SURVIVING_HISTORICAL_EDGE")
    return status, suspicious


def evaluate_atomic(
    registry: Mapping[str, Any],
    inputs: FeatureInputs,
    observations: Mapping[str, Sequence[Observation]],
    labels: Sequence[Mapping[str, str]],
    fold_states: Mapping[str, Sequence[FoldTagState]],
    baselines: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    p_rows: list[tuple[str, float]] = []
    family_rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    results: list[dict[str, Any]] = []
    for tag in registry["tags"]:
        tag_id = str(tag["tag_id"])
        per_target: dict[str, Any] = {}
        for target in TARGET_SPECS:
            target_labels = [row[target.label_key] for row in labels]
            model_rows: list[tuple[Mapping[str, float], str]] = []
            base_rows: list[tuple[Mapping[str, float], str]] = []
            frequency_losses: list[float] = []
            league_losses: list[float] = []
            loss_differences: list[float] = []
            brier_differences: list[float] = []
            dates: list[str] = []
            evaluated_indices: list[int] = []
            evaluated_folds: list[str] = []
            evaluated_teams: list[tuple[str, ...]] = []
            true_indices: list[int] = []
            known_indices: list[int] = []
            fold_metrics: list[dict[str, Any]] = []
            threshold_hashes: list[str] = []
            for snapshot, baseline in zip(
                fold_states[tag_id], baselines[target.target_id], strict=True
            ):
                train_indices = tuple(range(snapshot.train_end))
                validation_indices = tuple(
                    range(snapshot.train_end, snapshot.validation_end)
                )
                global_probs = baseline["global_probs"]
                conditional = conditional_probs(
                    train_indices,
                    target_labels,
                    snapshot.states,
                    target.categories,
                    global_probs,
                )
                fold_base_losses: list[float] = []
                fold_model_losses: list[float] = []
                fold_true = 0
                threshold_hashes.append(snapshot.threshold_hash)
                orientation = str(tag["orientation"])
                for index in validation_indices:
                    state = snapshot.states[index]
                    if state is None:
                        continue
                    base = baseline["simple"][index]
                    model = adjusted_probs(
                        base, conditional[state], global_probs, target.categories
                    )
                    label = target_labels[index]
                    base_loss = log_loss(base, label)
                    model_loss = log_loss(model, label)
                    base_brier = brier_loss(base, label, target.categories)
                    model_brier = brier_loss(model, label, target.categories)
                    base_rows.append((base, label))
                    model_rows.append((model, label))
                    frequency_losses.append(log_loss(global_probs, label))
                    league_losses.append(log_loss(baseline["league"][index], label))
                    loss_differences.append(base_loss - model_loss)
                    brier_differences.append(base_brier - model_brier)
                    dates.append(inputs.fixtures[index].kickoff.date().isoformat())
                    evaluated_indices.append(index)
                    evaluated_folds.append(snapshot.fold_id)
                    evaluated_teams.append(
                        (
                            inputs.facts_by_fixture[
                                inputs.fixtures[index].fixture_key
                            ][orientation].team_key,
                        )
                    )
                    known_indices.append(index)
                    if state:
                        true_indices.append(index)
                        fold_true += 1
                    fold_base_losses.append(base_loss)
                    fold_model_losses.append(model_loss)
                fold_metrics.append(
                    {
                        "fold_id": snapshot.fold_id,
                        "train_count": snapshot.train_end,
                        "validation_count": snapshot.validation_end - snapshot.train_end,
                        "known_count": len(fold_model_losses),
                        "true_count": fold_true,
                        "delta_log_loss": round(
                            (arithmetic_mean(fold_base_losses) or 0)
                            - (arithmetic_mean(fold_model_losses) or 0),
                            8,
                        )
                        if fold_model_losses
                        else None,
                    }
                )
            p_value_raw, cluster_count = one_sided_cluster_p(loss_differences, dates)
            true_unique = sorted(set(true_indices))
            known_unique = sorted(set(known_indices))
            league_counts = Counter(
                inputs.fixtures[index].competition_key for index in true_unique
            )
            dominant_league_share = (
                round(max(league_counts.values()) / len(true_unique), 8)
                if true_unique
                else None
            )
            coverage = rate(len(known_unique), OOF_COUNT)
            support_gate = (
                len(true_unique) >= 80
                and float(coverage or 0) >= 0.8
                and len(league_counts) >= 3
                and all(int(fold["true_count"]) >= 15 for fold in fold_metrics)
                and float(dominant_league_share or 1.0) <= 0.5
            )
            p_value = p_value_raw if support_gate else 1.0
            test_id = f"{tag_id}|{target.target_id}"
            family_id = f"{tag['family']}|{target.target_id}"
            p_rows.append((test_id, p_value))
            family_rows[family_id].append((test_id, p_value))
            per_target[target.target_id] = {
                "canonical_test_id": test_id,
                "known_oof": len(known_unique),
                "true_oof": len(true_unique),
                "false_oof": len(known_unique) - len(true_unique),
                "unknown_oof": OOF_COUNT - len(known_unique),
                "coverage_oof": coverage,
                "support_by_league": dict(sorted(league_counts.items())),
                "dominant_league_share": dominant_league_share,
                "simple_log_loss": round(arithmetic_mean([log_loss(p, y) for p, y in base_rows]) or 0, 8)
                if base_rows
                else None,
                "frequency_baseline_log_loss": round(arithmetic_mean(frequency_losses) or 0, 8)
                if frequency_losses
                else None,
                "league_baseline_log_loss": round(arithmetic_mean(league_losses) or 0, 8)
                if league_losses
                else None,
                "model_log_loss": round(arithmetic_mean([log_loss(p, y) for p, y in model_rows]) or 0, 8)
                if model_rows
                else None,
                "delta_log_loss": round(arithmetic_mean(loss_differences) or 0, 8)
                if loss_differences
                else None,
                "delta_brier": round(arithmetic_mean(brier_differences) or 0, 8)
                if brier_differences
                else None,
                "ece": ece(model_rows, target.categories),
                "p_value_raw": p_value_raw,
                "p_value": p_value,
                "blocked_test_p_value_forced_to_one": not support_gate,
                "family_id": family_id,
                "cluster_count": cluster_count,
                "fold_threshold_hashes": threshold_hashes,
                "folds": fold_metrics,
                "stability": _stability_summary(
                    loss_differences,
                    evaluated_indices,
                    evaluated_folds,
                    evaluated_teams,
                    inputs,
                ),
                "pre_multiple_testing_gate": {
                    "passed": support_gate,
                    "true_oof_gte_80": len(true_unique) >= 80,
                    "known_coverage_gte_0_8": float(coverage or 0) >= 0.8,
                    "at_least_three_leagues": len(league_counts) >= 3,
                    "per_fold_true_gte_15": all(
                        int(fold["true_count"]) >= 15 for fold in fold_metrics
                    ),
                    "dominant_league_share_lte_0_5": float(
                        dominant_league_share or 1.0
                    )
                    <= 0.5,
                },
            }
            snapshot_hash = object_hash(
                {
                    "definition_hash": tag["definition_hash"],
                    "fold_threshold_hashes": threshold_hashes,
                    "target_id": target.target_id,
                }
            )
            per_target[target.target_id]["tag_snapshot_hash"] = snapshot_hash
            per_target[target.target_id]["hypothesis_id"] = "hypothesis:" + object_hash(
                {
                    "tag_id": tag_id,
                    "tag_snapshot_hash": snapshot_hash,
                    "target_id": target.target_id,
                    "campaign": "PHASE-C-V2-ATOMIC-150-X-2",
                }
            )
        results.append(
            {
                "property_id": tag["property_id"],
                "tag_id": tag_id,
                "definition_hash": tag["definition_hash"],
                "target_metrics": per_target,
                "price_metrics": None,
                "status": "TESTED_RAW",
            }
        )
    if len(p_rows) != 300:
        raise RuntimeError(f"PHASE_C_V2_ATOMIC_TEST_COUNT_MISMATCH:{len(p_rows)}")
    q_global = bh_adjust(p_rows)
    q_family = {
        key: value
        for rows in family_rows.values()
        for key, value in bh_adjust(rows).items()
    }
    status_counts: Counter[str] = Counter()
    for row in results:
        best = "RAW_HISTORICAL_SIGNAL"
        for metric in row["target_metrics"].values():
            key = str(metric["canonical_test_id"])
            metric["q_value_atomic_global"] = q_global[key]
            metric["q_value_family"] = q_family[key]
            metric["q_value_campaign_global"] = None
            metric["q_value"] = max(q_global[key], q_family[key])
            status, suspicious = _status_atomic(metric)
            metric["status"] = status
            metric["review_gate"] = (
                "SUSPICIOUS_EDGE_REVIEW" if suspicious else "STANDARD_REVIEW"
            )
            metric["suspicious_reasons"] = suspicious
            if status == "SURVIVED_TEMPORAL_VALIDATION":
                best = status
            elif status == "SURVIVED_MULTIPLE_TESTING" and best != "SURVIVED_TEMPORAL_VALIDATION":
                best = status
            elif status == "LONG_TAIL_DEFERRED" and best == "RAW_HISTORICAL_SIGNAL":
                best = status
        row["status"] = best
        status_counts[best] += 1
    return {
        "schema_version": "phase-c-v2-atomic-results",
        "track": "HISTORICAL_RECONSTRUCTED_ONLY",
        "point_in_time_source_provenance": False,
        "tag_count": 150,
        "property_count": 16,
        "canonical_test_count": 300,
        "status_counts": dict(sorted(status_counts.items())),
        "results": sorted(results, key=lambda row: str(row["tag_id"])),
    }


def evaluate_pair_raw(
    pair: Mapping[str, Any],
    registry_by_id: Mapping[str, Mapping[str, Any]],
    inputs: FeatureInputs,
    labels: Sequence[Mapping[str, str]],
    fold_states: Mapping[str, Sequence[FoldTagState]],
    baselines: Mapping[str, Sequence[Mapping[str, Any]]],
    mask_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    tag_a = str(pair["parent_a"])
    tag_b = str(pair["parent_b"])
    tag_row_a = registry_by_id[tag_a]
    tag_row_b = registry_by_id[tag_b]
    per_target: dict[str, Any] = {}
    for target in TARGET_SPECS:
        target_labels = [row[target.label_key] for row in labels]
        pair_rows: list[tuple[Mapping[str, float], str]] = []
        comparator_rows: dict[str, list[tuple[Mapping[str, float], str]]] = {
            name: [] for name in (*PAIR_COMPARATORS, "BASE")
        }
        differences: dict[str, list[float]] = {name: [] for name in PAIR_COMPARATORS}
        brier_differences: dict[str, list[float]] = {
            name: [] for name in PAIR_COMPARATORS
        }
        dates: list[str] = []
        evaluated_indices: list[int] = []
        evaluated_folds: list[str] = []
        evaluated_teams: list[tuple[str, ...]] = []
        true_indices: list[int] = []
        known_indices: list[int] = []
        parent_true_indices: dict[str, list[int]] = {"PARENT_A": [], "PARENT_B": []}
        fold_metrics: list[dict[str, Any]] = []
        parent_threshold_hashes: dict[str, list[str]] = {
            "PARENT_A": [],
            "PARENT_B": [],
        }
        for snapshot_a, snapshot_b, baseline in zip(
            fold_states[tag_a], fold_states[tag_b], baselines[target.target_id], strict=True
        ):
            if (
                snapshot_a.fold_id != snapshot_b.fold_id
                or snapshot_a.train_end != snapshot_b.train_end
                or snapshot_a.validation_end != snapshot_b.validation_end
            ):
                raise RuntimeError("PHASE_C_V2_PAIR_FOLD_LINEAGE_MISMATCH")
            train_indices = tuple(range(snapshot_a.train_end))
            validation_indices = tuple(
                range(snapshot_a.train_end, snapshot_a.validation_end)
            )
            states_pair = tuple(
                None if a is None or b is None else a and b
                for a, b in zip(snapshot_a.states, snapshot_b.states, strict=True)
            )
            global_probs = baseline["global_probs"]
            conditional_pair = conditional_probs(
                train_indices,
                target_labels,
                states_pair,
                target.categories,
                global_probs,
            )
            conditional_a = conditional_probs(
                train_indices,
                target_labels,
                snapshot_a.states,
                target.categories,
                global_probs,
            )
            conditional_b = conditional_probs(
                train_indices,
                target_labels,
                snapshot_b.states,
                target.categories,
                global_probs,
            )
            fold_pair_losses: list[float] = []
            fold_comparator_losses: dict[str, list[float]] = {
                name: [] for name in PAIR_COMPARATORS
            }
            fold_true = 0
            parent_threshold_hashes["PARENT_A"].append(snapshot_a.threshold_hash)
            parent_threshold_hashes["PARENT_B"].append(snapshot_b.threshold_hash)
            for index in validation_indices:
                state = states_pair[index]
                state_a = snapshot_a.states[index]
                state_b = snapshot_b.states[index]
                if state is None or state_a is None or state_b is None:
                    continue
                base = baseline["simple"][index]
                pair_prediction = adjusted_probs(
                    base, conditional_pair[state], global_probs, target.categories
                )
                parent_a = adjusted_probs(
                    base, conditional_a[state_a], global_probs, target.categories
                )
                parent_b = adjusted_probs(
                    base, conditional_b[state_b], global_probs, target.categories
                )
                additive = combine_adjustments(
                    base,
                    conditional_a[state_a],
                    conditional_b[state_b],
                    global_probs,
                    target.categories,
                )
                label = target_labels[index]
                pair_loss = log_loss(pair_prediction, label)
                pair_rows.append((pair_prediction, label))
                comparator_rows["BASE"].append((base, label))
                for comparator_name, comparator_prediction in {
                    "PARENT_A": parent_a,
                    "PARENT_B": parent_b,
                    "ADDITIVE": additive,
                }.items():
                    comparator_loss = log_loss(comparator_prediction, label)
                    comparator_rows[comparator_name].append((comparator_prediction, label))
                    differences[comparator_name].append(comparator_loss - pair_loss)
                    brier_differences[comparator_name].append(
                        brier_loss(comparator_prediction, label, target.categories)
                        - brier_loss(pair_prediction, label, target.categories)
                    )
                    fold_comparator_losses[comparator_name].append(comparator_loss)
                dates.append(inputs.fixtures[index].kickoff.date().isoformat())
                evaluated_indices.append(index)
                evaluated_folds.append(snapshot_a.fold_id)
                fixture_facts = inputs.facts_by_fixture[inputs.fixtures[index].fixture_key]
                evaluated_teams.append(
                    tuple(
                        sorted(
                            {
                                fixture_facts[str(tag_row_a["orientation"])].team_key,
                                fixture_facts[str(tag_row_b["orientation"])].team_key,
                            }
                        )
                    )
                )
                known_indices.append(index)
                if state_a:
                    parent_true_indices["PARENT_A"].append(index)
                if state_b:
                    parent_true_indices["PARENT_B"].append(index)
                if state:
                    true_indices.append(index)
                    fold_true += 1
                fold_pair_losses.append(pair_loss)
            fold_metrics.append(
                {
                    "fold_id": snapshot_a.fold_id,
                    "known_count": len(fold_pair_losses),
                    "true_count": fold_true,
                    "delta_log_loss_by_comparator": {
                        name: round(
                            (arithmetic_mean(fold_comparator_losses[name]) or 0)
                            - (arithmetic_mean(fold_pair_losses) or 0),
                            8,
                        )
                        if fold_pair_losses
                        else None
                        for name in PAIR_COMPARATORS
                    },
                }
            )
        p_values_raw = {
            name: one_sided_cluster_p(differences[name], dates)[0]
            for name in PAIR_COMPARATORS
        }
        p_value_raw = max(p_values_raw.values())
        cluster_count = one_sided_cluster_p(differences["PARENT_A"], dates)[1]
        true_unique = sorted(set(true_indices))
        known_unique = sorted(set(known_indices))
        league_counts = Counter(
            inputs.fixtures[index].competition_key for index in true_unique
        )
        parent_support = {
            name: len(set(parent_true_indices[name]))
            for name in ("PARENT_A", "PARENT_B")
        }
        parent_floor = min(parent_support.values()) if parent_support else 0
        child_parent_ratio = (
            round(len(true_unique) / parent_floor, 8) if parent_floor else None
        )
        dominant_league_share = (
            round(max(league_counts.values()) / len(true_unique), 8)
            if true_unique
            else None
        )
        coverage = rate(len(known_unique), OOF_COUNT)
        support_gate = (
            len(true_unique) >= 80
            and float(coverage or 0) >= 0.8
            and len(league_counts) >= 3
            and all(int(fold["true_count"]) >= 15 for fold in fold_metrics)
            and float(dominant_league_share or 1.0) <= 0.5
            and float(child_parent_ratio or 0) >= 0.2
        )
        p_value = p_value_raw if support_gate else 1.0
        test_id = f"{pair['pair_id']}|{target.target_id}"
        family_pair = "__".join(
            sorted((str(tag_row_a["family"]), str(tag_row_b["family"])))
        )
        family_id = f"{family_pair}|{target.target_id}"
        parent_snapshots = {
            "PARENT_A": object_hash(
                {
                    "definition_hash": tag_row_a["definition_hash"],
                    "fold_threshold_hashes": parent_threshold_hashes["PARENT_A"],
                    "target_id": target.target_id,
                }
            ),
            "PARENT_B": object_hash(
                {
                    "definition_hash": tag_row_b["definition_hash"],
                    "fold_threshold_hashes": parent_threshold_hashes["PARENT_B"],
                    "target_id": target.target_id,
                }
            ),
        }
        pair_snapshot_hash = object_hash(
            {
                "pair_id": pair["pair_id"],
                "parent_definition_hashes": {
                    "PARENT_A": tag_row_a["definition_hash"],
                    "PARENT_B": tag_row_b["definition_hash"],
                },
                "parent_fold_threshold_hashes": parent_threshold_hashes,
                "parent_mask_ids": {
                    "PARENT_A": mask_records[tag_a]["mask_id"],
                    "PARENT_B": mask_records[tag_b]["mask_id"],
                },
                "parent_tag_snapshot_hashes": parent_snapshots,
                "target_id": target.target_id,
            }
        )
        per_target[target.target_id] = {
            "canonical_test_id": test_id,
            "known_oof": len(known_unique),
            "true_oof": len(true_unique),
            "false_oof": len(known_unique) - len(true_unique),
            "unknown_oof": OOF_COUNT - len(known_unique),
            "coverage_oof": coverage,
            "support_by_league": dict(sorted(league_counts.items())),
            "dominant_league_share": dominant_league_share,
            "parent_true_oof": parent_support,
            "child_to_smaller_parent_support_ratio": child_parent_ratio,
            "pair_log_loss": round(
                arithmetic_mean([log_loss(probabilities, label) for probabilities, label in pair_rows]) or 0,
                8,
            )
            if pair_rows
            else None,
            "comparator_log_loss": {
                name: round(
                    arithmetic_mean(
                        [log_loss(probabilities, label) for probabilities, label in comparator_rows[name]]
                    )
                    or 0,
                    8,
                )
                if comparator_rows[name]
                else None
                for name in (*PAIR_COMPARATORS, "BASE")
            },
            "delta_log_loss_by_comparator": {
                name: round(arithmetic_mean(differences[name]) or 0, 8)
                if differences[name]
                else None
                for name in PAIR_COMPARATORS
            },
            "delta_brier_by_comparator": {
                name: round(arithmetic_mean(brier_differences[name]) or 0, 8)
                if brier_differences[name]
                else None
                for name in PAIR_COMPARATORS
            },
            "ece": ece(pair_rows, target.categories),
            "p_values_raw_by_comparator": p_values_raw,
            "p_value_raw_intersection_union": p_value_raw,
            "p_value": p_value,
            "blocked_test_p_value_forced_to_one": not support_gate,
            "cluster_count": cluster_count,
            "folds": fold_metrics,
            "family_id": family_id,
            "stability_by_comparator": {
                name: _stability_summary(
                    differences[name],
                    evaluated_indices,
                    evaluated_folds,
                    evaluated_teams,
                    inputs,
                )
                for name in PAIR_COMPARATORS
            },
            "pre_multiple_testing_gate": {
                "passed": support_gate,
                "true_oof_gte_80": len(true_unique) >= 80,
                "known_coverage_gte_0_8": float(coverage or 0) >= 0.8,
                "at_least_three_leagues": len(league_counts) >= 3,
                "per_fold_true_gte_15": all(
                    int(fold["true_count"]) >= 15 for fold in fold_metrics
                ),
                "dominant_league_share_lte_0_5": float(dominant_league_share or 1.0)
                <= 0.5,
                "child_parent_support_ratio_gte_0_2": float(child_parent_ratio or 0)
                >= 0.2,
            },
            "parent_definition_hashes": {
                "PARENT_A": tag_row_a["definition_hash"],
                "PARENT_B": tag_row_b["definition_hash"],
            },
            "parent_fold_threshold_hashes": parent_threshold_hashes,
            "parent_mask_ids": {
                "PARENT_A": mask_records[tag_a]["mask_id"],
                "PARENT_B": mask_records[tag_b]["mask_id"],
            },
            "parent_tag_snapshot_hashes": parent_snapshots,
            "pair_snapshot_hash": pair_snapshot_hash,
            "hypothesis_id": "hypothesis:"
            + object_hash(
                {
                    "pair_id": pair["pair_id"],
                    "parents": [tag_a, tag_b],
                    "pair_snapshot_hash": pair_snapshot_hash,
                    "target_id": target.target_id,
                    "campaign": "PHASE-C-V2-PAIR-EXHAUSTIVE",
                }
            ),
        }
    return {
        "pair_id": pair["pair_id"],
        "parent_a": tag_a,
        "parent_b": tag_b,
        "parent_property_a": pair["parent_property_a"],
        "parent_property_b": pair["parent_property_b"],
        "shard_id": pair["shard_id"],
        "target_metrics": per_target,
        "price_metrics": None,
        "status": "TESTED_RAW",
    }


def finalize_pair_results(
    rows: Sequence[dict[str, Any]],
    atomic_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    p_rows: list[tuple[str, float]] = []
    family_rows: dict[str, list[tuple[str, float]]] = defaultdict(list)
    campaign_rows: list[tuple[str, float]] = []
    for atomic in atomic_report["results"]:
        for metric in atomic["target_metrics"].values():
            campaign_rows.append((str(metric["canonical_test_id"]), float(metric["p_value"])))
    for row in rows:
        for metric in row["target_metrics"].values():
            test_id = str(metric["canonical_test_id"])
            p_value = float(metric["p_value"])
            p_rows.append((test_id, p_value))
            campaign_rows.append((test_id, p_value))
            family_rows[str(metric["family_id"])].append((test_id, p_value))
    if len(p_rows) != 2 * len(rows):
        raise RuntimeError("PHASE_C_V2_PAIR_TEST_DENOMINATOR_MISMATCH")
    if len(campaign_rows) != 300 + 2 * len(rows):
        raise RuntimeError("PHASE_C_V2_CAMPAIGN_TEST_DENOMINATOR_MISMATCH")
    q_pair = bh_adjust(p_rows)
    q_family = {
        key: value
        for family in family_rows.values()
        for key, value in bh_adjust(family).items()
    }
    q_campaign = bh_adjust(campaign_rows)
    for atomic in atomic_report["results"]:
        atomic_best = "LONG_TAIL_DEFERRED"
        for metric in atomic["target_metrics"].values():
            test_id = str(metric["canonical_test_id"])
            metric["q_value_campaign_global"] = q_campaign[test_id]
            metric["q_value"] = max(
                float(metric["q_value_atomic_global"]),
                float(metric["q_value_family"]),
                q_campaign[test_id],
            )
            status, suspicious = _status_atomic(metric)
            metric["status"] = status
            metric["review_gate"] = (
                "SUSPICIOUS_EDGE_REVIEW" if suspicious else "STANDARD_REVIEW"
            )
            metric["suspicious_reasons"] = suspicious
            atomic_priority = {
                "LONG_TAIL_DEFERRED": 0,
                "RAW_HISTORICAL_SIGNAL": 1,
                "SURVIVED_MULTIPLE_TESTING": 2,
                "SURVIVED_TEMPORAL_VALIDATION": 3,
            }
            if atomic_priority[status] > atomic_priority[atomic_best]:
                atomic_best = status
        atomic["status"] = atomic_best
    pair_status_counts: Counter[str] = Counter()
    survivor_count = 0
    for row in rows:
        best = "REJECTED"
        for metric in row["target_metrics"].values():
            test_id = str(metric["canonical_test_id"])
            metric["q_value_pair_global"] = q_pair[test_id]
            metric["q_value_family"] = q_family[test_id]
            metric["q_value_campaign_global"] = q_campaign[test_id]
            metric["q_value"] = max(q_pair[test_id], q_family[test_id], q_campaign[test_id])
            fold_values = {
                name: [
                    float(fold["delta_log_loss_by_comparator"][name])
                    for fold in metric["folds"]
                    if fold["delta_log_loss_by_comparator"][name] is not None
                ]
                for name in PAIR_COMPARATORS
            }
            support_gate = bool(metric["pre_multiple_testing_gate"]["passed"])
            stability_gate = all(
                len(values) == 5
                and sum(value > 0 for value in values) >= 4
                and values[-1] > 0
                for values in fold_values.values()
            )
            incremental_gate = all(
                float(metric["delta_log_loss_by_comparator"][name] or 0) >= 0.005
                and float(metric["delta_brier_by_comparator"][name] or 0) > 0
                for name in PAIR_COMPARATORS
            )
            if float(metric["q_value"]) <= 0.05 and support_gate and incremental_gate:
                status = "SURVIVED_MULTIPLE_TESTING"
                if stability_gate and min(
                    float(metric["delta_brier_by_comparator"][name] or 0)
                    for name in PAIR_COMPARATORS
                ) >= 0.002:
                    status = "SURVIVED_TEMPORAL_VALIDATION"
                survivor_count += 1
            elif support_gate:
                status = (
                    "RAW_HISTORICAL_SIGNAL"
                    if min(
                        float(metric["delta_log_loss_by_comparator"][name] or -999)
                        for name in PAIR_COMPARATORS
                    )
                    > 0
                    else "REJECTED"
                )
            else:
                status = "LONG_TAIL_DEFERRED"
            pair_suspicious: list[str] = []
            if int(metric["true_oof"]) < 80:
                pair_suspicious.append("LOW_SUPPORT")
            if float(metric["dominant_league_share"] or 0) > 0.5:
                pair_suspicious.append("LEAGUE_CONCENTRATION")
            if status.startswith("SURVIVED_"):
                pair_suspicious.append("SURVIVING_HISTORICAL_EDGE")
            metric["status"] = status
            metric["review_gate"] = (
                "SUSPICIOUS_EDGE_REVIEW" if pair_suspicious else "STANDARD_REVIEW"
            )
            metric["suspicious_reasons"] = pair_suspicious
            priority = {
                "REJECTED": 0,
                "LONG_TAIL_DEFERRED": 1,
                "RAW_HISTORICAL_SIGNAL": 2,
                "SURVIVED_MULTIPLE_TESTING": 3,
                "SURVIVED_TEMPORAL_VALIDATION": 4,
            }
            if priority[status] > priority[best]:
                best = status
        row["status"] = best
        pair_status_counts[best] += 1
    atomic_status_counts = Counter(str(row["status"]) for row in atomic_report["results"])
    atomic_report["status_counts"] = dict(sorted(atomic_status_counts.items()))
    pair_report = {
        "schema_version": "phase-c-v2-pair-results",
        "verdict": "PAIR_CAMPAIGN_EXHAUSTIVE_OVER_FROZEN_ELIGIBLE_SPACE",
        "pair_count": len(rows),
        "canonical_test_count": len(p_rows),
        "campaign_test_count": len(campaign_rows),
        "status_counts": dict(sorted(pair_status_counts.items())),
        "surviving_test_count": survivor_count,
        "triple_search_locked": True,
        "price_metrics": None,
        "results": sorted(rows, key=lambda row: str(row["pair_id"])),
    }
    campaign_summary = {
        "schema_version": "phase-c-v2-campaign-multiplicity",
        "atomic_test_count": 300,
        "pair_test_count": len(p_rows),
        "campaign_test_count": len(campaign_rows),
        "method": "BH_GLOBAL_STAGE_AND_FAMILY_THEN_BH_CAMPAIGN_GLOBAL_MAX_Q",
        "blocked_tests_p_value": 1.0,
        "surviving_pair_test_count": survivor_count,
        "triple_verdict": (
            "NEXT_ULTRA_REVIEW_READY"
            if survivor_count
            else "TRIPLE_SEARCH_REMAINS_LOCKED_NO_PAIR_SURVIVOR"
        ),
        "triple_search_locked": True,
    }
    return pair_report, campaign_summary


__all__ = [
    "FOLDS",
    "FoldTagState",
    "FeatureInputs",
    "Fixture",
    "Observation",
    "PAIR_SHARD_COUNT",
    "PAIR_COMPARATORS",
    "OOF_COUNT",
    "TARGET_BLIND_SUPPORT_START",
    "TARGET_BLIND_TRAIN_END",
    "TARGET_SPECS",
    "TeamFact",
    "adjusted_probs",
    "arithmetic_mean",
    "bh_adjust",
    "brier_loss",
    "build_observations",
    "build_baselines",
    "build_fold_states",
    "build_structural_masks",
    "canonical_bytes",
    "canonical_pair_id",
    "combine_adjustments",
    "conditional_probs",
    "eligible_history",
    "evaluate_atomic",
    "evaluate_pair_raw",
    "enumerate_pair_census",
    "finalize_pair_results",
    "load_feature_inputs",
    "load_target_labels",
    "log_loss",
    "mask_int",
    "object_hash",
    "one_sided_cluster_p",
    "observation_for_tag",
    "parse_utc",
    "quantile",
    "tag_states",
]
