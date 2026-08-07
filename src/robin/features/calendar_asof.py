"""Deterministic, strictly as-of calendar features.

The module consumes synthetic or already-authorized fixture snapshots only.  It
has no storage, provider, SQL, deployment, or publication boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeAlias, TypedDict

JsonMapping: TypeAlias = Mapping[str, object]
FeatureValue: TypeAlias = int | Literal["TRUE", "FALSE", "UNKNOWN"]


class CalendarSnapshot(TypedDict):
    fixture_id: int
    home_team_id: int
    away_team_id: int
    kickoff: datetime
    known_at: datetime
    status: str

_PLAYED = {"FINISHED"}
_SCHEDULED_LOAD = {"SCHEDULED", "LIVE", "FINISHED", "ABANDONED"}
_WINDOWS = (7, 14, 28)
_CONGESTION_THRESHOLDS = {7: 3, 14: 5, 28: 8}


def render_calendar_result(value: Mapping[str, object]) -> bytes:
    """Return the canonical byte representation used by golden-pack tests."""

    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _mapping(value: object, label: str) -> JsonMapping:
    if not isinstance(value, Mapping):
        raise TypeError(label)
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(label)
    return value


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(label)
    return value


def _instant(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(label)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label}_REQUIRES_TIMEZONE")
    return parsed.astimezone(UTC)


def _latest_snapshot(fixture: JsonMapping, cutoff: datetime) -> CalendarSnapshot | None:
    revisions = []
    for raw in _sequence(fixture.get("revisions", []), "CALENDAR_REVISIONS"):
        revision = _mapping(raw, "CALENDAR_REVISION")
        known_at = _instant(revision.get("known_at"), "CALENDAR_KNOWN_AT")
        if known_at < cutoff:
            revisions.append((known_at, revision))
    if not revisions:
        return None
    _, latest = max(revisions, key=lambda item: item[0])
    status = latest.get("status")
    if not isinstance(status, str):
        raise TypeError("CALENDAR_STATUS")
    return {
        "fixture_id": _integer(fixture.get("fixture_id"), "CALENDAR_FIXTURE_ID"),
        "home_team_id": _integer(fixture.get("home_team_id"), "CALENDAR_HOME_TEAM_ID"),
        "away_team_id": _integer(fixture.get("away_team_id"), "CALENDAR_AWAY_TEAM_ID"),
        "kickoff": _instant(latest.get("kickoff"), "CALENDAR_KICKOFF"),
        "known_at": _instant(latest.get("known_at"), "CALENDAR_KNOWN_AT"),
        "status": status,
    }


def _team_in(snapshot: CalendarSnapshot, team_id: int) -> bool:
    return snapshot["home_team_id"] == team_id or snapshot["away_team_id"] == team_id


def _window_count(
    snapshots: Sequence[CalendarSnapshot],
    *,
    team_id: int,
    target_kickoff: datetime,
    days: int,
    statuses: set[str],
) -> int:
    start = target_kickoff - timedelta(days=days)
    return sum(
        1
        for snapshot in snapshots
        if _team_in(snapshot, team_id)
        and snapshot["status"] in statuses
        and start <= snapshot["kickoff"] < target_kickoff
    )


def _last_played(
    snapshots: Sequence[CalendarSnapshot],
    *,
    team_id: int,
    target_kickoff: datetime,
    venue: Literal["ANY", "HOME", "AWAY"],
) -> datetime | None:
    kickoffs = []
    for snapshot in snapshots:
        if snapshot["status"] not in _PLAYED or snapshot["kickoff"] >= target_kickoff:
            continue
        if venue == "HOME" and snapshot["home_team_id"] != team_id:
            continue
        if venue == "AWAY" and snapshot["away_team_id"] != team_id:
            continue
        if venue == "ANY" and not _team_in(snapshot, team_id):
            continue
        kickoffs.append(snapshot["kickoff"])
    return max(kickoffs, default=None)


def _days_since(target: datetime, prior: datetime | None) -> int | Literal["UNKNOWN"]:
    if prior is None:
        return "UNKNOWN"
    return max(0, int((target - prior).total_seconds() // 86_400))


def _away_streak(
    snapshots: Sequence[CalendarSnapshot],
    *,
    team_id: int,
    target_kickoff: datetime,
    target_is_away: bool,
) -> int:
    if not target_is_away:
        return 0
    played = sorted(
        (
            snapshot
            for snapshot in snapshots
            if snapshot["status"] in _PLAYED
            and snapshot["kickoff"] < target_kickoff
            and _team_in(snapshot, team_id)
        ),
        key=lambda item: (item["kickoff"], item["fixture_id"]),
        reverse=True,
    )
    streak = 1
    for snapshot in played:
        if snapshot["away_team_id"] != team_id:
            break
        streak += 1
    return streak


def _unknown_features() -> dict[str, Literal["UNKNOWN"]]:
    identifiers = [
        "REST_DAYS_HOME",
        "REST_DAYS_AWAY",
        "DAYS_SINCE_LAST_HOME_MATCH",
        "DAYS_SINCE_LAST_AWAY_MATCH",
        "CONSECUTIVE_AWAY_MATCHES_HOME",
        "CONSECUTIVE_AWAY_MATCHES_AWAY",
        "THIRD_CONSECUTIVE_AWAY_HOME",
        "THIRD_CONSECUTIVE_AWAY_AWAY",
        *[f"MATCHES_LAST_{days}D_HOME" for days in _WINDOWS],
        *[f"MATCHES_LAST_{days}D_AWAY" for days in _WINDOWS],
        *[f"FIXTURE_CONGESTION_{days}D" for days in _WINDOWS],
    ]
    return {identifier: "UNKNOWN" for identifier in identifiers}


def build_calendar_features(
    fixtures: Sequence[JsonMapping],
    *,
    target_fixture_id: int,
    cutoff: datetime,
    catalog_complete_at_cutoff: bool,
) -> dict[str, object]:
    """Build calendar variables from snapshots whose ``known_at`` is before cutoff.

    Scheduled load and played load are emitted separately.  The stable feature
    identifiers use played load for historical match counts and scheduled load
    for congestion flags.  An incomplete catalog fails closed to ``UNKNOWN``.
    """

    normalized_cutoff = cutoff.astimezone(UTC)
    visible = [
        snapshot
        for fixture in fixtures
        if (snapshot := _latest_snapshot(fixture, normalized_cutoff)) is not None
    ]
    targets = [item for item in visible if item["fixture_id"] == target_fixture_id]
    if len(targets) != 1:
        return {
            "schema_version": "calendar-strict-asof-result-v1",
            "target_fixture_id": target_fixture_id,
            "cutoff": normalized_cutoff.isoformat(),
            "catalog_complete_at_cutoff": catalog_complete_at_cutoff,
            "status": "TARGET_NOT_KNOWN_AS_OF",
            "features": _unknown_features(),
            "load_counts": {"SCHEDULED_LOAD": "UNKNOWN", "PLAYED_LOAD": "UNKNOWN"},
        }
    target = targets[0]
    others = [item for item in visible if item["fixture_id"] != target_fixture_id]
    home_id = _integer(target["home_team_id"], "CALENDAR_TARGET_HOME")
    away_id = _integer(target["away_team_id"], "CALENDAR_TARGET_AWAY")
    kickoff = target["kickoff"]
    if not isinstance(kickoff, datetime):
        raise TypeError("CALENDAR_TARGET_KICKOFF")
    if not catalog_complete_at_cutoff:
        return {
            "schema_version": "calendar-strict-asof-result-v1",
            "target_fixture_id": target_fixture_id,
            "cutoff": normalized_cutoff.isoformat(),
            "target_kickoff": kickoff.isoformat(),
            "catalog_complete_at_cutoff": False,
            "status": "SOURCE_COMPLETENESS_UNKNOWN",
            "features": _unknown_features(),
            "load_counts": {"SCHEDULED_LOAD": "UNKNOWN", "PLAYED_LOAD": "UNKNOWN"},
        }

    scheduled: dict[str, dict[str, int]] = {"HOME": {}, "AWAY": {}}
    played: dict[str, dict[str, int]] = {"HOME": {}, "AWAY": {}}
    for side, team_id in (("HOME", home_id), ("AWAY", away_id)):
        for days in _WINDOWS:
            scheduled[side][str(days)] = _window_count(
                others,
                team_id=team_id,
                target_kickoff=kickoff,
                days=days,
                statuses=_SCHEDULED_LOAD,
            )
            played[side][str(days)] = _window_count(
                others,
                team_id=team_id,
                target_kickoff=kickoff,
                days=days,
                statuses=_PLAYED,
            )

    home_streak = _away_streak(
        others, team_id=home_id, target_kickoff=kickoff, target_is_away=False
    )
    away_streak = _away_streak(
        others, team_id=away_id, target_kickoff=kickoff, target_is_away=True
    )
    features: dict[str, FeatureValue] = {
        "REST_DAYS_HOME": _days_since(
            kickoff,
            _last_played(others, team_id=home_id, target_kickoff=kickoff, venue="ANY"),
        ),
        "REST_DAYS_AWAY": _days_since(
            kickoff,
            _last_played(others, team_id=away_id, target_kickoff=kickoff, venue="ANY"),
        ),
        "DAYS_SINCE_LAST_HOME_MATCH": _days_since(
            kickoff,
            _last_played(others, team_id=home_id, target_kickoff=kickoff, venue="HOME"),
        ),
        "DAYS_SINCE_LAST_AWAY_MATCH": _days_since(
            kickoff,
            _last_played(others, team_id=away_id, target_kickoff=kickoff, venue="AWAY"),
        ),
        "CONSECUTIVE_AWAY_MATCHES_HOME": home_streak,
        "CONSECUTIVE_AWAY_MATCHES_AWAY": away_streak,
        "THIRD_CONSECUTIVE_AWAY_HOME": "TRUE" if home_streak >= 3 else "FALSE",
        "THIRD_CONSECUTIVE_AWAY_AWAY": "TRUE" if away_streak >= 3 else "FALSE",
    }
    for side in ("HOME", "AWAY"):
        for days in _WINDOWS:
            features[f"MATCHES_LAST_{days}D_{side}"] = played[side][str(days)]
    for days, threshold in _CONGESTION_THRESHOLDS.items():
        maximum = max(scheduled["HOME"][str(days)], scheduled["AWAY"][str(days)])
        features[f"FIXTURE_CONGESTION_{days}D"] = "TRUE" if maximum >= threshold else "FALSE"

    return {
        "schema_version": "calendar-strict-asof-result-v1",
        "target_fixture_id": target_fixture_id,
        "cutoff": normalized_cutoff.isoformat(),
        "target_kickoff": kickoff.isoformat(),
        "catalog_complete_at_cutoff": True,
        "status": "CALENDAR_STRICT_ASOF_MECHANICALLY_VALIDATED",
        "features": features,
        "load_counts": {"SCHEDULED_LOAD": scheduled, "PLAYED_LOAD": played},
    }
