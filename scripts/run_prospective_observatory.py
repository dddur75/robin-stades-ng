"""Bounded orchestration for the Jalon 12 prospective observatory.

The command is fail-closed: estimates never contact a provider, executions
require the exact estimate hash, and a capture is attempted only for a window
which is currently due.  Raw payloads go to the object-store adapter; reports
contain compact metadata only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, cast

from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Engine

from robin.domain.enums import DataAvailability, DataOrigin
from robin.prospective_observatory.budgets import (
    MAX_API_FOOTBALL_CALLS_TOTAL,
    MAX_ODDS_API_CREDITS_TOTAL,
    BudgetEntry,
    BudgetExceeded,
    BudgetLedger,
    ProviderKind,
)
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureAttempt,
    CaptureContext,
    CaptureFamily,
    CaptureReceipt,
    CaptureWindow,
    ProspectiveFixture,
    RetryDisposition,
    canonical_sha256,
)
from robin.prospective_observatory.gates import (
    GateEvaluation,
    GateName,
    GateObservation,
    GateStatus,
    aggregate_gate_evaluations,
    evaluate_fixture_gates,
)
from robin.prospective_observatory.ledger import (
    PublicEvidenceLedgerV3,
    build_observatory_ledger,
    observatory_ledger_summary,
)
from robin.prospective_observatory.multi_league import (
    ODDS_WINDOW_PRIORITY,
    CaptureProfile,
    ScopedBudgetUsage,
    active_competitions,
    authorize_scoped_budget,
    competition_registry,
    labels_for_profile,
)
from robin.prospective_observatory.r2 import (
    DurableProviderBudget,
    ObjectStore,
    ProspectiveR2Repository,
    StoredCapture,
)
from robin.prospective_observatory.replay import (
    InMemoryProjectionSink,
    ProjectionSink,
    replay_from_r2,
)
from robin.prospective_observatory.temporal import (
    classify_window,
    is_versioned_window_id,
    reconstructible_legacy_windows,
    retry_disposition,
    schedule_windows,
)
from robin.providers.api_football import ApiFootballProvider
from robin.providers.contracts import (
    CircuitOpenError,
    MissingCredentialError,
    ProviderResult,
    QuotaState,
    RateLimitError,
    TransientProviderError,
)
from robin.providers.the_odds_api import TheOddsApiProvider
from robin.storage.database import build_engine

DEFAULT_POLICY = Path("configs/prospective_observatory_v1.json")
SCHEMA_VERSION = "prospective-observatory-operation-v1"
SNAPSHOT_SCHEMA_VERSION = "prospective-observatory-snapshot-v1"
EXPECTED_ALEMBIC_REVISION = "0013_historical_evidence_index"
OBSERVATORY_SCHEMA_REVISION = "0009_jalon12_observatory"
SAFE_CODE_REVISION = "local-uncommitted"
PLAYER_FAMILIES = (
    CaptureFamily.SQUAD,
    CaptureFamily.PLAYER_STATUS,
    CaptureFamily.INJURY,
)
LINEUP_FAMILIES = (CaptureFamily.LINEUP, CaptureFamily.FORMATION)
ODDS_FAMILIES = (CaptureFamily.ODDS,)
GENERAL_FAMILIES = (
    CaptureFamily.FIXTURE,
    CaptureFamily.TEAM,
    CaptureFamily.EVENT_STATUS,
)
CAPTURE_REPORT_NAMES = {
    "capture-general": "general-capture",
    "capture-player": "player-capture",
    "capture-lineup": "lineup-capture",
    "capture-odds": "odds-capture",
}


def _stable_id(scope: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"robin:j12:{scope}:{value}"))


def asdict_gate(evaluation: GateEvaluation) -> dict[str, object]:
    return {
        "gate": evaluation.gate.value,
        "fixture_id": evaluation.fixture_id,
        "status": evaluation.status.value,
        "observations": evaluation.observations,
        "reason": evaluation.reason,
        "evidence": evaluation.evidence,
    }


def _db_value(value: object) -> object:
    if isinstance(value, datetime) and (
        value.tzinfo is None or value.utcoffset() is None
    ):
        return value.replace(tzinfo=UTC)
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_utc(value: str | None) -> datetime:
    if value is None:
        return _utc_now()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NOW_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger_jsonl_bytes(ledger: PublicEvidenceLedgerV3) -> bytes:
    return "".join(
        json.dumps(
            {
                **asdict(event),
                "event_kind": event.event_kind.value,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for event in ledger.events
    ).encode("utf-8")


def _write_immutable_bytes(path: Path, value: bytes) -> str:
    digest = hashlib.sha256(value).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise RuntimeError("PUBLIC_EVIDENCE_LEDGER_V3_APPEND_ONLY_CONFLICT")
    else:
        path.write_bytes(value)
    return digest


def _mapping(value: object, *, error: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(error)
    return cast(dict[str, object], value)


def _int_value(value: object, *, error: str) -> int:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, str, bytes, bytearray),
    ):
        raise ValueError(error)
    try:
        return int(value)
    except ValueError as exception:
        raise ValueError(error) from exception


@dataclass(frozen=True, slots=True)
class ObservatoryPolicy:
    path: Path
    value: dict[str, object]
    sha256: str

    @classmethod
    def load(cls, path: Path) -> ObservatoryPolicy:
        value = _mapping(_read_json(path), error="PROSPECTIVE_POLICY_INVALID")
        if value.get("schema_version") != "prospective-observatory-policy-v2":
            raise ValueError("PROSPECTIVE_POLICY_SCHEMA_INVALID")
        budgets = _mapping(
            value.get("provider_budgets"),
            error="PROSPECTIVE_POLICY_BUDGETS_INVALID",
        )
        api_budget = _mapping(
            budgets.get("api_football"),
            error="PROSPECTIVE_API_FOOTBALL_BUDGET_INVALID",
        )
        odds_budget = _mapping(
            budgets.get("odds_api"),
            error="PROSPECTIVE_ODDS_BUDGET_INVALID",
        )
        for budget, required in (
            (
                api_budget,
                (
                    "per_run",
                    "per_day",
                    "per_competition_per_run",
                    "per_competition_per_day",
                    "per_season",
                    "provider_reserve",
                ),
            ),
            (
                odds_budget,
                (
                    "per_run",
                    "per_day",
                    "per_week",
                    "per_competition_per_run",
                    "per_competition_per_day",
                    "provider_reserve",
                    "internal_safety_reserve",
                    "near_kickoff_reserve",
                    "circuit_breaker_failures",
                    "circuit_breaker_cooldown_minutes",
                ),
            ),
        ):
            if any(
                isinstance(budget.get(key), bool)
                or not isinstance(budget.get(key), int)
                or cast(int, budget.get(key)) <= 0
                for key in required
            ):
                raise ValueError("PROSPECTIVE_PROVIDER_BUDGET_LIMIT_INVALID")
        if api_budget["provider_reserve"] != 5_000:
            raise ValueError("PROSPECTIVE_API_FOOTBALL_RESERVE_MUST_BE_5000")
        if odds_budget["internal_safety_reserve"] != 2:
            raise ValueError("PROSPECTIVE_ODDS_INTERNAL_RESERVE_MUST_BE_2")
        if odds_budget.get("window_priority") != list(ODDS_WINDOW_PRIORITY):
            raise ValueError("PROSPECTIVE_ODDS_PRIORITY_INVALID")
        competitions = competition_registry(value)
        if len(competitions) != 5 or len(active_competitions(value)) != 5:
            raise ValueError("PROSPECTIVE_FIVE_LEAGUE_REGISTRY_REQUIRED")
        storage = _mapping(value.get("storage"), error="PROSPECTIVE_STORAGE_POLICY_INVALID")
        if (
            storage.get("raw_primary") != "R2"
            or storage.get("git_raw_payloads_allowed") != 0
            or storage.get("postgresql_payload_bodies_allowed") != 0
            or storage.get("append_only") is not True
        ):
            raise ValueError("PROSPECTIVE_R2_FIRST_POLICY_REQUIRED")
        invariants = _mapping(
            value.get("invariants"),
            error="PROSPECTIVE_INVARIANTS_INVALID",
        )
        expected = {
            "STORAGE_PAUSED": True,
            "P3_P4_PAUSED": True,
            "PRODUCTION_LOCKED": True,
            "REAL_BETS": False,
            "NO_BET_DEFAULT": True,
            "SOCIAL_PUBLISHING_ENABLED": False,
            "DEMO_MODE_ENABLED": False,
        }
        if invariants != expected:
            raise ValueError("PROSPECTIVE_FAIL_CLOSED_INVARIANTS_REQUIRED")
        return cls(path=path, value=value, sha256=canonical_sha256(value))

    @property
    def budgets(self) -> dict[str, object]:
        return _mapping(
            self.value["provider_budgets"],
            error="PROSPECTIVE_POLICY_BUDGETS_INVALID",
        )

    @property
    def fixture_registry(self) -> dict[str, object]:
        return _mapping(
            self.value["fixture_registry"],
            error="PROSPECTIVE_FIXTURE_POLICY_INVALID",
        )

    @property
    def operational_tolerance(self) -> timedelta:
        capture_windows = _mapping(
            self.value["capture_windows"],
            error="PROSPECTIVE_CAPTURE_WINDOW_POLICY_INVALID",
        )
        seconds = capture_windows.get("operational_tolerance_seconds")
        if not isinstance(seconds, int) or not 0 <= seconds <= 3600:
            raise ValueError("PROSPECTIVE_CAPTURE_TOLERANCE_INVALID")
        return timedelta(seconds=seconds)

    def competition(self, name: str) -> dict[str, object]:
        registry = self.value.get("competition_registry")
        if not isinstance(registry, list):
            raise ValueError("PROSPECTIVE_COMPETITION_REGISTRY_INVALID")
        matches = [
            _mapping(item, error="PROSPECTIVE_COMPETITION_INVALID")
            for item in registry
            if isinstance(item, dict) and item.get("competition") == name
        ]
        if len(matches) != 1:
            raise ValueError("PROSPECTIVE_COMPETITION_NOT_REGISTERED")
        return matches[0]

    def competitions(self) -> tuple[dict[str, object], ...]:
        registry = self.value.get("competition_registry")
        if not isinstance(registry, list):
            raise ValueError("PROSPECTIVE_COMPETITION_REGISTRY_INVALID")
        return tuple(
            _mapping(item, error="PROSPECTIVE_COMPETITION_INVALID")
            for item in registry
        )

    def provider_budget(self, provider: ProviderKind) -> dict[str, object]:
        key = (
            "api_football"
            if provider is ProviderKind.API_FOOTBALL
            else "odds_api"
        )
        return _mapping(
            self.budgets.get(key),
            error="PROSPECTIVE_PROVIDER_BUDGET_INVALID",
        )

    def run_cap(self, provider: ProviderKind) -> int:
        return _int_value(
            self.provider_budget(provider).get("per_run"),
            error="PROSPECTIVE_PROVIDER_RUN_CAP_INVALID",
        )

    def provider_reserve(self, provider: ProviderKind) -> int:
        return _int_value(
            self.provider_budget(provider).get("provider_reserve"),
            error="PROSPECTIVE_PROVIDER_RESERVE_INVALID",
        )

    def internal_safety_reserve(self, provider: ProviderKind) -> int:
        if provider is ProviderKind.API_FOOTBALL:
            return 0
        return _int_value(
            self.provider_budget(provider).get("internal_safety_reserve"),
            error="PROSPECTIVE_PROVIDER_INTERNAL_RESERVE_INVALID",
        )

    def near_kickoff_reserve(self) -> int:
        return _int_value(
            self.provider_budget(ProviderKind.ODDS_API).get(
                "near_kickoff_reserve"
            ),
            error="PROSPECTIVE_ODDS_NEAR_KICKOFF_RESERVE_INVALID",
        )

    def circuit_breaker_failures(self, provider: ProviderKind) -> int:
        if provider is not ProviderKind.ODDS_API:
            return 3
        return _int_value(
            self.provider_budget(provider).get("circuit_breaker_failures"),
            error="PROSPECTIVE_CIRCUIT_BREAKER_FAILURES_INVALID",
        )

    def circuit_breaker_cooldown_seconds(
        self,
        provider: ProviderKind,
    ) -> float:
        if provider is not ProviderKind.ODDS_API:
            return 60.0
        minutes = _int_value(
            self.provider_budget(provider).get(
                "circuit_breaker_cooldown_minutes"
            ),
            error="PROSPECTIVE_CIRCUIT_BREAKER_COOLDOWN_INVALID",
        )
        return float(minutes * 60)

    def capture_profile(self, competition: str) -> CaptureProfile:
        return CaptureProfile(str(self.competition(competition)["capture_profile"]))

    def odds_sport_key(self, competition: str) -> str:
        value = str(self.competition(competition).get("odds_sport_key", ""))
        if not value:
            raise ValueError("PROSPECTIVE_ODDS_SPORT_KEY_MISSING")
        return value

    def allowed_window_labels(
        self,
        competition: str,
        family: CaptureFamily,
    ) -> tuple[str, ...]:
        capture_windows = _mapping(
            self.value["capture_windows"],
            error="PROSPECTIVE_CAPTURE_WINDOW_POLICY_INVALID",
        )
        raw_labels = capture_windows.get(family.value)
        if not isinstance(raw_labels, list) or any(
            not isinstance(label, str) for label in raw_labels
        ):
            raise ValueError("PROSPECTIVE_CAPTURE_WINDOW_LABELS_INVALID")
        profile = self.capture_profile(competition)
        profiles = _mapping(
            self.value.get("capture_profiles"),
            error="PROSPECTIVE_CAPTURE_PROFILES_INVALID",
        )
        profile_policy = _mapping(
            profiles.get(profile.value),
            error="PROSPECTIVE_CAPTURE_PROFILE_POLICY_INVALID",
        )
        families = profile_policy.get("families")
        odds_windows = profile_policy.get("odds_windows")
        if (
            not isinstance(families, list)
            or any(not isinstance(value, str) for value in families)
            or not isinstance(odds_windows, list)
            or any(not isinstance(value, str) for value in odds_windows)
        ):
            raise ValueError("PROSPECTIVE_CAPTURE_PROFILE_POLICY_INVALID")
        if family.value not in families:
            return ()
        labels = labels_for_profile(
            profile,
            family,
            cast(list[str], raw_labels),
        )
        if family is CaptureFamily.ODDS:
            allowed = set(cast(list[str], odds_windows))
            return tuple(label for label in labels if label in allowed)
        return labels


def _budget_scope(reason: str) -> str | None:
    match = re.search(r"(?:^|;)SCOPE=([^;]+)(?:;|$)", reason)
    return match.group(1) if match is not None else None


def _budget_usage(
    state: OperationalState,
    *,
    provider: ProviderKind,
    competition: str,
    now: datetime,
) -> ScopedBudgetUsage:
    now_utc = now.astimezone(UTC)
    iso = now_utc.isocalendar()
    entries = tuple(
        entry
        for entry in state.budget_entries()
        if entry.provider is provider and entry.units > 0
    )
    day = sum(
        entry.units
        for entry in entries
        if entry.recorded_at.astimezone(UTC).date() == now_utc.date()
    )
    week = sum(
        entry.units
        for entry in entries
        if (
            entry.recorded_at.astimezone(UTC).isocalendar().year,
            entry.recorded_at.astimezone(UTC).isocalendar().week,
        )
        == (iso.year, iso.week)
    )
    competition_entries = tuple(
        entry
        for entry in entries
        if _budget_scope(entry.reason) == competition
    )
    competition_day = sum(
        entry.units
        for entry in competition_entries
        if entry.recorded_at.astimezone(UTC).date() == now_utc.date()
    )
    # The provider season follows the calendar-year label returned by
    # API-Football. Entries without an old scope are intentionally excluded
    # from the per-league count but remain included in global day/week usage.
    season = sum(
        entry.units
        for entry in competition_entries
        if entry.recorded_at.astimezone(UTC).year == now_utc.year
    )
    return ScopedBudgetUsage(
        day=day,
        week=week,
        competition_day=competition_day,
        season=season,
    )


def _authorize_budget_plan(
    state: OperationalState,
    *,
    policy: ObservatoryPolicy,
    provider: ProviderKind,
    units_by_competition: Mapping[str, int],
    provider_remaining: int,
    now: datetime,
) -> tuple[dict[str, object], ...]:
    provider_key = (
        "api_football"
        if provider is ProviderKind.API_FOOTBALL
        else "odds_api"
    )
    planned_before = 0
    decisions: list[dict[str, object]] = []
    for competition in sorted(units_by_competition):
        units = units_by_competition[competition]
        base = _budget_usage(
            state,
            provider=provider,
            competition=competition,
            now=now,
        )
        usage = ScopedBudgetUsage(
            run=planned_before,
            day=base.day + planned_before,
            week=base.week + planned_before,
            competition_run=0,
            competition_day=base.competition_day,
            season=base.season,
        )
        decision = authorize_scoped_budget(
            policy=policy.value,
            provider=provider_key,
            competition=competition,
            estimated_units=units,
            provider_remaining=provider_remaining - planned_before,
            usage=usage,
        )
        decisions.append(
            {
                **asdict(decision),
                "competition": competition,
                "provider": provider.value,
            }
        )
        if not decision.allowed:
            raise BudgetExceeded(
                f"PROSPECTIVE_ADAPTIVE_BUDGET_BLOCKED:"
                f"{provider.value}:{competition}:{decision.reason}"
            )
        planned_before += units
    return tuple(decisions)


class R2ObjectStore:
    """Small Cloudflare adapter with no deletion surface."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        from robin.historical.object_storage_migration import create_r2_client

        self.client, self.bucket = create_r2_client(environment)

    @staticmethod
    def _missing(error: ClientError) -> bool:
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}

    def get_object(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if self._missing(error):
                return None
            raise
        body = response.get("Body")
        if body is None or not hasattr(body, "read"):
            raise RuntimeError("R2_BODY_INVALID")
        payload = body.read()
        if not isinstance(payload, bytes):
            raise RuntimeError("R2_BODY_INVALID")
        return payload

    def put_if_absent(self, key: str, data: bytes) -> bool:
        try:
            cast(Any, self.client).put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                IfNoneMatch="*",
                Metadata={"lane": "prospective-deep-data", "append-only": "true"},
            )
            return True
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}:
                return False
            raise

    def iter_keys(self, prefix: str) -> Iterable[str]:
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": self.bucket,
                "Prefix": prefix,
                "MaxKeys": 1000,
            }
            if token is not None:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)  # type: ignore[attr-defined]
            contents = response.get("Contents", [])
            if not isinstance(contents, list):
                raise RuntimeError("R2_LIST_RESPONSE_INVALID")
            for item in contents:
                if isinstance(item, Mapping) and isinstance(item.get("Key"), str):
                    yield str(item["Key"])
            if not bool(response.get("IsTruncated")):
                return
            candidate = response.get("NextContinuationToken")
            if not isinstance(candidate, str) or not candidate:
                raise RuntimeError("R2_LIST_CURSOR_MISSING")
            token = candidate


class OddsFixtureIdentityError(RuntimeError):
    pass


class DirectoryObjectStore:
    """Append-only local adapter used only by cache tests and pilot-mock."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / Path(key)).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("OBJECT_KEY_OUTSIDE_CACHE_ROOT")
        return candidate

    def get_object(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def put_if_absent(self, key: str, data: bytes) -> bool:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(data)
        except FileExistsError:
            return False
        return True

    def iter_keys(self, prefix: str) -> Iterable[str]:
        prefix_path = self._path(f"{prefix.rstrip('/')}/_prefix")
        root = prefix_path.parent
        if not root.exists():
            return ()
        return tuple(
            sorted(
                path.relative_to(self.root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
        )


class OperationalState(Protocol):
    def register_fixture(
        self,
        fixture: ProspectiveFixture,
        capture: StoredCapture,
    ) -> bool: ...

    def fixtures(self) -> tuple[ProspectiveFixture, ...]: ...

    def fixture_versions(self) -> tuple[ProspectiveFixture, ...]: ...

    def fixture_lifecycle_heads(self) -> tuple[ProspectiveFixture, ...]: ...

    def schedule_window(self, window: CaptureWindow) -> bool: ...

    def schedule_windows_batch(
        self,
        windows: Iterable[CaptureWindow],
    ) -> tuple[int, int]: ...

    def windows(self) -> tuple[CaptureWindow, ...]: ...

    def append_attempt(self, attempt: CaptureAttempt) -> bool: ...

    def attempts(self) -> tuple[CaptureAttempt, ...]: ...

    def persist_capture(self, capture: StoredCapture) -> bool: ...

    def budget_used(self, provider: ProviderKind) -> int: ...

    def budget_entries(self) -> tuple[BudgetEntry, ...]: ...

    def external_quota_remaining(
        self,
        provider: ProviderKind,
        *,
        now: datetime,
    ) -> int | None: ...

    def append_budget(
        self,
        *,
        idempotency_key: str,
        provider: ProviderKind,
        units: int,
        provider_remaining: int,
        provider_reserve: int,
        recorded_at: datetime,
        reason: str,
        code_revision: str,
    ) -> bool: ...

    def projection_sink(self) -> ProjectionSink: ...

    def receipts(self) -> tuple[CaptureReceipt, ...]: ...

    def gate_observations(self) -> tuple[GateObservation, ...]: ...

    def append_gate(
        self,
        evaluation: GateEvaluation,
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> bool: ...

    def append_gates_batch(
        self,
        evaluations: Iterable[GateEvaluation],
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> tuple[int, int]: ...


@dataclass(slots=True)
class MemoryOperationalState:
    fixture_rows: dict[str, tuple[str, ProspectiveFixture]] = field(default_factory=dict)
    fixture_version_rows: dict[str, ProspectiveFixture] = field(default_factory=dict)
    window_rows: dict[str, CaptureWindow] = field(default_factory=dict)
    attempt_rows: dict[str, CaptureAttempt] = field(default_factory=dict)
    receipt_rows: dict[str, CaptureReceipt] = field(default_factory=dict)
    budget_rows: dict[str, BudgetEntry] = field(default_factory=dict)
    gate_rows: dict[str, GateEvaluation] = field(default_factory=dict)
    sink: InMemoryProjectionSink = field(default_factory=InMemoryProjectionSink)

    def register_fixture(
        self,
        fixture: ProspectiveFixture,
        capture: StoredCapture,
    ) -> bool:
        value = (fixture.registry_hash, fixture)
        version_already_registered = (
            fixture.registry_hash in self.fixture_version_rows
        )
        self.fixture_version_rows.setdefault(fixture.registry_hash, fixture)
        existing = self.fixture_rows.get(fixture.fixture_id)
        if version_already_registered:
            self.persist_capture(capture)
            if (
                existing is None
                or existing[1].registered_at <= fixture.registered_at
            ):
                self.fixture_rows[fixture.fixture_id] = value
            return False
        if existing is not None and existing[0] == fixture.registry_hash:
            # Ingestion metadata (registered_at/code_revision) is deliberately
            # outside the business-version hash. Keep each R2 receipt while
            # avoiding a second fixture row for an unchanged provider fixture.
            self.persist_capture(capture)
            self.fixture_rows[fixture.fixture_id] = value
            return False
        self.fixture_rows[fixture.fixture_id] = value
        self.persist_capture(capture)
        return True

    def fixtures(self) -> tuple[ProspectiveFixture, ...]:
        return tuple(
            row[1] for row in self.fixture_rows.values() if not row[1].cancelled
        )

    def fixture_versions(self) -> tuple[ProspectiveFixture, ...]:
        return tuple(self.fixture_version_rows.values())

    def fixture_lifecycle_heads(self) -> tuple[ProspectiveFixture, ...]:
        return tuple(row[1] for row in self.fixture_rows.values())

    def schedule_window(self, window: CaptureWindow) -> bool:
        existing = self.window_rows.get(window.window_id)
        if existing is not None:
            if existing != window:
                raise ValueError("CAPTURE_WINDOW_IDEMPOTENCY_CONFLICT")
            return False
        self.window_rows[window.window_id] = window
        return True

    def schedule_windows_batch(
        self,
        windows: Iterable[CaptureWindow],
    ) -> tuple[int, int]:
        inserted = 0
        duplicates = 0
        for window in windows:
            if self.schedule_window(window):
                inserted += 1
            else:
                duplicates += 1
        return inserted, duplicates

    def windows(self) -> tuple[CaptureWindow, ...]:
        return tuple(self.window_rows.values())

    def append_attempt(self, attempt: CaptureAttempt) -> bool:
        existing = self.attempt_rows.get(attempt.idempotency_key)
        if existing is not None:
            if existing != attempt:
                raise ValueError("CAPTURE_ATTEMPT_IDEMPOTENCY_CONFLICT")
            return False
        if any(
            item.window_id == attempt.window_id
            and item.attempt_number == attempt.attempt_number
            for item in self.attempt_rows.values()
        ):
            raise ValueError("CAPTURE_ATTEMPT_NUMBER_CONFLICT")
        self.attempt_rows[attempt.idempotency_key] = attempt
        return True

    def attempts(self) -> tuple[CaptureAttempt, ...]:
        return tuple(self.attempt_rows.values())

    def persist_capture(self, capture: StoredCapture) -> bool:
        key = capture.receipt.receipt_hash
        existing = self.receipt_rows.get(key)
        if existing is not None:
            if existing != capture.receipt:
                raise ValueError("CAPTURE_RECEIPT_IDEMPOTENCY_CONFLICT")
            return False
        self.receipt_rows[key] = capture.receipt
        return True

    def budget_used(self, provider: ProviderKind) -> int:
        return sum(
            entry.units
            for entry in self.budget_rows.values()
            if entry.provider is provider
        )

    def budget_entries(self) -> tuple[BudgetEntry, ...]:
        return tuple(self.budget_rows.values())

    def external_quota_remaining(
        self,
        provider: ProviderKind,
        *,
        now: datetime,
    ) -> int | None:
        del provider, now
        return None

    def append_budget(
        self,
        *,
        idempotency_key: str,
        provider: ProviderKind,
        units: int,
        provider_remaining: int,
        provider_reserve: int,
        recorded_at: datetime,
        reason: str,
        code_revision: str,
    ) -> bool:
        del provider_remaining, provider_reserve, code_revision
        if units < 0:
            raise ValueError("PROVIDER_BUDGET_UNITS_INVALID")
        value = BudgetEntry(
            idempotency_key=idempotency_key,
            provider=provider,
            units=units,
            recorded_at=recorded_at,
            reason=reason,
        )
        existing = self.budget_rows.get(idempotency_key)
        if existing is not None:
            if existing != value:
                raise ValueError("PROVIDER_BUDGET_IDEMPOTENCY_CONFLICT")
            return False
        hard_limit = (
            MAX_API_FOOTBALL_CALLS_TOTAL
            if provider is ProviderKind.API_FOOTBALL
            else MAX_ODDS_API_CREDITS_TOTAL
        )
        if self.budget_used(provider) + units > hard_limit:
            raise BudgetExceeded(
                f"PROSPECTIVE_PROVIDER_CAP_EXCEEDED:{provider.value}"
            )
        self.budget_rows[idempotency_key] = value
        return True

    def projection_sink(self) -> ProjectionSink:
        return self.sink

    def receipts(self) -> tuple[CaptureReceipt, ...]:
        return tuple(self.receipt_rows.values())

    def gate_observations(self) -> tuple[GateObservation, ...]:
        rows = self.sink.rows
        return tuple(
            GateObservation(
                receipt=receipt,
                projection=(
                    dict(rows[receipt.receipt_hash][1])
                    if receipt.receipt_hash in rows
                    else {}
                ),
            )
            for receipt in self.receipt_rows.values()
        )

    def append_gate(
        self,
        evaluation: GateEvaluation,
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> bool:
        key = canonical_sha256(
            {
                "evaluation": asdict_gate(evaluation),
                "evaluated_at": evaluated_at.isoformat(),
                "code_revision": code_revision,
            }
        )
        if key in self.gate_rows:
            return False
        self.gate_rows[key] = evaluation
        return True

    def append_gates_batch(
        self,
        evaluations: Iterable[GateEvaluation],
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> tuple[int, int]:
        inserted = 0
        duplicates = 0
        for evaluation in evaluations:
            if self.append_gate(
                evaluation,
                evaluated_at=evaluated_at,
                code_revision=code_revision,
            ):
                inserted += 1
            else:
                duplicates += 1
        return inserted, duplicates


class SQLAlchemyOperationalState(MemoryOperationalState):
    """Database-backed implementation using reflected Jalon 12 tables.

    The in-memory mirrors are only a typed working set. Every write is first
    persisted transactionally, with exact-duplicate checks and no update path.
    """

    REQUIRED_TABLES = {
        "prospective_fixtures",
        "capture_windows",
        "capture_attempts",
        "capture_receipts",
        "prospective_payload_index",
        "prospective_player_status",
        "prospective_injuries",
        "prospective_lineups",
        "prospective_formations",
        "prospective_odds_snapshots",
        "temporal_data_gates",
        "provider_budget_ledger",
    }

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self.engine = engine
        names = set(inspect(engine).get_table_names())
        missing = self.REQUIRED_TABLES - names
        if missing:
            raise RuntimeError(
                f"PROSPECTIVE_DATABASE_TABLES_MISSING:{','.join(sorted(missing))}"
            )
        with engine.connect() as connection:
            revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
        if str(revision) != EXPECTED_ALEMBIC_REVISION:
            raise RuntimeError("PROSPECTIVE_DATABASE_REVISION_0013_REQUIRED")
        metadata = MetaData()
        metadata.reflect(bind=engine, only=sorted(self.REQUIRED_TABLES))
        self.tables = {name: metadata.tables[name] for name in self.REQUIRED_TABLES}
        self._restore()

    @staticmethod
    def _row_for(table: Table, values: Mapping[str, object]) -> dict[str, object]:
        return {key: value for key, value in values.items() if key in table.c}

    def _insert_exact(
        self,
        table_name: str,
        *,
        key_values: Mapping[str, object],
        values: Mapping[str, object],
    ) -> bool:
        table = self.tables[table_name]
        row = self._row_for(table, values)
        keys = self._row_for(table, key_values)
        if not keys:
            raise RuntimeError(f"PROSPECTIVE_DATABASE_KEY_COLUMNS_MISSING:{table_name}")
        predicate = [table.c[name] == value for name, value in keys.items()]
        with self.engine.begin() as connection:
            existing = connection.execute(select(table).where(*predicate)).mappings().first()
            if existing is not None:
                comparable = {key: existing[key] for key in row if key in existing}
                if any(
                    _json_compatible(comparable[key]) != _json_compatible(value)
                    for key, value in row.items()
                ):
                    raise ValueError(f"PROSPECTIVE_DATABASE_IDEMPOTENCY_CONFLICT:{table_name}")
                return False
            connection.execute(table.insert().values(**row))
        return True

    def _restore(self) -> None:
        fixture_table = self.tables["prospective_fixtures"]
        window_table = self.tables["capture_windows"]
        attempt_table = self.tables["capture_attempts"]
        receipt_table = self.tables["capture_receipts"]
        budget_table = self.tables["provider_budget_ledger"]
        with self.engine.connect() as connection:
            fixture_rows = connection.execute(select(fixture_table)).mappings()
            for row in fixture_rows:
                fixture = ProspectiveFixture.model_validate(
                    {
                        "fixture_id": row["fixture_id"],
                        "competition": row["competition"],
                        "season": str(row["season"]),
                        "phase": row["phase"],
                        "home_team_id": str(row["home_team_id"]),
                        "away_team_id": str(row["away_team_id"]),
                        "kickoff_at": _db_value(row["kickoff_at"]),
                        "provider": row["provider"],
                        "provider_fixture_id": str(row["provider_fixture_id"]),
                        "registered_at": _db_value(row["registered_at"]),
                        "code_revision": row["code_revision"],
                        "cancelled": bool(row["cancelled"]),
                        "kickoff_reliable": True,
                        # The compact SQL projection predates this policy
                        # metadata. Reconstruct it with the current discovery
                        # default; the immutable provider identity deliberately
                        # excludes the horizon.
                        "horizon_days": int(row.get("horizon_days", 45)),
                        "lifecycle_version_hash": str(row["registry_hash"]),
                    }
                )
                self.fixture_version_rows.setdefault(
                    fixture.registry_hash,
                    fixture,
                )
                existing = self.fixture_rows.get(fixture.fixture_id)
                if existing is None or existing[1].registered_at < fixture.registered_at:
                    self.fixture_rows[fixture.fixture_id] = (
                        fixture.registry_hash,
                        fixture,
                    )
            for row in connection.execute(select(window_table)).mappings():
                window = CaptureWindow.model_validate(
                    {
                        key: _db_value(row[key])
                        for key in CaptureWindow.model_fields
                        if key in row
                    }
                )
                self.window_rows[window.window_id] = window
            for row in connection.execute(select(attempt_table)).mappings():
                attempt = CaptureAttempt.model_validate(
                    {
                        key: _db_value(row[key])
                        for key in CaptureAttempt.model_fields
                        if key in row
                    }
                )
                self.attempt_rows[attempt.idempotency_key] = attempt
            for row in connection.execute(select(receipt_table)).mappings():
                receipt_data = {
                    key: _db_value(row[key])
                    for key in CaptureReceipt.model_fields
                    if key in row
                }
                receipt = CaptureReceipt.model_validate(receipt_data)
                self.receipt_rows[receipt.receipt_hash] = receipt
            for row in connection.execute(select(budget_table)).mappings():
                key = str(row["idempotency_key"])
                self.budget_rows[key] = BudgetEntry(
                    idempotency_key=key,
                    provider=ProviderKind(str(row["provider"])),
                    units=int(row["units"]),
                    recorded_at=cast(datetime, _db_value(row["recorded_at"])),
                    reason=str(row["reason"]),
                )

    def register_fixture(
        self,
        fixture: ProspectiveFixture,
        capture: StoredCapture,
    ) -> bool:
        version_already_registered = (
            fixture.registry_hash in self.fixture_version_rows
        )
        self.fixture_version_rows.setdefault(fixture.registry_hash, fixture)
        existing = self.fixture_rows.get(fixture.fixture_id)
        if version_already_registered:
            self.persist_capture(capture)
            if (
                existing is None
                or existing[1].registered_at <= fixture.registered_at
            ):
                self.fixture_rows[fixture.fixture_id] = (
                    fixture.registry_hash,
                    fixture,
                )
            return False
        if existing is not None and existing[0] == fixture.registry_hash:
            self.persist_capture(capture)
            self.fixture_rows[fixture.fixture_id] = (
                fixture.registry_hash,
                fixture,
            )
            return False
        values = fixture.model_dump()
        values.update(
            {
                "id": _stable_id("fixture", fixture.registry_hash),
                "idempotency_key": fixture.registry_hash,
                "registry_hash": fixture.registry_hash,
                "append_only": True,
            }
        )
        inserted = self._insert_exact(
            "prospective_fixtures",
            key_values={"idempotency_key": fixture.registry_hash},
            values=values,
        )
        self.persist_capture(capture)
        self.fixture_rows[fixture.fixture_id] = (
            fixture.registry_hash,
            fixture,
        )
        return inserted

    def schedule_window(self, window: CaptureWindow) -> bool:
        inserted, _ = self.schedule_windows_batch((window,))
        return inserted == 1

    def schedule_windows_batch(
        self,
        windows: Iterable[CaptureWindow],
    ) -> tuple[int, int]:
        immutable = (
            "fixture_id",
            "family",
            "label",
            "due_at",
            "opens_at",
            "cutoff_at",
            "kickoff_at",
            "operational_tolerance_seconds",
            "policy_version",
        )
        pending: dict[str, tuple[CaptureWindow, dict[str, object]]] = {}
        duplicates = 0
        for window in windows:
            fixture_entry = self.fixture_rows.get(window.fixture_id)
            if fixture_entry is None:
                raise RuntimeError("CAPTURE_WINDOW_FIXTURE_MISSING")
            fixture_record_id = _stable_id("fixture", fixture_entry[0])
            values = window.model_dump()
            values.update(
                {
                    "id": _stable_id("window", window.window_id),
                    "fixture_record_id": fixture_record_id,
                    "append_only": True,
                }
            )
            existing = self.window_rows.get(window.window_id)
            if existing is not None:
                for name in immutable:
                    if _json_compatible(getattr(existing, name)) != _json_compatible(
                        values[name]
                    ):
                        raise ValueError("CAPTURE_WINDOW_IDEMPOTENCY_CONFLICT")
                duplicates += 1
                continue
            pending_existing = pending.get(window.window_id)
            if pending_existing is not None:
                if pending_existing[0] != window:
                    raise ValueError("CAPTURE_WINDOW_IDEMPOTENCY_CONFLICT")
                duplicates += 1
                continue
            pending[window.window_id] = (window, values)

        if not pending:
            return 0, duplicates
        table = self.tables["capture_windows"]
        rows = [
            self._row_for(table, values)
            for _, values in pending.values()
        ]
        with self.engine.begin() as connection:
            connection.execute(table.insert(), rows)
        self.window_rows.update(
            {
                window_id: window
                for window_id, (window, _) in pending.items()
            }
        )
        return len(pending), duplicates

    def append_attempt(self, attempt: CaptureAttempt) -> bool:
        if attempt.window_id not in self.window_rows:
            raise RuntimeError("CAPTURE_ATTEMPT_WINDOW_MISSING")
        values = attempt.model_dump()
        values.update(
            {
                "id": _stable_id("attempt", attempt.attempt_id),
                "window_record_id": _stable_id("window", attempt.window_id),
                "append_only": True,
            }
        )
        inserted = self._insert_exact(
            "capture_attempts",
            key_values={"idempotency_key": attempt.idempotency_key},
            values=values,
        )
        self.attempt_rows[attempt.idempotency_key] = attempt
        return inserted

    def persist_capture(self, capture: StoredCapture) -> bool:
        receipt = capture.receipt
        existing = self.receipt_rows.get(receipt.receipt_hash)
        if existing is not None:
            if existing != receipt:
                raise ValueError("CAPTURE_RECEIPT_IDEMPOTENCY_CONFLICT")
            return False
        values = receipt.model_dump()
        receipt_id = _stable_id("receipt", receipt.receipt_hash)
        values.update(
            {
                "id": receipt_id,
                "receipt_hash": receipt.receipt_hash,
                "window_record_id": (
                    _stable_id("window", receipt.window_id)
                    if receipt.window_id is not None
                    and receipt.window_id in self.window_rows
                    else None
                ),
                "append_only": True,
            }
        )
        inserted = self._insert_exact(
            "capture_receipts",
            key_values={"receipt_hash": receipt.receipt_hash},
            values=values,
        )
        index_values = {
            "id": _stable_id("payload-index", receipt.receipt_hash),
            "receipt_id": receipt_id,
            "fixture_id": receipt.fixture_id,
            "family": receipt.family.value,
            "payload_sha256": receipt.payload_sha256,
            "payload_bytes": receipt.payload_bytes,
            "stored_bytes": receipt.stored_bytes,
            "r2_key": receipt.r2_key,
            "receipt_r2_key": receipt.receipt_r2_key,
            "observed_at": receipt.observed_at,
            "indexed_at": receipt.materialized_at,
            "code_revision": receipt.code_revision,
            "append_only": True,
        }
        self._insert_exact(
            "prospective_payload_index",
            key_values={"receipt_id": receipt_id},
            values=index_values,
        )
        self.receipt_rows[receipt.receipt_hash] = receipt
        return inserted

    def append_budget(
        self,
        *,
        idempotency_key: str,
        provider: ProviderKind,
        units: int,
        provider_remaining: int,
        provider_reserve: int,
        recorded_at: datetime,
        reason: str,
        code_revision: str,
    ) -> bool:
        if units < 0 or provider_remaining < 0 or provider_reserve < 0:
            raise ValueError("PROVIDER_BUDGET_STATE_INVALID")
        value = BudgetEntry(
            idempotency_key=idempotency_key,
            provider=provider,
            units=units,
            recorded_at=recorded_at,
            reason=reason,
        )
        existing = self.budget_rows.get(idempotency_key)
        if existing is not None:
            if existing != value:
                raise ValueError("PROVIDER_BUDGET_IDEMPOTENCY_CONFLICT")
            return False
        cumulative_units = self.budget_used(provider) + units
        hard_limit = (
            MAX_API_FOOTBALL_CALLS_TOTAL
            if provider is ProviderKind.API_FOOTBALL
            else MAX_ODDS_API_CREDITS_TOTAL
        )
        if cumulative_units > hard_limit:
            raise BudgetExceeded(
                f"PROSPECTIVE_PROVIDER_CAP_EXCEEDED:{provider.value}"
            )
        values = {
            "id": _stable_id("budget", idempotency_key),
            "idempotency_key": idempotency_key,
            "provider": provider.value,
            "units": units,
            "cumulative_units": cumulative_units,
            "hard_limit": hard_limit,
            "provider_remaining": provider_remaining,
            "provider_reserve": provider_reserve,
            "recorded_at": recorded_at,
            "reason": reason,
            "code_revision": code_revision,
            "append_only": True,
        }
        inserted = self._insert_exact(
            "provider_budget_ledger",
            key_values={"idempotency_key": idempotency_key},
            values=values,
        )
        self.budget_rows[idempotency_key] = value
        return inserted

    def external_quota_remaining(
        self,
        provider: ProviderKind,
        *,
        now: datetime,
    ) -> int | None:
        if provider is not ProviderKind.ODDS_API:
            return None
        if "provider_call_logs" not in set(inspect(self.engine).get_table_names()):
            return None
        table = Table("provider_call_logs", MetaData(), autoload_with=self.engine)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(table.c.quota_remaining, table.c.requested_at)
                .where(
                    table.c.provider.in_(("the-odds-api", "odds-api")),
                    table.c.quota_remaining.is_not(None),
                )
                .order_by(table.c.requested_at.desc())
                .limit(1)
            ).first()
        if row is None:
            return None
        observed_at = cast(datetime, _db_value(row.requested_at))
        if now - observed_at > timedelta(days=7):
            return None
        return int(row.quota_remaining)

    def gate_observations(self) -> tuple[GateObservation, ...]:
        receipt_by_id = {
            _stable_id("receipt", receipt.receipt_hash): receipt
            for receipt in self.receipt_rows.values()
        }
        projections: dict[str, list[tuple[dict[str, object], bool]]] = {}
        table_fields: dict[
            str,
            Callable[[Mapping[str, object]], dict[str, object]],
        ] = {
            "prospective_player_status": lambda row: {
                "players": [str(row["player_id"])],
                "player_id": str(row["player_id"]),
                "status": str(row["status"]),
            },
            "prospective_injuries": lambda row: {
                "player_id": str(row["player_id"]),
                "status": str(row["status"]),
            },
            "prospective_lineups": lambda row: {
                "team_id": str(row["team_id"]),
                "starters": list(cast(list[object], row["starter_ids"])),
            },
            "prospective_formations": lambda row: {
                "team_id": str(row["team_id"]),
                "formation": str(row["formation"]),
            },
            "prospective_odds_snapshots": lambda row: {
                "bookmaker": str(row["bookmaker"]),
                "market": str(row["market"]),
                "selection": str(row["selection"]),
                "odds": float(cast(float | int | str, row["odds"])),
                "margin": float(cast(float | int | str, row["margin"])),
                "observed_at": cast(datetime, _db_value(row["observed_at"])).isoformat(),
            },
        }
        with self.engine.connect() as connection:
            for table_name, projector in table_fields.items():
                for row in connection.execute(
                    select(self.tables[table_name])
                ).mappings():
                    receipt_id = str(row["receipt_id"])
                    identity_ok = bool(row.get("identities_complete", True))
                    projections.setdefault(receipt_id, []).append(
                        (
                            projector(cast(Mapping[str, object], row)),
                            identity_ok,
                        )
                    )
        observations: list[GateObservation] = []
        for receipt_id, receipt in receipt_by_id.items():
            values = projections.get(receipt_id, [({}, True)])
            observations.extend(
                GateObservation(
                    receipt=receipt,
                    projection=projection,
                    identity_ok=identity_ok,
                )
                for projection, identity_ok in values
            )
        return tuple(observations)

    def append_gate(
        self,
        evaluation: GateEvaluation,
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> bool:
        inserted, _ = self.append_gates_batch(
            (evaluation,),
            evaluated_at=evaluated_at,
            code_revision=code_revision,
        )
        return inserted == 1

    def append_gates_batch(
        self,
        evaluations: Iterable[GateEvaluation],
        *,
        evaluated_at: datetime,
        code_revision: str,
    ) -> tuple[int, int]:
        table = self.tables["temporal_data_gates"]
        pending: dict[str, tuple[GateEvaluation, dict[str, object]]] = {}
        duplicates = 0
        for evaluation in evaluations:
            evidence = asdict_gate(evaluation)
            evidence_hash = canonical_sha256(evidence)
            idempotency_key = canonical_sha256(
                {
                    "evidence_hash": evidence_hash,
                    "evaluated_at": evaluated_at.isoformat(),
                }
            )
            fixture = self.fixture_rows.get(evaluation.fixture_id)
            if fixture is None:
                raise RuntimeError("TEMPORAL_GATE_FIXTURE_MISSING")
            values: dict[str, object] = {
                "id": _stable_id("gate", idempotency_key),
                "idempotency_key": idempotency_key,
                "fixture_id": evaluation.fixture_id,
                "gate_name": evaluation.gate.value,
                "status": evaluation.status.value,
                "coverage": (
                    1.0
                    if evaluation.status is GateStatus.PASSED
                    else 0.0
                ),
                "observations": evaluation.observations,
                "reason": evaluation.reason,
                "evidence": evidence,
                "evidence_hash": evidence_hash,
                "cutoff_at": fixture[1].kickoff_at
                - timedelta(microseconds=1),
                "evaluated_at": evaluated_at,
                "code_revision": code_revision,
                "append_only": True,
            }
            previous = pending.get(idempotency_key)
            if previous is not None:
                if previous[1] != values:
                    raise ValueError(
                        "TEMPORAL_GATE_IDEMPOTENCY_CONFLICT"
                    )
                duplicates += 1
                continue
            pending[idempotency_key] = (evaluation, values)

        if not pending:
            return 0, duplicates
        keys = tuple(pending)
        with self.engine.begin() as connection:
            existing_rows = {
                str(row["idempotency_key"]): row
                for row in connection.execute(
                    select(table).where(
                        table.c.idempotency_key.in_(keys)
                    )
                ).mappings()
            }
            rows: list[dict[str, object]] = []
            for key, (_, values) in pending.items():
                existing = existing_rows.get(key)
                if existing is not None:
                    row = self._row_for(table, values)
                    if any(
                        _json_compatible(existing[name])
                        != _json_compatible(value)
                        for name, value in row.items()
                    ):
                        raise ValueError(
                            "TEMPORAL_GATE_IDEMPOTENCY_CONFLICT"
                        )
                    duplicates += 1
                    continue
                rows.append(self._row_for(table, values))
            if rows:
                connection.execute(table.insert(), rows)
        self.gate_rows.update(
            {
                key: evaluation
                for key, (evaluation, _) in pending.items()
            }
        )
        return len(rows), duplicates

    def projection_sink(self) -> ProjectionSink:
        return SQLAlchemyProjectionSink(self)


class SQLAlchemyProjectionSink:
    """Rebuild compact PostgreSQL projections from immutable R2 receipts."""

    def __init__(
        self,
        state: SQLAlchemyOperationalState,
        *,
        skip_existing_projections: bool = False,
    ) -> None:
        self.state = state
        self.skip_existing_projections = skip_existing_projections

    def bootstrap(
        self,
        captures: Iterable[StoredCapture],
        *,
        tolerance: timedelta,
    ) -> None:
        """Restore fixture/window indexes before receipt FK projection."""

        captures = tuple(captures)
        registry_captures: list[
            tuple[ProspectiveFixture, StoredCapture]
        ] = []
        versions_by_fixture: dict[
            str,
            dict[str, ProspectiveFixture],
        ] = {}
        for stored in captures:
            if stored.receipt.family is not CaptureFamily.FIXTURE:
                continue
            if not isinstance(stored.payload, Mapping):
                continue
            contract = stored.payload.get("fixture_contract")
            if not isinstance(contract, Mapping):
                continue
            fixture = ProspectiveFixture.model_validate(dict(contract))
            registry_captures.append((fixture, stored))
            existing_version = versions_by_fixture.setdefault(
                fixture.fixture_id,
                {},
            ).get(fixture.registry_hash)
            if (
                existing_version is None
                or existing_version.registered_at > fixture.registered_at
            ):
                versions_by_fixture[fixture.fixture_id][
                    fixture.registry_hash
                ] = fixture
        for fixture, stored in sorted(
            registry_captures,
            key=lambda item: (
                item[0].registered_at,
                item[0].registry_hash,
                item[1].receipt.receipt_hash,
            ),
        ):
            self.state.register_fixture(fixture, stored)
        for stored in captures:
            receipt = stored.receipt
            if receipt.window_id is None:
                continue
            if receipt.window_id in self.state.window_rows:
                continue
            fixture_versions = tuple(
                versions_by_fixture.get(receipt.fixture_id, {}).values()
            )
            exact_matches: list[
                tuple[ProspectiveFixture, CaptureWindow]
            ] = []
            legacy_matches: list[
                tuple[ProspectiveFixture, CaptureWindow]
            ] = []
            for fixture in fixture_versions:
                candidates = (
                    *schedule_windows(
                        fixture,
                        receipt.family,
                        scheduled_at=receipt.requested_at,
                        tolerance=tolerance,
                    ),
                    *reconstructible_legacy_windows(
                        fixture,
                        receipt.family,
                        scheduled_at=receipt.requested_at,
                        tolerance=tolerance,
                    ),
                )
                for candidate in candidates:
                    if (
                        candidate.label != receipt.window_label
                        or candidate.kickoff_at != receipt.kickoff_at
                        or candidate.cutoff_at != receipt.cutoff_at
                    ):
                        continue
                    if candidate.window_id == receipt.window_id:
                        exact_matches.append((fixture, candidate))
                    elif (
                        not is_versioned_window_id(receipt.window_id)
                        and fixture.registered_at <= receipt.requested_at
                    ):
                        legacy_matches.append(
                            (
                                fixture,
                                candidate.model_copy(
                                    update={"window_id": receipt.window_id}
                                ),
                            )
                        )
            if legacy_matches:
                unique_legacy_matches: dict[
                    tuple[str, str, str, datetime, datetime, datetime],
                    tuple[ProspectiveFixture, CaptureWindow],
                ] = {}
                for fixture, candidate in legacy_matches:
                    key = (
                        fixture.registry_hash,
                        candidate.family.value,
                        candidate.label,
                        candidate.due_at,
                        candidate.opens_at,
                        candidate.cutoff_at,
                    )
                    unique_legacy_matches.setdefault(
                        key,
                        (fixture, candidate),
                    )
                legacy_matches = list(unique_legacy_matches.values())
            matches = exact_matches
            if not matches and legacy_matches:
                latest_registration = max(
                    fixture.registered_at
                    for fixture, _ in legacy_matches
                )
                matches = [
                    item
                    for item in legacy_matches
                    if item[0].registered_at == latest_registration
                ]
            if len(matches) != 1:
                raise RuntimeError("R2_REPLAY_WINDOW_CONTRACT_MISMATCH")
            fixture, window = matches[0]
            current_fixture = self.state.fixture_rows.get(fixture.fixture_id)
            self.state.fixture_rows[fixture.fixture_id] = (
                fixture.registry_hash,
                fixture,
            )
            try:
                self.state.schedule_window(window)
            finally:
                if current_fixture is None:
                    self.state.fixture_rows.pop(fixture.fixture_id, None)
                else:
                    self.state.fixture_rows[fixture.fixture_id] = current_fixture

    @staticmethod
    def _records(projection: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
        data = projection.get("data")
        if isinstance(data, Mapping) and isinstance(data.get("value"), list):
            data = data["value"]
        if isinstance(data, list):
            return tuple(item for item in data if isinstance(item, Mapping))
        if isinstance(data, Mapping):
            return (data,)
        return ()

    def _player_rows(
        self,
        receipt: CaptureReceipt,
        projection: Mapping[str, object],
        projection_hash: str,
    ) -> bool:
        inserted = False
        table_name = (
            "prospective_injuries"
            if receipt.family is CaptureFamily.INJURY
            else "prospective_player_status"
        )
        records: list[Mapping[str, object]] = []
        for record in self._records(projection):
            if receipt.family is not CaptureFamily.SQUAD:
                records.append(record)
                continue
            team = record.get("team")
            players = record.get("players")
            if not isinstance(team, Mapping) or not isinstance(players, list):
                continue
            records.extend(
                {
                    "team": team,
                    "player": {**player, "status": "SQUAD_MEMBER"},
                }
                for player in players
                if isinstance(player, Mapping)
            )
        for record in records:
            player = record.get("player")
            team = record.get("team")
            if not isinstance(player, Mapping) or not isinstance(team, Mapping):
                continue
            player_id = str(player.get("id", "")).strip()
            team_id = str(team.get("id", "")).strip()
            status = str(
                player.get("type") or player.get("status") or "OBSERVED"
            ).strip()
            if not player_id or not team_id or not status:
                continue
            key = f"{receipt.receipt_hash}:{player_id}:{status}"
            values = {
                "id": _stable_id(table_name, key),
                "receipt_id": _stable_id("receipt", receipt.receipt_hash),
                "fixture_id": receipt.fixture_id,
                "team_id": team_id,
                "player_id": player_id,
                "status": status,
                "reason": player.get("reason"),
                "observed_at": receipt.observed_at,
                "cutoff_at": receipt.cutoff_at,
                "projection_hash": projection_hash,
                "code_revision": receipt.code_revision,
                "append_only": True,
            }
            inserted |= self.state._insert_exact(
                table_name,
                key_values={
                    "receipt_id": values["receipt_id"],
                    "player_id": player_id,
                    **({"status": status} if table_name == "prospective_injuries" else {}),
                },
                values=values,
            )
        return inserted

    def _lineup_rows(
        self,
        receipt: CaptureReceipt,
        projection: Mapping[str, object],
        projection_hash: str,
    ) -> bool:
        inserted = False
        for record in self._records(projection):
            team = record.get("team")
            if not isinstance(team, Mapping):
                continue
            team_id = str(team.get("id", "")).strip()
            if not team_id:
                continue
            receipt_id = _stable_id("receipt", receipt.receipt_hash)
            if receipt.family is CaptureFamily.FORMATION:
                formation = str(record.get("formation", "")).strip()
                if not formation:
                    continue
                values = {
                    "id": _stable_id(
                        "formation",
                        f"{receipt.receipt_hash}:{team_id}",
                    ),
                    "receipt_id": receipt_id,
                    "fixture_id": receipt.fixture_id,
                    "team_id": team_id,
                    "formation": formation,
                    "observed_at": receipt.observed_at,
                    "cutoff_at": receipt.cutoff_at,
                    "projection_hash": projection_hash,
                    "code_revision": receipt.code_revision,
                    "append_only": True,
                }
                inserted |= self.state._insert_exact(
                    "prospective_formations",
                    key_values={"receipt_id": receipt_id, "team_id": team_id},
                    values=values,
                )
                continue
            start_xi = record.get("startXI")
            if not isinstance(start_xi, list):
                continue
            starter_ids = [
                str(player["player"]["id"])
                for player in start_xi
                if isinstance(player, Mapping)
                and isinstance(player.get("player"), Mapping)
                and player["player"].get("id") is not None
            ]
            if len(starter_ids) != 11 or len(set(starter_ids)) != 11:
                continue
            values = {
                "id": _stable_id("lineup", f"{receipt.receipt_hash}:{team_id}"),
                "receipt_id": receipt_id,
                "fixture_id": receipt.fixture_id,
                "team_id": team_id,
                "starter_ids": starter_ids,
                "starter_count": 11,
                "identities_complete": True,
                "observed_at": receipt.observed_at,
                "cutoff_at": receipt.cutoff_at,
                "lineup_hash": canonical_sha256(starter_ids),
                "code_revision": receipt.code_revision,
                "append_only": True,
            }
            inserted |= self.state._insert_exact(
                "prospective_lineups",
                key_values={"receipt_id": receipt_id, "team_id": team_id},
                values=values,
            )
        return inserted

    def _odds_rows(
        self,
        receipt: CaptureReceipt,
        projection: Mapping[str, object],
    ) -> bool:
        inserted = False
        receipt_id = _stable_id("receipt", receipt.receipt_hash)
        for event in self._records(projection):
            bookmakers = event.get("bookmakers")
            if not isinstance(bookmakers, list):
                continue
            for bookmaker_value in bookmakers:
                if not isinstance(bookmaker_value, Mapping):
                    continue
                bookmaker = str(bookmaker_value.get("key", "")).strip()
                markets = bookmaker_value.get("markets")
                if not bookmaker or not isinstance(markets, list):
                    continue
                for market_value in markets:
                    if not isinstance(market_value, Mapping):
                        continue
                    provider_market = str(market_value.get("key", ""))
                    market = {
                        "h2h": "1X2",
                        "totals": "OVER_UNDER_2_5",
                    }.get(provider_market)
                    outcomes = market_value.get("outcomes")
                    if market is None or not isinstance(outcomes, list):
                        continue
                    prices = [
                        float(outcome["price"])
                        for outcome in outcomes
                        if isinstance(outcome, Mapping)
                        and isinstance(outcome.get("price"), (int, float))
                        and float(outcome["price"]) > 1.0
                        and (
                            provider_market != "totals"
                            or float(outcome.get("point", 0.0)) == 2.5
                        )
                    ]
                    margin = max(sum(1.0 / price for price in prices) - 1.0, 0.0)
                    for outcome in outcomes:
                        if (
                            not isinstance(outcome, Mapping)
                            or not isinstance(outcome.get("price"), (int, float))
                            or float(outcome["price"]) <= 1.0
                            or (
                                provider_market == "totals"
                                and float(outcome.get("point", 0.0)) != 2.5
                            )
                        ):
                            continue
                        selection = str(outcome.get("name", "")).strip()
                        if not selection:
                            continue
                        key = (
                            f"{receipt.receipt_hash}:{bookmaker}:"
                            f"{market}:{selection}"
                        )
                        snapshot_hash = canonical_sha256(
                            {
                                "bookmaker": bookmaker,
                                "market": market,
                                "selection": selection,
                                "odds": float(outcome["price"]),
                                "margin": margin,
                                "observed_at": receipt.observed_at.isoformat(),
                            }
                        )
                        values = {
                            "id": _stable_id("odds", key),
                            "receipt_id": receipt_id,
                            "fixture_id": receipt.fixture_id,
                            "bookmaker": bookmaker,
                            "market": market,
                            "selection": selection,
                            "odds": float(outcome["price"]),
                            "margin": margin,
                            "observed_at": receipt.observed_at,
                            "cutoff_at": receipt.cutoff_at,
                            "fixture_match_status": "MATCHED_EXACT",
                            "snapshot_hash": snapshot_hash,
                            "code_revision": receipt.code_revision,
                            "append_only": True,
                        }
                        inserted |= self.state._insert_exact(
                            "prospective_odds_snapshots",
                            key_values={
                                "receipt_id": receipt_id,
                                "bookmaker": bookmaker,
                                "market": market,
                                "selection": selection,
                            },
                            values=values,
                        )
        return inserted

    def insert_capture(
        self,
        receipt: CaptureReceipt,
        projection: Mapping[str, object],
        projection_hash: str,
    ) -> bool:
        stored = StoredCapture(
            receipt=receipt,
            payload={},
            payload_created=False,
            receipt_created=False,
        )
        inserted = self.state.persist_capture(stored)
        if not inserted and self.skip_existing_projections:
            # Replay validates every compact table against a projection
            # independently derived from R2 after this pass. Avoid thousands
            # of duplicate point queries here; missing or extra rows still
            # fail closed in _assert_r2_postgresql_projection_parity.
            return False
        if receipt.quality_status is not AvailabilityStatus.CAPTURED:
            return inserted
        if receipt.family in {
            CaptureFamily.SQUAD,
            CaptureFamily.INJURY,
            CaptureFamily.PLAYER_STATUS,
        }:
            inserted |= self._player_rows(receipt, projection, projection_hash)
        elif receipt.family in {
            CaptureFamily.LINEUP,
            CaptureFamily.FORMATION,
        }:
            inserted |= self._lineup_rows(receipt, projection, projection_hash)
        elif receipt.family is CaptureFamily.ODDS:
            inserted |= self._odds_rows(receipt, projection)
        return inserted


def _json_compatible(value: object) -> object:
    if isinstance(value, datetime):
        normalized = (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None or value.utcoffset() is None
            else value.astimezone(UTC)
        )
        return normalized.isoformat()
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _provider_quota_remaining(result: ProviderResult) -> int | None:
    if result.quota.remaining is not None:
        return result.quota.remaining

    def walk(value: object) -> int | None:
        if isinstance(value, Mapping):
            requests_value = value.get("requests")
            if isinstance(requests_value, Mapping):
                current = requests_value.get("current")
                limit = requests_value.get("limit_day", requests_value.get("limit"))
                try:
                    if current is not None and limit is not None:
                        return int(limit) - int(current)
                except (TypeError, ValueError):
                    return None
            for child in value.values():
                found = walk(child)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child)
                if found is not None:
                    return found
        return None

    for record in result.records:
        found = walk(record)
        if found is not None:
            return found
    return None


def _current_provider_season(result: ProviderResult) -> int:
    seasons: list[int] = []
    for record in result.records:
        values = record.get("seasons")
        if not isinstance(values, list):
            continue
        for value in values:
            if (
                isinstance(value, Mapping)
                and value.get("current") is True
                and isinstance(value.get("year"), int)
            ):
                seasons.append(int(value["year"]))
    unique = sorted(set(seasons))
    if len(unique) != 1:
        raise RuntimeError("API_FOOTBALL_CURRENT_SEASON_NOT_UNIQUE")
    return unique[0]


def _fixture_records(result: ProviderResult) -> tuple[dict[str, object], ...]:
    return tuple(dict(record) for record in result.records)


def _fixture_record_diagnostics(
    records: Iterable[Mapping[str, object]],
    *,
    now: datetime,
    until: datetime,
) -> dict[str, int]:
    """Describe a valid provider response without confusing emptiness and errors."""

    received = 0
    in_horizon = 0
    outside_horizon = 0
    schema_errors = 0
    for record in records:
        received += 1
        fixture = record.get("fixture")
        league = record.get("league")
        teams = record.get("teams")
        if not all(
            isinstance(value, Mapping)
            for value in (fixture, league, teams)
        ):
            schema_errors += 1
            continue
        fixture_map = cast(Mapping[str, object], fixture)
        league_map = cast(Mapping[str, object], league)
        teams_map = cast(Mapping[str, object], teams)
        home = teams_map.get("home")
        away = teams_map.get("away")
        if (
            not isinstance(home, Mapping)
            or not isinstance(away, Mapping)
            or not str(fixture_map.get("id", "")).strip()
            or not str(league_map.get("season", "")).strip()
        ):
            schema_errors += 1
            continue
        try:
            kickoff = _provider_datetime(fixture_map.get("date"))
        except (TypeError, ValueError):
            schema_errors += 1
            continue
        if now < kickoff <= until:
            in_horizon += 1
        else:
            outside_horizon += 1
    return {
        "records_received": received,
        "records_in_current_horizon": in_horizon,
        "records_outside_current_horizon": outside_horizon,
        "provider_payload_schema_errors": schema_errors,
    }


def _provider_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("PROVIDER_KICKOFF_UTC_REQUIRED")
    return parsed.astimezone(UTC)


def _prospective_fixture(
    record: Mapping[str, object],
    *,
    competition: str,
    registered_at: datetime,
    code_revision: str,
    horizon_days: int,
    excluded_statuses: set[str],
    require_verified_phase: bool,
    require_reliable_utc_kickoff: bool,
) -> ProspectiveFixture | None:
    fixture = record.get("fixture")
    league = record.get("league")
    teams = record.get("teams")
    if not all(isinstance(value, Mapping) for value in (fixture, league, teams)):
        return None
    fixture_map = cast(Mapping[str, object], fixture)
    league_map = cast(Mapping[str, object], league)
    teams_map = cast(Mapping[str, object], teams)
    status = fixture_map.get("status")
    status_short = (
        str(status.get("short", "")) if isinstance(status, Mapping) else ""
    )
    cancelled = status_short in excluded_statuses
    if require_reliable_utc_kickoff and status_short in {"", "TBD"}:
        return None
    home = teams_map.get("home")
    away = teams_map.get("away")
    if not isinstance(home, Mapping) or not isinstance(away, Mapping):
        return None
    try:
        kickoff = _provider_datetime(fixture_map.get("date"))
    except (TypeError, ValueError):
        if require_reliable_utc_kickoff:
            return None
        raise
    if not registered_at < kickoff <= (
        registered_at + timedelta(days=horizon_days)
    ):
        return None
    provider_fixture_id = str(fixture_map.get("id", "")).strip()
    season = str(league_map.get("season", "")).strip()
    phase = str(league_map.get("round", "")).strip()
    home_id = str(home.get("id", "")).strip()
    away_id = str(away.get("id", "")).strip()
    if (
        not all((provider_fixture_id, season, phase, home_id, away_id))
        or (
            require_verified_phase
            and phase.casefold() in {"tbd", "unknown", "unverified"}
        )
    ):
        return None
    return ProspectiveFixture(
        fixture_id=f"api-football:{provider_fixture_id}",
        competition=competition,
        season=season,
        phase=phase,
        home_team_id=home_id,
        away_team_id=away_id,
        kickoff_at=kickoff,
        provider="api-football",
        provider_fixture_id=provider_fixture_id,
        registered_at=registered_at,
        code_revision=code_revision,
        cancelled=cancelled,
        horizon_days=horizon_days,
    )


def _filter_fixtures(
    records: Iterable[Mapping[str, object]],
    *,
    policy: ObservatoryPolicy,
    competition: str,
    now: datetime,
    code_revision: str,
    expected_season: int | None = None,
) -> tuple[tuple[ProspectiveFixture, Mapping[str, object]], ...]:
    registry = policy.fixture_registry
    horizon_days = _int_value(
        registry["horizon_days"],
        error="PROSPECTIVE_HORIZON_DAYS_INVALID",
    )
    max_rounds = _int_value(
        registry["max_matchdays_per_competition"],
        error="PROSPECTIVE_MAX_MATCHDAYS_INVALID",
    )
    excluded = {str(value) for value in cast(list[object], registry["excluded_statuses"])}
    horizon = now + timedelta(days=horizon_days)
    candidates: list[tuple[ProspectiveFixture, Mapping[str, object]]] = []
    for record in records:
        fixture = _prospective_fixture(
            record,
            competition=competition,
            registered_at=now,
            code_revision=code_revision,
            horizon_days=horizon_days,
            excluded_statuses=excluded,
            require_verified_phase=bool(registry["require_verified_phase"]),
            require_reliable_utc_kickoff=bool(
                registry["require_reliable_utc_kickoff"]
            ),
        )
        if (
            fixture is not None
            and (expected_season is None or fixture.season == str(expected_season))
            and now < fixture.kickoff_at <= horizon
        ):
            candidates.append((fixture, record))
    ordered_rounds: list[str] = []
    for fixture, _ in sorted(candidates, key=lambda item: item[0].kickoff_at):
        if fixture.phase not in ordered_rounds:
            ordered_rounds.append(fixture.phase)
    selected_rounds = set(ordered_rounds[:max_rounds])
    return tuple(
        sorted(
            (
                (fixture, record)
                for fixture, record in candidates
                if fixture.cancelled or fixture.phase in selected_rounds
            ),
            key=lambda item: (item[0].kickoff_at, item[0].fixture_id),
        )
    )


def _fixture_lifecycle_tombstones(
    records: Iterable[Mapping[str, object]],
    *,
    state: OperationalState,
    policy: ObservatoryPolicy,
    competition: str,
    now: datetime,
    code_revision: str,
    selected_fixture_ids: set[str],
) -> tuple[tuple[ProspectiveFixture, Mapping[str, object]], ...]:
    """Close an active fixture when the provider explicitly withdraws reliability.

    A `TBD`/excluded lifecycle update may no longer satisfy the prospective
    admission contract, but silently dropping that update would leave the
    previous kickoff and all of its windows active.  We therefore append a
    cancelled version based on the last admitted fixture.  The provider record
    remains the immutable evidence; no historical version or window is mutated.
    Malformed records without an explicit provider fixture id/status never
    deactivate anything.
    """

    excluded = {
        str(value)
        for value in cast(
            list[object],
            policy.fixture_registry["excluded_statuses"],
        )
    }
    lifecycle_statuses = excluded | {"TBD"}
    active = {fixture.fixture_id: fixture for fixture in state.fixtures()}
    tombstones: list[tuple[ProspectiveFixture, Mapping[str, object]]] = []
    seen: set[str] = set()
    for record in records:
        fixture_value = record.get("fixture")
        if not isinstance(fixture_value, Mapping):
            continue
        provider_fixture_id = str(fixture_value.get("id", "")).strip()
        status_value = fixture_value.get("status")
        status_short = (
            str(status_value.get("short", "")).strip()
            if isinstance(status_value, Mapping)
            else ""
        )
        fixture_id = f"api-football:{provider_fixture_id}"
        current = active.get(fixture_id)
        if (
            not provider_fixture_id
            or status_short not in lifecycle_statuses
            or fixture_id in selected_fixture_ids
            or fixture_id in seen
            or current is None
            or current.competition != competition
            or current.kickoff_at <= now
        ):
            continue
        tombstones.append(
            (
                current.model_copy(
                    update={
                        "registered_at": now,
                        "code_revision": code_revision,
                        "cancelled": True,
                        "lifecycle_version_hash": None,
                    }
                ),
                record,
            )
        )
        seen.add(fixture_id)
    return tuple(
        sorted(
            tombstones,
            key=lambda item: (item[0].kickoff_at, item[0].fixture_id),
        )
    )


def _version_fixture_lifecycle_transitions(
    fixtures: Iterable[tuple[ProspectiveFixture, Mapping[str, object]]],
    *,
    state: OperationalState,
) -> tuple[tuple[ProspectiveFixture, Mapping[str, object]], ...]:
    """Bind recurring business states to an immutable lifecycle chain.

    A fixture can transition from NS to a TBD/cancelled tombstone and later
    return to the exact same NS payload and kickoff. Its plain business hash
    would then alias the first NS row. A transition-derived hash creates a new
    append-only version, while a routine reobservation of the current state
    keeps the existing hash and remains idempotent.
    """

    heads = {
        fixture.fixture_id: fixture
        for fixture in state.fixture_lifecycle_heads()
    }
    versioned: list[tuple[ProspectiveFixture, Mapping[str, object]]] = []
    for fixture, record in fixtures:
        candidate = fixture.model_copy(
            update={"lifecycle_version_hash": None}
        )
        current = heads.get(candidate.fixture_id)
        if current is None:
            resolved = candidate
        elif current.business_hash == candidate.business_hash:
            resolved = candidate.model_copy(
                update={
                    "lifecycle_version_hash": current.registry_hash,
                }
            )
        else:
            resolved = candidate.model_copy(
                update={
                    "lifecycle_version_hash": canonical_sha256(
                        {
                            "schema_version": (
                                "prospective-fixture-lifecycle-v1"
                            ),
                            "fixture_id": candidate.fixture_id,
                            "previous_registry_hash": (
                                current.registry_hash
                            ),
                            "business_hash": candidate.business_hash,
                        }
                    )
                }
            )
        heads[resolved.fixture_id] = resolved
        versioned.append((resolved, record))
    return tuple(versioned)


def _estimate(
    *,
    command: str,
    policy: ObservatoryPolicy,
    units: int,
    provider: ProviderKind,
    windows_due: int,
    now: datetime,
    window_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    estimate: dict[str, object] = {
        "schema_version": "prospective-provider-estimate-v2",
        "command": command,
        "generated_at": now.isoformat(),
        "policy_sha256": policy.sha256,
        "provider": provider.value,
        "estimated_units": units,
        "windows_due": windows_due,
        "window_ids_sha256": canonical_sha256(sorted(window_ids)),
        "run_cap": policy.run_cap(provider),
        "provider_reserve": policy.provider_reserve(provider),
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
    }
    estimate["estimate_sha256"] = canonical_sha256(estimate)
    return estimate


def _verified_estimate(
    path: Path,
    *,
    command: str,
    policy: ObservatoryPolicy,
) -> dict[str, object]:
    estimate = _mapping(_read_json(path), error="PROVIDER_ESTIMATE_INVALID")
    recorded_hash = estimate.pop("estimate_sha256", None)
    if (
        recorded_hash != canonical_sha256(estimate)
        or estimate.get("command") != command
        or estimate.get("policy_sha256") != policy.sha256
    ):
        raise ValueError("PROVIDER_ESTIMATE_HASH_OR_SCOPE_MISMATCH")
    estimate["estimate_sha256"] = recorded_hash
    return estimate


def _base_snapshot(policy: ObservatoryPolicy, *, now: datetime) -> dict[str, object]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "status": "NO_DUE_WINDOW_SUCCESS",
        "generated_at": now.isoformat(),
        "source": {
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "revision": os.environ.get("GITHUB_SHA"),
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
        },
        "fixtures": {
            "tracked": 0,
            "horizon_days": _int_value(
                policy.fixture_registry["horizon_days"],
                error="PROSPECTIVE_HORIZON_DAYS_INVALID",
            ),
            "windows_planned": 0,
            "windows_due": 0,
        },
        "captures": {
            "by_family": {
                family.value: {
                    "due": 0,
                    "attempted": 0,
                    "captured": 0,
                    "empty": 0,
                    "missed": 0,
                    "invalid": 0,
                    "bytes": 0,
                    "hashes": 0,
                }
                for family in CaptureFamily
            },
            "attempted": 0,
            "captured": 0,
            "empty": 0,
            "missed": 0,
            "invalid": 0,
            "bytes": 0,
            "hashes": 0,
        },
        "temporal": {
            "before_cutoff": 0,
            "late": 0,
            "rejected": 0,
            "gates": 0,
        },
        "providers": {
            "api_football_calls": 0,
            "odds_api_credits": 0,
            "budgets": {
                "api_football": dict(
                    policy.provider_budget(ProviderKind.API_FOOTBALL)
                ),
                "odds_api": dict(
                    policy.provider_budget(ProviderKind.ODDS_API)
                ),
            },
            "reserves": {
                "api_football": policy.provider_reserve(
                    ProviderKind.API_FOOTBALL
                ),
                "odds_api": policy.provider_reserve(ProviderKind.ODDS_API),
                "odds_api_internal_safety": policy.internal_safety_reserve(
                    ProviderKind.ODDS_API
                ),
                "odds_near_kickoff": policy.near_kickoff_reserve(),
            },
            "errors": 0,
        },
        "r2": {
            "objects_added": 0,
            "bytes": 0,
            "recovery_objects": 0,
            "recovery_bytes": 0,
            "verified": 0,
            "lag": 0,
            "deletions": 0,
            "replay_status": "NOT_RUN",
        },
        "postgresql": {
            "migration": OBSERVATORY_SCHEMA_REVISION,
            "tables": len(SQLAlchemyOperationalState.REQUIRED_TABLES),
            "inserts": 0,
            "duplicates_avoided": 0,
            "reconstruction_status": "NOT_RUN",
            "payload_body_rows": 0,
        },
        "gates": {
            "by_name": {
                gate.value: {
                    "status": GateStatus.BLOCKED_BY_COVERAGE.value,
                    "passed": 0,
                    "total": 0,
                    "reason": "NO_PROSPECTIVE_OBSERVATION",
                }
                for gate in GateName
            }
        },
        "invariants": {
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "no_bet_default": True,
            "social_publishing_enabled": False,
            "demo_mode_enabled": False,
            "storage_paused": True,
            "p3_p4_paused": True,
        },
    }


def _report(
    *,
    command: str,
    policy: ObservatoryPolicy,
    now: datetime,
    snapshot: dict[str, object],
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "generated_at": now.isoformat(),
        "policy_sha256": policy.sha256,
        "observatory": snapshot,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "deletions": 0,
        "raw_payloads_in_git": 0,
    }
    if extra:
        value.update(extra)
    value["report_sha256"] = canonical_sha256(value)
    return value


def _capture_set_sha256(receipts: Iterable[CaptureReceipt]) -> str:
    """Lier gate et replay au même ensemble exact de reçus R2."""

    return canonical_sha256(
        sorted(
            (receipt.receipt_hash, receipt.payload_sha256)
            for receipt in receipts
        )
    )


def _capture_provenance(
    receipts: Iterable[CaptureReceipt],
) -> dict[str, int]:
    """Summarize immutable receipt provenance without exposing raw payloads."""

    live_receipts = 0
    cache_test_receipts = 0
    unverified_receipts = 0
    provider_calls_recorded = 0
    for receipt in receipts:
        provider_calls_recorded += receipt.provider_calls
        if (
            receipt.provider == "cache-test"
            or receipt.source_endpoint.startswith("cache://")
        ):
            cache_test_receipts += 1
        elif (
            receipt.provider in {"api-football", "the-odds-api"}
            and receipt.source_endpoint.startswith("/")
        ):
            live_receipts += 1
        else:
            unverified_receipts += 1
    return {
        "live_provider_receipts": live_receipts,
        "cache_test_receipts": cache_test_receipts,
        "unverified_receipts": unverified_receipts,
        "provider_calls_recorded": provider_calls_recorded,
    }


def _reject_non_durable_execution_inputs(
    args: argparse.Namespace,
    *,
    state: OperationalState,
) -> None:
    """Keep cache/local adapters outside durable provider executions."""

    durable_database = (
        isinstance(state, SQLAlchemyOperationalState)
        and state.engine.dialect.name != "sqlite"
    )
    execute = bool(getattr(args, "execute", False))
    if args.cache is not None and (execute or durable_database):
        raise ValueError("CACHE_INPUT_FORBIDDEN_FOR_DURABLE_EXECUTION")
    if args.object_store_root is not None and (execute or durable_database):
        raise ValueError("LOCAL_OBJECT_STORE_FORBIDDEN_FOR_PROVIDER_EXECUTION")


def _record_provider_units_before_call(
    state: OperationalState,
    repository: ProspectiveR2Repository,
    *,
    operation_key: str,
    step: str,
    provider: ProviderKind,
    units: int,
    provider_remaining: int,
    provider_reserve: int,
    recorded_at: datetime,
    code_revision: str,
    budget_scope: str = "SHARED",
) -> None:
    """Durably journal a provider transport before control reaches it."""

    if units < 0:
        raise ValueError("PROVIDER_UNITS_NEGATIVE")
    idempotency_key = f"{operation_key}:provider-step:{step}"
    if (
        not budget_scope
        or ";" in budget_scope
        or len(budget_scope) > 120
    ):
        raise ValueError("PROVIDER_BUDGET_SCOPE_INVALID")
    reason = f"RESERVED_BEFORE_PROVIDER_CALL:{step};SCOPE={budget_scope}"
    record = DurableProviderBudget(
        idempotency_key=idempotency_key,
        provider=provider.value,
        units=units,
        provider_remaining=max(provider_remaining, 0),
        provider_reserve=provider_reserve,
        recorded_at=recorded_at,
        reason=reason,
        code_revision=code_revision,
    )
    budget_writer = getattr(repository, "record_provider_budget", None)
    if callable(budget_writer):
        budget_writer(record)
    elif isinstance(state, SQLAlchemyOperationalState):
        raise RuntimeError("R2_PROVIDER_BUDGET_JOURNAL_REQUIRED")
    state.append_budget(
        idempotency_key=idempotency_key,
        provider=provider,
        units=units,
        provider_remaining=max(provider_remaining, 0),
        provider_reserve=provider_reserve,
        recorded_at=recorded_at,
        reason=reason,
        code_revision=code_revision,
    )


def _provider_call_guard_key(
    *,
    command: str,
    request_scope: str,
    step: str,
    provider: ProviderKind,
    window: CaptureWindow,
    attempt_number: int,
) -> str:
    kind = "f" if step.startswith("fixture-freshness:") else "d"
    return (
        f"pcg1:{provider.value}:{command}:{kind}:"
        f"{canonical_sha256(request_scope)}:{canonical_sha256(step)}:"
        f"{canonical_sha256(window.window_id)}:a{attempt_number}"
    )


def _provider_call_guard_completions(
    repository: ProspectiveR2Repository,
) -> dict[str, str]:
    """Map completed guard keys to the immutable R2 receipt proving them."""

    reader = getattr(repository, "provider_budgets", None)
    if not callable(reader):
        return {}
    guard_prefix = "pcg1:"
    completion_prefix = "pcc1:"
    records = tuple(reader())
    guards_by_hash = {
        hashlib.sha256(record.idempotency_key.encode("utf-8")).hexdigest(): (
            record.idempotency_key
        )
        for record in records
        if record.idempotency_key.startswith(guard_prefix)
    }
    completed: dict[str, str] = {}
    for record in records:
        if not record.idempotency_key.startswith(completion_prefix):
            continue
        value = record.idempotency_key.removeprefix(completion_prefix)
        guard_hash, separator, receipt_hash = value.partition(":")
        guard_key = guards_by_hash.get(guard_hash)
        if (
            not separator
            or guard_key is None
            or re.fullmatch(r"[0-9a-f]{64}", guard_hash) is None
            or re.fullmatch(r"[0-9a-f]{64}", receipt_hash) is None
        ):
            raise RuntimeError("R2_PROVIDER_CALL_COMPLETION_INVALID")
        existing = completed.get(guard_key)
        if existing is not None and existing != receipt_hash:
            raise RuntimeError("R2_PROVIDER_CALL_COMPLETION_CONFLICT")
        completed[guard_key] = receipt_hash
    return completed


def _provider_call_guard_keys(
    *,
    command: str,
    request_scope: str,
    step: str,
    provider: ProviderKind,
    windows: Iterable[CaptureWindow],
    prior_attempt_counts: Mapping[str, int],
) -> dict[str, str]:
    return {
        window.window_id: _provider_call_guard_key(
            command=command,
            request_scope=request_scope,
            step=step,
            provider=provider,
            window=window,
            attempt_number=(
                prior_attempt_counts.get(window.window_id, 0) + 1
            ),
        )
        for window in sorted(windows, key=lambda item: item.window_id)
    }


def _reserve_provider_call_guards(
    state: OperationalState,
    repository: ProspectiveR2Repository,
    *,
    command: str,
    request_scope: str,
    step: str,
    provider: ProviderKind,
    windows: Iterable[CaptureWindow],
    prior_attempt_counts: Mapping[str, int],
    provider_remaining: int,
    provider_reserve: int,
    recorded_at: datetime,
    code_revision: str,
    budget_scope: str = "SHARED",
) -> dict[str, str]:
    """Fail closed when a prior transport may have returned without a receipt.

    The provider budget reservation proves only that control was about to cross
    the network boundary.  A process can still stop after the remote response
    and before the first R2 capture intent.  One immutable, zero-unit guard per
    affected window and attempt makes that ambiguity durable.  A later run must
    not issue the transport again: it raises an explicit incident instead of
    silently spending quota or pretending that the missing response is safe to
    replay.
    """

    writer = getattr(repository, "record_provider_budget", None)
    if not callable(writer):
        if isinstance(state, SQLAlchemyOperationalState):
            raise RuntimeError("R2_PROVIDER_CALL_GUARD_REQUIRED")
        return {}
    guard_keys = _provider_call_guard_keys(
        command=command,
        request_scope=request_scope,
        step=step,
        provider=provider,
        windows=windows,
        prior_attempt_counts=prior_attempt_counts,
    )
    completed = _provider_call_guard_completions(repository)
    for window_id, idempotency_key in guard_keys.items():
        attempt_number = prior_attempt_counts.get(window_id, 0) + 1
        if (
            not budget_scope
            or ";" in budget_scope
            or len(budget_scope) > 120
        ):
            raise ValueError("PROVIDER_BUDGET_SCOPE_INVALID")
        record = DurableProviderBudget(
            idempotency_key=idempotency_key,
            provider=provider.value,
            units=0,
            provider_remaining=max(provider_remaining, 0),
            provider_reserve=provider_reserve,
            recorded_at=recorded_at,
            reason=(
                f"GUARDED_BEFORE_PROVIDER_CALL:{step};"
                f"SCOPE={budget_scope}"
            ),
            code_revision=code_revision,
        )
        if not writer(record):
            if idempotency_key in completed:
                raise RuntimeError(
                    "PROVIDER_CALL_ALREADY_COMPLETED_REPLAY_REQUIRED:"
                    f"{provider.value}:{command}:{window_id}:"
                    f"attempt:{attempt_number}"
                )
            raise RuntimeError(
                "PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED:"
                f"{provider.value}:{command}:{window_id}:"
                f"attempt:{attempt_number}"
            )
        state.append_budget(
            idempotency_key=idempotency_key,
            provider=provider,
            units=0,
            provider_remaining=max(provider_remaining, 0),
            provider_reserve=provider_reserve,
            recorded_at=recorded_at,
            reason=record.reason,
            code_revision=code_revision,
        )
    return guard_keys


def _complete_provider_call_guards(
    state: OperationalState,
    repository: ProspectiveR2Repository,
    *,
    guard_keys: Iterable[str],
    receipt: CaptureReceipt,
    provider: ProviderKind,
    provider_remaining: int,
    provider_reserve: int,
) -> None:
    """Append an immutable receipt link for every completed transport guard."""

    writer = getattr(repository, "record_provider_budget", None)
    if not callable(writer):
        if isinstance(state, SQLAlchemyOperationalState):
            raise RuntimeError("R2_PROVIDER_CALL_COMPLETION_REQUIRED")
        return
    for guard_key in sorted(set(guard_keys)):
        guard_hash = hashlib.sha256(guard_key.encode("utf-8")).hexdigest()
        idempotency_key = (
            f"pcc1:{guard_hash}:{receipt.receipt_hash}"
        )
        record = DurableProviderBudget(
            idempotency_key=idempotency_key,
            provider=provider.value,
            units=0,
            provider_remaining=max(provider_remaining, 0),
            provider_reserve=provider_reserve,
            recorded_at=receipt.response_received_at,
            reason=f"COMPLETED_BY_R2_RECEIPT:{guard_hash}",
            code_revision=receipt.code_revision,
        )
        writer(record)
        state.append_budget(
            idempotency_key=idempotency_key,
            provider=provider,
            units=0,
            provider_remaining=max(provider_remaining, 0),
            provider_reserve=provider_reserve,
            recorded_at=receipt.response_received_at,
            reason=f"COMPLETED_BY_R2_RECEIPT:{guard_hash}",
            code_revision=receipt.code_revision,
        )


def _reconcile_provider_call_guard_completions(
    state: OperationalState,
    repository: ProspectiveR2Repository,
    *,
    command: str,
    provider: ProviderKind,
    windows: Iterable[CaptureWindow],
    prior_attempt_counts: Mapping[str, int],
) -> int:
    """Link guards to receipts when a stop happened between those R2 writes."""

    reader = getattr(repository, "provider_budgets", None)
    if not callable(reader):
        return 0
    prefix = f"pcg1:{provider.value}:{command}:"
    records = tuple(
        record
        for record in reader()
        if record.idempotency_key.startswith(prefix)
    )
    completed = _provider_call_guard_completions(repository)
    receipts = tuple(state.receipts())
    inserted = 0
    for window in sorted(windows, key=lambda item: item.window_id):
        attempt_number = prior_attempt_counts.get(window.window_id, 0) + 1
        suffix = (
            f":{canonical_sha256(window.window_id)}:a{attempt_number}"
        )
        for record in records:
            guard_key = record.idempotency_key
            if not guard_key.endswith(suffix) or guard_key in completed:
                continue
            freshness_guard = (
                f"pcg1:{provider.value}:{command}:f:"
                in guard_key
            )
            proof = next(
                (
                    receipt
                    for receipt in sorted(
                        receipts,
                        key=lambda item: (
                            item.response_received_at,
                            item.receipt_hash,
                        ),
                        reverse=True,
                    )
                    if receipt.provider == "api-football"
                    and receipt.response_received_at >= record.recorded_at
                    and (
                        (
                            freshness_guard
                            and receipt.window_id is None
                            and receipt.fixture_id == window.fixture_id
                            and receipt.family is CaptureFamily.FIXTURE
                            and receipt.source_endpoint == "/fixtures"
                        )
                        or (
                            not freshness_guard
                            and receipt.window_id == window.window_id
                        )
                    )
                ),
                None,
            )
            if proof is None:
                continue
            _complete_provider_call_guards(
                state,
                repository,
                guard_keys=(guard_key,),
                receipt=proof,
                provider=provider,
                provider_remaining=record.provider_remaining,
                provider_reserve=record.provider_reserve,
            )
            completed[guard_key] = proof.receipt_hash
            inserted += 1
    return inserted


def _assert_no_unresolved_provider_call_guards(
    repository: ProspectiveR2Repository,
    *,
    command: str,
    provider: ProviderKind,
    windows: Iterable[CaptureWindow],
    prior_attempt_counts: Mapping[str, int],
) -> None:
    """Stop before any preflight when a data transport outcome is ambiguous."""

    reader = getattr(repository, "provider_budgets", None)
    if not callable(reader):
        return
    prefix = f"pcg1:{provider.value}:{command}:"
    completed = _provider_call_guard_completions(repository)
    guard_keys = {
        record.idempotency_key
        for record in reader()
        if record.idempotency_key.startswith(prefix)
    }
    for window in sorted(windows, key=lambda item: item.window_id):
        attempt_number = prior_attempt_counts.get(window.window_id, 0) + 1
        suffix = (
            f":{canonical_sha256(window.window_id)}:a{attempt_number}"
        )
        if any(
            key.endswith(suffix) and key not in completed
            for key in guard_keys
        ):
            raise RuntimeError(
                "PROVIDER_CALL_OUTCOME_UNKNOWN_FAIL_CLOSED:"
                f"{provider.value}:{command}:{window.window_id}:"
                f"attempt:{attempt_number}"
            )


def _assert_provider_transport_available(
    provider: object,
) -> None:
    """Probe optional adapters without breaking lightweight test providers."""

    probe = getattr(provider, "assert_transport_available", None)
    if probe is None:
        return
    if not callable(probe):
        raise RuntimeError("PROVIDER_TRANSPORT_PREFLIGHT_INVALID")
    probe()


def _database_state() -> SQLAlchemyOperationalState:
    database_url = os.getenv("ROBIN_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("PROSPECTIVE_DATABASE_URL_MISSING")
    return SQLAlchemyOperationalState(build_engine(database_url))


def _repository(*, cache_root: Path | None = None) -> ProspectiveR2Repository:
    store: ObjectStore
    if cache_root is not None:
        store = DirectoryObjectStore(cache_root)
    else:
        store = R2ObjectStore(os.environ)
    return ProspectiveR2Repository(store)


def _code_revision(value: str | None) -> str:
    candidate = value or os.getenv("GITHUB_SHA") or SAFE_CODE_REVISION
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", candidate):
        raise ValueError("CODE_REVISION_INVALID")
    return candidate


def run_fixture_registry(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
    repository: ProspectiveR2Repository | None = None,
    provider: ApiFootballProvider | None = None,
) -> dict[str, object]:
    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    command = "fixture-registry"
    output = args.output
    estimate = _estimate(
        command=command,
        policy=policy,
        units=3,
        provider=ProviderKind.API_FOOTBALL,
        windows_due=1,
        now=now,
    )
    if args.estimate:
        _write_json(output / "fixture-registry-estimate.json", estimate)
        return estimate
    if not args.execute and args.cache is None:
        raise ValueError("FIXTURE_REGISTRY_MODE_REQUIRED")

    if args.execute:
        verified = _verified_estimate(
            args.estimate_file,
            command=command,
            policy=policy,
        )
        if (
            verified.get("provider") != ProviderKind.API_FOOTBALL.value
            or _int_value(
                verified["estimated_units"],
                error="PROVIDER_ESTIMATE_UNITS_INVALID",
            )
            != 3
            or _int_value(
                verified["windows_due"],
                error="PROVIDER_ESTIMATE_WINDOWS_INVALID",
            )
            != 1
            or verified.get("window_ids_sha256")
            != canonical_sha256([])
        ):
            raise ValueError("PROVIDER_ESTIMATE_SCOPE_CHANGED")

    competition = policy.competition(args.competition)
    horizon_days = _int_value(
        policy.fixture_registry["horizon_days"],
        error="PROSPECTIVE_HORIZON_DAYS_INVALID",
    )
    until = now + timedelta(days=horizon_days)
    state = state or (
        _database_state() if args.execute else MemoryOperationalState()
    )
    _reject_non_durable_execution_inputs(args, state=state)
    repository = repository or _repository(cache_root=args.object_store_root)
    _reconcile_r2_state(
        state=state,
        repository=repository,
        policy=policy,
    )
    budget_admissions: tuple[dict[str, object], ...] = ()
    if args.execute:
        provider_reserve = policy.provider_reserve(
            ProviderKind.API_FOOTBALL
        )
        last_remaining = state.external_quota_remaining(
            ProviderKind.API_FOOTBALL,
            now=now,
        )
        budget_admissions = _authorize_budget_plan(
            state,
            policy=policy,
            provider=ProviderKind.API_FOOTBALL,
            units_by_competition={args.competition: 3},
            provider_remaining=(
                last_remaining
                if last_remaining is not None
                else provider_reserve + 3
            ),
            now=now,
        )
    api_calls = 0
    quota_remaining: int | None = None
    current_season: int | None = None
    registry_requested_at = now
    registry_received_at = now
    registry_observed_at = now
    registry_result: ProviderResult | None = None
    if args.cache is not None:
        cache = _mapping(_read_json(args.cache), error="FIXTURE_CACHE_INVALID")
        records_value = cache.get("fixtures", [])
        if not isinstance(records_value, list):
            raise ValueError("FIXTURE_CACHE_RECORDS_INVALID")
        records = tuple(
            _mapping(item, error="FIXTURE_CACHE_RECORD_INVALID")
            for item in records_value
        )
        season_value = cache.get("current_season")
        current_season = (
            _int_value(season_value, error="FIXTURE_CACHE_SEASON_INVALID")
            if season_value is not None
            else None
        )
    else:
        provider = provider or ApiFootballProvider(
            api_key=os.getenv("API_FOOTBALL_KEY"),
            league_id=_int_value(
                competition["provider_id"],
                error="PROSPECTIVE_COMPETITION_PROVIDER_ID_INVALID",
            ),
            offline=False,
            max_retries=0,
        )
        provider_reserve = policy.provider_reserve(
            ProviderKind.API_FOOTBALL
        )
        operation_key = f"{command}:{uuid.uuid4()}"
        _record_provider_units_before_call(
            state,
            repository,
            operation_key=operation_key,
            step="status",
            provider=ProviderKind.API_FOOTBALL,
            units=1,
            provider_remaining=0,
            provider_reserve=provider_reserve,
            recorded_at=now,
            code_revision=_code_revision(args.code_revision),
            budget_scope=args.competition,
        )
        api_calls += 1
        status = provider.get_status()
        status_error = _provider_result_error(status)
        if status_error is not None:
            raise RuntimeError(f"API_FOOTBALL_STATUS_FAILED:{status_error}")
        quota_remaining = _provider_quota_remaining(status)
        if quota_remaining is None:
            raise RuntimeError("API_FOOTBALL_QUOTA_UNKNOWN_BEFORE_FIXTURE_CALL")
        BudgetLedger().authorize(
            ProviderKind.API_FOOTBALL,
            2,
            provider_remaining=quota_remaining,
            provider_reserve=provider_reserve,
        )
        _record_provider_units_before_call(
            state,
            repository,
            operation_key=operation_key,
            step="competition",
            provider=ProviderKind.API_FOOTBALL,
            units=1,
            provider_remaining=quota_remaining - 1,
            provider_reserve=provider_reserve,
            recorded_at=now,
            code_revision=_code_revision(args.code_revision),
            budget_scope=args.competition,
        )
        api_calls += 1
        competition_response = provider.get_competitions(
            league_id=_int_value(
                competition["provider_id"],
                error="PROSPECTIVE_COMPETITION_PROVIDER_ID_INVALID",
            ),
            current=True,
        )
        competition_error = _provider_result_error(competition_response)
        if competition_error is not None:
            raise RuntimeError(
                f"API_FOOTBALL_COMPETITION_FAILED:{competition_error}"
            )
        current_season = _current_provider_season(competition_response)
        _record_provider_units_before_call(
            state,
            repository,
            operation_key=operation_key,
            step="fixtures",
            provider=ProviderKind.API_FOOTBALL,
            units=1,
            provider_remaining=quota_remaining - 2,
            provider_reserve=provider_reserve,
            recorded_at=now,
            code_revision=_code_revision(args.code_revision),
            budget_scope=args.competition,
        )
        api_calls += 1
        response = provider.get_fixtures(
            league_id=_int_value(
                competition["provider_id"],
                error="PROSPECTIVE_COMPETITION_PROVIDER_ID_INVALID",
            ),
            season=current_season,
            date_from=now.date().isoformat(),
            date_to=until.date().isoformat(),
        )
        registry_result = response
        fixture_error = _provider_result_error(response)
        if fixture_error is not None:
            raise RuntimeError(
                f"API_FOOTBALL_FIXTURES_FAILED:{fixture_error}"
            )
        records = _fixture_records(response)
        registry_requested_at = response.requested_at or now
        registry_received_at = response.received_at or response.observed_at
        registry_observed_at = response.observed_at
        quota_remaining = (
            _provider_quota_remaining(response)
            if _provider_quota_remaining(response) is not None
            else quota_remaining - 2
        )

    diagnostics = _fixture_record_diagnostics(
        records,
        now=now,
        until=until,
    )
    selected = _filter_fixtures(
        records,
        policy=policy,
        competition=args.competition,
        now=now,
        code_revision=_code_revision(args.code_revision),
        expected_season=current_season,
    )
    admitted = selected
    verified_identity_slots = 0
    verified_team_ids: set[str] = set()
    for fixture, raw_record in admitted:
        teams = raw_record.get("teams")
        if not isinstance(teams, Mapping):
            continue
        home = teams.get("home")
        away = teams.get("away")
        if not isinstance(home, Mapping) or not isinstance(away, Mapping):
            continue
        if (
            str(home.get("name", "")).strip()
            and str(home.get("id", "")).strip() == fixture.home_team_id
        ):
            verified_identity_slots += 1
            verified_team_ids.add(fixture.home_team_id)
        if (
            str(away.get("name", "")).strip()
            and str(away.get("id", "")).strip() == fixture.away_team_id
        ):
            verified_identity_slots += 1
            verified_team_ids.add(fixture.away_team_id)
    lifecycle_tombstones = _fixture_lifecycle_tombstones(
        records,
        state=state,
        policy=policy,
        competition=args.competition,
        now=now,
        code_revision=_code_revision(args.code_revision),
        selected_fixture_ids={fixture.fixture_id for fixture, _ in selected},
    )
    selected = tuple(
        sorted(
            (*selected, *lifecycle_tombstones),
            key=lambda item: (item[0].kickoff_at, item[0].fixture_id),
        )
    )
    selected = _version_fixture_lifecycle_transitions(
        selected,
        state=state,
    )
    inserted = 0
    duplicates = 0
    objects_added = 0
    r2_bytes = 0
    for index, (fixture, raw_record) in enumerate(selected):
        cutoff = fixture.kickoff_at - timedelta(microseconds=1)
        quality = (
            AvailabilityStatus.CAPTURED
            if registry_received_at < cutoff
            else AvailabilityStatus.TEMPORALITY_FAILED
        )
        context = CaptureContext(
            window_id=None,
            window_label="REGISTRY",
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider=("cache-test" if args.cache is not None else fixture.provider),
            family=CaptureFamily.FIXTURE,
            requested_at=registry_requested_at,
            response_received_at=registry_received_at,
            observed_at=max(registry_observed_at, registry_received_at),
            kickoff_at=fixture.kickoff_at,
            cutoff_at=cutoff,
            http_status=200,
            source_endpoint=(
                "cache://fixture-registry"
                if args.cache is not None
                else "/fixtures"
            ),
            complete=quality is AvailabilityStatus.CAPTURED,
            quality_status=quality,
            provider_calls=1 if index == 0 and api_calls else 0,
            code_revision=fixture.code_revision,
            materialized_at=now,
        )
        capture_payload = _r2_capture_payload(
            result=registry_result,
            normalized_records=[dict(raw_record)],
            cache_payload=dict(raw_record),
        )
        capture_payload["fixture_contract"] = fixture.model_dump(mode="json")
        capture = repository.capture(payload=capture_payload, context=context)
        objects_added += int(capture.payload_created) + int(capture.receipt_created)
        r2_bytes += capture.receipt.stored_bytes
        if state.register_fixture(fixture, capture):
            inserted += 1
        else:
            duplicates += 1
    snapshot = _base_snapshot(policy, now=now)
    cast(dict[str, object], snapshot["fixtures"]).update(
        {
            "tracked": len(state.fixtures()),
            "windows_planned": 0,
            "windows_due": 0,
        }
    )
    cast(dict[str, object], snapshot["providers"]).update(
        {"api_football_calls": api_calls}
    )
    cast(dict[str, object], snapshot["r2"]).update(
        {
            "objects_added": objects_added,
            "bytes": r2_bytes,
            "verified": objects_added,
            "replay_status": "NOT_RUN",
        }
    )
    cast(dict[str, object], snapshot["postgresql"]).update(
        {"inserts": inserted, "duplicates_avoided": duplicates}
    )
    snapshot["status"] = (
        "FIXTURE_REGISTRY_CAPTURED" if selected else "NO_ELIGIBLE_FIXTURE"
    )
    report = _report(
        command=command,
        policy=policy,
        now=now,
        snapshot=snapshot,
        extra={
            "competition": args.competition,
            "provider_id": competition["provider_id"],
            "horizon_from": now.date().isoformat(),
            "horizon_to": until.date().isoformat(),
            "max_matchdays": policy.fixture_registry[
                "max_matchdays_per_competition"
            ],
            "fixtures_received": len(records),
            "provider_response_valid": True,
            "provider_response_empty": len(records) == 0,
            **diagnostics,
            "fixtures_registered": len(selected),
            "fixtures_valid": len(admitted),
            "kickoffs_reliable": len(admitted),
            "identity_slots_expected": len(admitted) * 2,
            "identity_slots_verified": verified_identity_slots,
            "teams_verified": len(verified_team_ids),
            "fixture_tombstones_registered": len(lifecycle_tombstones),
            "fixtures_inserted": inserted,
            "duplicates_avoided": duplicates,
            "quota_remaining": quota_remaining,
            "provider_season": current_season,
            "provider_calls": api_calls,
            "budget_admissions": list(budget_admissions),
        },
    )
    _write_json(output / "fixture-registry.json", report)
    return report


def run_scheduler(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
) -> dict[str, object]:
    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    state = state or _database_state()
    due = 0
    missed = 0
    by_family: Counter[str] = Counter()
    planned_windows: list[CaptureWindow] = []
    for fixture in state.fixtures():
        for family in CaptureFamily:
            allowed_labels = set(
                policy.allowed_window_labels(fixture.competition, family)
            )
            if not allowed_labels:
                continue
            for window in schedule_windows(
                fixture,
                family,
                scheduled_at=now,
                tolerance=policy.operational_tolerance,
            ):
                if window.label not in allowed_labels:
                    continue
                status = classify_window(window, now=now)
                stored_window = window.model_copy(update={"status": status})
                planned_windows.append(stored_window)
                by_family[f"{family.value}:{status.value}"] += 1
                due += int(status is AvailabilityStatus.DUE)
                missed += int(status is AvailabilityStatus.MISSED_WINDOW)
    inserted, duplicates = state.schedule_windows_batch(planned_windows)
    snapshot = _base_snapshot(policy, now=now)
    cast(dict[str, object], snapshot["fixtures"]).update(
        {
            "tracked": len(state.fixtures()),
            "windows_planned": inserted + duplicates,
            "windows_due": due,
        }
    )
    cast(dict[str, object], snapshot["captures"]).update({"missed": missed})
    cast(dict[str, object], snapshot["postgresql"]).update(
        {"inserts": inserted, "duplicates_avoided": duplicates}
    )
    snapshot["status"] = (
        "CAPTURE_WINDOWS_DUE" if due else "NO_DUE_WINDOW_SUCCESS"
    )
    report = _report(
        command="scheduler",
        policy=policy,
        now=now,
        snapshot=snapshot,
        extra={
            "windows_inserted": inserted,
            "duplicates_avoided": duplicates,
            "windows_due": due,
            "windows_missed": missed,
            "by_family_status": dict(sorted(by_family.items())),
            "provider_calls": 0,
            "odds_api_credits": 0,
        },
    )
    _write_json(args.output / "scheduler-plan.json", report)
    return report


def _due_windows(
    state: OperationalState,
    *,
    families: tuple[CaptureFamily, ...],
    now: datetime,
    maximum_attempts: int | None = None,
) -> tuple[CaptureWindow, ...]:
    completed_window_ids = {
        receipt.window_id
        for receipt in state.receipts()
        if receipt.window_id is not None
        and receipt.quality_status
        in {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        }
    }
    attempt_counts = Counter(attempt.window_id for attempt in state.attempts())
    return tuple(
        sorted(
            (
                window
                for window in _active_windows(state)
                if window.family in families
                and classify_window(window, now=now) is AvailabilityStatus.DUE
                and window.window_id not in completed_window_ids
                and (
                    maximum_attempts is None
                    or attempt_counts[window.window_id] < maximum_attempts
                )
            ),
            key=lambda item: (item.cutoff_at, item.window_id),
        )
    )


def _window_matches_fixture_version(
    window: CaptureWindow,
    fixture: ProspectiveFixture,
) -> bool:
    """Return whether a window belongs to the current fixture business version.

    Versioned Jalon-12 windows are matched by their exact deterministic ID.
    Legacy pilot windows remain append-only replay evidence and are never
    operational. ``registered_at`` is ingestion metadata, not a durable
    business-version discriminator, so activation never depends on it.
    """

    if window.fixture_id != fixture.fixture_id or window.kickoff_at != fixture.kickoff_at:
        return False
    tolerance = timedelta(seconds=window.operational_tolerance_seconds)
    expected = next(
        (
            candidate
            for candidate in schedule_windows(
                fixture,
                window.family,
                scheduled_at=window.scheduled_at,
                tolerance=tolerance,
            )
            if candidate.label == window.label
        ),
        None,
    )
    if expected is None:
        return False
    return window.window_id == expected.window_id


def _active_windows(state: OperationalState) -> tuple[CaptureWindow, ...]:
    current_fixtures = {
        fixture.fixture_id: fixture for fixture in state.fixtures()
    }
    return tuple(
        window
        for window in state.windows()
        if (
            (fixture := current_fixtures.get(window.fixture_id)) is not None
            and _window_matches_fixture_version(window, fixture)
        )
    )


def _reconcile_receipt_attempts(state: OperationalState) -> int:
    """Rebuild a missing compact attempt from an immutable R2/PG receipt."""

    attempts = list(state.attempts())
    inserted = 0
    for receipt in sorted(
        state.receipts(),
        key=lambda item: (item.requested_at, item.receipt_hash),
    ):
        if receipt.window_id is None or any(
            attempt.window_id == receipt.window_id
            and attempt.idempotency_key.endswith(
                f":{receipt.payload_sha256}"
            )
            for attempt in attempts
        ):
            continue
        attempt_number = (
            max(
                (
                    attempt.attempt_number
                    for attempt in attempts
                    if attempt.window_id == receipt.window_id
                ),
                default=0,
            )
            + 1
        )
        if attempt_number > 5:
            raise RuntimeError("CAPTURE_ATTEMPT_RECONCILIATION_LIMIT_EXCEEDED")
        successful_statuses = {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        }
        attempt = CaptureAttempt(
            attempt_id=canonical_sha256(
                {
                    "receipt_hash": receipt.receipt_hash,
                    "reconciliation": "IMMUTABLE_RECEIPT",
                }
            ),
            idempotency_key=(
                f"{receipt.window_id}:attempt:{attempt_number}:"
                f"{receipt.payload_sha256}"
            ),
            window_id=receipt.window_id,
            fixture_id=receipt.fixture_id,
            provider=receipt.provider,
            family=receipt.family,
            attempted_at=receipt.requested_at,
            status=receipt.quality_status,
            retry_disposition=(
                RetryDisposition.NOT_REQUIRED
                if receipt.quality_status in successful_statuses
                else RetryDisposition.RETRY_PENDING
            ),
            attempt_number=attempt_number,
            http_status=receipt.http_status,
            provider_calls=receipt.provider_calls,
            provider_credits=(
                2
                if receipt.provider == "the-odds-api"
                and receipt.provider_calls
                else 0
            ),
            error_code=(
                None
                if receipt.quality_status in successful_statuses
                else "RECONSTRUCTED_FROM_IMMUTABLE_RECEIPT"
            ),
            code_revision=receipt.code_revision,
        )
        if state.append_attempt(attempt):
            inserted += 1
        attempts.append(attempt)
    return inserted


def _capture_estimated_units(
    command: str,
    due: tuple[CaptureWindow, ...],
    fixture_by_id: Mapping[str, ProspectiveFixture] | None = None,
) -> tuple[ProviderKind, int]:
    if command == "capture-odds":
        if not due:
            return ProviderKind.ODDS_API, 0
        competitions = (
            {
                fixture.competition
                for window in due
                if (fixture := fixture_by_id.get(window.fixture_id)) is not None
            }
            if fixture_by_id is not None
            else {"legacy-single-sport"}
        )
        return ProviderKind.ODDS_API, 2 * len(competitions)
    if not due:
        return ProviderKind.API_FOOTBALL, 0
    families_by_fixture: dict[str, set[CaptureFamily]] = {}
    for window in due:
        families_by_fixture.setdefault(window.fixture_id, set()).add(window.family)
    calls = 1  # /status is mandatory before any API-Football capture.
    for families in families_by_fixture.values():
        if command == "capture-general":
            calls += 1
        elif command == "capture-lineup":
            calls += 2  # bounded fixture freshness + lineup payload
        else:
            calls += 1  # bounded fixture freshness
            calls += int(
                bool(
                    families
                    & {CaptureFamily.INJURY, CaptureFamily.PLAYER_STATUS}
                )
            )
            calls += 2 if CaptureFamily.SQUAD in families else 0
    return ProviderKind.API_FOOTBALL, calls


def _payload_for_cache(
    cache: Mapping[str, object],
    *,
    window: CaptureWindow,
) -> object:
    payloads = cache.get("payloads", {})
    if not isinstance(payloads, Mapping):
        raise ValueError("CAPTURE_CACHE_PAYLOADS_INVALID")
    fixture_payloads = payloads.get(window.fixture_id, {})
    if not isinstance(fixture_payloads, Mapping):
        return []
    return fixture_payloads.get(window.family.value, [])


def _capture_request_key(
    command: str,
    window: CaptureWindow,
    fixture_by_id: Mapping[str, ProspectiveFixture] | None = None,
) -> tuple[str, str]:
    family_group = (
        "injury-status"
        if window.family in {CaptureFamily.INJURY, CaptureFamily.PLAYER_STATUS}
        else window.family.value
    )
    return (
        (
            (
                fixture_by_id[window.fixture_id].competition
                if fixture_by_id is not None
                and window.fixture_id in fixture_by_id
                else "legacy-single-sport"
            )
            if command == "capture-odds"
            else window.fixture_id
        ),
        "lineup"
        if command == "capture-lineup"
        else ("general" if command == "capture-general" else family_group),
    )


def _provider_capture(
    *,
    command: str,
    fixture: ProspectiveFixture,
    family: CaptureFamily,
    provider: ApiFootballProvider | TheOddsApiProvider,
    odds_sport_key: str | None = None,
    before_provider_call: Callable[[str, int, int], None] | None = None,
) -> tuple[ProviderResult, str, int, int]:
    def before(step: str, calls: int, credits: int) -> None:
        if before_provider_call is not None:
            before_provider_call(step, calls, credits)

    fixture_id = int(fixture.provider_fixture_id)
    if command == "capture-general":
        before("fixtures", 1, 0)
        result = cast(ApiFootballProvider, provider).get_fixtures(
            fixture_id=fixture_id
        )
        return result, "/fixtures", 1, 0
    if command == "capture-player":
        if family is CaptureFamily.SQUAD:
            football = cast(ApiFootballProvider, provider)
            before("squad-home", 1, 0)
            home = football.get_squads(team_id=int(fixture.home_team_id))
            before("squad-away", 1, 0)
            away = football.get_squads(team_id=int(fixture.away_team_id))
            sides_present = (
                home.availability is DataAvailability.PRESENT
                and away.availability is DataAvailability.PRESENT
            )
            quota_remaining = [
                value
                for value in (
                    home.quota.remaining,
                    away.quota.remaining,
                )
                if value is not None
            ]
            quota_last_cost = [
                value
                for value in (
                    home.quota.last_cost,
                    away.quota.last_cost,
                )
                if value is not None
            ]
            combined = home.model_copy(
                update={
                    "availability": (
                        DataAvailability.PRESENT
                        if sides_present
                        else DataAvailability.ERROR
                    ),
                    "records": home.records + away.records,
                    "raw_payload": {
                        "home": (
                            home.raw_payload
                            if home.raw_payload is not None
                            else [dict(record) for record in home.records]
                        ),
                        "away": (
                            away.raw_payload
                            if away.raw_payload is not None
                            else [dict(record) for record in away.records]
                        ),
                    },
                    "observed_at": max(home.observed_at, away.observed_at),
                    "requested_at": min(
                        home.requested_at or home.observed_at,
                        away.requested_at or away.observed_at,
                    ),
                    "received_at": max(
                        home.received_at or home.observed_at,
                        away.received_at or away.observed_at,
                    ),
                    "http_status": max(home.http_status or 200, away.http_status or 200),
                    "quota": QuotaState(
                        remaining=(
                            min(quota_remaining)
                            if quota_remaining
                            else None
                        ),
                        last_cost=(
                            sum(quota_last_cost)
                            if len(quota_last_cost) == 2
                            else None
                        ),
                    ),
                    "message": (
                        None
                        if sides_present
                        else "SQUAD_SIDE_UNAVAILABLE"
                    ),
                }
            )
            return combined, "/players/squads", 2, 0
        if family not in {
            CaptureFamily.INJURY,
            CaptureFamily.PLAYER_STATUS,
        }:
            raise RuntimeError("PLAYER_CAPTURE_FAMILY_UNSUPPORTED")
        before("injuries", 1, 0)
        result = cast(ApiFootballProvider, provider).get_injuries(
            fixture_id=fixture_id
        )
        return result, "/injuries", 1, 0
    if command == "capture-lineup":
        before("lineups", 1, 0)
        result = cast(ApiFootballProvider, provider).get_lineups(
            fixture_id=fixture_id
        )
        return result, "/fixtures/lineups", 1, 0
    before("odds", 1, 2)
    odds_provider = cast(TheOddsApiProvider, provider)
    if odds_sport_key is not None and hasattr(
        odds_provider,
        "get_odds_for_sport",
    ):
        result = odds_provider.get_odds_for_sport(odds_sport_key)
    else:
        result = odds_provider.get_odds()
    sport_key = odds_sport_key or "soccer_france_ligue_one"
    return result, f"/sports/{sport_key}/odds", 1, 2


def _fixture_identities(
    repository: ProspectiveR2Repository,
) -> dict[str, tuple[str, str, datetime]]:
    identities: dict[str, tuple[str, str, datetime]] = {}
    for stored in repository.iter_captures():
        if (
            stored.receipt.family is not CaptureFamily.FIXTURE
            or not isinstance(stored.payload, Mapping)
        ):
            continue
        normalized = stored.payload.get("normalized_family_records")
        raw: object = (
            normalized[0]
            if isinstance(normalized, list) and normalized
            else stored.payload.get("provider_payload")
        )
        if not isinstance(raw, Mapping):
            continue
        teams = raw.get("teams")
        fixture = raw.get("fixture")
        if not isinstance(teams, Mapping) or not isinstance(fixture, Mapping):
            continue
        home = teams.get("home")
        away = teams.get("away")
        if not isinstance(home, Mapping) or not isinstance(away, Mapping):
            continue
        home_name = str(home.get("name", "")).strip()
        away_name = str(away.get("name", "")).strip()
        if not home_name or not away_name:
            continue
        identities[stored.receipt.fixture_id] = (
            home_name,
            away_name,
            _provider_datetime(fixture.get("date")),
        )
    return identities


def _match_odds_records(
    records: Iterable[Mapping[str, object]],
    *,
    fixture_id: str,
    identities: Mapping[str, tuple[str, str, datetime]],
) -> list[dict[str, object]]:
    identity = identities.get(fixture_id)
    if identity is None:
        raise OddsFixtureIdentityError("ODDS_FIXTURE_IDENTITY_UNAVAILABLE")
    expected_home, expected_away, expected_kickoff = identity
    matches: list[dict[str, object]] = []
    for record in records:
        try:
            kickoff = _provider_datetime(record.get("commence_time"))
        except (TypeError, ValueError):
            continue
        if (
            str(record.get("home_team", "")).strip().casefold()
            == expected_home.casefold()
            and str(record.get("away_team", "")).strip().casefold()
            == expected_away.casefold()
            and abs((kickoff - expected_kickoff).total_seconds()) <= 60
        ):
            matches.append(dict(record))
    if len(matches) != 1:
        raise OddsFixtureIdentityError(
            "ODDS_FIXTURE_MATCH_AMBIGUOUS"
            if len(matches) > 1
            else "ODDS_FIXTURE_MATCH_MISSING"
        )
    return matches


def _r2_capture_payload(
    *,
    result: ProviderResult | None,
    normalized_records: object,
    cache_payload: object | None = None,
) -> dict[str, object]:
    """Keep the provider envelope immutable while exposing a replay contract.

    `raw_payload` comes only from the decoded response body. Request URLs,
    headers and query parameters are never accepted by this boundary.
    """

    raw_payload = result.raw_payload if result is not None else None
    if raw_payload is not None:
        raw_kind = "PROVIDER_RESPONSE_ENVELOPE"
    else:
        raw_payload = (
            cache_payload
            if cache_payload is not None
            else [dict(record) for record in result.records]
            if result is not None
            else normalized_records
        )
        raw_kind = "CANONICAL_PROVIDER_RECORDS"
    return {
        "raw_payload_kind": raw_kind,
        "raw_provider_payload": raw_payload,
        "normalized_family_records": normalized_records,
    }


def _normalized_capture_payload(payload: object) -> object:
    if not isinstance(payload, Mapping):
        return payload
    contract_keys = {
        "raw_payload_kind",
        "raw_provider_payload",
        "normalized_family_records",
    }
    present = contract_keys & set(payload)
    if not present:
        return payload
    if present != contract_keys:
        raise RuntimeError("R2_CAPTURE_CONTRACT_INCOMPLETE")
    if payload["raw_payload_kind"] not in {
        "PROVIDER_RESPONSE_ENVELOPE",
        "CANONICAL_PROVIDER_RECORDS",
    }:
        raise RuntimeError("R2_CAPTURE_RAW_KIND_INVALID")
    return payload["normalized_family_records"]


def _raw_provider_records(raw_payload: object) -> list[dict[str, object]]:
    if isinstance(raw_payload, list):
        return [
            dict(record)
            for record in raw_payload
            if isinstance(record, Mapping)
        ]
    if not isinstance(raw_payload, Mapping):
        return []
    response = raw_payload.get("response")
    if isinstance(response, list):
        return [
            dict(record) for record in response if isinstance(record, Mapping)
        ]
    if set(raw_payload) == {"home", "away"}:
        return [
            record
            for side in ("home", "away")
            for record in _raw_provider_records(raw_payload[side])
        ]
    return [dict(raw_payload)]


def _renormalize_r2_payload(
    receipt: CaptureReceipt,
    payload: object,
) -> object:
    normalized = _normalized_capture_payload(payload)
    if not isinstance(payload, Mapping) or "raw_payload_kind" not in payload:
        return normalized
    raw = payload["raw_provider_payload"]
    raw_kind = payload["raw_payload_kind"]
    if raw_kind == "CANONICAL_PROVIDER_RECORDS":
        candidates = (
            [dict(raw)]
            if isinstance(raw, Mapping) and isinstance(normalized, list)
            else raw
        )
        if canonical_sha256(candidates) != canonical_sha256(normalized):
            raise RuntimeError("R2_RAW_NORMALIZATION_MISMATCH")
        return candidates

    records = _raw_provider_records(raw)
    provider_fixture_id = receipt.fixture_id.rsplit(":", maxsplit=1)[-1]
    fixture_records = [
        record
        for record in records
        if isinstance(record.get("fixture"), Mapping)
        and str(cast(Mapping[str, object], record["fixture"]).get("id"))
        == provider_fixture_id
    ]
    if receipt.family is CaptureFamily.FIXTURE:
        derived: object = fixture_records
    elif receipt.family is CaptureFamily.TEAM:
        derived = [
            record["teams"]
            for record in fixture_records
            if isinstance(record.get("teams"), Mapping)
        ]
    elif receipt.family is CaptureFamily.EVENT_STATUS:
        derived = [
            {
                "fixture": {
                    "id": cast(Mapping[str, object], record["fixture"]).get(
                        "id"
                    ),
                    "status": cast(
                        Mapping[str, object],
                        record["fixture"],
                    ).get("status"),
                }
            }
            for record in fixture_records
        ]
    elif receipt.family is CaptureFamily.FORMATION:
        derived = [
            {
                "team": record.get("team"),
                "formation": record.get("formation"),
            }
            for record in records
        ]
    elif receipt.family is CaptureFamily.ODDS:
        normalized_records = (
            normalized if isinstance(normalized, list) else []
        )
        matching = [
            record
            for record in records
            if any(
                canonical_sha256(record) == canonical_sha256(candidate)
                for candidate in normalized_records
            )
        ]
        if len(normalized_records) != 1 or len(matching) != 1:
            raise RuntimeError("R2_RAW_NORMALIZATION_MISMATCH")
        derived = matching
    else:
        derived = records
    if canonical_sha256(derived) != canonical_sha256(normalized):
        raise RuntimeError("R2_RAW_NORMALIZATION_MISMATCH")
    return derived


def _operational_replay_projection(
    receipt: CaptureReceipt,
    payload: object,
) -> Mapping[str, object]:
    return {
        "fixture_id": receipt.fixture_id,
        "family": receipt.family.value,
        "observed_at": receipt.observed_at.isoformat(),
        "payload_sha256": receipt.payload_sha256,
        # Ephemeral replay input only; SQL sinks extract compact fields and
        # never persist this raw body.
        "data": _renormalize_r2_payload(receipt, payload),
    }


def _seed_legacy_sql_budget_journal(
    *,
    state: OperationalState,
    repository: ProspectiveR2Repository,
) -> None:
    """Idempotently complete a pre-hardening SQL-to-R2 budget migration."""

    if not isinstance(state, SQLAlchemyOperationalState):
        return
    if not state.budget_rows:
        return
    table = state.tables["provider_budget_ledger"]
    with state.engine.connect() as connection:
        rows = tuple(connection.execute(select(table)).mappings())
    for row in sorted(
        rows,
        key=lambda item: (
            cast(datetime, _db_value(item["recorded_at"])),
            str(item["idempotency_key"]),
        ),
    ):
        repository.record_provider_budget(
            DurableProviderBudget(
                idempotency_key=str(row["idempotency_key"]),
                provider=str(row["provider"]),
                units=int(row["units"]),
                provider_remaining=int(row["provider_remaining"]),
                provider_reserve=int(row["provider_reserve"]),
                recorded_at=cast(datetime, _db_value(row["recorded_at"])),
                reason=str(row["reason"]),
                code_revision=str(row["code_revision"]),
            )
        )


def _reconcile_provider_budget_journal(
    *,
    state: OperationalState,
    repository: ProspectiveR2Repository,
    captures: tuple[StoredCapture, ...],
) -> int:
    _seed_legacy_sql_budget_journal(state=state, repository=repository)
    records = repository.provider_budgets()
    for record in records:
        state.append_budget(
            idempotency_key=record.idempotency_key,
            provider=ProviderKind(record.provider),
            units=record.units,
            provider_remaining=record.provider_remaining,
            provider_reserve=record.provider_reserve,
            recorded_at=record.recorded_at,
            reason=record.reason,
            code_revision=record.code_revision,
        )
    if isinstance(state, SQLAlchemyOperationalState):
        table = state.tables["provider_budget_ledger"]
        with state.engine.connect() as connection:
            sql_rows = {
                str(row["idempotency_key"]): row
                for row in connection.execute(select(table)).mappings()
            }
        durable_rows = {
            record.idempotency_key: record for record in records
        }
        if set(durable_rows) != set(sql_rows):
            raise RuntimeError("R2_POSTGRESQL_PROVIDER_BUDGET_PARITY_FAILED")
        for key, record in durable_rows.items():
            row = sql_rows[key]
            if {
                "provider": str(row["provider"]),
                "units": int(row["units"]),
                "provider_remaining": int(row["provider_remaining"]),
                "provider_reserve": int(row["provider_reserve"]),
                "recorded_at": _json_compatible(
                    _db_value(row["recorded_at"])
                ),
                "reason": str(row["reason"]),
                "code_revision": str(row["code_revision"]),
            } != {
                "provider": record.provider,
                "units": record.units,
                "provider_remaining": record.provider_remaining,
                "provider_reserve": record.provider_reserve,
                "recorded_at": record.recorded_at.isoformat(),
                "reason": record.reason,
                "code_revision": record.code_revision,
            }:
                raise RuntimeError(
                    "R2_POSTGRESQL_PROVIDER_BUDGET_PARITY_FAILED"
                )
    billed_capture_exists = any(
        capture.receipt.provider_calls > 0 for capture in captures
    )
    if (
        billed_capture_exists
        and not records
        and isinstance(state, SQLAlchemyOperationalState)
        and state.engine.dialect.name != "sqlite"
    ):
        raise RuntimeError("R2_PROVIDER_BUDGET_HISTORY_REQUIRED")
    return len(records)


class _ProjectionParityCollector:
    """Duck-typed sink state used to derive exact rows from R2 payloads."""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {}

    def persist_capture(self, capture: StoredCapture) -> bool:
        del capture
        return False

    def _insert_exact(
        self,
        table_name: str,
        *,
        key_values: Mapping[str, object],
        values: Mapping[str, object],
    ) -> bool:
        del key_values
        self.rows.setdefault(table_name, []).append(dict(values))
        return True


def _projection_row_fingerprint(row: Mapping[str, object]) -> str:
    return canonical_sha256(
        {
            key: _json_compatible(_db_value(value))
            for key, value in sorted(row.items())
        }
    )


def _assert_r2_postgresql_projection_parity(
    *,
    state: SQLAlchemyOperationalState,
    captures: tuple[StoredCapture, ...],
) -> None:
    collector = _ProjectionParityCollector()
    sink = SQLAlchemyProjectionSink(
        cast(SQLAlchemyOperationalState, cast(object, collector))
    )
    for capture in sorted(
        captures,
        key=lambda item: item.receipt.receipt_hash,
    ):
        receipt = capture.receipt
        if receipt.quality_status is not AvailabilityStatus.CAPTURED:
            continue
        projection = _operational_replay_projection(
            receipt,
            capture.payload,
        )
        sink.insert_capture(
            receipt,
            projection,
            canonical_sha256(projection),
        )

    projection_tables = (
        "prospective_player_status",
        "prospective_injuries",
        "prospective_lineups",
        "prospective_formations",
        "prospective_odds_snapshots",
    )
    with state.engine.connect() as connection:
        for table_name in projection_tables:
            expected = sorted(
                _projection_row_fingerprint(row)
                for row in collector.rows.get(table_name, [])
            )
            actual = sorted(
                _projection_row_fingerprint(
                    cast(Mapping[str, object], row)
                )
                for row in connection.execute(
                    select(state.tables[table_name])
                ).mappings()
            )
            if actual != expected:
                raise RuntimeError(
                    "R2_POSTGRESQL_PROJECTION_PARITY_FAILED:"
                    f"{table_name}"
                )


def _assert_r2_postgresql_capture_parity(
    *,
    state: OperationalState,
    captures: tuple[StoredCapture, ...],
) -> None:
    if not isinstance(state, SQLAlchemyOperationalState):
        return
    r2_receipts = {
        capture.receipt.receipt_hash: capture.receipt for capture in captures
    }
    state_receipts = {
        receipt.receipt_hash: receipt for receipt in state.receipts()
    }
    if r2_receipts != state_receipts:
        raise RuntimeError("R2_POSTGRESQL_CAPTURE_RECEIPT_PARITY_FAILED")
    receipt_table = state.tables["capture_receipts"]
    index_table = state.tables["prospective_payload_index"]
    with state.engine.connect() as connection:
        rows = tuple(
            connection.execute(
                select(
                    receipt_table.c.receipt_hash,
                    receipt_table.c.id.label("receipt_id"),
                    receipt_table.c.fixture_id,
                    receipt_table.c.family,
                    receipt_table.c.observed_at,
                    receipt_table.c.payload_sha256,
                    receipt_table.c.payload_bytes,
                    receipt_table.c.stored_bytes,
                    receipt_table.c.r2_key,
                    receipt_table.c.receipt_r2_key,
                    index_table.c.receipt_id.label("index_receipt_id"),
                    index_table.c.fixture_id.label("index_fixture_id"),
                    index_table.c.family.label("index_family"),
                    index_table.c.observed_at.label("index_observed_at"),
                    index_table.c.payload_sha256.label("index_payload_sha256"),
                    index_table.c.payload_bytes.label("index_payload_bytes"),
                    index_table.c.stored_bytes.label("index_stored_bytes"),
                    index_table.c.r2_key.label("index_r2_key"),
                    index_table.c.receipt_r2_key.label("index_receipt_r2_key"),
                ).outerjoin(
                    index_table,
                    index_table.c.receipt_id == receipt_table.c.id,
                )
            ).mappings()
        )
    if len(rows) != len(r2_receipts):
        raise RuntimeError("R2_POSTGRESQL_PAYLOAD_INDEX_PARITY_FAILED")
    seen: set[str] = set()
    for row in rows:
        receipt_hash = str(row["receipt_hash"])
        receipt = r2_receipts.get(receipt_hash)
        if receipt is None or receipt_hash in seen:
            raise RuntimeError("R2_POSTGRESQL_PAYLOAD_INDEX_PARITY_FAILED")
        seen.add(receipt_hash)
        expected = {
            "fixture_id": receipt.fixture_id,
            "family": receipt.family.value,
            "observed_at": receipt.observed_at.isoformat(),
            "payload_sha256": receipt.payload_sha256,
            "payload_bytes": receipt.payload_bytes,
            "stored_bytes": receipt.stored_bytes,
            "r2_key": receipt.r2_key,
            "receipt_r2_key": receipt.receipt_r2_key,
        }
        actual = {
            "fixture_id": str(row["fixture_id"]),
            "family": str(row["family"]),
            "observed_at": cast(
                datetime,
                _db_value(row["observed_at"]),
            ).isoformat(),
            "payload_sha256": str(row["payload_sha256"]),
            "payload_bytes": int(row["payload_bytes"]),
            "stored_bytes": int(row["stored_bytes"]),
            "r2_key": str(row["r2_key"]),
            "receipt_r2_key": str(row["receipt_r2_key"]),
        }
        index_actual = {
            "fixture_id": str(row["index_fixture_id"]),
            "family": str(row["index_family"]),
            "observed_at": (
                cast(
                    datetime,
                    _db_value(row["index_observed_at"]),
                ).isoformat()
                if row["index_observed_at"] is not None
                else ""
            ),
            "payload_sha256": str(row["index_payload_sha256"]),
            "payload_bytes": (
                int(row["index_payload_bytes"])
                if row["index_payload_bytes"] is not None
                else -1
            ),
            "stored_bytes": (
                int(row["index_stored_bytes"])
                if row["index_stored_bytes"] is not None
                else -1
            ),
            "r2_key": str(row["index_r2_key"]),
            "receipt_r2_key": str(row["index_receipt_r2_key"]),
        }
        if (
            row["receipt_id"] != row["index_receipt_id"]
            or actual != expected
            or index_actual != expected
        ):
            raise RuntimeError("R2_POSTGRESQL_PAYLOAD_INDEX_PARITY_FAILED")
    _assert_r2_postgresql_projection_parity(
        state=state,
        captures=captures,
    )


def _reconcile_r2_state(
    *,
    state: OperationalState,
    repository: ProspectiveR2Repository,
    policy: ObservatoryPolicy,
) -> dict[str, int]:
    """Reconcile R2 into SQL before any due-window selection or provider call."""

    pending_reconciler = getattr(
        repository,
        "reconcile_pending_receipts",
        None,
    )
    recovered_r2_objects = (
        int(pending_reconciler())
        if callable(pending_reconciler)
        else 0
    )
    capture_reader = getattr(repository, "iter_captures", None)
    budget_reader = getattr(repository, "provider_budgets", None)
    if not callable(capture_reader) or not callable(budget_reader):
        if isinstance(state, SQLAlchemyOperationalState):
            raise RuntimeError("PROSPECTIVE_R2_RECONCILIATION_REQUIRED")
        return {
            "captures": 0,
            "projection_inserts": 0,
            "attempts_reconstructed": _reconcile_receipt_attempts(state),
            "budget_records": 0,
            "r2_recovered_objects": recovered_r2_objects,
        }
    captures = tuple(capture_reader())
    if isinstance(state, SQLAlchemyOperationalState):
        bootstrap = SQLAlchemyProjectionSink(state)
        bootstrap.bootstrap(captures, tolerance=policy.operational_tolerance)
    else:
        for capture in captures:
            receipt = capture.receipt
            contract = (
                capture.payload.get("fixture_contract")
                if isinstance(capture.payload, Mapping)
                else None
            )
            if receipt.window_id is None and isinstance(contract, Mapping):
                state.register_fixture(
                    ProspectiveFixture.model_validate(dict(contract)),
                    capture,
                )
            elif receipt.window_id in {
                window.window_id for window in state.windows()
            }:
                state.persist_capture(capture)
    durable = replay_from_r2(
        repository,
        state.projection_sink(),
        normalizer=_operational_replay_projection,
    )
    attempts_reconstructed = _reconcile_receipt_attempts(state)
    budget_records = _reconcile_provider_budget_journal(
        state=state,
        repository=repository,
        captures=captures,
    )
    _assert_r2_postgresql_capture_parity(state=state, captures=captures)
    return {
        "captures": len(captures),
        "projection_inserts": durable.projections_inserted,
        "attempts_reconstructed": attempts_reconstructed,
        "budget_records": budget_records,
        "r2_recovered_objects": recovered_r2_objects,
    }


def _provider_result_error(result: ProviderResult) -> str | None:
    unavailable_absence = (
        result.availability.value == "ABSENT"
        and result.message != "réponse valide sans donnée"
    )
    if (
        result.availability.value == "ERROR"
        or (result.http_status is not None and result.http_status >= 400)
        or result.message == "credential_absent"
        or unavailable_absence
    ):
        if result.message in {
            "MISSINGCREDENTIALERROR",
            "ODDS_QUOTA_HEADERS_MISSING",
            "RATELIMITERROR",
            "TRANSIENTPROVIDERERROR",
            "REGISTRY_STALE",
        }:
            return result.message
        return (
            f"HTTP_{result.http_status}"
            if result.http_status is not None
            else "PROVIDER_UNAVAILABLE"
        )
    return None


def _fixture_freshness_error(
    result: ProviderResult,
    fixture: ProspectiveFixture,
) -> str | None:
    provider_error = _provider_result_error(result)
    if provider_error is not None:
        return provider_error
    matching = tuple(
        record
        for record in result.records
        if isinstance(record.get("fixture"), Mapping)
        and str(cast(Mapping[str, object], record["fixture"]).get("id"))
        == fixture.provider_fixture_id
    )
    if len(matching) != 1:
        return "REGISTRY_STALE"
    record = matching[0]
    fixture_value = cast(Mapping[str, object], record["fixture"])
    teams = record.get("teams")
    status = fixture_value.get("status")
    if (
        not isinstance(teams, Mapping)
        or not isinstance(teams.get("home"), Mapping)
        or not isinstance(teams.get("away"), Mapping)
        or not isinstance(status, Mapping)
    ):
        return "REGISTRY_STALE"
    try:
        kickoff_at = _provider_datetime(fixture_value.get("date"))
    except (TypeError, ValueError):
        return "REGISTRY_STALE"
    home = cast(Mapping[str, object], teams["home"])
    away = cast(Mapping[str, object], teams["away"])
    if (
        kickoff_at != fixture.kickoff_at
        or str(home.get("id")) != fixture.home_team_id
        or str(away.get("id")) != fixture.away_team_id
        or str(status.get("short", "")).strip() != "NS"
    ):
        return "REGISTRY_STALE"
    return None


def _family_payload(
    *,
    command: str,
    family: CaptureFamily,
    result: ProviderResult,
    fixture: ProspectiveFixture,
    identities: Mapping[str, tuple[str, str, datetime]],
) -> object:
    records = [dict(record) for record in result.records]
    if command == "capture-odds":
        return _match_odds_records(
            records,
            fixture_id=fixture.fixture_id,
            identities=identities,
        )
    if command == "capture-general" and family is CaptureFamily.FIXTURE:
        return [
            record
            for record in records
            if isinstance(record.get("fixture"), Mapping)
            and str(
                cast(Mapping[str, object], record["fixture"]).get("id")
            )
            == fixture.provider_fixture_id
        ]
    if command == "capture-general" and family is CaptureFamily.TEAM:
        return [
            record["teams"]
            for record in records
            if isinstance(record.get("teams"), Mapping)
        ]
    if command == "capture-general" and family is CaptureFamily.EVENT_STATUS:
        return [
            {
                "fixture": {
                    "id": cast(Mapping[str, object], record["fixture"]).get("id"),
                    "status": cast(Mapping[str, object], record["fixture"]).get(
                        "status"
                    ),
                }
            }
            for record in records
            if isinstance(record.get("fixture"), Mapping)
        ]
    if command == "capture-lineup" and family is CaptureFamily.FORMATION:
        return [
            {
                "team": record.get("team"),
                "formation": record.get("formation"),
            }
            for record in records
        ]
    return records


def _payload_records(payload: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(item for item in payload if isinstance(item, Mapping))


def _record_id(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    raw = value.get("id")
    return "" if raw is None else str(raw).strip()


def _valid_lineup_record(record: Mapping[str, object]) -> tuple[str, ...] | None:
    start_xi = record.get("startXI")
    if not isinstance(start_xi, list):
        return None
    starters = tuple(
        _record_id(item.get("player"))
        for item in start_xi
        if isinstance(item, Mapping)
    )
    if (
        len(starters) != 11
        or any(not player_id for player_id in starters)
        or len(set(starters)) != 11
    ):
        return None
    return starters


def _formation_is_normalizable(value: object) -> bool:
    try:
        lines = tuple(int(item) for item in str(value).strip().split("-"))
    except ValueError:
        return False
    return (
        3 <= len(lines) <= 5
        and all(item > 0 for item in lines)
        and sum(lines) == 10
    )


def _odds_payload_has_supported_price(
    records: tuple[Mapping[str, object], ...],
) -> bool:
    for event in records:
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for bookmaker in bookmakers:
            if (
                not isinstance(bookmaker, Mapping)
                or not str(bookmaker.get("key", "")).strip()
                or not isinstance(bookmaker.get("markets"), list)
            ):
                continue
            for market in cast(list[object], bookmaker["markets"]):
                if not isinstance(market, Mapping):
                    continue
                market_key = str(market.get("key", ""))
                outcomes = market.get("outcomes")
                if market_key not in {"h2h", "totals"} or not isinstance(
                    outcomes, list
                ):
                    continue
                for outcome in outcomes:
                    if not isinstance(outcome, Mapping):
                        continue
                    price = outcome.get("price")
                    if (
                        str(outcome.get("name", "")).strip()
                        and isinstance(price, (int, float))
                        and float(price) > 1.0
                        and (
                            market_key != "totals"
                            or (
                                isinstance(outcome.get("point"), (int, float))
                                and float(cast(float | int, outcome["point"])) == 2.5
                            )
                        )
                    ):
                        return True
    return False


def _capture_payload_complete(
    *,
    family: CaptureFamily,
    payload: object,
    fixture: ProspectiveFixture,
) -> bool:
    """Validate the compact family contract before a window can complete."""

    records = _payload_records(payload)
    if not records or len(records) != len(cast(list[object], payload)):
        return False
    expected_teams = {fixture.home_team_id, fixture.away_team_id}
    if family is CaptureFamily.FIXTURE:
        return (
            len(records) == 1
            and _record_id(records[0].get("fixture"))
            == fixture.provider_fixture_id
        )
    if family is CaptureFamily.TEAM:
        if len(records) != 1:
            return False
        return {
            _record_id(records[0].get("home")),
            _record_id(records[0].get("away")),
        } == expected_teams
    if family is CaptureFamily.EVENT_STATUS:
        if len(records) != 1:
            return False
        fixture_value = records[0].get("fixture")
        if not isinstance(fixture_value, Mapping):
            return False
        status = fixture_value.get("status")
        return (
            _record_id(fixture_value) == fixture.provider_fixture_id
            and isinstance(status, Mapping)
            and bool(str(status.get("short", "")).strip())
        )
    if family is CaptureFamily.SQUAD:
        valid_teams: set[str] = set()
        for record in records:
            team_id = _record_id(record.get("team"))
            players = record.get("players")
            if (
                team_id not in expected_teams
                or not isinstance(players, list)
                or not players
                or any(
                    not isinstance(player, Mapping) or not _record_id(player)
                    for player in players
                )
            ):
                return False
            valid_teams.add(team_id)
        return valid_teams == expected_teams
    if family in {CaptureFamily.PLAYER_STATUS, CaptureFamily.INJURY}:
        return all(
            _record_id(record.get("team")) in expected_teams
            and isinstance(record.get("player"), Mapping)
            and bool(_record_id(record.get("player")))
            and bool(
                str(
                    cast(Mapping[str, object], record["player"]).get("type")
                    or cast(Mapping[str, object], record["player"]).get("status")
                    or ""
                ).strip()
            )
            for record in records
        )
    if family is CaptureFamily.LINEUP:
        team_ids: set[str] = set()
        for record in records:
            team_id = _record_id(record.get("team"))
            if (
                team_id not in expected_teams
                or team_id in team_ids
                or _valid_lineup_record(record) is None
            ):
                return False
            team_ids.add(team_id)
        return team_ids == expected_teams
    if family is CaptureFamily.FORMATION:
        team_ids = set()
        for record in records:
            team_id = _record_id(record.get("team"))
            formation = str(record.get("formation", "")).strip()
            if (
                team_id not in expected_teams
                or team_id in team_ids
                or not _formation_is_normalizable(formation)
            ):
                return False
            team_ids.add(team_id)
        return team_ids == expected_teams
    if family is CaptureFamily.ODDS:
        return len(records) == 1 and _odds_payload_has_supported_price(records)
    return False


def run_capture(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
    repository: ProspectiveR2Repository | None = None,
    provider: ApiFootballProvider | TheOddsApiProvider | None = None,
) -> dict[str, object]:
    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    command = str(args.command)
    families = {
        "capture-general": GENERAL_FAMILIES,
        "capture-player": PLAYER_FAMILIES,
        "capture-lineup": LINEUP_FAMILIES,
        "capture-odds": ODDS_FAMILIES,
    }[command]
    state = state or _database_state()
    _reject_non_durable_execution_inputs(args, state=state)
    provisional_due = _due_windows(
        state,
        families=families,
        now=now,
        maximum_attempts=args.max_attempts,
    )
    provider_free_noop = (
        not provisional_due
        and repository is None
        and args.object_store_root is None
    )
    if (
        repository is None
        and args.object_store_root is None
        and (args.estimate or provider_free_noop)
    ):
        _reconcile_receipt_attempts(state)
        recovery = {
            "captures": 0,
            "projection_inserts": 0,
            "attempts_reconstructed": 0,
            "budget_records": 0,
            "r2_recovered_objects": 0,
        }
    else:
        repository = repository or _repository(
            cache_root=args.object_store_root
        )
        recovery = _reconcile_r2_state(
            state=state,
            repository=repository,
            policy=policy,
        )
    due = _due_windows(
        state,
        families=families,
        now=now,
        maximum_attempts=args.max_attempts,
    )
    if command == "capture-odds":
        priority = {
            label: index for index, label in enumerate(ODDS_WINDOW_PRIORITY)
        }
        due = tuple(
            sorted(
                due,
                key=lambda window: (
                    priority.get(window.label, len(priority)),
                    window.cutoff_at,
                    window.window_id,
                ),
            )
        )
    fixture_by_id = {
        fixture.fixture_id: fixture for fixture in state.fixtures()
    }
    provider_kind, units = _capture_estimated_units(
        command,
        due,
        fixture_by_id,
    )
    due_by_competition: dict[str, tuple[CaptureWindow, ...]] = {}
    for window in due:
        fixture = fixture_by_id.get(window.fixture_id)
        if fixture is None:
            raise RuntimeError("CAPTURE_WINDOW_FIXTURE_MISSING")
        due_by_competition[fixture.competition] = (
            *due_by_competition.get(fixture.competition, ()),
            window,
        )
    units_by_competition: dict[str, int] = {}
    for competition, scoped_due in due_by_competition.items():
        if provider_kind is ProviderKind.ODDS_API:
            units_by_competition[competition] = 2
        else:
            _, scoped_units = _capture_estimated_units(
                command,
                scoped_due,
                fixture_by_id,
            )
            units_by_competition[competition] = max(scoped_units - 1, 0)
    if (
        provider_kind is ProviderKind.API_FOOTBALL
        and units_by_competition
    ):
        units_by_competition[sorted(units_by_competition)[0]] += 1
    if sum(units_by_competition.values()) != units:
        raise RuntimeError("PROSPECTIVE_PROVIDER_COMPETITION_COST_MISMATCH")
    budget_admissions: tuple[dict[str, object], ...] = ()
    if units:
        last_remaining = state.external_quota_remaining(
            provider_kind,
            now=now,
        )
        budget_admissions = _authorize_budget_plan(
            state,
            policy=policy,
            provider=provider_kind,
            units_by_competition=units_by_competition,
            provider_remaining=(
                last_remaining
                if last_remaining is not None
                else policy.provider_reserve(provider_kind) + units
            ),
            now=now,
        )
    estimate = _estimate(
        command=command,
        policy=policy,
        units=units,
        provider=provider_kind,
        windows_due=len(due),
        now=now,
        window_ids=tuple(window.window_id for window in due),
    )
    estimate.pop("estimate_sha256")
    estimate["budget_admissions"] = list(budget_admissions)
    estimate["estimate_sha256"] = canonical_sha256(estimate)
    report_prefix = CAPTURE_REPORT_NAMES[command]
    if args.estimate:
        _write_json(args.output / f"{report_prefix}-estimate.json", estimate)
        return estimate
    if not args.execute and args.cache is None:
        raise ValueError("CAPTURE_MODE_REQUIRED")
    if args.execute:
        verified = _verified_estimate(
            args.estimate_file,
            command=command,
            policy=policy,
        )
        if _int_value(
            verified["windows_due"],
            error="PROVIDER_ESTIMATE_WINDOWS_INVALID",
        ) != len(due):
            raise ValueError("PROVIDER_ESTIMATE_DUE_WINDOWS_CHANGED")
        if (
            verified.get("provider") != provider_kind.value
            or _int_value(
                verified["estimated_units"],
                error="PROVIDER_ESTIMATE_UNITS_INVALID",
            )
            != units
            or verified.get("window_ids_sha256")
            != canonical_sha256(sorted(window.window_id for window in due))
        ):
            raise ValueError("PROVIDER_ESTIMATE_SCOPE_CHANGED")
    if not due:
        snapshot = _base_snapshot(policy, now=now)
        cast(dict[str, object], snapshot["fixtures"]).update(
            {
                "tracked": len(state.fixtures()),
                "windows_planned": len(state.windows()),
                "windows_due": 0,
            }
        )
        report = _report(
            command=command,
            policy=policy,
            now=now,
            snapshot=snapshot,
            extra={
                "status": "NO_DUE_WINDOW_SUCCESS",
                "provider_calls": 0,
                "odds_api_credits": 0,
                "r2_puts": 0,
                "recovery_r2_puts": recovery.get(
                    "r2_recovered_objects",
                    0,
                ),
                "capture_attempts": 0,
                "attempts": 0,
                "retries": 0,
                "budget_admissions": [],
                "estimated_units_by_competition": {},
                "preflight_reconciliation": recovery,
            },
        )
        _write_json(args.output / f"{report_prefix}-report.json", report)
        return report
    if repository is None:
        raise RuntimeError("PROSPECTIVE_R2_REPOSITORY_REQUIRED")

    configured_cap = policy.run_cap(provider_kind)
    admission_cap = (
        configured_cap - policy.internal_safety_reserve(provider_kind)
        if provider_kind is ProviderKind.ODDS_API and args.execute
        else configured_cap
    )
    if units > admission_cap:
        raise BudgetExceeded(f"PROSPECTIVE_PROVIDER_CAP_EXCEEDED:{provider_kind.value}")
    cache: dict[str, object] | None = None
    provider_calls = 0
    provider_credits = 0
    provider_remaining = 0
    provider_reserve = 0
    odds_cost_contract_mismatch = False
    operation_key = f"{command}:{uuid.uuid4()}"
    prior_attempt_counts = Counter(
        attempt.window_id for attempt in state.attempts()
    )
    if args.cache is not None:
        cache = _mapping(_read_json(args.cache), error="CAPTURE_CACHE_INVALID")
    else:
        _reconcile_provider_call_guard_completions(
            state,
            repository,
            command=command,
            provider=provider_kind,
            windows=due,
            prior_attempt_counts=prior_attempt_counts,
        )
        _assert_no_unresolved_provider_call_guards(
            repository,
            command=command,
            provider=provider_kind,
            windows=due,
            prior_attempt_counts=prior_attempt_counts,
        )
        if provider_kind is ProviderKind.API_FOOTBALL:
            if provider is None:
                provider = ApiFootballProvider(
                    api_key=os.getenv("API_FOOTBALL_KEY"),
                    offline=False,
                    max_retries=0,
                )
            provider_reserve = policy.provider_reserve(
                ProviderKind.API_FOOTBALL
            )
            _assert_provider_transport_available(provider)
            _record_provider_units_before_call(
                state,
                repository,
                operation_key=operation_key,
                step="status",
                provider=ProviderKind.API_FOOTBALL,
                units=1,
                provider_remaining=0,
                provider_reserve=provider_reserve,
                recorded_at=now,
                code_revision=_code_revision(args.code_revision),
            )
            provider_calls = 1
            status = cast(ApiFootballProvider, provider).get_status()
            status_error = _provider_result_error(status)
            if status_error is not None:
                raise RuntimeError(
                    f"API_FOOTBALL_STATUS_FAILED:{status_error}"
                )
            remaining = _provider_quota_remaining(status)
            if remaining is None:
                raise RuntimeError("API_FOOTBALL_QUOTA_UNKNOWN_BEFORE_CAPTURE")
            provider_remaining = remaining
            BudgetLedger().authorize(
                ProviderKind.API_FOOTBALL,
                max(units - 1, 0),
                provider_remaining=provider_remaining,
                provider_reserve=provider_reserve,
            )
        else:
            if provider is None:
                provider = TheOddsApiProvider(
                    api_key=os.getenv("ODDS_API_KEY"),
                    offline=False,
                    max_retries=0,
                    circuit_failure_threshold=(
                        policy.circuit_breaker_failures(
                            ProviderKind.ODDS_API
                        )
                    ),
                    circuit_cooldown_seconds=(
                        policy.circuit_breaker_cooldown_seconds(
                            ProviderKind.ODDS_API
                        )
                    ),
                )
            near_kickoff = any(
                window.label == "NEAR_KICKOFF" for window in due
            )
            provider_reserve = policy.provider_reserve(
                ProviderKind.ODDS_API
            ) + (
                policy.near_kickoff_reserve()
                if near_kickoff
                else 0
            )
            _assert_provider_transport_available(provider)
            _record_provider_units_before_call(
                state,
                repository,
                operation_key=operation_key,
                step="quota-preflight",
                provider=ProviderKind.ODDS_API,
                units=0,
                provider_remaining=0,
                provider_reserve=provider_reserve,
                recorded_at=now,
                code_revision=_code_revision(args.code_revision),
            )
            preflight = cast(
                TheOddsApiProvider,
                provider,
            ).get_competitions()
            provider_calls = 1
            if (
                _provider_result_error(preflight) is not None
                or preflight.quota.remaining is None
            ):
                raise RuntimeError("ODDS_API_FRESH_QUOTA_PREFLIGHT_FAILED")
            provider_remaining = preflight.quota.remaining
            BudgetLedger().authorize(
                ProviderKind.ODDS_API,
                units,
                provider_remaining=preflight.quota.remaining,
                provider_reserve=provider_reserve,
                near_kickoff=near_kickoff,
            )

    odds_identities = (
        _fixture_identities(repository) if command == "capture-odds" else {}
    )
    attempts = 0
    captured = 0
    empty = 0
    invalid_payloads = 0
    objects_added = 0
    bytes_added = 0
    projection_inserts = 0
    skipped_after_kickoff = 0
    skipped_after_cutoff = 0
    provider_errors = 0
    identity_errors = 0
    retry_attempts = 0
    circuit_open = False
    seen_provider_requests: dict[
        tuple[str, str],
        tuple[ProviderResult, str, int, int],
    ] = {}
    provider_guard_keys_by_window: dict[str, list[str]] = {}
    freshness_errors: dict[str, tuple[str, AvailabilityStatus]] = {}
    freshness_call_pending: set[str] = set()
    if (
        cache is None
        and provider_kind is ProviderKind.API_FOOTBALL
        and command in {"capture-player", "capture-lineup"}
    ):
        if provider is None:
            raise RuntimeError("PROVIDER_ADAPTER_MISSING")
        for fixture_id in sorted({window.fixture_id for window in due}):
            fixture = fixture_by_id.get(fixture_id)
            if fixture is None:
                raise RuntimeError("CAPTURE_WINDOW_FIXTURE_MISSING")
            operation_now = (
                _utc_now()
                if args.execute and args.now is None
                else now
            )
            fixture_windows = tuple(
                window for window in due if window.fixture_id == fixture_id
            )
            if not any(
                window.opens_at <= operation_now < window.cutoff_at
                and operation_now < fixture.kickoff_at
                for window in fixture_windows
            ):
                # The batch may have crossed a cutoff after its initial due
                # selection. Never spend even the freshness call in that case;
                # the per-window loop below records the missed window.
                continue
            step = f"fixture-freshness:{canonical_sha256(fixture_id)}"
            request_scope = canonical_sha256(
                {"fixture_id": fixture_id, "kind": "freshness"}
            )
            expected_guard_keys = _provider_call_guard_keys(
                command=command,
                request_scope=request_scope,
                step=step,
                provider=ProviderKind.API_FOOTBALL,
                windows=fixture_windows,
                prior_attempt_counts=prior_attempt_counts,
            )
            completed_guards = _provider_call_guard_completions(repository)
            completed_receipts = {
                completed_guards[key]
                for key in expected_guard_keys.values()
                if key in completed_guards
            }
            if (
                expected_guard_keys
                and len(completed_receipts) == 1
                and all(
                    key in completed_guards
                    for key in expected_guard_keys.values()
                )
            ):
                receipt_hash = next(iter(completed_receipts))
                freshness_receipt = next(
                    (
                        receipt
                        for receipt in state.receipts()
                        if receipt.receipt_hash == receipt_hash
                        and receipt.window_id is None
                        and receipt.fixture_id == fixture_id
                        and receipt.family is CaptureFamily.FIXTURE
                        and receipt.source_endpoint == "/fixtures"
                    ),
                    None,
                )
                if freshness_receipt is None:
                    raise RuntimeError(
                        "R2_PROVIDER_CALL_COMPLETION_RECEIPT_MISSING"
                    )
                if freshness_receipt.quality_status is not AvailabilityStatus.CAPTURED:
                    freshness_errors[fixture_id] = (
                        (
                            "REGISTRY_STALE"
                            if freshness_receipt.quality_status
                            is AvailabilityStatus.IDENTITY_FAILED
                            else "FRESHNESS_REPLAY_NOT_CAPTURED"
                        ),
                        freshness_receipt.quality_status,
                    )
                continue
            if completed_receipts:
                raise RuntimeError(
                    "R2_PROVIDER_CALL_COMPLETION_SCOPE_INCOMPLETE"
                )
            freshness_guard_keys = _reserve_provider_call_guards(
                state,
                repository,
                command=command,
                request_scope=request_scope,
                step=step,
                provider=ProviderKind.API_FOOTBALL,
                windows=fixture_windows,
                prior_attempt_counts=prior_attempt_counts,
                provider_remaining=max(provider_remaining - 1, 0),
                provider_reserve=provider_reserve,
                recorded_at=operation_now,
                code_revision=_code_revision(args.code_revision),
                budget_scope=fixture.competition,
            )
            _record_provider_units_before_call(
                state,
                repository,
                operation_key=operation_key,
                step=step,
                provider=ProviderKind.API_FOOTBALL,
                units=1,
                provider_remaining=max(provider_remaining - 1, 0),
                provider_reserve=provider_reserve,
                recorded_at=operation_now,
                code_revision=_code_revision(args.code_revision),
                budget_scope=fixture.competition,
            )
            provider_calls += 1
            provider_remaining = max(provider_remaining - 1, 0)
            freshness = cast(ApiFootballProvider, provider).get_fixtures(
                fixture_id=int(fixture.provider_fixture_id)
            )
            error_code = _fixture_freshness_error(freshness, fixture)
            records = [
                dict(record)
                for record in freshness.records
                if isinstance(record.get("fixture"), Mapping)
                and str(
                    cast(
                        Mapping[str, object],
                        record["fixture"],
                    ).get("id")
                )
                == fixture.provider_fixture_id
            ]
            quality = (
                AvailabilityStatus.CAPTURED
                if error_code is None
                else (
                    AvailabilityStatus.IDENTITY_FAILED
                    if error_code == "REGISTRY_STALE"
                    else AvailabilityStatus.PROVIDER_UNAVAILABLE
                )
            )
            requested_at = freshness.requested_at or operation_now
            received_at = freshness.received_at or freshness.observed_at
            context = CaptureContext(
                window_id=None,
                window_label="REGISTRY",
                fixture_id=fixture.fixture_id,
                competition=fixture.competition,
                season=fixture.season,
                provider="api-football",
                family=CaptureFamily.FIXTURE,
                requested_at=requested_at,
                response_received_at=received_at,
                observed_at=max(received_at, operation_now),
                kickoff_at=fixture.kickoff_at,
                cutoff_at=fixture.kickoff_at - timedelta(microseconds=1),
                http_status=freshness.http_status or 200,
                source_endpoint="/fixtures",
                complete=error_code is None,
                quality_status=quality,
                provider_calls=1,
                code_revision=_code_revision(args.code_revision),
                materialized_at=operation_now,
            )
            capture_payload = _r2_capture_payload(
                result=freshness,
                normalized_records=records,
            )
            if error_code is None:
                capture_payload["fixture_contract"] = fixture.model_dump(
                    mode="json"
                )
            freshness_capture = repository.capture(
                payload=capture_payload,
                context=context,
            )
            _complete_provider_call_guards(
                state,
                repository,
                guard_keys=freshness_guard_keys.values(),
                receipt=freshness_capture.receipt,
                provider=ProviderKind.API_FOOTBALL,
                provider_remaining=provider_remaining,
                provider_reserve=provider_reserve,
            )
            if error_code is None:
                state.register_fixture(fixture, freshness_capture)
            else:
                state.persist_capture(freshness_capture)
                freshness_errors[fixture_id] = (error_code, quality)
                freshness_call_pending.add(fixture_id)
            objects_added += int(
                freshness_capture.payload_created
            ) + int(freshness_capture.receipt_created)
            bytes_added += freshness_capture.receipt.stored_bytes
    for window in due:
        operation_now = (
            _utc_now()
            if args.execute and cache is None and args.now is None
            else now
        )
        attempt_number = prior_attempt_counts[window.window_id] + 1
        fixture = fixture_by_id.get(window.fixture_id)
        if fixture is None:
            raise RuntimeError("CAPTURE_WINDOW_FIXTURE_MISSING")
        freshness_failure = freshness_errors.get(fixture.fixture_id)
        if freshness_failure is not None:
            error_code, failure_status = freshness_failure
            calls = int(fixture.fixture_id in freshness_call_pending)
            freshness_call_pending.discard(fixture.fixture_id)
            failure = CaptureAttempt(
                attempt_id=canonical_sha256(
                    {
                        "window_id": window.window_id,
                        "attempted_at": operation_now.isoformat(),
                        "error_code": error_code,
                        "attempt_number": attempt_number,
                    }
                ),
                idempotency_key=(
                    f"{window.window_id}:attempt:{attempt_number}:"
                    f"freshness-error:{error_code}"
                ),
                window_id=window.window_id,
                fixture_id=fixture.fixture_id,
                provider="api-football",
                family=window.family,
                attempted_at=operation_now,
                status=failure_status,
                retry_disposition=retry_disposition(
                    window=window,
                    now=operation_now,
                    attempts=attempt_number,
                    maximum_attempts=args.max_attempts,
                ),
                attempt_number=attempt_number,
                http_status=200,
                provider_calls=calls,
                provider_credits=0,
                error_code=error_code,
                code_revision=_code_revision(args.code_revision),
            )
            state.append_attempt(failure)
            attempts += 1
            retry_attempts += int(attempt_number > 1)
            identity_errors += int(
                error_code == "REGISTRY_STALE" and calls > 0
            )
            provider_errors += int(
                error_code != "REGISTRY_STALE" and calls > 0
            )
            continue
        if operation_now >= window.cutoff_at:
            missed = CaptureAttempt(
                attempt_id=canonical_sha256(
                    {
                        "window_id": window.window_id,
                        "attempted_at": operation_now.isoformat(),
                        "attempt_number": attempt_number,
                        "status": AvailabilityStatus.MISSED_WINDOW.value,
                    }
                ),
                idempotency_key=(
                    f"{window.window_id}:attempt:{attempt_number}:"
                    "missed-before-provider-call"
                ),
                window_id=window.window_id,
                fixture_id=fixture.fixture_id,
                provider=(
                    "the-odds-api"
                    if provider_kind is ProviderKind.ODDS_API
                    else "api-football"
                ),
                family=window.family,
                attempted_at=operation_now,
                status=AvailabilityStatus.MISSED_WINDOW,
                retry_disposition=RetryDisposition.LATE_RETRY,
                attempt_number=attempt_number,
                provider_calls=0,
                provider_credits=0,
                error_code="WINDOW_CUTOFF_PASSED_BEFORE_PROVIDER_CALL",
                code_revision=_code_revision(args.code_revision),
            )
            state.append_attempt(missed)
            attempts += 1
            retry_attempts += int(attempt_number > 1)
            skipped_after_cutoff += 1
            skipped_after_kickoff += int(operation_now >= fixture.kickoff_at)
            continue
        if operation_now >= fixture.kickoff_at:
            skipped_after_kickoff += 1
            continue
        endpoint = f"cache://{window.family.value.casefold()}"
        result: ProviderResult | None = None
        if cache is not None:
            payload = _payload_for_cache(cache, window=window)
            http_status = 200
            requested_at = operation_now
            received_at = operation_now
            calls = 0
            credits = 0
        else:
            request_key = _capture_request_key(
                command,
                window,
                fixture_by_id,
            )
            request_windows = tuple(
                candidate
                for candidate in due
                if _capture_request_key(
                    command,
                    candidate,
                    fixture_by_id,
                )
                == request_key
                and candidate.opens_at <= operation_now < candidate.cutoff_at
                and (
                    candidate_fixture := fixture_by_id.get(
                        candidate.fixture_id
                    )
                )
                is not None
                and operation_now < candidate_fixture.kickoff_at
            )
            cached_result = seen_provider_requests.get(request_key)
            if cached_result is None:
                if provider is None:
                    raise RuntimeError("PROVIDER_ADAPTER_MISSING")
                expected_request_credits = (
                    2 if provider_kind is ProviderKind.ODDS_API else 0
                )
                request_calls = 0
                request_credits = 0
                request_step = canonical_sha256(request_key)

                def record_before_provider_call(
                    step: str,
                    calls_to_record: int,
                    credits_to_record: int,
                ) -> None:
                    nonlocal provider_calls
                    nonlocal provider_credits
                    nonlocal provider_remaining
                    nonlocal request_calls
                    nonlocal request_credits
                    _assert_provider_transport_available(provider)
                    reserved_units = (
                        credits_to_record
                        if provider_kind is ProviderKind.ODDS_API
                        else calls_to_record
                    )
                    reserved_guards = _reserve_provider_call_guards(
                        state,
                        repository,
                        command=command,
                        request_scope=request_step,
                        step=step,
                        provider=provider_kind,
                        windows=request_windows,
                        prior_attempt_counts=prior_attempt_counts,
                        provider_remaining=(
                            provider_remaining - reserved_units
                        ),
                        provider_reserve=provider_reserve,
                        recorded_at=operation_now,
                        code_revision=_code_revision(
                            args.code_revision
                        ),
                        budget_scope=fixture.competition,
                    )
                    for guarded_window_id, guard_key in (
                        reserved_guards.items()
                    ):
                        provider_guard_keys_by_window.setdefault(
                            guarded_window_id,
                            [],
                        ).append(guard_key)
                    _record_provider_units_before_call(
                        state,
                        repository,
                        operation_key=operation_key,
                        step=(
                            f"{request_step}:{step}:"
                            f"{request_calls + calls_to_record}"
                        ),
                        provider=provider_kind,
                        units=reserved_units,
                        provider_remaining=(
                            provider_remaining - reserved_units
                        ),
                        provider_reserve=provider_reserve,
                        recorded_at=operation_now,
                        code_revision=_code_revision(
                            args.code_revision
                        ),
                        budget_scope=fixture.competition,
                    )
                    if provider_kind is ProviderKind.API_FOOTBALL:
                        provider_remaining = max(
                            provider_remaining - reserved_units,
                            0,
                        )
                    provider_calls += calls_to_record
                    provider_credits += credits_to_record
                    request_calls += calls_to_record
                    request_credits += credits_to_record

                try:
                    result, endpoint, contract_calls, contract_credits = (
                        _provider_capture(
                            command=command,
                            fixture=fixture,
                            family=window.family,
                            provider=provider,
                            odds_sport_key=(
                                policy.odds_sport_key(
                                    fixture.competition
                                )
                                if command == "capture-odds"
                                else None
                            ),
                            before_provider_call=(
                                record_before_provider_call
                            ),
                        )
                    )
                except CircuitOpenError:
                    circuit_open = True
                    break
                except (
                    MissingCredentialError,
                    RateLimitError,
                    TransientProviderError,
                ) as error:
                    error_code = type(error).__name__.upper()
                    endpoint = (
                        (
                            f"/sports/{policy.odds_sport_key(fixture.competition)}/odds"
                        )
                        if provider_kind is ProviderKind.ODDS_API
                        else (
                            "/players/squads"
                            if window.family is CaptureFamily.SQUAD
                            else "/provider-request"
                        )
                    )
                    result = ProviderResult(
                        provider=(
                            "the-odds-api"
                            if provider_kind is ProviderKind.ODDS_API
                            else "api-football"
                        ),
                        endpoint=endpoint,
                        availability=DataAvailability.ERROR,
                        observed_at=operation_now,
                        origin=DataOrigin.LIVE_SOURCE,
                        requested_at=operation_now,
                        received_at=operation_now,
                        message=error_code,
                    )
                else:
                    if (
                        contract_calls != request_calls
                        or contract_credits != request_credits
                    ):
                        raise RuntimeError(
                            "PROVIDER_CALL_COST_CONTRACT_MISMATCH"
                        )
                if command == "capture-general":
                    freshness_error = _fixture_freshness_error(
                        result,
                        fixture,
                    )
                    if freshness_error is not None:
                        result = result.model_copy(
                            update={
                                "availability": DataAvailability.ERROR,
                                "message": freshness_error,
                            }
                        )
                if provider_kind is ProviderKind.ODDS_API:
                    if (
                        result.quota.last_cost is None
                        or result.quota.remaining is None
                    ):
                        result = result.model_copy(
                            update={
                                "availability": DataAvailability.ERROR,
                                "message": "ODDS_QUOTA_HEADERS_MISSING",
                            }
                        )
                        request_credits = units
                    else:
                        actual_credits = result.quota.last_cost
                        actual_remaining = result.quota.remaining
                        if actual_credits > expected_request_credits:
                            _record_provider_units_before_call(
                                state,
                                repository,
                                operation_key=operation_key,
                                step=(
                                    f"{canonical_sha256(request_key)}:"
                                    "observed-cost-delta"
                                ),
                                provider=provider_kind,
                                units=(
                                    actual_credits
                                    - expected_request_credits
                                ),
                                provider_remaining=actual_remaining,
                                provider_reserve=provider_reserve,
                                recorded_at=operation_now,
                                code_revision=_code_revision(
                                    args.code_revision
                                ),
                                budget_scope=fixture.competition,
                            )
                        if actual_credits != request_credits:
                            odds_cost_contract_mismatch = True
                            result = result.model_copy(
                                update={
                                    "availability": DataAvailability.ERROR,
                                    "message": (
                                        "ODDS_ACTUAL_COST_CONTRACT_MISMATCH"
                                    ),
                                }
                            )
                        request_credits = actual_credits
                        provider_remaining = actual_remaining
                        provider_credits += (
                            actual_credits - expected_request_credits
                        )
                seen_provider_requests[request_key] = (
                    result,
                    endpoint,
                    request_calls,
                    request_credits,
                )
                calls = request_calls
                credits = request_credits
            else:
                result, endpoint, _, _ = cached_result
                calls = 0
                credits = 0
            http_status = result.http_status or 200
            requested_at = result.requested_at or operation_now
            received_at = result.received_at or result.observed_at
            provider_error_code = _provider_result_error(result)
            if provider_error_code is not None:
                failure = CaptureAttempt(
                    attempt_id=canonical_sha256(
                        {
                            "window_id": window.window_id,
                            "attempted_at": operation_now.isoformat(),
                            "error_code": provider_error_code,
                            "attempt_number": attempt_number,
                        }
                    ),
                    idempotency_key=(
                        f"{window.window_id}:attempt:{attempt_number}:"
                        f"provider-error:{provider_error_code}"
                    ),
                    window_id=window.window_id,
                    fixture_id=fixture.fixture_id,
                    provider=result.provider,
                    family=window.family,
                    attempted_at=operation_now,
                    status=AvailabilityStatus.PROVIDER_UNAVAILABLE,
                    retry_disposition=retry_disposition(
                        window=window,
                        now=operation_now,
                        attempts=attempt_number,
                        maximum_attempts=args.max_attempts,
                    ),
                    attempt_number=attempt_number,
                    http_status=result.http_status,
                    provider_calls=calls,
                    provider_credits=credits,
                    error_code=provider_error_code,
                    code_revision=_code_revision(args.code_revision),
                )
                state.append_attempt(failure)
                attempts += 1
                retry_attempts += int(attempt_number > 1)
                # One failed physical request may feed several family windows.
                # Report the provider failure once, while retaining one
                # durable attempt per affected family.
                provider_errors += int(bool(calls or credits))
                continue
            try:
                payload = _family_payload(
                    command=command,
                    family=window.family,
                    result=result,
                    fixture=fixture,
                    identities=odds_identities,
                )
            except OddsFixtureIdentityError as error:
                error_code = str(error)
                failure = CaptureAttempt(
                    attempt_id=canonical_sha256(
                        {
                            "window_id": window.window_id,
                                "attempted_at": operation_now.isoformat(),
                                "error_code": error_code,
                                "attempt_number": attempt_number,
                            }
                        ),
                        idempotency_key=(
                            f"{window.window_id}:attempt:{attempt_number}:"
                            f"identity-error:{error_code}"
                    ),
                    window_id=window.window_id,
                    fixture_id=fixture.fixture_id,
                    provider=result.provider,
                    family=window.family,
                        attempted_at=operation_now,
                        status=AvailabilityStatus.IDENTITY_FAILED,
                        retry_disposition=retry_disposition(
                            window=window,
                            now=operation_now,
                            attempts=attempt_number,
                            maximum_attempts=args.max_attempts,
                        ),
                        attempt_number=attempt_number,
                    http_status=result.http_status,
                    provider_calls=calls,
                    provider_credits=credits,
                    error_code=error_code,
                    code_revision=_code_revision(args.code_revision),
                )
                state.append_attempt(failure)
                attempts += 1
                retry_attempts += int(attempt_number > 1)
                identity_errors += 1
                continue
        if received_at >= window.cutoff_at:
            quality = AvailabilityStatus.TEMPORALITY_FAILED
        elif payload in ([], (), {}):
            quality = (
                AvailabilityStatus.CAPTURED_EMPTY
                if window.family
                in {
                    CaptureFamily.PLAYER_STATUS,
                    CaptureFamily.INJURY,
                    CaptureFamily.LINEUP,
                    CaptureFamily.FORMATION,
                }
                else AvailabilityStatus.INVALID_PAYLOAD
            )
        elif _capture_payload_complete(
            family=window.family,
            payload=payload,
            fixture=fixture,
        ):
            quality = AvailabilityStatus.CAPTURED
        else:
            quality = AvailabilityStatus.INVALID_PAYLOAD
        context = CaptureContext(
            window_id=window.window_id,
            window_label=window.label,
            fixture_id=fixture.fixture_id,
            competition=fixture.competition,
            season=fixture.season,
            provider=(
                "cache-test"
                if cache is not None
                else (
                    "the-odds-api"
                    if provider_kind is ProviderKind.ODDS_API
                    else "api-football"
                )
            ),
            family=window.family,
            requested_at=requested_at,
            response_received_at=received_at,
            observed_at=max(received_at, operation_now),
            kickoff_at=fixture.kickoff_at,
            cutoff_at=window.cutoff_at,
            http_status=http_status,
            source_endpoint=endpoint,
            complete=quality is AvailabilityStatus.CAPTURED,
            quality_status=quality,
            provider_calls=calls,
            code_revision=_code_revision(args.code_revision),
            materialized_at=operation_now,
        )
        capture_payload = _r2_capture_payload(
            result=result,
            normalized_records=payload,
            cache_payload=payload if cache is not None else None,
        )
        capture = repository.capture(payload=capture_payload, context=context)
        _complete_provider_call_guards(
            state,
            repository,
            guard_keys=provider_guard_keys_by_window.get(
                window.window_id,
                (),
            ),
            receipt=capture.receipt,
            provider=provider_kind,
            provider_remaining=provider_remaining,
            provider_reserve=provider_reserve,
        )
        state.persist_capture(capture)
        if quality is AvailabilityStatus.CAPTURED:
            projection = {
                "fixture_id": capture.receipt.fixture_id,
                "family": capture.receipt.family.value,
                "observed_at": capture.receipt.observed_at.isoformat(),
                "payload_sha256": capture.receipt.payload_sha256,
                "data": _normalized_capture_payload(capture.payload),
            }
            projection_hash = canonical_sha256(projection)
            projection_inserts += int(
                state.projection_sink().insert_capture(
                    capture.receipt,
                    projection,
                    projection_hash,
                )
            )
        attempt = CaptureAttempt(
            attempt_id=canonical_sha256(
                {
                    "window_id": window.window_id,
                    "attempted_at": now.isoformat(),
                    "attempt_number": attempt_number,
                }
            ),
            idempotency_key=(
                f"{window.window_id}:attempt:{attempt_number}:"
                f"{capture.receipt.payload_sha256}"
            ),
            window_id=window.window_id,
            fixture_id=fixture.fixture_id,
            provider=context.provider,
            family=window.family,
            attempted_at=requested_at,
            status=quality,
            retry_disposition=(
                RetryDisposition.NOT_REQUIRED
                if quality
                in {
                    AvailabilityStatus.CAPTURED,
                    AvailabilityStatus.CAPTURED_EMPTY,
                }
                else retry_disposition(
                    window=window,
                    now=received_at,
                    attempts=attempt_number,
                    maximum_attempts=args.max_attempts,
                )
            ),
            attempt_number=attempt_number,
            http_status=http_status,
            provider_calls=calls,
            provider_credits=credits,
            error_code=(
                "PAYLOAD_CONTRACT_INVALID"
                if quality is AvailabilityStatus.INVALID_PAYLOAD
                else None
            ),
            code_revision=context.code_revision,
        )
        state.append_attempt(attempt)
        attempts += 1
        retry_attempts += int(attempt_number > 1)
        captured += int(quality is AvailabilityStatus.CAPTURED)
        empty += int(quality is AvailabilityStatus.CAPTURED_EMPTY)
        invalid_payloads += int(quality is AvailabilityStatus.INVALID_PAYLOAD)
        objects_added += int(capture.payload_created) + int(capture.receipt_created)
        bytes_added += capture.receipt.stored_bytes

    if odds_cost_contract_mismatch:
        # The provider has already charged the request. Persist the observed
        # cost first, then fail closed so no payload can be admitted under a
        # stale pricing contract.
        raise RuntimeError("ODDS_ACTUAL_COST_CONTRACT_MISMATCH")
    snapshot = _base_snapshot(policy, now=now)
    cast(dict[str, object], snapshot["fixtures"]).update(
        {
            "tracked": len(state.fixtures()),
            "windows_planned": len(state.windows()),
            "windows_due": len(due),
        }
    )
    capture_snapshot = cast(dict[str, object], snapshot["captures"])
    capture_snapshot.update(
        {
            "attempted": attempts,
            "captured": captured,
            "empty": empty,
            "invalid": invalid_payloads,
            "bytes": bytes_added,
            "hashes": attempts,
        }
    )
    by_family = cast(dict[str, dict[str, int]], capture_snapshot["by_family"])
    for window in due:
        by_family[window.family.value]["due"] += 1
    for receipt in state.receipts():
        if receipt.window_id in {window.window_id for window in due}:
            family = by_family[receipt.family.value]
            family["attempted"] += 1
            family["captured"] += int(
                receipt.quality_status is AvailabilityStatus.CAPTURED
            )
            family["empty"] += int(
                receipt.quality_status is AvailabilityStatus.CAPTURED_EMPTY
            )
            family["invalid"] += int(
                receipt.quality_status is AvailabilityStatus.INVALID_PAYLOAD
            )
            family["bytes"] += receipt.stored_bytes
            family["hashes"] += 1
    current_receipts = [
        receipt
        for receipt in state.receipts()
        if receipt.window_id in {window.window_id for window in due}
    ]
    before_cutoff = sum(receipt.temporally_admissible for receipt in current_receipts)
    late = len(current_receipts) - before_cutoff
    cast(dict[str, object], snapshot["temporal"]).update(
        {
            "before_cutoff": before_cutoff,
            "late": late,
            "rejected": skipped_after_kickoff + late,
        }
    )
    cast(dict[str, object], snapshot["providers"]).update(
        {
            "api_football_calls": (
                provider_calls
                if provider_kind is ProviderKind.API_FOOTBALL
                else 0
            ),
            "odds_api_credits": provider_credits,
            "errors": provider_errors + identity_errors,
            "retries": retry_attempts,
        }
    )
    cast(dict[str, object], snapshot["r2"]).update(
        {
            "objects_added": objects_added,
            "bytes": bytes_added,
            "verified": objects_added,
        }
    )
    cast(dict[str, object], snapshot["postgresql"]).update(
        {"inserts": attempts + projection_inserts}
    )
    snapshot["status"] = (
        "CAPTURE_STOPPED_CIRCUIT_OPEN"
        if circuit_open
        else (
            "CAPTURE_WINDOWS_MISSED"
            if skipped_after_cutoff and not captured and not empty
            else (
                "CAPTURE_PARTIAL_PROVIDER_UNAVAILABLE"
                if provider_errors or identity_errors
                else (
                    "CAPTURE_PARTIAL_INVALID_PAYLOAD"
                    if invalid_payloads
                    else "CAPTURED_DUE_WINDOWS"
                )
            )
        )
    )
    report = _report(
        command=command,
        policy=policy,
        now=now,
        snapshot=snapshot,
        extra={
            "status": snapshot["status"],
            "provider_calls": provider_calls,
            "odds_api_credits": provider_credits,
            "attempts": attempts,
            "captured": captured,
            "captured_empty": empty,
            "invalid_payloads": invalid_payloads,
            "skipped_after_kickoff": skipped_after_kickoff,
            "skipped_after_cutoff": skipped_after_cutoff,
            "retries": retry_attempts,
            "provider_errors": provider_errors,
            "identity_errors": identity_errors,
            "circuit_open": circuit_open,
            "projection_inserts": projection_inserts,
            "budget_admissions": list(budget_admissions),
            "estimated_units_by_competition": units_by_competition,
            "preflight_reconciliation": recovery,
        },
    )
    _write_json(args.output / f"{report_prefix}-report.json", report)
    return report


def run_replay_audit(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
    repository: ProspectiveR2Repository | None = None,
) -> dict[str, object]:
    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    state = state or _database_state()
    _reject_non_durable_execution_inputs(args, state=state)
    repository = repository or _repository(cache_root=args.object_store_root)

    first_sink = InMemoryProjectionSink()
    first = replay_from_r2(
        repository,
        first_sink,
        normalizer=_operational_replay_projection,
    )
    second = replay_from_r2(
        repository,
        first_sink,
        normalizer=_operational_replay_projection,
    )
    if (
        first.dataset_hash != second.dataset_hash
        or second.projections_inserted != 0
        or second.duplicates_avoided != first.payloads_replayed
    ):
        raise RuntimeError("R2_REPLAY_NOT_IDEMPOTENT")
    stored_captures = tuple(repository.iter_captures())
    durable_sink = state.projection_sink()
    if isinstance(state, SQLAlchemyOperationalState):
        bootstrap = SQLAlchemyProjectionSink(state)
        bootstrap.bootstrap(
            stored_captures,
            tolerance=policy.operational_tolerance,
        )
        durable_sink = SQLAlchemyProjectionSink(
            state,
            skip_existing_projections=True,
        )
    durable = replay_from_r2(
        repository,
        durable_sink,
        normalizer=_operational_replay_projection,
    )
    attempts_reconstructed = _reconcile_receipt_attempts(state)
    budget_records = _reconcile_provider_budget_journal(
        state=state,
        repository=repository,
        captures=stored_captures,
    )
    _assert_r2_postgresql_capture_parity(
        state=state,
        captures=stored_captures,
    )
    receipt_fixture_ids = {
        capture.receipt.fixture_id for capture in stored_captures
    }
    reconstructed_fixture_ids = {fixture.fixture_id for fixture in state.fixtures()}
    reconstruction_complete = receipt_fixture_ids <= reconstructed_fixture_ids
    snapshot = _base_snapshot(policy, now=now)
    cast(dict[str, object], snapshot["fixtures"]).update(
        {"tracked": len(state.fixtures()), "windows_planned": len(state.windows())}
    )
    cast(dict[str, object], snapshot["r2"]).update(
        {
            "objects_added": first.physical_unique_objects,
            "verified": first.physical_unique_objects,
            "bytes": first.physical_unique_bytes,
            "recovery_objects": first.physical_recovery_objects,
            "recovery_bytes": first.physical_recovery_bytes,
            "replay_status": "R2_REPLAY_VERIFIED",
        }
    )
    cast(dict[str, object], snapshot["postgresql"]).update(
        {
            "inserts": durable.projections_inserted,
            # The public replay metric describes the proved idempotent pass,
            # independently of whether the durable sink needed reconstruction
            # during the first pass.
            "duplicates_avoided": second.duplicates_avoided,
            "reconstruction_status": (
                "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2"
                if reconstruction_complete
                else "RECONSTRUCTION_INCOMPLETE"
            ),
        }
    )
    snapshot["status"] = (
        "R2_REPLAY_VERIFIED"
        if reconstruction_complete
        else "R2_REPLAY_PARTIAL_FIXTURE_INDEX"
    )
    report = _report(
        command="replay-audit",
        policy=policy,
        now=now,
        snapshot=snapshot,
        extra={
            "status": snapshot["status"],
            "objects_examined": first.physical_unique_objects,
            "physical_unique_objects": first.physical_unique_objects,
            "physical_unique_bytes": first.physical_unique_bytes,
            "physical_payload_objects": first.physical_payload_objects,
            "physical_payload_bytes": first.physical_payload_bytes,
            "physical_receipt_objects": first.physical_receipt_objects,
            "physical_receipt_bytes": first.physical_receipt_bytes,
            "physical_recovery_objects": first.physical_recovery_objects,
            "physical_recovery_bytes": first.physical_recovery_bytes,
            "logical_references": first.logical_references,
            "logical_payload_bytes_read": (
                first.logical_payload_bytes_read
            ),
            "logical_receipt_bytes_read": (
                first.logical_receipt_bytes_read
            ),
            "logical_bytes_read": first.logical_bytes_read,
            "namespace_verified": first.namespace_verified,
            "selection_truncated": False,
            "complete_replay": True,
            "payloads_replayed": first.payloads_replayed,
            "dataset_hash": first.dataset_hash,
            "capture_set_sha256": _capture_set_sha256(
                capture.receipt for capture in stored_captures
            ),
            "capture_provenance": _capture_provenance(
                capture.receipt for capture in stored_captures
            ),
            "second_pass_inserts": second.projections_inserted,
            "second_pass_duplicates": second.duplicates_avoided,
            "provider_calls": 0,
            "odds_api_credits": 0,
            "hash_mismatches": first.hash_mismatches,
            "data_loss": first.data_loss,
            "fixtures_reconstructed": len(reconstructed_fixture_ids),
            "fixture_ids_expected": len(receipt_fixture_ids),
            "attempts_reconstructed": attempts_reconstructed,
            "budget_records_reconstructed": budget_records,
        },
    )
    _write_json(args.output / "r2-replay-audit.json", report)
    return report


def _aggregate_operational_snapshot(
    snapshot: dict[str, object],
    *,
    state: OperationalState,
    now: datetime,
) -> None:
    receipts = state.receipts()
    attempts = state.attempts()
    windows = _active_windows(state)
    completed_window_ids = {
        receipt.window_id
        for receipt in receipts
        if receipt.window_id is not None
        and receipt.quality_status
        in {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        }
    }
    missed_windows = {
        window.window_id
        for window in windows
        if window.window_id not in completed_window_ids
        and classify_window(window, now=now)
        is AvailabilityStatus.MISSED_WINDOW
    }
    captures = cast(dict[str, object], snapshot["captures"])
    by_family = cast(dict[str, dict[str, int]], captures["by_family"])
    for family in CaptureFamily:
        family_receipts = tuple(
            receipt for receipt in receipts if receipt.family is family
        )
        family_attempts = tuple(
            attempt for attempt in attempts if attempt.family is family
        )
        family_windows = tuple(
            window for window in windows if window.family is family
        )
        item = by_family[family.value]
        item.update(
            {
                "due": sum(
                    classify_window(window, now=now)
                    is AvailabilityStatus.DUE
                    for window in family_windows
                ),
                "attempted": len(family_attempts),
                "captured": sum(
                    receipt.quality_status is AvailabilityStatus.CAPTURED
                    for receipt in family_receipts
                ),
                "empty": sum(
                    receipt.quality_status
                    is AvailabilityStatus.CAPTURED_EMPTY
                    for receipt in family_receipts
                ),
                "missed": sum(
                    window.window_id in missed_windows
                    for window in family_windows
                ),
                "invalid": sum(
                    receipt.quality_status
                    in {
                        AvailabilityStatus.INVALID_PAYLOAD,
                        AvailabilityStatus.TEMPORALITY_FAILED,
                    }
                    for receipt in family_receipts
                ),
                "bytes": sum(receipt.stored_bytes for receipt in family_receipts),
                "hashes": len(family_receipts),
            }
        )
    captures.update(
        {
            "attempted": len(attempts),
            "captured": sum(
                receipt.quality_status is AvailabilityStatus.CAPTURED
                for receipt in receipts
            ),
            "empty": sum(
                receipt.quality_status is AvailabilityStatus.CAPTURED_EMPTY
                for receipt in receipts
            ),
            "missed": len(missed_windows),
            "invalid": sum(
                receipt.quality_status
                in {
                    AvailabilityStatus.INVALID_PAYLOAD,
                    AvailabilityStatus.TEMPORALITY_FAILED,
                }
                for receipt in receipts
            ),
            "bytes": sum(receipt.stored_bytes for receipt in receipts),
            "hashes": len(receipts),
        }
    )
    providers = cast(dict[str, object], snapshot["providers"])
    providers.update(
        {
            "api_football_calls": state.budget_used(
                ProviderKind.API_FOOTBALL
            ),
            "odds_api_credits": state.budget_used(ProviderKind.ODDS_API),
            "retries": sum(attempt.attempt_number > 1 for attempt in attempts),
            "errors": sum(
                attempt.status
                in {
                    AvailabilityStatus.PROVIDER_UNAVAILABLE,
                    AvailabilityStatus.IDENTITY_FAILED,
                    AvailabilityStatus.INVALID_PAYLOAD,
                }
                for attempt in attempts
            ),
            "used": {
                "api_football": state.budget_used(
                    ProviderKind.API_FOOTBALL
                ),
                "odds_api": state.budget_used(ProviderKind.ODDS_API),
            },
        }
    )
    payload_objects = {
        receipt.r2_key: receipt.stored_bytes for receipt in receipts
    }
    receipt_objects = {receipt.receipt_r2_key for receipt in receipts}
    cast(dict[str, object], snapshot["r2"]).update(
        {
            "objects_added": len(payload_objects) + len(receipt_objects),
            "bytes": sum(payload_objects.values()),
            "verified": len(payload_objects) + len(receipt_objects),
            "lag": 0,
        }
    )
    cast(dict[str, object], snapshot["postgresql"]).update(
        {"inserts": len(receipts) + len(attempts)}
    )


def run_gate_report(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
    repository: ProspectiveR2Repository | None = None,
) -> dict[str, object]:
    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    state = state or _database_state()
    if (
        repository is not None
        or (
            isinstance(state, SQLAlchemyOperationalState)
            and state.engine.dialect.name != "sqlite"
        )
        or getattr(args, "object_store_root", None) is not None
    ):
        repository = repository or _repository(
            cache_root=getattr(args, "object_store_root", None)
        )
        _reconcile_r2_state(
            state=state,
            repository=repository,
            policy=policy,
        )
    else:
        _reconcile_receipt_attempts(state)
    fixtures = state.fixtures()
    lifecycle_heads = state.fixture_lifecycle_heads()
    all_windows = state.windows()
    windows = _active_windows(state)
    receipts = state.receipts()
    identities = _fixture_identities(repository) if repository is not None else {}
    completed_window_ids = {
        receipt.window_id
        for receipt in receipts
        if receipt.window_id is not None
        and receipt.quality_status
        in {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        }
    }
    active_window_ids = {window.window_id for window in windows}
    observations = tuple(
        observation
        for observation in state.gate_observations()
        if observation.receipt.window_id in active_window_ids
    )
    evaluations = tuple(
        evaluation
        for fixture in fixtures
        for evaluation in evaluate_fixture_gates(
            fixture.fixture_id,
            observations,
        )
    )
    gate_inserts, gate_duplicates = state.append_gates_batch(
        evaluations,
        evaluated_at=now,
        code_revision=_code_revision(args.code_revision),
    )
    aggregates = aggregate_gate_evaluations(evaluations)
    ledger = build_observatory_ledger(
        fixtures=state.fixture_versions(),
        windows=all_windows,
        attempts=state.attempts(),
        receipts=receipts,
        gates=evaluations,
        frozen_at=now,
        code_revision=_code_revision(args.code_revision),
    )
    ledger_summary = observatory_ledger_summary(ledger)
    ledger_bytes = _ledger_jsonl_bytes(ledger)
    ledger_content_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    ledger_path = (
        args.output
        / f"public-evidence-ledger-v3-{ledger_content_sha256}.jsonl"
    )
    _write_immutable_bytes(ledger_path, ledger_bytes)
    ledger_summary.update(
        {
            "artifact": ledger_path.name,
            "artifact_sha256": ledger_content_sha256,
        }
    )
    snapshot = _base_snapshot(policy, now=now)
    _aggregate_operational_snapshot(snapshot, state=state, now=now)
    snapshot["ledger"] = ledger_summary
    due_windows = _due_windows(
        state,
        families=tuple(CaptureFamily),
        now=now,
    )
    cast(dict[str, object], snapshot["fixtures"]).update(
        {
            "tracked": len(fixtures),
            "windows_planned": len(windows),
            "windows_due": len(due_windows),
            "registry": [
                {
                    "fixture_id": fixture.fixture_id,
                    "canonical_key": fixture.fixture_id,
                    "provider": fixture.provider,
                    "provider_fixture_id": fixture.provider_fixture_id,
                    "home_team_id": fixture.home_team_id,
                    "away_team_id": fixture.away_team_id,
                    "home_name": (
                        identities[fixture.fixture_id][0]
                        if fixture.fixture_id in identities
                        else None
                    ),
                    "away_name": (
                        identities[fixture.fixture_id][1]
                        if fixture.fixture_id in identities
                        else None
                    ),
                    "competition": fixture.competition,
                    "season": fixture.season,
                    "phase": fixture.phase,
                    "kickoff_at": fixture.kickoff_at.isoformat(),
                    "registered_at": fixture.registered_at.isoformat(),
                    "status": "TOMBSTONED" if fixture.cancelled else "REGISTERED",
                    "cancelled": fixture.cancelled,
                    "lifecycle_version_hash": fixture.registry_hash,
                }
                for fixture in sorted(
                    lifecycle_heads,
                    key=lambda item: (item.kickoff_at, item.fixture_id),
                )
            ],
            "evidence": [
                {
                    "fixture_id": receipt.fixture_id,
                    "family": receipt.family.value,
                    "status": receipt.quality_status.value,
                    "observed_at": receipt.observed_at.isoformat(),
                    "response_received_at": receipt.response_received_at.isoformat(),
                    "window_id": receipt.window_id,
                    "temporally_admissible": receipt.temporally_admissible,
                }
                for receipt in sorted(
                    receipts,
                    key=lambda item: (
                        item.fixture_id,
                        item.observed_at,
                        item.family.value,
                    ),
                )
            ],
            "next": [
                {
                    "fixture_id": fixture.fixture_id,
                    "home": fixture.home_team_id,
                    "away": fixture.away_team_id,
                    "competition": fixture.competition,
                    "kickoff_at": fixture.kickoff_at.isoformat(),
                    "status": "REGISTERED",
                }
                for fixture in sorted(
                    (
                        item
                        for item in fixtures
                        if not item.cancelled and item.kickoff_at > now
                    ),
                    key=lambda item: item.kickoff_at,
                )[:20]
            ],
        }
    )
    windows_snapshot = snapshot.setdefault("windows", {})
    if not isinstance(windows_snapshot, dict):
        raise RuntimeError("PROSPECTIVE_WINDOWS_SNAPSHOT_INVALID")
    windows_snapshot.update(
        {
            "planned": len(windows),
            "due": len(due_windows),
            "inactive_legacy": len(all_windows) - len(windows),
            "registry": [
                {
                    "window_id": window.window_id,
                    "fixture_id": window.fixture_id,
                    "family": window.family.value,
                    "label": window.label,
                    "opens_at": window.opens_at.isoformat(),
                    "due_at": window.due_at.isoformat(),
                    "cutoff_at": window.cutoff_at.isoformat(),
                    "kickoff_at": window.kickoff_at.isoformat(),
                    "status": classify_window(
                        window,
                        now=now,
                        already_captured=window.window_id in completed_window_ids,
                    ).value,
                    "policy_version": window.policy_version,
                    "active": True,
                    "acknowledged": window.window_id in completed_window_ids,
                }
                for window in sorted(
                    windows,
                    key=lambda item: (
                        item.opens_at,
                        item.fixture_id,
                        item.family.value,
                    ),
                )
            ],
            "next": [
                {
                    "fixture_id": window.fixture_id,
                    "family": window.family.value,
                    "label": window.label,
                    "opens_at": window.opens_at.isoformat(),
                    "due_at": window.due_at.isoformat(),
                    "cutoff_at": window.cutoff_at.isoformat(),
                    "kickoff_at": window.kickoff_at.isoformat(),
                    "status": classify_window(window, now=now).value,
                }
                for window in sorted(
                    (item for item in windows if item.cutoff_at > now),
                    key=lambda item: item.due_at,
                )[:20]
            ],
        }
    )
    admissible = sum(receipt.temporally_admissible for receipt in receipts)
    cast(dict[str, object], snapshot["temporal"]).update(
        {
            "before_cutoff": admissible,
            "late": len(receipts) - admissible,
            "rejected": len(receipts) - admissible,
        }
    )
    by_name = cast(
        dict[str, dict[str, object]],
        cast(dict[str, object], snapshot["gates"])["by_name"],
    )
    for aggregate in aggregates:
        scoped = [item for item in evaluations if item.gate is aggregate.gate]
        reasons = sorted({item.reason for item in scoped})
        by_name[aggregate.gate.value] = {
            "status": aggregate.status.value,
            "passed": aggregate.passed,
            "total": aggregate.fixtures,
            "reason": ",".join(reasons) if reasons else "NO_FIXTURE",
        }
    cast(dict[str, object], snapshot["temporal"])["gates"] = len(evaluations)
    postgresql = cast(dict[str, object], snapshot["postgresql"])
    postgresql["inserts"] = _int_value(
        postgresql["inserts"],
        error="PROSPECTIVE_POSTGRES_INSERT_COUNT_INVALID",
    ) + gate_inserts
    snapshot["status"] = (
        "PROSPECTIVE_GATES_ACCUMULATING"
        if evaluations
        else "GATES_BLOCKED_BY_COVERAGE"
    )
    report = _report(
        command="gate-report",
        policy=policy,
        now=now,
        snapshot=snapshot,
        extra={
            "status": snapshot["status"],
            "fixtures": len(state.fixtures()),
            "active_windows": len(windows),
            "inactive_windows": len(all_windows) - len(windows),
            "receipts": len(receipts),
            "temporally_admissible": admissible,
            "gate_evaluations": len(evaluations),
            "gate_rows_inserted": gate_inserts,
            "gate_duplicates_avoided": gate_duplicates,
            "capture_set_sha256": _capture_set_sha256(receipts),
            "capture_provenance": _capture_provenance(receipts),
            "ledger_artifact": ledger_path.name,
            "ledger_sha256": ledger_content_sha256,
            "ledger_events": len(ledger.events),
            "provider_calls": 0,
            "odds_api_credits": 0,
            "decisions": 0,
            "stakes": 0,
        },
    )
    _write_json(args.output / "gate-report.json", report)
    return report


def run_next_due_report(
    args: argparse.Namespace,
    *,
    state: OperationalState | None = None,
) -> dict[str, object]:
    """Publish the next canonical window per fixture and family, provider-free."""

    now = _parse_utc(args.now)
    policy = ObservatoryPolicy.load(args.policy)
    state = state or _database_state()
    fixtures = {fixture.fixture_id: fixture for fixture in state.fixtures()}
    completed = {
        receipt.window_id
        for receipt in state.receipts()
        if receipt.window_id is not None
        and receipt.quality_status
        in {
            AvailabilityStatus.CAPTURED,
            AvailabilityStatus.CAPTURED_EMPTY,
            AvailabilityStatus.COMPLETE,
        }
    }
    workflow_by_family = {
        CaptureFamily.FIXTURE: "61 - Planificateur horaire Deep Data prospectif",
        CaptureFamily.TEAM: "61 - Planificateur horaire Deep Data prospectif",
        CaptureFamily.EVENT_STATUS: (
            "61 - Planificateur horaire Deep Data prospectif"
        ),
        CaptureFamily.SQUAD: (
            "62 - Capture blessures et joueurs prospective"
        ),
        CaptureFamily.PLAYER_STATUS: (
            "62 - Capture blessures et joueurs prospective"
        ),
        CaptureFamily.INJURY: (
            "62 - Capture blessures et joueurs prospective"
        ),
        CaptureFamily.LINEUP: (
            "63 - Capture lineups et formations prospective"
        ),
        CaptureFamily.FORMATION: (
            "63 - Capture lineups et formations prospective"
        ),
        CaptureFamily.ODDS: "64 - Capture cotes prospective",
    }
    max_cost_by_family: dict[CaptureFamily, dict[str, int]] = {
        CaptureFamily.FIXTURE: {"api_football_calls": 2},
        CaptureFamily.TEAM: {"api_football_calls": 2},
        CaptureFamily.EVENT_STATUS: {"api_football_calls": 2},
        CaptureFamily.SQUAD: {"api_football_calls": 4},
        CaptureFamily.PLAYER_STATUS: {"api_football_calls": 3},
        CaptureFamily.INJURY: {"api_football_calls": 3},
        CaptureFamily.LINEUP: {"api_football_calls": 3},
        CaptureFamily.FORMATION: {"api_football_calls": 3},
        CaptureFamily.ODDS: {
            "provider_http_calls": 2,
            "odds_api_credits": 2,
        },
    }
    next_by_scope: dict[
        tuple[str, CaptureFamily],
        CaptureWindow,
    ] = {}
    for window in _active_windows(state):
        if window.window_id in completed or window.cutoff_at <= now:
            continue
        key = (window.fixture_id, window.family)
        current = next_by_scope.get(key)
        if current is None or (
            window.opens_at,
            window.window_id,
        ) < (
            current.opens_at,
            current.window_id,
        ):
            next_by_scope[key] = window
    entries = [
        {
            "fixture_id": window.fixture_id,
            "kickoff_at": fixtures[window.fixture_id].kickoff_at.isoformat(),
            "family": family.value,
            "label": window.label,
            "opens_at": window.opens_at.isoformat(),
            "due_at": window.due_at.isoformat(),
            "cutoff_at": window.cutoff_at.isoformat(),
            "max_cost": max_cost_by_family[family],
            "workflow": workflow_by_family[family],
            "expected_state": classify_window(window, now=now).value,
        }
        for (fixture_id, family), window in sorted(
            next_by_scope.items(),
            key=lambda item: (
                item[1].opens_at,
                item[0][0],
                item[0][1].value,
            ),
        )
        if fixture_id in fixtures
    ]
    report: dict[str, object] = {
        "schema_version": "jalon12-next-due-windows-v1",
        "generated_at": now.isoformat(),
        "policy_version": cast(
            Mapping[str, object],
            policy.value["capture_windows"],
        )["policy_version"],
        "fixtures": len(fixtures),
        "active_windows": len(_active_windows(state)),
        "entries": entries,
        "provider_calls": 0,
        "odds_api_credits": 0,
        "capture_attempts": 0,
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
    }
    report["report_sha256"] = canonical_sha256(report)
    _write_json(args.report_path, report)
    return report


def run_pilot_mock(args: argparse.Namespace) -> dict[str, object]:
    now = _parse_utc(args.now)
    state = MemoryOperationalState()
    repository = _repository(cache_root=args.object_store_root)
    fixture_args = argparse.Namespace(**vars(args))
    fixture_args.command = "fixture-registry"
    fixture_args.estimate = False
    fixture_args.execute = False
    fixture_args.estimate_file = None
    fixture_args.competition = args.competition
    run_fixture_registry(fixture_args, state=state, repository=repository)
    scheduler_args = argparse.Namespace(**vars(args))
    scheduler_args.command = "scheduler"
    run_scheduler(scheduler_args, state=state)
    captures: list[dict[str, object]] = []
    for command in ("capture-player", "capture-lineup", "capture-odds"):
        capture_args = argparse.Namespace(**vars(args))
        capture_args.command = command
        capture_args.estimate = False
        capture_args.execute = False
        capture_args.estimate_file = None
        capture_args.max_attempts = 3
        captures.append(
            run_capture(
                capture_args,
                state=state,
                repository=repository,
            )
        )
    replay_args = argparse.Namespace(**vars(args))
    replay_args.command = "replay-audit"
    replay = run_replay_audit(replay_args, state=state, repository=repository)
    gate_args = argparse.Namespace(**vars(args))
    gate_args.command = "gate-report"
    gates = run_gate_report(
        gate_args,
        state=state,
        repository=repository,
    )
    policy = ObservatoryPolicy.load(args.policy)
    report = _report(
        command="pilot-mock",
        policy=policy,
        now=now,
        snapshot=cast(dict[str, object], gates["observatory"]),
        extra={
            "status": "MOCK_CACHE_PILOT_VERIFIED_NOT_LIVE",
            "publishable_as_live": False,
            "cache_sha256": canonical_sha256(_read_json(args.cache)),
            "capture_reports": [item["report_sha256"] for item in captures],
            "replay_report_sha256": replay["report_sha256"],
            "provider_calls": 0,
            "odds_api_credits": 0,
            "business_duplicates": 0,
            "deletions": 0,
        },
    )
    _write_json(args.output / "pilot-report.json", report)
    return report


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/prospective-observatory"),
    )
    parser.add_argument("--now")
    parser.add_argument("--code-revision")
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--object-store-root", type=Path)


def _estimate_execute(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--estimate", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--estimate-file", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    registry = commands.add_parser("fixture-registry")
    _common(registry)
    _estimate_execute(registry)
    registry.add_argument("--competition", default="Ligue 1")
    registry.add_argument("--max-attempts", type=int, default=1, choices=(1, 2, 3))

    scheduler = commands.add_parser("scheduler")
    _common(scheduler)

    for name in CAPTURE_REPORT_NAMES:
        capture = commands.add_parser(name)
        _common(capture)
        _estimate_execute(capture)
        capture.add_argument("--max-attempts", type=int, default=3, choices=(1, 2, 3))

    replay = commands.add_parser("replay-audit")
    _common(replay)

    gates = commands.add_parser("gate-report")
    _common(gates)

    next_due = commands.add_parser("next-due-report")
    _common(next_due)
    next_due.add_argument(
        "--report-path",
        type=Path,
        default=Path("reports/jalon12/next-due-windows.json"),
    )

    pilot = commands.add_parser("pilot-mock")
    _common(pilot)
    pilot.add_argument("--competition", default="Ligue 1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "execute", False) and getattr(args, "estimate_file", None) is None:
        raise ValueError("EXECUTION_REQUIRES_ESTIMATE_FILE")
    if args.command == "fixture-registry":
        result = run_fixture_registry(args)
    elif args.command == "scheduler":
        result = run_scheduler(args)
    elif args.command in CAPTURE_REPORT_NAMES:
        result = run_capture(args)
    elif args.command == "replay-audit":
        result = run_replay_audit(args)
    elif args.command == "gate-report":
        result = run_gate_report(args)
    elif args.command == "next-due-report":
        result = run_next_due_report(args)
    else:
        if args.cache is None or args.object_store_root is None:
            raise ValueError("PILOT_MOCK_REQUIRES_CACHE_AND_OBJECT_STORE_ROOT")
        result = run_pilot_mock(args)
    print(
        json.dumps(
            {
                "command": args.command,
                "status": result.get("status", "REPORT_WRITTEN"),
                "report_sha256": result.get("report_sha256"),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
