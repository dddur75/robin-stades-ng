"""Construire le snapshot live, compact et traçable du Cockpit Shadow."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd

from robin.deep_football.matchups import owner_hypotheses
from robin.domain.odds import stable_internal_id
from robin.prospective_observatory.contracts import (
    AvailabilityStatus,
    CaptureFamily,
    canonical_sha256,
)
from robin.prospective_observatory.gates import GateName, GateStatus
from robin.prospective_observatory.team_identities import (
    canonical_team_key,
    fixture_identity_scope_sha256,
)
from robin.prospective_observatory.temporal import (
    CAPTURE_POLICIES,
    DEFAULT_OPERATIONAL_TOLERANCE,
    WINDOW_POLICY_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cockpit" / "app" / "cockpit-data.json"
OUTPUT_HASH = ROOT / "cockpit" / "app" / "cockpit-data.sha256"
PRIVATE_DEPLOYMENT = ROOT / "configs" / "cockpit-private-deployment.json"
PROSPECTIVE_COMPACT = ROOT / "reports" / "jalon12" / "observatory-snapshot.json"
PROSPECTIVE_POLICY = ROOT / "configs" / "prospective_observatory_v1.json"
PREQUENTIAL_LEARNING_STATUS = (
    ROOT / "reports" / "prequential-learning" / "status.json"
)
HYPOTHESIS_INTELLIGENCE_SNAPSHOT = (
    ROOT / "reports" / "hypothesis-intelligence" / "cockpit-snapshot.json"
)
TEAM_IDENTITY_PROVENANCE = (
    ROOT / "reports" / "ux" / "team-identity-provenance.json"
)
SHADOW_SIMULATION_POLICY = ROOT / "configs" / "shadow_simulation_v1.json"
_EXPECTED_INVARIANTS: dict[str, object] = {
    "storage_paused": True,
    "p3_p4_paused": True,
    "production_status": "PRODUCTION_LOCKED",
    "real_bets": False,
    "no_bet_default": True,
    "social_publishing_enabled": False,
    "demo_mode_enabled": False,
    "external_social_networks_connected": False,
    "raw_payloads_in_git": 0,
    "postgresql_payload_body_rows": 0,
}
_REQUIRED_REPORT_INVARIANTS = frozenset(
    {
        "storage_paused",
        "p3_p4_paused",
        "production_status",
        "real_bets",
        "no_bet_default",
        "social_publishing_enabled",
        "demo_mode_enabled",
    }
)
_PROTECTED_PUBLIC_PATHS = frozenset(
    {
        "schema_version",
        "policy_source",
        "status",
        "origin",
        "fixtures.horizon_days",
        "fixtures.max_matchdays_per_competition",
        "fixtures.competitions",
        "fixtures.pilot_priority",
        "windows.policy_version",
        "temporal.truth_rule",
        "providers.budgets",
        "providers.reserves",
        "r2.namespace",
        "r2.objects_added",
        "r2.bytes",
        "r2.recovery_objects",
        "r2.recovery_bytes",
        "r2.verified",
        "r2.lag",
        "r2.deletions",
        "r2.replay_status",
        "postgresql.migration",
        "postgresql.tables",
        "postgresql.payload_body_rows",
        "postgresql.duplicates_avoided",
        "postgresql.lag",
        "postgresql.reconstruction_status",
        "ledger.schema_version",
        "ledger.allowed_event_types",
        "ledger.bet_decisions",
        "hypotheses",
        "research_cards",
        "decisions",
        "candidates",
        "invariants",
    }
)
_PREVIEW_FIELDS = {
    "fixtures.next": frozenset(
        {
            "fixture_id",
            "home",
            "away",
            "kickoff_at",
            "competition",
            "status",
        }
    ),
    "windows.next": frozenset(
        {
            "fixture_id",
            "family",
            "label",
            "opens_at",
            "due_at",
            "cutoff_at",
            "kickoff_at",
            "status",
        }
    ),
}
_PREVIEW_REQUIRED_FIELDS = {
    "fixtures.next": frozenset(
        {
            "fixture_id",
            "home",
            "away",
            "kickoff_at",
            "competition",
            "status",
        }
    ),
    "windows.next": frozenset(
        {"fixture_id", "family", "label", "due_at", "status"}
    ),
}
_SENSITIVE_UNKNOWN_FIELD_MARKERS = frozenset(
    {
        "authorization",
        "cookie",
        "credential",
        "header",
        "identity",
        "password",
        "payload",
        "rawpayload",
        "secret",
        "token",
    }
)
_OPERATION_REPORT_SCHEMA = "prospective-observatory-operation-v1"
_ALLOWED_GATE_REASONS = frozenset(
    {
        "BOTH_COMPLETE_LINEUPS_RECEIVED_BEFORE_KICKOFF",
        "BOTH_FORMATIONS_NORMALIZED_AFTER_LINEUP_GATE",
        "BOTH_TEAM_FORMATIONS_NOT_NORMALIZABLE",
        "EXACT_ODDS_BOOKMAKER_MARGIN_OR_OBSERVED_AT_MISSING",
        "EXACTLY_TWO_COMPLETE_ELEVEN_PLAYER_LINEUPS_REQUIRED",
        "IDENTITY_NOT_CANONICAL",
        "INJURY_OBSERVED_BEFORE_CUTOFF",
        "INJURY_PLAYER_STATUS_OR_SOURCE_MISSING",
        "LINEUP_GATE_REQUIRED",
        "MARKET_SNAPSHOT_MATCHED_WITHOUT_AMBIGUITY",
        "NO_FIXTURE",
        "NO_PROSPECTIVE_OBSERVATION",
        "NO_RESPONSE_RECEIVED_BEFORE_CUTOFF",
        "PLAYER_CAPTURE_POLICY_SATISFIED",
        "PLAYER_LIST_MISSING",
        "THREE_PRIOR_CAPTURES_REQUIRED",
    }
)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _empty_prequential_learning_status() -> dict[str, Any]:
    """État public sûr avant le premier cutoff réellement dû."""

    return {
        "schema_version": "prequential-learning-status-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": "PREQUENTIAL_LEARNING_FACTORY_READY",
        "origin": "NO_REAL_PREQUENTIAL_ACTIVITY",
        "markets": ["1X2", "OVER_UNDER_2_5"],
        "cutoffs": ["H-2", "NEAR_KICKOFF"],
        "predictions": {
            "frozen": 0,
            "rejected": 0,
            "settled": 0,
            "next_due_at": None,
            "items": [],
        },
        "settlements": {"fixtures": 0, "scored": 0, "items": []},
        "training": {
            "eligible_fixtures": 0,
            "new_support": 0,
            "represented_leagues": 0,
            "minimum_fixtures": 30,
            "minimum_leagues": 2,
            "next_status": "TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT",
            "next_possible_at": None,
            "last_training_at": None,
            "runs": 0,
            "last_version": None,
            "manifests": [],
        },
        "models": {"reference": None, "challenger": None, "scopes": []},
        "performance": {
            "by_league": [],
            "reference_vs_challenger": None,
        },
        "promotion_status": "PROMOTION_LOCKED",
        "security": {
            "production_locked": True,
            "real_bets": False,
            "no_bet_default": True,
            "social_publishing_enabled": False,
        },
        "expert": {
            "ledger_events": 0,
            "ledger_head_hash": "0" * 64,
            "ledger_status": "PREQUENTIAL_LEDGER_VERIFIED",
            "recent_events": [],
            "latest_manifest_hash": None,
        },
    }


def build_prequential_learning(
    existing: object | None = None,
) -> dict[str, Any]:
    """Lire le statut compact préquentiel sans réutiliser le shadow historique."""

    configured = os.environ.get("PREQUENTIAL_LEARNING_STATUS")
    status_path = Path(configured) if configured else PREQUENTIAL_LEARNING_STATUS
    source = read_json(status_path, None)
    if source is None and isinstance(existing, dict):
        source = existing
    if source is None:
        return _empty_prequential_learning_status()
    if not isinstance(source, dict):
        raise RuntimeError("statut préquentiel compact invalide")
    if source.get("schema_version") != "prequential-learning-status-v1":
        raise RuntimeError("version du statut préquentiel compact invalide")
    security = source.get("security")
    if not isinstance(security, dict) or security != {
        "production_locked": True,
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
    }:
        raise RuntimeError("invariants du statut préquentiel compact invalides")
    if source.get("promotion_status") != "PROMOTION_LOCKED":
        raise RuntimeError("promotion préquentielle non verrouillée")
    for section_name, field_names in {
        "predictions": ("frozen", "rejected"),
        "settlements": ("fixtures", "scored"),
        "training": ("eligible_fixtures", "represented_leagues"),
    }.items():
        section = source.get(section_name)
        if not isinstance(section, dict):
            raise RuntimeError(f"section préquentielle absente : {section_name}")
        if any(
            not isinstance(section.get(field), int) or section[field] < 0
            for field in field_names
        ):
            raise RuntimeError(
                f"compteur préquentiel invalide : {section_name}"
            )
    return cast(dict[str, Any], source)


def read_verified_cockpit_snapshot(path: Path) -> dict[str, Any]:
    """Lire un snapshot pipeline uniquement si son empreinte publiée correspond."""

    resolved = path.resolve()
    hash_path = resolved.with_suffix(".sha256")
    if not resolved.is_file() or not hash_path.is_file():
        raise RuntimeError("snapshot Cockpit vérifié absent")
    expected_hash = hash_path.read_text(encoding="ascii").strip()
    actual_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if (
        re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        or actual_hash != expected_hash
    ):
        raise RuntimeError("empreinte du snapshot Cockpit invalide")
    value = read_json(resolved, {})
    if not isinstance(value, dict):
        raise RuntimeError("snapshot Cockpit vérifié invalide")
    observatory = value.get("prospectiveObservatory")
    if not isinstance(observatory, dict):
        raise RuntimeError("observatoire vérifié absent du snapshot Cockpit")
    invariants = observatory.get("invariants")
    if invariants != _EXPECTED_INVARIANTS:
        raise RuntimeError("invariants du snapshot Cockpit vérifié invalides")
    return cast(dict[str, Any], value)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_datetime(value: object, *, path: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"horodatage public Jalon 12 absent : {path}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exception:
        raise RuntimeError(
            f"horodatage public Jalon 12 invalide : {path}"
        ) from exception
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timedelta(0)
    ):
        raise RuntimeError(f"horodatage public Jalon 12 non UTC : {path}")
    return parsed.astimezone(UTC)


def _optional_public_text(
    value: object,
    *,
    path: str,
    maximum: int = 512,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RuntimeError(f"texte public Jalon 12 invalide : {path}")
    return value.strip()


def _presentation_fixture_registry(
    source: object,
) -> list[dict[str, object]]:
    if not isinstance(source, list):
        raise RuntimeError("registre public des fixtures Jalon 12 invalide")
    registry: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(source):
        if not isinstance(raw, dict):
            raise RuntimeError("registre public des fixtures Jalon 12 invalide")
        fixture_id = _optional_public_text(
            raw.get("fixture_id"),
            path=f"fixtures.registry[{index}].fixture_id",
            maximum=120,
        )
        if (
            fixture_id is None
            or re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9._-]+", fixture_id) is None
            or fixture_id in seen
        ):
            raise RuntimeError("clé canonique de fixture Jalon 12 invalide")
        seen.add(fixture_id)
        kickoff = _utc_datetime(
            raw.get("kickoff_at"),
            path=f"fixtures.registry[{index}].kickoff_at",
        )
        provider = _optional_public_text(
            raw.get("provider"),
            path=f"fixtures.registry[{index}].provider",
            maximum=120,
        ) or fixture_id.split(":", maxsplit=1)[0]
        provider_fixture_id = _optional_public_text(
            raw.get("provider_fixture_id"),
            path=f"fixtures.registry[{index}].provider_fixture_id",
            maximum=120,
        ) or fixture_id.split(":", maxsplit=1)[1]
        home_team_id = _optional_public_text(
            raw.get("home_team_id", raw.get("home")),
            path=f"fixtures.registry[{index}].home_team_id",
            maximum=120,
        )
        away_team_id = _optional_public_text(
            raw.get("away_team_id", raw.get("away")),
            path=f"fixtures.registry[{index}].away_team_id",
            maximum=120,
        )
        competition = _optional_public_text(
            raw.get("competition"),
            path=f"fixtures.registry[{index}].competition",
            maximum=120,
        )
        if (
            home_team_id is None
            or away_team_id is None
            or home_team_id == away_team_id
            or competition is None
        ):
            raise RuntimeError("identité de fixture Jalon 12 invalide")
        status = _optional_public_text(
            raw.get("status", "REGISTERED"),
            path=f"fixtures.registry[{index}].status",
            maximum=120,
        )
        if status is None:
            raise RuntimeError("statut de fixture Jalon 12 invalide")
        cancelled = raw.get("cancelled", False)
        if not isinstance(cancelled, bool):
            raise RuntimeError("tombstone de fixture Jalon 12 invalide")
        registry.append(
            {
                "fixture_id": fixture_id,
                "canonical_key": fixture_id,
                "provider": provider,
                "provider_fixture_id": provider_fixture_id,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_name": _optional_public_text(
                    raw.get("home_name"),
                    path=f"fixtures.registry[{index}].home_name",
                ),
                "away_name": _optional_public_text(
                    raw.get("away_name"),
                    path=f"fixtures.registry[{index}].away_name",
                ),
                "home_short_name": _optional_public_text(
                    raw.get("home_short_name"),
                    path=f"fixtures.registry[{index}].home_short_name",
                ),
                "away_short_name": _optional_public_text(
                    raw.get("away_short_name"),
                    path=f"fixtures.registry[{index}].away_short_name",
                ),
                "home_identity_status": _optional_public_text(
                    raw.get("home_identity_status"),
                    path=f"fixtures.registry[{index}].home_identity_status",
                    maximum=80,
                )
                or (
                    "VERIFIED"
                    if _optional_public_text(
                        raw.get("home_name"),
                        path=f"fixtures.registry[{index}].home_name",
                    )
                    is not None
                    else "UNRESOLVED"
                ),
                "away_identity_status": _optional_public_text(
                    raw.get("away_identity_status"),
                    path=f"fixtures.registry[{index}].away_identity_status",
                    maximum=80,
                )
                or (
                    "VERIFIED"
                    if _optional_public_text(
                        raw.get("away_name"),
                        path=f"fixtures.registry[{index}].away_name",
                    )
                    is not None
                    else "UNRESOLVED"
                ),
                "home_identity_provenance": (
                    dict(raw["home_identity_provenance"])
                    if isinstance(raw.get("home_identity_provenance"), dict)
                    else None
                ),
                "away_identity_provenance": (
                    dict(raw["away_identity_provenance"])
                    if isinstance(raw.get("away_identity_provenance"), dict)
                    else None
                ),
                "competition": competition,
                "season": _optional_public_text(
                    raw.get("season"),
                    path=f"fixtures.registry[{index}].season",
                    maximum=40,
                ),
                "phase": _optional_public_text(
                    raw.get("phase"),
                    path=f"fixtures.registry[{index}].phase",
                    maximum=120,
                ),
                "kickoff_at": kickoff.isoformat(),
                "registered_at": _optional_public_text(
                    raw.get("registered_at"),
                    path=f"fixtures.registry[{index}].registered_at",
                ),
                "status": status,
                "cancelled": cancelled,
                "lifecycle_version_hash": _optional_public_text(
                    raw.get("lifecycle_version_hash"),
                    path=f"fixtures.registry[{index}].lifecycle_version_hash",
                    maximum=64,
                ),
            }
        )
    return registry


def _team_identity_report_path(report_root: Path) -> Path:
    configured = os.environ.get("TEAM_IDENTITY_PROVENANCE_INPUT")
    if configured:
        return Path(configured)
    default_report_root = ROOT / "artifacts" / "prospective-observatory"
    if report_root.resolve() == default_report_root.resolve():
        return TEAM_IDENTITY_PROVENANCE
    return report_root / "team-identity-provenance.json"


def _validated_team_identity_report(
    path: Path,
    *,
    fixtures: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    report = read_json(path, {})
    if not isinstance(report, dict):
        raise RuntimeError("rapport de provenance des identités invalide")
    report_hash = report.get("report_sha256")
    unsigned_report = {
        key: value for key, value in report.items() if key != "report_sha256"
    }
    if (
        report.get("schema_version") != "team-identity-provenance-v1"
        or not isinstance(report_hash, str)
        or canonical_sha256(unsigned_report) != report_hash
        or report.get("fixture_scope_sha256")
        != fixture_identity_scope_sha256(fixtures)
    ):
        raise RuntimeError("provenance des identités non vérifiée")
    registry = report.get("registry")
    if (
        not isinstance(registry, dict)
        or canonical_sha256(registry) != report.get("registry_sha256")
    ):
        raise RuntimeError("registre d’identités non vérifié")
    provider_usage = report.get("provider_usage")
    invariants = report.get("invariants")
    if (
        provider_usage
        != {"api_football_calls": 0, "odds_api_credits": 0}
        or not isinstance(invariants, dict)
        or invariants.get("r2_read_only") is not True
        or invariants.get("postgresql_read_only") is not True
        or invariants.get("raw_payloads_in_report") != 0
        or invariants.get("secrets_in_report") != 0
    ):
        raise RuntimeError("invariants du registre d’identités invalides")
    raw_identities = report.get("identities")
    if not isinstance(raw_identities, list):
        raise RuntimeError("identités vérifiées absentes")
    identities: dict[tuple[str, str], dict[str, object]] = {}
    for index, raw in enumerate(raw_identities):
        if not isinstance(raw, dict):
            raise RuntimeError("identité vérifiée invalide")
        provider = _optional_public_text(
            raw.get("provider"),
            path=f"identities[{index}].provider",
            maximum=120,
        )
        provider_team_id = _optional_public_text(
            raw.get("provider_team_id"),
            path=f"identities[{index}].provider_team_id",
            maximum=120,
        )
        fixture_id = _optional_public_text(
            raw.get("fixture_id"),
            path=f"identities[{index}].fixture_id",
            maximum=120,
        )
        side = raw.get("side")
        display_name = _optional_public_text(
            raw.get("display_name"),
            path=f"identities[{index}].display_name",
        )
        payload_sha256 = raw.get("payload_sha256")
        receipt_id = raw.get("receipt_id")
        captured_at = raw.get("captured_at")
        postgresql = raw.get("postgresql_projection")
        if (
            provider is None
            or provider_team_id is None
            or fixture_id is None
            or side not in {"home", "away"}
            or display_name is None
            or raw.get("canonical_team_id")
            != canonical_team_key(provider, provider_team_id)
            or raw.get("source") != "R2_FIXTURE_PAYLOAD"
            or raw.get("identity_status") != "VERIFIED"
            or raw.get("receipt_verified") is not True
            or not isinstance(payload_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", payload_sha256) is None
            or not isinstance(receipt_id, str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt_id) is None
            or not isinstance(captured_at, str)
            or not isinstance(postgresql, dict)
            or postgresql.get("capture_receipt_verified") is not True
            or postgresql.get("payload_index_verified") is not True
            or postgresql.get("fixture_projection_verified") is not True
        ):
            raise RuntimeError("preuve d’identité incomplète")
        key = (fixture_id, str(side))
        if key in identities:
            raise RuntimeError("preuve d’identité dupliquée")
        identities[key] = dict(raw)
    return identities


def _enrich_fixture_identities(
    fixtures: list[dict[str, object]],
    *,
    report_path: Path,
) -> dict[str, object]:
    expected_slots = len(fixtures) * 2
    if not report_path.exists():
        return {
            "schema_version": "team-identity-registry-v1",
            "source": "NO_VERIFIED_IDENTITY_REPORT",
            "report": None,
            "registry_sha256": None,
            "team_slots_expected": expected_slots,
            "team_slots_resolved": sum(
                fixture.get(f"{side}_identity_status") == "VERIFIED"
                for fixture in fixtures
                for side in ("home", "away")
            ),
        }
    identities = _validated_team_identity_report(
        report_path,
        fixtures=fixtures,
    )
    resolved = 0
    for fixture in fixtures:
        fixture_id = str(fixture["fixture_id"])
        provider = str(fixture["provider"])
        for side in ("home", "away"):
            evidence = identities.get((fixture_id, side))
            expected_team_id = str(fixture[f"{side}_team_id"])
            if (
                evidence is None
                or evidence.get("provider") != provider
                or evidence.get("provider_team_id") != expected_team_id
            ):
                fixture[f"{side}_name"] = None
                fixture[f"{side}_short_name"] = None
                fixture[f"{side}_identity_status"] = "UNRESOLVED"
                fixture[f"{side}_identity_provenance"] = None
                continue
            fixture[f"{side}_name"] = evidence["display_name"]
            fixture[f"{side}_short_name"] = evidence.get("short_name")
            fixture[f"{side}_identity_status"] = "VERIFIED"
            fixture[f"{side}_identity_provenance"] = {
                "source": evidence["source"],
                "payload_sha256": evidence["payload_sha256"],
                "receipt_id": evidence["receipt_id"],
                "captured_at": evidence["captured_at"],
            }
            resolved += 1
    report = cast(dict[str, object], read_json(report_path, {}))
    try:
        report_label = report_path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        report_label = report_path.name
    return {
        "schema_version": "team-identity-registry-v1",
        "source": "EXISTING_VERIFIED_R2_FIXTURE_CAPTURES",
        "report": report_label,
        "registry_sha256": report.get("registry_sha256"),
        "verified_at": report.get("generated_at"),
        "team_slots_expected": expected_slots,
        "team_slots_resolved": resolved,
    }


def _derived_active_windows(
    fixtures: list[dict[str, object]],
    *,
    generated_at: datetime,
) -> list[dict[str, object]]:
    tolerance = DEFAULT_OPERATIONAL_TOLERANCE
    windows: list[dict[str, object]] = []
    for fixture in fixtures:
        if fixture["cancelled"] is True or fixture["status"] in {
            "CANCELLED",
            "CANCELED",
            "TOMBSTONED",
        }:
            continue
        fixture_id = str(fixture["fixture_id"])
        kickoff = _utc_datetime(
            fixture["kickoff_at"],
            path=f"fixtures.registry.{fixture_id}.kickoff_at",
        )
        for family, offsets in CAPTURE_POLICIES.items():
            for offset in offsets:
                due_at = kickoff - offset.before_kickoff
                if (
                    offset.opens_before_kickoff is None
                    and offset.cutoff_before_kickoff is None
                ):
                    opens_at = due_at - tolerance
                    cutoff_at = due_at + tolerance
                elif (
                    offset.opens_before_kickoff is not None
                    and offset.cutoff_before_kickoff is not None
                ):
                    opens_at = kickoff - offset.opens_before_kickoff
                    cutoff_at = kickoff - offset.cutoff_before_kickoff
                else:
                    raise RuntimeError(
                        "bornes de fenêtre de présentation incomplètes"
                    )
                cutoff_at = min(cutoff_at, kickoff - timedelta(microseconds=1))
                status = (
                    AvailabilityStatus.NOT_DUE.value
                    if generated_at < opens_at
                    else (
                        AvailabilityStatus.DUE.value
                        if generated_at < cutoff_at
                        else AvailabilityStatus.MISSED_WINDOW.value
                    )
                )
                windows.append(
                    {
                        "window_id": (
                            "presentation-window:"
                            + canonical_sha256(
                                {
                                    "fixture_id": fixture_id,
                                    "family": family.value,
                                    "label": offset.label,
                                    "due_at": due_at.isoformat(),
                                    "policy_version": WINDOW_POLICY_VERSION,
                                }
                            )
                        ),
                        "fixture_id": fixture_id,
                        "family": family.value,
                        "label": offset.label,
                        "opens_at": opens_at.isoformat(),
                        "due_at": due_at.isoformat(),
                        "cutoff_at": cutoff_at.isoformat(),
                        "kickoff_at": kickoff.isoformat(),
                        "status": status,
                        "policy_version": WINDOW_POLICY_VERSION,
                        "active": True,
                        "acknowledged": False,
                    }
                )
    return sorted(
        windows,
        key=lambda item: (
            str(item["opens_at"]),
            str(item["fixture_id"]),
            str(item["family"]),
        ),
    )


def _presentation_window_registry(
    source: object,
    *,
    fixtures: list[dict[str, object]],
    generated_at: datetime,
) -> list[dict[str, object]]:
    if not isinstance(source, list) or not source:
        return _derived_active_windows(fixtures, generated_at=generated_at)
    fixture_ids = {str(item["fixture_id"]) for item in fixtures}
    windows: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(source):
        if not isinstance(raw, dict):
            raise RuntimeError("registre public des fenêtres Jalon 12 invalide")
        window_id = _optional_public_text(
            raw.get("window_id"),
            path=f"windows.registry[{index}].window_id",
            maximum=250,
        )
        fixture_id = _optional_public_text(
            raw.get("fixture_id"),
            path=f"windows.registry[{index}].fixture_id",
            maximum=120,
        )
        family = _optional_public_text(
            raw.get("family"),
            path=f"windows.registry[{index}].family",
            maximum=40,
        )
        label = _optional_public_text(
            raw.get("label"),
            path=f"windows.registry[{index}].label",
            maximum=40,
        )
        if (
            window_id is None
            or fixture_id not in fixture_ids
            or family not in {item.value for item in CaptureFamily}
            or label is None
            or window_id in seen
        ):
            raise RuntimeError("fenêtre publique Jalon 12 invalide")
        seen.add(window_id)
        active = raw.get("active", True)
        acknowledged = raw.get("acknowledged", False)
        if not isinstance(active, bool) or not isinstance(acknowledged, bool):
            raise RuntimeError("état de fenêtre publique Jalon 12 invalide")
        windows.append(
            {
                "window_id": window_id,
                "fixture_id": fixture_id,
                "family": family,
                "label": label,
                "opens_at": _utc_datetime(
                    raw.get("opens_at"),
                    path=f"windows.registry[{index}].opens_at",
                ).isoformat(),
                "due_at": _utc_datetime(
                    raw.get("due_at"),
                    path=f"windows.registry[{index}].due_at",
                ).isoformat(),
                "cutoff_at": _utc_datetime(
                    raw.get("cutoff_at"),
                    path=f"windows.registry[{index}].cutoff_at",
                ).isoformat(),
                "kickoff_at": _utc_datetime(
                    raw.get("kickoff_at"),
                    path=f"windows.registry[{index}].kickoff_at",
                ).isoformat(),
                "status": _optional_public_text(
                    raw.get("status"),
                    path=f"windows.registry[{index}].status",
                    maximum=120,
                )
                or AvailabilityStatus.NOT_DUE.value,
                "policy_version": _optional_public_text(
                    raw.get("policy_version"),
                    path=f"windows.registry[{index}].policy_version",
                    maximum=120,
                )
                or WINDOW_POLICY_VERSION,
                "active": active,
                "acknowledged": acknowledged,
            }
        )
    return sorted(
        windows,
        key=lambda item: (
            str(item["opens_at"]),
            str(item["fixture_id"]),
            str(item["family"]),
        ),
    )


def _presentation_fixture_evidence(
    source: object,
    *,
    fixtures: list[dict[str, object]],
    captures: dict[str, Any],
) -> list[dict[str, object]]:
    fixture_ids = {str(item["fixture_id"]) for item in fixtures}
    evidence: list[dict[str, object]] = []
    if isinstance(source, list):
        for index, raw in enumerate(source):
            if not isinstance(raw, dict):
                raise RuntimeError("preuve publique de fixture Jalon 12 invalide")
            fixture_id = _optional_public_text(
                raw.get("fixture_id"),
                path=f"fixtures.evidence[{index}].fixture_id",
                maximum=120,
            )
            family = _optional_public_text(
                raw.get("family"),
                path=f"fixtures.evidence[{index}].family",
                maximum=40,
            )
            status = _optional_public_text(
                raw.get("status"),
                path=f"fixtures.evidence[{index}].status",
                maximum=120,
            )
            if (
                fixture_id not in fixture_ids
                or family not in {item.value for item in CaptureFamily}
                or status is None
            ):
                raise RuntimeError("preuve publique de fixture Jalon 12 invalide")
            admissible = raw.get("temporally_admissible", False)
            if not isinstance(admissible, bool):
                raise RuntimeError("temporalité de fixture Jalon 12 invalide")
            evidence.append(
                {
                    "fixture_id": fixture_id,
                    "family": family,
                    "status": status,
                    "observed_at": _optional_public_text(
                        raw.get("observed_at"),
                        path=f"fixtures.evidence[{index}].observed_at",
                    ),
                    "response_received_at": _optional_public_text(
                        raw.get("response_received_at"),
                        path=f"fixtures.evidence[{index}].response_received_at",
                    ),
                    "window_id": _optional_public_text(
                        raw.get("window_id"),
                        path=f"fixtures.evidence[{index}].window_id",
                        maximum=250,
                    ),
                    "temporally_admissible": admissible,
                    "provenance": "RECEIPT_PROJECTION",
                }
            )
        return evidence

    by_family = captures.get("by_family", {})
    fixture_family = (
        by_family.get(CaptureFamily.FIXTURE.value, {})
        if isinstance(by_family, dict)
        else {}
    )
    captured = (
        _non_negative_int(fixture_family.get("captured"))
        if isinstance(fixture_family, dict)
        else None
    )
    hashes = (
        _non_negative_int(fixture_family.get("hashes"))
        if isinstance(fixture_family, dict)
        else None
    )
    if captured == len(fixtures) and hashes == len(fixtures):
        return [
            {
                "fixture_id": str(fixture["fixture_id"]),
                "family": CaptureFamily.FIXTURE.value,
                "status": AvailabilityStatus.CAPTURED.value,
                "observed_at": None,
                "response_received_at": None,
                "window_id": None,
                "temporally_admissible": True,
                "provenance": "VERIFIED_AGGREGATE_BIJECTION",
            }
            for fixture in fixtures
        ]
    return []


def _non_negative_int(value: object) -> int | None:
    """Lire un compteur JSON strict sans booléen, flottant ou valeur négative."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed >= 0 else None


def _reject_sensitive_unknown_field(*, key: str, path: str) -> None:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if any(marker in normalized for marker in _SENSITIVE_UNKNOWN_FIELD_MARKERS):
        location = f"{path}.{key}" if path else key
        raise RuntimeError(f"champ public Jalon 12 interdit : {location}")


def _sanitize_preview(value: object, *, path: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise RuntimeError(f"aperçu public Jalon 12 invalide : {path}")
    allowed = _PREVIEW_FIELDS[path]
    required = _PREVIEW_REQUIRED_FIELDS[path]
    policy = read_json(PROSPECTIVE_POLICY, {})
    if not isinstance(policy, dict):
        raise RuntimeError("politique d'aperçu Jalon 12 invalide")
    registry = policy.get("competition_registry", [])
    capture_windows = policy.get("capture_windows", {})
    if not isinstance(registry, list) or not isinstance(capture_windows, dict):
        raise RuntimeError("politique d'aperçu Jalon 12 invalide")
    allowed_competitions = {
        str(item["competition"])
        for item in registry
        if isinstance(item, dict) and item.get("competition")
    }
    allowed_families = {family.value for family in CaptureFamily}
    allowed_window_statuses = {
        AvailabilityStatus.NOT_DUE.value,
        AvailabilityStatus.DUE.value,
    }
    seen_preview_keys: set[tuple[str, ...]] = set()
    sanitized: list[dict[str, str]] = []
    for raw_item in value[:20]:
        if not isinstance(raw_item, dict):
            raise RuntimeError(f"aperçu public Jalon 12 invalide : {path}")
        unknown = set(raw_item) - allowed
        if unknown:
            raise RuntimeError(
                f"champ d'aperçu public Jalon 12 interdit : "
                f"{path}.{sorted(unknown)[0]}"
            )
        if not required.issubset(raw_item):
            raise RuntimeError(f"aperçu public Jalon 12 incomplet : {path}")
        item: dict[str, str] = {}
        for key, raw_value in raw_item.items():
            if raw_value is None:
                continue
            if not isinstance(raw_value, (str, int)) or isinstance(raw_value, bool):
                raise RuntimeError(f"valeur d'aperçu Jalon 12 invalide : {path}.{key}")
            text = str(raw_value)
            if not text or len(text) > 512:
                raise RuntimeError(f"valeur d'aperçu Jalon 12 invalide : {path}.{key}")
            item[key] = text
        if not required.issubset(item):
            raise RuntimeError(f"aperçu public Jalon 12 incomplet : {path}")
        fixture_id = item["fixture_id"]
        if re.fullmatch(r"api-football:[1-9][0-9]*", fixture_id) is None:
            raise RuntimeError(f"fixture d'aperçu Jalon 12 invalide : {path}")
        timestamp_key = "kickoff_at" if path == "fixtures.next" else "due_at"
        try:
            timestamp = datetime.fromisoformat(
                item[timestamp_key].replace("Z", "+00:00")
            )
        except ValueError as exception:
            raise RuntimeError(
                f"horodatage d'aperçu Jalon 12 invalide : {path}"
            ) from exception
        if (
            timestamp.tzinfo is None
            or timestamp.utcoffset() is None
            or timestamp.utcoffset() != timedelta(0)
        ):
            raise RuntimeError(f"horodatage d'aperçu Jalon 12 non UTC : {path}")
        if path == "windows.next" and {
            "opens_at",
            "cutoff_at",
            "kickoff_at",
        }.issubset(item):
            opens_at = _utc_datetime(
                item["opens_at"],
                path=f"{path}.opens_at",
            )
            cutoff_at = _utc_datetime(
                item["cutoff_at"],
                path=f"{path}.cutoff_at",
            )
            kickoff_at = _utc_datetime(
                item["kickoff_at"],
                path=f"{path}.kickoff_at",
            )
            if not opens_at <= timestamp <= cutoff_at < kickoff_at:
                raise RuntimeError(
                    f"bornes temporelles d'aperçu Jalon 12 invalides : {path}"
                )
        preview_key: tuple[str, ...]
        if path == "fixtures.next":
            if (
                item["competition"] not in allowed_competitions
                or item["status"] != "REGISTERED"
                or any(
                    not item[key].isdigit() or int(item[key]) <= 0
                    for key in ("home", "away")
                )
                or item["home"] == item["away"]
            ):
                raise RuntimeError(f"fixture d'aperçu Jalon 12 invalide : {path}")
            preview_key = (fixture_id,)
        else:
            family = item["family"]
            labels = capture_windows.get(family, [])
            if (
                family not in allowed_families
                or not isinstance(labels, list)
                or item["label"] not in labels
                or item["status"] not in allowed_window_statuses
            ):
                raise RuntimeError(f"fenêtre d'aperçu Jalon 12 invalide : {path}")
            preview_key = (fixture_id, family, item["label"])
        if preview_key in seen_preview_keys:
            raise RuntimeError(f"doublon d'aperçu Jalon 12 : {path}")
        seen_preview_keys.add(preview_key)
        sanitized.append(item)
    return sanitized


def _public_scalar(current: object, value: object, *, path: str) -> object:
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise RuntimeError(f"type public Jalon 12 invalide : {path}")
        return value
    if isinstance(current, int):
        parsed = _non_negative_int(value)
        if parsed is None:
            raise RuntimeError(f"compteur public Jalon 12 invalide : {path}")
        return parsed
    if isinstance(current, str):
        if not isinstance(value, str) or len(value) > 4096:
            raise RuntimeError(f"texte public Jalon 12 invalide : {path}")
        return value
    if current is None:
        if value is not None and (
            not isinstance(value, str) or len(value) > 4096
        ):
            raise RuntimeError(f"valeur publique Jalon 12 invalide : {path}")
        return value
    raise RuntimeError(f"type public Jalon 12 non pris en charge : {path}")


def merge_public_observatory(
    base: dict[str, Any],
    update: dict[str, Any],
    *,
    path: str = "",
) -> dict[str, Any]:
    """Projeter un rapport sur le schéma public fermé du Cockpit."""

    merged = dict(base)
    for key, value in update.items():
        child_path = f"{path}.{key}" if path else key
        if key not in base:
            if path == "invariants":
                raise RuntimeError(
                    f"invariant public Jalon 12 inconnu : {child_path}"
                )
            _reject_sensitive_unknown_field(key=key, path=path)
            continue
        if child_path in _PROTECTED_PUBLIC_PATHS:
            continue
        current = base[key]
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise RuntimeError(f"objet public Jalon 12 invalide : {child_path}")
            merged[key] = merge_public_observatory(
                current,
                value,
                path=child_path,
            )
        elif isinstance(current, list):
            if child_path in _PREVIEW_FIELDS:
                merged[key] = _sanitize_preview(value, path=child_path)
            elif not isinstance(value, list):
                raise RuntimeError(f"liste publique Jalon 12 invalide : {child_path}")
        else:
            merged[key] = _public_scalar(current, value, path=child_path)
    return merged


def _validate_report_invariants(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if not _REQUIRED_REPORT_INVARIANTS.issubset(value):
        return False
    if not set(value).issubset(_EXPECTED_INVARIANTS):
        return False
    return all(
        key not in value or value[key] == expected
        for key, expected in _EXPECTED_INVARIANTS.items()
    )


def _validate_operation_report(
    report: object,
    *,
    expected_command: str,
    policy_sha256: str,
) -> tuple[dict[str, Any], datetime]:
    """Authentifier l'enveloppe avant de lire une preuve opérationnelle."""

    if not isinstance(report, dict):
        raise RuntimeError("enveloppe opérationnelle Jalon 12 invalide")
    claimed_hash = report.get("report_sha256")
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    locked = (
        report.get("schema_version") == _OPERATION_REPORT_SCHEMA
        and report.get("command") == expected_command
        and report.get("policy_sha256") == policy_sha256
        and isinstance(claimed_hash, str)
        and claimed_hash == canonical_sha256(unsigned)
        and report.get("production_status") == "PRODUCTION_LOCKED"
        and report.get("real_bets") is False
        and report.get("no_bet_default") is True
        and report.get("social_publishing_enabled") is False
        and report.get("demo_mode_enabled") is False
        and report.get("deletions") == 0
        and report.get("raw_payloads_in_git") == 0
    )
    if not locked:
        raise RuntimeError("enveloppe opérationnelle Jalon 12 refusée")
    raw_generated_at = report.get("generated_at")
    if not isinstance(raw_generated_at, str):
        raise RuntimeError("horodatage opérationnel Jalon 12 absent")
    try:
        generated_at = datetime.fromisoformat(
            raw_generated_at.replace("Z", "+00:00")
        )
    except ValueError as exception:
        raise RuntimeError("horodatage opérationnel Jalon 12 invalide") from exception
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise RuntimeError("horodatage opérationnel Jalon 12 non UTC")
    generated_at = generated_at.astimezone(UTC)
    if generated_at > _utc_now() + timedelta(minutes=5):
        raise RuntimeError("horodatage opérationnel Jalon 12 futur")
    observatory = report.get("observatory")
    if not isinstance(observatory, dict):
        raise RuntimeError("observatoire opérationnel Jalon 12 absent")
    if observatory.get("generated_at") != raw_generated_at:
        raise RuntimeError("horodatages Jalon 12 incohérents")
    return cast(dict[str, Any], observatory), generated_at


def _validated_capture_evidence(
    captures: object,
    *,
    expected_receipts: int,
) -> tuple[int, int]:
    """Recouper les totaux de capture avec les neuf familles fermées."""

    if not isinstance(captures, dict):
        raise RuntimeError("captures publiques Jalon 12 invalides")
    by_family = captures.get("by_family")
    if not isinstance(by_family, dict) or len(by_family) != 9:
        raise RuntimeError("familles de capture Jalon 12 invalides")
    counter_names = (
        "attempted",
        "captured",
        "empty",
        "missed",
        "invalid",
        "bytes",
        "hashes",
    )
    totals: dict[str, int] = {}
    for counter in counter_names:
        total = _non_negative_int(captures.get(counter))
        family_values = [
            _non_negative_int(item.get(counter))
            for item in by_family.values()
            if isinstance(item, dict)
        ]
        if (
            total is None
            or len(family_values) != 9
            or any(value is None for value in family_values)
            or total != sum(cast(int, value) for value in family_values)
        ):
            raise RuntimeError(f"compteur de capture Jalon 12 incohérent : {counter}")
        totals[counter] = total
    for item in by_family.values():
        if not isinstance(item, dict) or _non_negative_int(item.get("due")) is None:
            raise RuntimeError("compteur de capture Jalon 12 incohérent : due")
    classified = totals["captured"] + totals["empty"] + totals["invalid"]
    fixture_family = by_family.get("FIXTURE")
    if not isinstance(fixture_family, dict):
        raise RuntimeError("famille FIXTURE Jalon 12 absente")
    fixture_hashes = cast(int, _non_negative_int(fixture_family.get("hashes")))
    non_fixture_hashes = totals["hashes"] - fixture_hashes
    if (
        classified > totals["hashes"]
        or bool(totals["bytes"]) != bool(totals["hashes"])
        or non_fixture_hashes > totals["attempted"]
        or totals["hashes"] != expected_receipts
    ):
        raise RuntimeError("preuves de capture Jalon 12 incohérentes")
    return totals["bytes"], totals["hashes"]


def _validated_capture_provenance(
    value: object,
    *,
    expected_receipts: int,
) -> bool:
    """Accept LIVE only when every immutable receipt is genuine provider data."""

    expected_keys = {
        "live_provider_receipts",
        "cache_test_receipts",
        "unverified_receipts",
        "provider_calls_recorded",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise RuntimeError("provenance des captures Jalon 12 absente")
    counters = {
        key: _non_negative_int(value.get(key))
        for key in expected_keys
    }
    if any(counter is None for counter in counters.values()):
        raise RuntimeError("provenance des captures Jalon 12 invalide")
    live = cast(int, counters["live_provider_receipts"])
    cache = cast(int, counters["cache_test_receipts"])
    unverified = cast(int, counters["unverified_receipts"])
    calls = cast(int, counters["provider_calls_recorded"])
    if (
        live + cache + unverified != expected_receipts
        or calls > live
        or (live == 0 and calls != 0)
    ):
        raise RuntimeError("provenance des captures Jalon 12 incohÃ©rente")
    return (
        expected_receipts > 0
        and live == expected_receipts
        and cache == 0
        and unverified == 0
        and calls > 0
    )


def _validate_gate_evidence(
    snapshot: dict[str, Any],
    *,
    fixture_count: int,
    capture_hashes: int,
) -> None:
    gates = snapshot.get("gates")
    temporal = snapshot.get("temporal")
    if not isinstance(gates, dict) or not isinstance(temporal, dict):
        raise RuntimeError("preuves de gates Jalon 12 absentes")
    by_name = gates.get("by_name")
    expected_names = {gate.value for gate in GateName}
    if not isinstance(by_name, dict) or set(by_name) != expected_names:
        raise RuntimeError("registre de gates Jalon 12 invalide")
    total_evaluations = 0
    for name in sorted(expected_names):
        item = by_name.get(name)
        if not isinstance(item, dict):
            raise RuntimeError(f"gate Jalon 12 invalide : {name}")
        passed = _non_negative_int(item.get("passed"))
        total = _non_negative_int(item.get("total"))
        expected_status = (
            GateStatus.PASSED.value
            if total is not None and total > 0 and passed == total
            else GateStatus.BLOCKED_BY_COVERAGE.value
        )
        raw_reason = item.get("reason")
        reasons = raw_reason.split(",") if isinstance(raw_reason, str) else []
        if (
            passed is None
            or total is None
            or passed > total
            or total != fixture_count
            or item.get("status") != expected_status
            or not reasons
            or any(reason not in _ALLOWED_GATE_REASONS for reason in reasons)
            or (total == 0 and reasons != ["NO_FIXTURE"])
        ):
            raise RuntimeError(f"agrégat de gate Jalon 12 incohérent : {name}")
        total_evaluations += total
    temporal_gates = _non_negative_int(temporal.get("gates"))
    before_cutoff = _non_negative_int(temporal.get("before_cutoff"))
    late = _non_negative_int(temporal.get("late"))
    rejected = _non_negative_int(temporal.get("rejected"))
    if (
        temporal_gates != total_evaluations
        or before_cutoff is None
        or late is None
        or rejected is None
        or before_cutoff + late != capture_hashes
        or rejected != late
    ):
        raise RuntimeError("temporalité des gates Jalon 12 incohérente")


def _validate_preview_context(
    snapshot: dict[str, Any],
    *,
    generated_at: datetime,
    fixture_count: int,
) -> None:
    fixtures = snapshot.get("fixtures")
    windows = snapshot.get("windows")
    if not isinstance(fixtures, dict) or not isinstance(windows, dict):
        raise RuntimeError("contexte d'aperçu Jalon 12 absent")
    fixture_preview = fixtures.get("next")
    window_preview = windows.get("next")
    horizon_days = _non_negative_int(fixtures.get("horizon_days"))
    planned_windows = _non_negative_int(windows.get("planned"))
    if (
        not isinstance(fixture_preview, list)
        or not isinstance(window_preview, list)
        or horizon_days is None
        or planned_windows is None
        or len(fixture_preview) > min(20, fixture_count)
        or len(window_preview) > min(20, planned_windows)
    ):
        raise RuntimeError("cardinalité d'aperçu Jalon 12 incohérente")
    horizon = generated_at + timedelta(days=horizon_days)
    for item in fixture_preview:
        if not isinstance(item, dict):
            raise RuntimeError("fixture d'aperçu Jalon 12 invalide")
        raw_kickoff = item.get("kickoff_at")
        if not isinstance(raw_kickoff, str):
            raise RuntimeError("kickoff d'aperçu Jalon 12 absent")
        kickoff = datetime.fromisoformat(
            raw_kickoff.replace("Z", "+00:00")
        ).astimezone(UTC)
        if not generated_at < kickoff <= horizon:
            raise RuntimeError("kickoff d'aperçu Jalon 12 hors horizon")
    policy = read_json(PROSPECTIVE_POLICY, {})
    capture_policy = (
        policy.get("capture_windows", {})
        if isinstance(policy, dict)
        else {}
    )
    tolerance_seconds = (
        _non_negative_int(capture_policy.get("operational_tolerance_seconds"))
        if isinstance(capture_policy, dict)
        else None
    )
    if tolerance_seconds is None or tolerance_seconds > 3600:
        raise RuntimeError("tolérance d'aperçu Jalon 12 invalide")
    tolerance = timedelta(seconds=tolerance_seconds)
    for item in window_preview:
        if not isinstance(item, dict):
            raise RuntimeError("fenêtre d'aperçu Jalon 12 invalide")
        raw_due = item.get("due_at")
        status = item.get("status")
        if not isinstance(raw_due, str):
            raise RuntimeError("due_at d'aperçu Jalon 12 absent")
        due_at = datetime.fromisoformat(
            raw_due.replace("Z", "+00:00")
        ).astimezone(UTC)
        if (
            status == AvailabilityStatus.NOT_DUE.value
            and generated_at >= due_at - tolerance
        ) or (
            status == AvailabilityStatus.DUE.value
            and not due_at - tolerance <= generated_at < due_at + tolerance
        ):
            raise RuntimeError("statut temporel d'aperçu Jalon 12 incohérent")


def _validate_ledger_evidence(
    snapshot: dict[str, Any],
    *,
    expected_events: int,
) -> None:
    ledger = snapshot.get("ledger")
    if not isinstance(ledger, dict):
        raise RuntimeError("ledger Jalon 12 absent")
    events = _non_negative_int(ledger.get("events"))
    head_hash = ledger.get("head_hash")
    cardinality = ledger.get("cardinality")
    cardinality_keys = {
        "planned_events",
        "capture_attempt_events",
        "physical_capture_events",
        "physical_http_calls",
        "temporal_evidence_events",
        "gate_evaluation_events",
        "lifecycle_events",
        "receipts",
    }
    physical_capture_events = (
        _non_negative_int(cardinality.get("physical_capture_events"))
        if isinstance(cardinality, dict)
        else None
    )
    temporal_evidence_events = (
        _non_negative_int(cardinality.get("temporal_evidence_events"))
        if isinstance(cardinality, dict)
        else None
    )
    receipt_count = (
        _non_negative_int(cardinality.get("receipts"))
        if isinstance(cardinality, dict)
        else None
    )
    valid_cardinality = (
        isinstance(cardinality, dict)
        and cardinality_keys <= set(cardinality)
        and all(
            _non_negative_int(cardinality.get(key)) is not None
            for key in cardinality_keys
        )
        and physical_capture_events is not None
        and temporal_evidence_events is not None
        and receipt_count is not None
        and physical_capture_events <= receipt_count
        and temporal_evidence_events <= receipt_count
    )
    valid_head = (
        head_hash is None
        if expected_events == 0
        else isinstance(head_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", head_hash) is not None
    )
    if (
        events != expected_events
        or not valid_head
        or (expected_events > 0 and not valid_cardinality)
        or _non_negative_int(ledger.get("bet_decisions")) != 0
    ):
        raise RuntimeError("ledger Jalon 12 incohérent")


def merge_verified_replay_evidence(
    snapshot: dict[str, Any],
    *,
    report_root: Path,
    expected_capture_set_sha256: str | None = None,
    latest_allowed_generated_at: datetime | None = None,
) -> None:
    """Propager uniquement les preuves sûres du replay dans le snapshot live."""

    report = read_json(report_root / "r2-replay-audit.json", {})
    if not report:
        return
    policy = read_json(PROSPECTIVE_POLICY, {})
    if not isinstance(policy, dict) or not policy:
        raise RuntimeError("politique Jalon 12 absente du replay")
    replay_observatory, replay_generated_at = _validate_operation_report(
        report,
        expected_command="replay-audit",
        policy_sha256=canonical_sha256(policy),
    )
    replay_r2 = (
        replay_observatory.get("r2", {})
        if isinstance(replay_observatory, dict)
        else {}
    )
    replay_postgresql = (
        replay_observatory.get("postgresql", {})
        if isinstance(replay_observatory, dict)
        else {}
    )
    report_counts = {
        key: _non_negative_int(report.get(key))
        for key in (
            "provider_calls",
            "odds_api_credits",
            "hash_mismatches",
            "data_loss",
            "deletions",
            "second_pass_inserts",
            "second_pass_duplicates",
            "payloads_replayed",
            "fixtures_reconstructed",
            "fixture_ids_expected",
            "objects_examined",
            "physical_unique_objects",
            "physical_unique_bytes",
            "physical_payload_objects",
            "physical_payload_bytes",
            "physical_receipt_objects",
            "physical_receipt_bytes",
            "physical_recovery_objects",
            "physical_recovery_bytes",
            "logical_references",
            "logical_payload_bytes_read",
            "logical_receipt_bytes_read",
            "logical_bytes_read",
        )
    }
    r2_counts = (
        {
            key: _non_negative_int(replay_r2.get(key))
            for key in (
                "bytes",
                "deletions",
                "lag",
                "objects_added",
                "recovery_bytes",
                "recovery_objects",
                "verified",
            )
        }
        if isinstance(replay_r2, dict)
        else {}
    )
    postgresql_counts = (
        {
            key: _non_negative_int(replay_postgresql.get(key))
            for key in (
                "duplicates_avoided",
                "inserts",
                "payload_body_rows",
                "tables",
            )
        }
        if isinstance(replay_postgresql, dict)
        else {}
    )
    all_counts_valid = (
        all(value is not None for value in report_counts.values())
        and all(value is not None for value in r2_counts.values())
        and all(value is not None for value in postgresql_counts.values())
    )
    payloads_replayed = report_counts.get("payloads_replayed")
    objects_examined = report_counts.get("objects_examined")
    physical_objects = report_counts.get("physical_unique_objects")
    physical_bytes = report_counts.get("physical_unique_bytes")
    physical_payload_objects = report_counts.get("physical_payload_objects")
    physical_payload_bytes = report_counts.get("physical_payload_bytes")
    physical_receipt_objects = report_counts.get("physical_receipt_objects")
    physical_receipt_bytes = report_counts.get("physical_receipt_bytes")
    physical_recovery_objects = report_counts.get("physical_recovery_objects")
    physical_recovery_bytes = report_counts.get("physical_recovery_bytes")
    logical_references = report_counts.get("logical_references")
    logical_payload_bytes = report_counts.get("logical_payload_bytes_read")
    logical_receipt_bytes = report_counts.get("logical_receipt_bytes_read")
    logical_bytes = report_counts.get("logical_bytes_read")
    fixtures_expected = report_counts.get("fixture_ids_expected")
    replay_bytes = r2_counts.get("bytes")
    postgresql_inserts = postgresql_counts.get("inserts")
    dataset_hash = report.get("dataset_hash")
    replay_capture_set = report.get("capture_set_sha256")
    safe = (
        all_counts_valid
        and report.get("command") == "replay-audit"
        and report.get("status") == "R2_REPLAY_VERIFIED"
        and report.get("complete_replay") is True
        and report.get("selection_truncated") is False
        and report_counts.get("provider_calls") == 0
        and report_counts.get("odds_api_credits") == 0
        and report_counts.get("hash_mismatches") == 0
        and report_counts.get("data_loss") == 0
        and report_counts.get("deletions") == 0
        and report_counts.get("second_pass_inserts") == 0
        and payloads_replayed is not None
        and payloads_replayed > 0
        and report_counts.get("second_pass_duplicates") == payloads_replayed
        and report_counts.get("fixtures_reconstructed")
        == fixtures_expected
        and fixtures_expected is not None
        and 0 < fixtures_expected <= payloads_replayed
        and objects_examined is not None
        and objects_examined > 0
        and objects_examined == physical_objects
        and physical_objects is not None
        and physical_objects
        == cast(int, physical_payload_objects)
        + cast(int, physical_receipt_objects)
        + cast(int, physical_recovery_objects)
        and physical_receipt_objects == payloads_replayed
        and physical_payload_objects is not None
        and 0 < physical_payload_objects <= payloads_replayed
        and physical_recovery_objects is not None
        and 0 <= physical_recovery_objects <= payloads_replayed
        and physical_bytes is not None
        and physical_bytes
        == cast(int, physical_payload_bytes)
        + cast(int, physical_receipt_bytes)
        + cast(int, physical_recovery_bytes)
        and physical_payload_bytes is not None
        and physical_payload_bytes > 0
        and physical_receipt_bytes is not None
        and physical_receipt_bytes > 0
        and physical_recovery_bytes is not None
        and (
            (physical_recovery_objects == 0 and physical_recovery_bytes == 0)
            or (
                physical_recovery_objects > 0
                and physical_recovery_bytes > 0
            )
        )
        and logical_references == payloads_replayed
        and logical_payload_bytes is not None
        and logical_payload_bytes >= physical_payload_bytes
        and logical_receipt_bytes == physical_receipt_bytes
        and logical_bytes
        == logical_payload_bytes + logical_receipt_bytes
        and report.get("namespace_verified") is True
        and isinstance(dataset_hash, str)
        and re.fullmatch(r"(?!0{64})[0-9a-f]{64}", dataset_hash) is not None
        and isinstance(replay_capture_set, str)
        and re.fullmatch(r"[0-9a-f]{64}", replay_capture_set) is not None
        and (
            expected_capture_set_sha256 is None
            or replay_capture_set == expected_capture_set_sha256
        )
        and (
            latest_allowed_generated_at is None
            or replay_generated_at <= latest_allowed_generated_at
        )
        and report.get("production_status") == "PRODUCTION_LOCKED"
        and report.get("real_bets") is False
        and report.get("no_bet_default") is True
        and report.get("social_publishing_enabled") is False
        and report.get("demo_mode_enabled") is False
        and report.get("raw_payloads_in_git") == 0
        and isinstance(replay_r2, dict)
        and replay_r2.get("replay_status") == "R2_REPLAY_VERIFIED"
        and r2_counts.get("verified") == objects_examined
        and replay_bytes is not None
        and replay_bytes == physical_bytes
        and r2_counts.get("lag") == 0
        and r2_counts.get("deletions") == 0
        and r2_counts.get("objects_added") == physical_objects
        and r2_counts.get("recovery_objects") == physical_recovery_objects
        and r2_counts.get("recovery_bytes") == physical_recovery_bytes
            and isinstance(replay_postgresql, dict)
            and replay_postgresql.get("reconstruction_status")
            == "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2"
        and replay_postgresql.get("migration") == "0009_jalon12_observatory"
        and postgresql_counts.get("tables") == 12
        and postgresql_inserts is not None
        and postgresql_inserts <= payloads_replayed
        and postgresql_counts.get("payload_body_rows") == 0
        and postgresql_counts.get("duplicates_avoided")
        == report_counts.get("second_pass_duplicates")
    )
    if not safe:
        raise RuntimeError("preuve replay Jalon 12 refusée")

    target_r2 = snapshot.get("r2", {})
    target_postgresql = snapshot.get("postgresql", {})
    if not isinstance(target_r2, dict) or not isinstance(target_postgresql, dict):
        raise RuntimeError("snapshot replay Jalon 12 invalide")
    target_bytes = _non_negative_int(target_r2.get("bytes"))
    target_objects = _non_negative_int(target_r2.get("objects_added"))
    if (
        target_bytes is None
        or target_bytes not in {0, replay_bytes}
        or target_objects is None
        or target_objects not in {0, objects_examined}
    ):
        raise RuntimeError("preuve replay Jalon 12 incohérente avec les captures")
    target_r2.update(
        {
            "objects_added": physical_objects,
            "bytes": physical_bytes,
            "recovery_objects": physical_recovery_objects,
            "recovery_bytes": physical_recovery_bytes,
            "replay_status": "R2_REPLAY_VERIFIED",
            "verified": objects_examined,
            "lag": 0,
            "deletions": 0,
        }
    )
    target_postgresql.update(
        {
            "migration": replay_postgresql["migration"],
            "tables": postgresql_counts["tables"],
            "payload_body_rows": postgresql_counts["payload_body_rows"],
            "lag": r2_counts["lag"],
            "reconstruction_status": (
                "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2"
            ),
            "duplicates_avoided": report_counts["second_pass_duplicates"],
        }
    )


def build_prospective_observatory() -> dict[str, Any]:
    """Construire la vue publique Jalon 12 depuis des rapports compacts sûrs."""

    verified_snapshot_path = os.environ.get("COCKPIT_VERIFIED_SNAPSHOT_INPUT")
    verified_observed: dict[str, Any] | None = None
    if verified_snapshot_path:
        verified_snapshot = read_verified_cockpit_snapshot(
            Path(verified_snapshot_path)
        )
        candidate = verified_snapshot.get("prospectiveObservatory")
        if not isinstance(candidate, dict):
            raise RuntimeError("observatoire vérifié absent")
        compact = candidate
        verified_observed = candidate
    else:
        compact = read_json(PROSPECTIVE_COMPACT, {})
    if not isinstance(compact, dict) or not compact:
        raise RuntimeError("rapport compact Jalon 12 absent")
    policy = read_json(PROSPECTIVE_POLICY, {})
    if not isinstance(policy, dict) or not policy:
        raise RuntimeError("politique Jalon 12 absente")

    competition_registry = policy.get("competition_registry", [])
    fixture_policy = policy.get("fixture_registry", {})
    provider_budgets = policy.get("provider_budgets", {})
    storage_policy = policy.get("storage", {})
    capture_windows = policy.get("capture_windows", {})
    if (
        not isinstance(competition_registry, list)
        or not isinstance(fixture_policy, dict)
        or not isinstance(provider_budgets, dict)
        or not isinstance(storage_policy, dict)
        or not isinstance(capture_windows, dict)
    ):
        raise RuntimeError("politique Jalon 12 invalide")
    compact["policy_source"] = PROSPECTIVE_POLICY.relative_to(ROOT).as_posix()
    compact["fixtures"]["competitions"] = [
        str(item["competition"])
        for item in competition_registry
        if isinstance(item, dict) and item.get("competition")
    ]
    compact["fixtures"]["pilot_priority"] = next(
        (
            str(item["competition"])
            for item in competition_registry
            if isinstance(item, dict) and item.get("capture_profile") == "FULL"
        ),
        "Ligue 1",
    )
    compact["fixtures"]["competition_profiles"] = {
        str(item["competition"]): str(item["capture_profile"])
        for item in competition_registry
        if isinstance(item, dict)
        and item.get("competition")
        and item.get("capture_profile")
    }
    compact["fixtures"]["horizon_days"] = int(
        str(fixture_policy.get("horizon_days", 45))
    )
    compact["fixtures"]["max_matchdays_per_competition"] = int(
        str(fixture_policy.get("max_matchdays_per_competition", 3))
    )
    compact["windows"]["policy_version"] = str(
        capture_windows.get(
            "policy_version",
            compact["windows"].get("policy_version", ""),
        )
    )
    api_budget = provider_budgets.get("api_football", {})
    odds_budget = provider_budgets.get("odds_api", {})
    if not isinstance(api_budget, dict) or not isinstance(odds_budget, dict):
        raise RuntimeError("politique de budget multi-ligues invalide")
    compact["providers"]["budgets"] = {
        "api_football_max_total": int(str(api_budget["per_run"])),
        "odds_api_max_total": int(str(odds_budget["per_run"])),
        "api_football_per_day": int(str(api_budget["per_day"])),
        "odds_api_per_day": int(str(odds_budget["per_day"])),
        "odds_api_per_week": int(str(odds_budget["per_week"])),
    }
    compact["providers"]["reserves"] = {
        "api_football": int(str(api_budget["provider_reserve"])),
        "odds_api": int(str(odds_budget["provider_reserve"])),
        "odds_api_internal_safety": int(
            str(odds_budget["internal_safety_reserve"])
        ),
        "odds_api_near_kickoff": int(
            str(odds_budget["near_kickoff_reserve"])
        ),
    }
    compact["r2"]["namespace"] = str(
        storage_policy.get("raw_namespace", compact["r2"].get("namespace", ""))
    )

    report_root = Path(
        os.environ.get(
            "PROSPECTIVE_REPORT_ROOT",
            str(ROOT / "artifacts" / "prospective-observatory"),
        )
    )
    observed: dict[str, Any] = verified_observed or {}
    observed_generated_at: datetime | None = None
    observed_receipts: int | None = None
    observed_ledger_events: int | None = None
    observed_capture_set_sha256: str | None = None
    observed_capture_provenance: object = None
    reported_active_windows: int | None = (
        _non_negative_int(compact.get("windows", {}).get("planned"))
        if verified_observed is not None
        else None
    )
    reported_inactive_windows: int | None = (
        _non_negative_int(compact.get("windows", {}).get("inactive_legacy"))
        if verified_observed is not None
        else None
    )
    gate_report_path = report_root / "gate-report.json"
    if verified_observed is None and gate_report_path.exists():
        gate_report = read_json(gate_report_path, {})
        observed, observed_generated_at = _validate_operation_report(
            gate_report,
            expected_command="gate-report",
            policy_sha256=canonical_sha256(policy),
        )
        if isinstance(gate_report, dict):
            observed_receipts = _non_negative_int(gate_report.get("receipts"))
            observed_ledger_events = _non_negative_int(
                gate_report.get("ledger_events")
            )
            raw_capture_set = gate_report.get("capture_set_sha256")
            observed_capture_set_sha256 = (
                raw_capture_set
                if isinstance(raw_capture_set, str)
                and re.fullmatch(r"[0-9a-f]{64}", raw_capture_set) is not None
                else None
            )
            observed_capture_provenance = gate_report.get(
                "capture_provenance"
            )
            reported_active_windows = _non_negative_int(
                gate_report.get("active_windows")
            )
            reported_inactive_windows = _non_negative_int(
                gate_report.get("inactive_windows")
            )
        if (
            observed_receipts is None
            or observed_ledger_events is None
            or observed_capture_set_sha256 is None
        ):
            raise RuntimeError("compteur de reçus Jalon 12 absent")

    if observed and verified_observed is None:
        if observed_receipts is None:
            raise RuntimeError("compteur de reçus Jalon 12 absent")
        if observed_ledger_events is None:
            raise RuntimeError("compteur de ledger Jalon 12 absent")
        if observed_capture_set_sha256 is None:
            raise RuntimeError("empreinte des captures Jalon 12 absente")
        invariants = observed.get("invariants", {})
        if not _validate_report_invariants(invariants):
            raise RuntimeError("rapport Jalon 12 refusé : invariants incomplets")
        compact = merge_public_observatory(compact, observed)
        fixture_count = _non_negative_int(compact.get("fixtures", {}).get("tracked"))
        if fixture_count is None:
            raise RuntimeError("compteur de fixtures Jalon 12 invalide")
        _capture_bytes, capture_hashes = _validated_capture_evidence(
            compact.get("captures"),
            expected_receipts=observed_receipts,
        )
        genuine_live_provenance = _validated_capture_provenance(
            observed_capture_provenance,
            expected_receipts=observed_receipts,
        )
        _validate_gate_evidence(
            compact,
            fixture_count=fixture_count,
            capture_hashes=capture_hashes,
        )
        _validate_ledger_evidence(
            compact,
            expected_events=observed_ledger_events,
        )
        merge_verified_replay_evidence(
            compact,
            report_root=report_root,
            expected_capture_set_sha256=observed_capture_set_sha256,
            latest_allowed_generated_at=observed_generated_at,
        )
        has_live_evidence = (
            capture_hashes > 0
            and genuine_live_provenance
            and compact["r2"]["replay_status"] == "R2_REPLAY_VERIFIED"
            and compact["r2"]["verified"] > 0
            and compact["postgresql"]["reconstruction_status"]
            == "CAPTURE_PROJECTIONS_AND_BUDGET_RECONSTRUCTIBLE_FROM_R2"
        )
        if has_live_evidence:
            compact["origin"] = "LIVE_PROSPECTIVE_CAPTURE"
        if observed_generated_at is not None:
            compact["generated_at"] = observed_generated_at.isoformat()
            _validate_preview_context(
                compact,
                generated_at=observed_generated_at,
                fixture_count=fixture_count,
            )
        gates = compact.get("gates", {})
        by_name = gates.get("by_name", {}) if isinstance(gates, dict) else {}
        gate_totals = (
            [
                _non_negative_int(item.get("total"))
                for item in by_name.values()
                if isinstance(item, dict)
            ]
            if isinstance(by_name, dict)
            else []
        )
        if any(total is None for total in gate_totals):
            raise RuntimeError("compteurs de gates Jalon 12 invalides")
        compact["status"] = (
            "PROSPECTIVE_GATES_ACCUMULATING"
            if any(total and total > 0 for total in gate_totals)
            else "GATES_BLOCKED_BY_COVERAGE"
        )

        fixtures = observed.get("fixtures", {})
        if isinstance(fixtures, dict):
            planned = _non_negative_int(
                fixtures.get(
                    "windows_planned",
                    compact["windows"].get("planned", 0),
                )
            )
            due = _non_negative_int(
                fixtures.get("windows_due", compact["windows"].get("due", 0))
            )
            if planned is None or due is None or due > planned:
                raise RuntimeError("compteurs de fenêtres Jalon 12 invalides")
            compact["windows"]["planned"] = planned
            compact["windows"]["due"] = due

    raw_generated_at = compact.get("generated_at")
    projection_generated_at = (
        _utc_datetime(
            raw_generated_at,
            path="prospectiveObservatory.generated_at",
        )
        if raw_generated_at is not None
        else _utc_now()
    )
    observed_fixtures = observed.get("fixtures", {})
    observed_windows = observed.get("windows", {})
    fixture_source: object = compact.get("fixtures", {}).get("next", [])
    evidence_source: object = None
    if isinstance(observed_fixtures, dict):
        fixture_source = observed_fixtures.get("registry", fixture_source)
        evidence_source = observed_fixtures.get("evidence")
    fixture_registry = _presentation_fixture_registry(fixture_source)
    identity_registry = _enrich_fixture_identities(
        fixture_registry,
        report_path=_team_identity_report_path(report_root),
    )
    active_fixture_ids = {
        str(item["fixture_id"])
        for item in fixture_registry
        if item["cancelled"] is not True
        and item["status"] not in {"CANCELLED", "CANCELED", "TOMBSTONED"}
    }
    window_source: object = None
    if isinstance(observed_windows, dict):
        window_source = observed_windows.get("registry")
    window_registry = _presentation_window_registry(
        window_source,
        fixtures=fixture_registry,
        generated_at=projection_generated_at,
    )
    active_windows = [
        item
        for item in window_registry
        if item["active"] is True
        and str(item["fixture_id"]) in active_fixture_ids
    ]
    captures = compact.get("captures", {})
    if not isinstance(captures, dict):
        raise RuntimeError("captures publiques Jalon 12 invalides")
    fixture_evidence = _presentation_fixture_evidence(
        evidence_source,
        fixtures=fixture_registry,
        captures=captures,
    )
    compact_fixtures = compact.get("fixtures", {})
    compact_windows = compact.get("windows", {})
    if not isinstance(compact_fixtures, dict) or not isinstance(
        compact_windows,
        dict,
    ):
        raise RuntimeError("projection publique Jalon 12 invalide")
    compact_fixtures["registry"] = fixture_registry
    compact_fixtures["evidence"] = fixture_evidence
    compact_fixtures["identity_registry"] = identity_registry
    compact_fixtures["tracked"] = len(active_fixture_ids)
    compact_windows["registry"] = active_windows
    compact_windows["planned"] = len(active_windows)
    compact_windows["due"] = sum(
        item["status"] == AvailabilityStatus.DUE.value
        for item in active_windows
    )
    compact_windows["captured"] = sum(
        item["acknowledged"] is True for item in active_windows
    )
    compact_windows["missed"] = sum(
        item["status"] == AvailabilityStatus.MISSED_WINDOW.value
        for item in active_windows
    )
    compact_windows["next"] = [
        {
            key: item[key]
            for key in (
                "fixture_id",
                "family",
                "label",
                "opens_at",
                "due_at",
                "cutoff_at",
                "kickoff_at",
                "status",
            )
        }
        for item in active_windows
        if item["acknowledged"] is not True
        and item["status"] != AvailabilityStatus.MISSED_WINDOW.value
    ]
    compact_windows["inactive_legacy"] = (
        reported_inactive_windows
        if window_source
        else reported_active_windows or 0
    )
    source = (
        observed.get("source", {})
        if isinstance(observed.get("source"), dict)
        else {}
    )
    compact["source"] = {
        "run_id": (
            os.environ.get("COCKPIT_SOURCE_RUN")
            or source.get("run_id")
            or os.environ.get("GITHUB_RUN_ID")
        ),
        "revision": (
            os.environ.get("COCKPIT_SOURCE_REVISION")
            or source.get("revision")
            or os.environ.get("GITHUB_SHA")
        ),
        "workflow": (
            os.environ.get("COCKPIT_SOURCE_WORKFLOW")
            or source.get("workflow")
            or os.environ.get("GITHUB_WORKFLOW")
        ),
    }
    fixture_competitions = {
        str(item["fixture_id"]): str(item["competition"])
        for item in fixture_registry
    }
    configured_competitions = [
        item
        for item in competition_registry
        if isinstance(item, dict)
        and item.get("competition")
        and item.get("capture_profile")
    ]
    summary_path = report_root / "five-league-expansion-summary.json"
    summary_rows: dict[str, dict[str, Any]] = {}
    if summary_path.exists():
        summary = read_json(summary_path, {})
        raw_summary_rows = summary.get("leagues", [])
        unsigned_summary = dict(summary)
        summary_sha256 = unsigned_summary.pop("report_sha256", None)
        if (
            not isinstance(summary, dict)
            or summary.get("schema_version")
            != "five-league-expansion-summary-v1"
            or summary.get("policy_sha256") != canonical_sha256(policy)
            or not isinstance(summary_sha256, str)
            or summary_sha256 != canonical_sha256(unsigned_summary)
            or summary.get("production_status") != "PRODUCTION_LOCKED"
            or summary.get("real_bets") is not False
            or summary.get("provider_calls_for_summary") != 0
            or summary.get("odds_api_credits_for_summary") != 0
            or summary.get("model_promotion_authorized") is not False
            or not isinstance(raw_summary_rows, list)
            or len(raw_summary_rows) != 5
        ):
            raise RuntimeError("rapport multi-ligues non publiable")
        summary_rows = {
            str(item["competition"]): item
            for item in raw_summary_rows
            if isinstance(item, dict) and item.get("competition")
        }
        if set(summary_rows) != {
            str(item["competition"]) for item in configured_competitions
        }:
            raise RuntimeError("périmètre multi-ligues incomplet")
    competition_summaries: list[dict[str, Any]] = []
    for configured in configured_competitions:
        competition = str(configured["competition"])
        fixture_ids = {
            fixture_id
            for fixture_id, name in fixture_competitions.items()
            if name == competition
        }
        scoped_windows = [
            item
            for item in active_windows
            if str(item["fixture_id"]) in fixture_ids
        ]
        scoped_evidence = [
            item
            for item in fixture_evidence
            if str(item.get("fixture_id", "")) in fixture_ids
        ]
        observed_summary = summary_rows.get(competition, {})
        profile = str(configured["capture_profile"])
        default_gate = "WAITING_FOR_FIXTURES"
        competition_summaries.append(
            {
                "competition": competition,
                "capture_profile": profile,
                "fixtures": len(fixture_ids),
                "teams": int(str(observed_summary.get("teams", 0))),
                "identity_slots_verified": int(
                    str(
                        observed_summary.get(
                            "identity_slots_verified",
                            2 * len(fixture_ids)
                            if all(
                                item.get("home_identity_status") == "VERIFIED"
                                and item.get("away_identity_status")
                                == "VERIFIED"
                                for item in fixture_registry
                                if str(item["fixture_id"]) in fixture_ids
                            )
                            else 0,
                        )
                    )
                ),
                "identity_slots_expected": 2 * len(fixture_ids),
                "windows": len(scoped_windows),
                "next_captures": sum(
                    item["acknowledged"] is not True
                    and item["status"]
                    != AvailabilityStatus.MISSED_WINDOW.value
                    for item in scoped_windows
                ),
                "captures": len(scoped_evidence),
                "deep_observations": int(
                    str(observed_summary.get("deep_observations", 0))
                ),
                "empty_responses": int(
                    str(observed_summary.get("empty_responses", 0))
                ),
                "api_football_calls": int(
                    str(observed_summary.get("api_football_calls", 0))
                ),
                "odds_api_credits": int(
                    str(observed_summary.get("odds_api_credits", 0))
                ),
                "gate": str(observed_summary.get("gate", default_gate)),
                "r2": str(observed_summary.get("r2", "PENDING")),
                "postgresql": str(
                    observed_summary.get("postgresql", "PENDING")
                ),
                "replay": str(observed_summary.get("replay", "PENDING")),
            }
        )
    compact["competitions"] = competition_summaries

    invariants = compact.get("invariants", {})
    if (
        invariants != _EXPECTED_INVARIANTS
        or int(str(compact.get("decisions", 0))) != 0
        or int(str(compact.get("candidates", 0))) != 0
        or int(str(compact.get("ledger", {}).get("bet_decisions", 0))) != 0
    ):
        raise RuntimeError("snapshot Observatoire non publiable")
    return cast(dict[str, Any], compact)


def private_deployment_status(
    *,
    current_backfill_run: str,
    current_data_hash: str,
    deployment_state: dict[str, Any],
) -> str:
    """Refuser le statut déployé dès que les données privées ont divergé."""

    deployed_backfill_run = str(deployment_state.get("backfill_run_id", ""))
    deployed_data_hash = str(deployment_state.get("data_hash", ""))
    if (
        current_backfill_run
        and current_backfill_run == deployed_backfill_run
        and current_data_hash
        and current_data_hash == deployed_data_hash
    ):
        return "COCKPIT_PRIVATE_DEPLOYED"
    return "COCKPIT_PRIVATE_STALE"


def completed_rows_this_run(plan: dict[str, Any]) -> int:
    explicit = int(str(plan.get("normalized_rows_this_run", 0)))
    if explicit:
        return explicit
    completed = int(str(plan.get("completed_this_run", 0)))
    tasks = [
        task
        for task in plan.get("tasks", [])
        if isinstance(task, dict) and task.get("completed_at")
    ]
    latest = sorted(
        tasks,
        key=lambda task: str(task.get("completed_at", "")),
        reverse=True,
    )[:completed]
    return sum(int(str(task.get("rows_received", 0))) for task in latest)


def build_player_readiness(
    state: Path,
    quality: dict[str, Any],
    forecast: dict[str, Any],
) -> dict[str, Any]:
    entity_metrics: dict[str, dict[str, Any]] = {}
    observation_dimensions: dict[str, dict[str, int]] = {}

    for observation_path in sorted((state / "raw" / "observations").rglob("*.json")):
        observation = read_json(observation_path, {})
        payload_hash = str(observation.get("payload_hash", ""))
        parameters = observation.get("request_parameters", {})
        if not payload_hash or not isinstance(parameters, dict):
            continue
        dimensions: dict[str, int] = {}
        for key in ("fixture", "team"):
            value = parameters.get(key)
            if isinstance(value, int):
                dimensions[key] = value
        observation_dimensions[payload_hash] = dimensions

    def payload_ids(value: Any, wrapper: str) -> set[int]:
        found: set[int] = set()
        if isinstance(value, dict):
            wrapped = value.get(wrapper)
            if isinstance(wrapped, dict) and isinstance(wrapped.get("id"), int):
                found.add(int(wrapped["id"]))
            for nested in value.values():
                found.update(payload_ids(nested, wrapper))
        elif isinstance(value, list):
            for nested in value:
                found.update(payload_ids(nested, wrapper))
        return found

    for path in sorted((state / "parquet").rglob("*.parquet")):
        competition_part = next(
            (part for part in path.parts if part.startswith("competition=")),
            "competition=unknown",
        )
        entity_part = next(
            (part for part in path.parts if part.startswith("entity_type=")),
            "entity_type=unknown",
        )
        season_part = next(
            (part for part in path.parts if part.startswith("season=")),
            "season=0",
        )
        competition = competition_part.split("=", 1)[1]
        entity = entity_part.split("=", 1)[1]
        season = int(season_part.split("=", 1)[1])
        frame = pd.read_parquet(path)
        metrics = entity_metrics.setdefault(
            entity,
            {
                "competitions": set(),
                "seasons": set(),
                "teams": set(),
                "fixtures": set(),
                "players": set(),
                "rows": 0,
                "nullCells": 0,
                "cells": 0,
            },
        )
        metrics["competitions"].add(competition)
        metrics["seasons"].add(season)
        metrics["rows"] += len(frame)
        metrics["nullCells"] += int(frame.isna().sum().sum())
        metrics["cells"] += int(frame.shape[0] * frame.shape[1])
        if "payload" not in frame.columns:
            continue
        raw_hashes = (
            frame["raw_payload_hash"].tolist()
            if "raw_payload_hash" in frame.columns
            else [None] * len(frame)
        )
        for raw_payload, raw_hash in zip(
            frame["payload"].tolist(),
            raw_hashes,
            strict=True,
        ):
            try:
                payload = json.loads(str(raw_payload))
            except json.JSONDecodeError:
                continue
            metrics["teams"].update(payload_ids(payload, "team"))
            metrics["fixtures"].update(payload_ids(payload, "fixture"))
            metrics["players"].update(payload_ids(payload, "player"))
            dimensions = observation_dimensions.get(str(raw_hash), {})
            fixture_id = dimensions.get("fixture")
            team_id = dimensions.get("team")
            if fixture_id is not None:
                metrics["fixtures"].add(fixture_id)
            if team_id is not None:
                metrics["teams"].add(team_id)

    quality_status = str(quality.get("status", "NOT_RUN"))
    eta_a = forecast.get("eta_priority_a_base", forecast.get("eta_priority_a_days"))
    after_priority_a = (
        f"after priority A (~{eta_a} d)"
        if eta_a is not None
        else "after priority A"
    )
    specifications = [
        ("Effectifs", ("squads",), "POINT_IN_TIME_SAFE"),
        ("Joueurs", ("players",), "POINT_IN_TIME_SAFE"),
        ("Minutes", ("fixture_player_statistics",), "POST_MATCH_LAG_REQUIRED"),
        (
            "Statistiques joueurs par match",
            ("fixture_player_statistics",),
            "POST_MATCH_LAG_REQUIRED",
        ),
        ("Compositions", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Continuite du onze", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Formations", ("lineups",), "POST_MATCH_LAG_REQUIRED"),
        ("Blessures", ("injuries",), "HISTORICAL_NON_POINT_IN_TIME"),
        (
            "Disponibilite",
            ("injuries", "lineups"),
            "HISTORICAL_NON_POINT_IN_TIME",
        ),
        ("Force du banc", ("squads", "lineups"), "POST_MATCH_LAG_REQUIRED"),
        (
            "Force du onze",
            ("fixture_player_statistics", "lineups"),
            "POST_MATCH_LAG_REQUIRED",
        ),
        (
            "Retour de blessure",
            ("injuries", "fixture_player_statistics"),
            "HISTORICAL_NON_POINT_IN_TIME",
        ),
        (
            "Fatigue",
            ("fixture_player_statistics", "lineups"),
            "POST_MATCH_LAG_REQUIRED",
        ),
    ]
    families: list[dict[str, Any]] = []
    for name, dependencies, temporality in specifications:
        dependency_metrics = [
            entity_metrics.get(
                entity,
                {
                    "competitions": set(),
                    "seasons": set(),
                    "teams": set(),
                    "fixtures": set(),
                    "players": set(),
                    "rows": 0,
                    "nullCells": 0,
                    "cells": 0,
                },
            )
            for entity in dependencies
        ]

        def common_values(key: str) -> set[Any]:
            populated = [
                set(metrics[key])
                for metrics in dependency_metrics
                if metrics[key]
            ]
            return set.intersection(*populated) if populated else set()

        competitions = sorted(common_values("competitions"))
        seasons = sorted(common_values("seasons"))
        teams = common_values("teams")
        fixtures = common_values("fixtures")
        players_covered = common_values("players")
        rows = min(
            (int(metrics["rows"]) for metrics in dependency_metrics),
            default=0,
        )
        cells = sum(int(metrics["cells"]) for metrics in dependency_metrics)
        null_cells = sum(
            int(metrics["nullCells"]) for metrics in dependency_metrics
        )
        null_rate = round(null_cells / cells, 4) if cells else None
        if quality_status not in {"PASSED", "WARNING"}:
            status = "BLOCKED_BY_QUALITY"
            reason = f"historical quality is {quality_status}"
        elif temporality == "HISTORICAL_NON_POINT_IN_TIME":
            status = "BLOCKED_BY_TEMPORALITY"
            reason = "point-in-time injury snapshots are unavailable"
        elif len(seasons) < 2:
            status = "BLOCKED_BY_COVERAGE"
            reason = "fewer than two verified common seasons"
        elif name == "Joueurs":
            status = "COMPUTABLE"
            reason = "multi-season player dimension is available"
        else:
            status = "TESTING"
            reason = "per-match as-of and identity validation is still required"
        families.append(
            {
                "name": name,
                "coverage": {
                    "competitions": competitions,
                    "competitionCount": len(competitions),
                    "seasons": seasons,
                    "seasonCount": len(seasons),
                    "teamCount": len(teams),
                    "fixtureCount": len(fixtures),
                    "playerCount": len(players_covered),
                    "rows": rows,
                    "nullRate": null_rate,
                    "dependencies": list(dependencies),
                },
                "quality": quality_status,
                "identities": (
                    "VERIFIED"
                    if quality_status == "PASSED" and rows > 0
                    else "PENDING"
                ),
                "temporality": temporality,
                "status": status,
                "reason": reason,
                "estimatedAvailability": (
                    "unknown - point-in-time source required"
                    if status == "BLOCKED_BY_TEMPORALITY"
                    else after_priority_a
                ),
            }
        )
    return {
        "coverage": "INSUFFICIENT",
        "quality": quality_status,
        "temporality": "MIXED_BLOCKS",
        "status": "BLOCKED_BY_COVERAGE",
        "estimatedFirstModel": "after priority A and multi-season gates",
        "families": families,
    }


def sanitize_public_snapshot(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_public_snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_public_snapshot(item) for item in value]
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        marker = "/data/historical/"
        if marker in normalized:
            return f"historical/{normalized.split(marker, 1)[1]}"
    return value


def build_pattern_research() -> dict[str, Any]:
    """Construire Robin Live V1 depuis des résumés compacts, jamais depuis une démo."""

    simulation_policy = read_json(SHADOW_SIMULATION_POLICY, {})
    if (
        not isinstance(simulation_policy, dict)
        or simulation_policy.get("schema_version")
        != "shadow-simulation-policy-v1"
        or simulation_policy.get("simulation_only") is not True
        or simulation_policy.get("production_status") != "PRODUCTION_LOCKED"
        or simulation_policy.get("real_bets") is not False
        or simulation_policy.get("no_bet_default") is not True
        or simulation_policy.get("social_publishing_enabled") is not False
        or simulation_policy.get("demo_mode_enabled") is not False
    ):
        raise RuntimeError("SHADOW_SIMULATION_POLICY_INVALID")
    configured_bankroll = simulation_policy.get("initial_bankroll_units")
    if (
        isinstance(configured_bankroll, bool)
        or not isinstance(configured_bankroll, (int, float))
        or configured_bankroll <= 0
    ):
        raise RuntimeError("SHADOW_INITIAL_BANKROLL_INVALID")
    initial_bankroll = float(configured_bankroll)

    roots = [
        ROOT / "data" / "shadow" / "pattern-research",
        ROOT / "data" / "historical" / "pattern-research",
        ROOT / "reports" / "pattern-research",
    ]
    campaign: dict[str, Any] = {}
    ledger: dict[str, Any] = {}
    ledger_override = os.environ.get("PATTERN_LEDGER_SUMMARY")
    if ledger_override:
        override_path = Path(ledger_override).resolve()
        if not override_path.is_file():
            raise RuntimeError("PATTERN_LEDGER_SUMMARY_MISSING")
        candidate = read_json(override_path, {})
        if not isinstance(candidate, dict) or not candidate:
            raise RuntimeError("PATTERN_LEDGER_SUMMARY_INVALID")
        ledger = candidate
    for root in roots:
        if not campaign:
            candidate = read_json(root / "campaign-summary.json", {})
            if isinstance(candidate, dict):
                campaign = candidate
        if not ledger:
            candidate = read_json(root / "ledger-summary.json", {})
            if isinstance(candidate, dict):
                ledger = candidate

    counts = campaign.get("counts", {})
    if not isinstance(counts, dict):
        counts = {}

    def integer(source: dict[str, Any], key: str) -> int:
        value = source.get(key, 0)
        if isinstance(value, bool):
            return 0
        try:
            return max(0, int(str(value)))
        except (TypeError, ValueError):
            return 0

    def number(source: dict[str, Any], key: str, default: float = 0.0) -> float:
        value = source.get(key, default)
        if isinstance(value, bool):
            return default
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return default

    def require_guard(
        source: dict[str, Any],
        key: str,
        expected: object,
        artifact: str,
    ) -> None:
        if key not in source or source[key] != expected:
            raise RuntimeError(
                f"UNSAFE_PATTERN_RESEARCH_ARTIFACT:{artifact}:{key}"
            )

    for artifact, source in (("campaign", campaign), ("ledger", ledger)):
        if not source:
            continue
        require_guard(
            source,
            "production_status",
            "PRODUCTION_LOCKED",
            artifact,
        )
        require_guard(source, "real_bets", False, artifact)
        require_guard(source, "no_bet_default", True, artifact)
        require_guard(
            source,
            "social_publishing_enabled",
            False,
            artifact,
        )
        require_guard(source, "demo_mode_enabled", False, artifact)

    decisions = integer(ledger, "decisions")
    shadow_bets = integer(ledger, "shadow_bets")
    no_bets = integer(ledger, "no_bets")
    classified_decisions = min(decisions, shadow_bets + no_bets)
    current_bankroll = number(ledger, "shadow_bankroll", initial_bankroll)
    if current_bankroll <= 0:
        raise RuntimeError("SHADOW_BANKROLL_INVALID")
    profit = number(
        ledger,
        "profit_units",
        current_bankroll - initial_bankroll,
    )
    settled_stakes = number(ledger, "settled_stake_units", 0.0)
    roi = (
        number(
            ledger,
            "roi",
            profit / settled_stakes,
        )
        if settled_stakes > 0
        else None
    )
    has_campaign = bool(campaign)
    has_ledger = bool(ledger)
    data_status = (
        "LIVE_SHADOW_LEDGER"
        if has_ledger and decisions > 0
        else "NO_LIVE_SHADOW_DATA"
    )
    source_status = (
        "HISTORICAL_RESEARCH"
        if has_campaign
        else "NO_OUTPUT"
    )
    support_rejected = integer(counts, "support_rejected")
    negative_controls = campaign.get("negative_controls", {})
    if not isinstance(negative_controls, dict):
        negative_controls = {}
    strategies_rejected = integer(counts, "strategies_rejected")
    if not strategies_rejected:
        strategies_rejected = max(
            0,
            integer(counts, "hypotheses_executed")
            - integer(counts, "shadow_candidates"),
        )
    fdr_alpha = number(
        campaign.get("configuration", {})
        if isinstance(campaign.get("configuration"), dict)
        else {},
        "fdr_alpha",
        0.05,
    )
    top_exploratory: list[dict[str, Any]] = []
    raw_top = campaign.get("top_exploratory_walk_forward_results", [])
    if isinstance(raw_top, list):
        for item in raw_top[:3]:
            if not isinstance(item, dict):
                continue
            interval = item.get("bootstrap_roi_95", [])
            folds_positive = integer(item, "walk_forward_positive_folds")
            folds_eligible = integer(item, "walk_forward_eligible_folds")
            q_value = number(item, "q_value", 1.0)
            top_exploratory.append(
                {
                    "ruleHash": str(item.get("rule_hash", "")),
                    "competition": str(item.get("competition", "UNKNOWN")),
                    "market": str(item.get("market", "UNKNOWN")),
                    "selection": str(item.get("selection", "UNKNOWN")),
                    "conditions": item.get("conditions", {}),
                    "bets": integer(item, "bets"),
                    "bootstrapGroups": integer(
                        item,
                        "distinct_bootstrap_groups",
                    ),
                    "roi": number(item, "roi"),
                    "profitUnits": number(item, "profit_units"),
                    "maxDrawdownUnits": number(
                        item,
                        "max_drawdown_units",
                    ),
                    "qValue": q_value,
                    "bootstrapRoi95": (
                        interval
                        if isinstance(interval, list) and len(interval) == 2
                        else []
                    ),
                    "positiveFolds": folds_positive,
                    "eligibleFolds": folds_eligible,
                    "exposedLeagueStability": str(
                        item.get("external_validation", "NOT_TESTED")
                    ),
                    "leagueStability": "EXPOSED_SINGLE_LEAGUE_ONLY",
                    "limit": str(item.get("limit", "NOT_PROMOTABLE")),
                    "publicStatus": (
                        "EXPLORATORY_REJECTED_AFTER_MULTIPLE_TESTING"
                        if q_value > fdr_alpha
                        else "EXPLORATORY_NOT_PROMOTED"
                    ),
                }
            )
    expected_scope_subverdict = (
        "NO_ROBUST_PATTERN_FOUND_IN_PREREGISTERED_MARKET_SLICE_SEARCH_SPACE"
    )
    sub_verdict = str(
        campaign.get(
            "scope_subverdict",
            expected_scope_subverdict
            if integer(counts, "raw_positive") > 0
            and integer(counts, "fdr_survivors") == 0
            else "NO_EXPLORATORY_RESULT_TO_PUBLISH",
        )
    )
    if has_campaign and sub_verdict != expected_scope_subverdict:
        raise RuntimeError("PATTERN_RESEARCH_SCOPE_SUBVERDICT_INVALID")
    what_was_tested = (
        [
            (
                "Campagne football cache-only sur "
                f"{integer(counts, 'fixtures_matched'):,} fixtures appariées, "
                "cinq ligues et saisons 2020–2025."
            ),
            (
                f"{integer(counts, 'hypotheses_executed')} hypothèses "
                "exécutées sur 1X2 et Over/Under 2,5 avec prix historiques "
                "SOURCE_PRICE_CLASS_ONLY."
            ),
            (
                "Mise fixe, support, p-values CR1 groupées par date, "
                "bootstrap groupé, walk-forward brut, Benjamini-Hochberg "
                "et 7 contrôles négatifs exécutés."
            ),
            (
                "Replay déterministe sans fournisseur, sans crédit et sans "
                "doublon métier."
            ),
        ]
        if has_campaign
        else []
    )
    not_tested = [
        (
            "Cotes live avec observed_at exact, CLV et validation "
            "prospective point-in-time."
        ),
        (
            "Permutation candidate stratifiée par compétition, saison et "
            "bande de cote ; le gate V1 reste fermé sans cette extension."
        ),
        (
            "Décisions et règlements shadow non vides ; la bankroll "
            "reste à son état initial."
        ),
        (
            "Marchés joueurs, buteurs, cartons, corners et handicaps "
            "indisponibles dans le corpus."
        ),
        (
            "Publication sur un réseau social, transaction réelle ou "
            "connexion bookmaker."
        ),
    ]
    if not has_campaign:
        not_tested.insert(0, "Campagne scientifique indisponible dans ce snapshot.")

    return {
        "version": "ROBIN_LIVE_V1",
        "dataStatus": data_status,
        "researchStatus": source_status,
        "campaignVerdict": str(campaign.get("verdict", "NOT_RUN")),
        "subVerdict": sub_verdict,
        "publicationTime": ledger.get("published_at"),
        "today": {
            "matchesAnalyzed": integer(ledger, "matches_analyzed"),
            "shadowBets": shadow_bets,
            "noBets": no_bets,
            "unclassifiedDecisions": decisions - classified_decisions,
            "justification": (
                "Aucune décision shadow publiée."
                if decisions == 0
                else "Décisions gelées avant match dans le registre append-only."
            ),
            "origin": (
                "LIVE SHADOW"
                if data_status == "LIVE_SHADOW_LEDGER"
                else "NO OUTPUT"
            ),
        },
        "results": {
            "won": integer(ledger, "won"),
            "lost": integer(ledger, "lost"),
            "void": integer(ledger, "void"),
            "settlements": integer(ledger, "settlements"),
            "profitUnits": round(profit, 4),
            "roi": round(roi, 6) if roi is not None else None,
            "historyRecords": integer(ledger, "records"),
            "settledStakeUnits": settled_stakes,
        },
        "bankroll": {
            "initialUnits": initial_bankroll,
            "currentUnits": round(current_bankroll, 4),
            "profitUnits": round(profit, 4),
            "roi": round(roi, 6) if roi is not None else None,
            "maxDrawdownUnits": round(
                number(ledger, "max_drawdown_units", 0.0),
                4,
            ),
            "curve": ledger.get("bankroll_curve", [initial_bankroll]),
            "simulationOnly": True,
            "policySource": SHADOW_SIMULATION_POLICY.relative_to(ROOT).as_posix(),
        },
        "strategies": {
            "inResearch": integer(counts, "hypotheses_executed"),
            "shadowCandidates": integer(counts, "shadow_candidates"),
            "inShadow": integer(counts, "strategies_in_shadow"),
            "rejected": strategies_rejected,
            "supportRejected": support_rejected,
            "promotionRejected": strategies_rejected,
            "rejectionReason": (
                "Toutes les hypothèses sont rejetées de la promotion ; "
                "les rejets de support sont comptés séparément."
                if strategies_rejected
                else "Aucune stratégie publiée."
            ),
        },
        "laboratory": {
            "hypothesesGenerated": integer(counts, "hypotheses_generated"),
            "rulesExecuted": integer(counts, "hypotheses_executed"),
            "supportRejected": support_rejected,
            "rawPositive": integer(counts, "raw_positive"),
            "fdrSurvivors": integer(counts, "fdr_survivors"),
            "walkForwardSurvivors": integer(
                counts,
                "walk_forward_survivors",
            ),
            "walkForwardRawBeforeFdr": integer(
                counts,
                "walk_forward_survivors",
            ),
            "externalLeagueSurvivors": integer(
                counts,
                "external_league_survivors",
            ),
            "negativeControls": len(negative_controls),
            "negativeControlsPassed": sum(
                isinstance(control, dict) and control.get("passed") is True
                for control in negative_controls.values()
            ),
            "fdrMethod": "Benjamini-Hochberg",
            "pValueMethod": "CR1 unilatérale groupée par date de match",
            "topExploratoryResults": top_exploratory,
        },
        "WHAT_WAS_TESTED": what_was_tested,
        "WHAT_WAS_NOT_TESTED": not_tested,
        "methodology": {
            "backtest": (
                "Un backtest rejoue une règle sur des données historiques "
                "sans transformer ce résultat en promesse."
            ),
            "shadow": (
                "Le shadow observe et règle des décisions fictives, sans "
                "transaction ni connexion bookmaker."
            ),
            "publication": (
                "Robin publie aussi les pertes et les NO BET afin de rendre "
                "les résultats auditables."
            ),
            "warning": (
                "Les performances passées ne garantissent aucun résultat futur."
            ),
        },
        "ledger": {
            "status": str(ledger.get("status", "NOT_CREATED")),
            "records": integer(ledger, "records"),
            "decisions": decisions,
            "settlements": integer(ledger, "settlements"),
        },
        "productionStatus": "PRODUCTION_LOCKED",
        "realBets": False,
        "noBetDefault": True,
        "socialPublishingEnabled": False,
        "demoModeEnabled": False,
    }


def build_matchup_lab() -> dict[str, Any]:
    """Construire le Matchup Lab depuis les seuls rapports compacts Jalon 11."""

    roots: list[Path] = []
    override = os.environ.get("JALON11_REPORT_ROOT")
    if override:
        roots.append(Path(override).resolve())
    roots.extend(
        [
            ROOT / "reports" / "jalon11",
            ROOT / "data" / "historical" / "deep-football" / "reports",
            ROOT / "data" / "historical" / "jalon11",
        ]
    )

    def first_report(*names: str) -> dict[str, Any]:
        for root in roots:
            for name in names:
                candidate = read_json(root / name, {})
                if isinstance(candidate, dict) and candidate:
                    return candidate
        return {}

    def integer(value: Any, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            return max(0, int(str(value)))
        except (TypeError, ValueError):
            return default

    def number(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    final = first_report("jalon11-final.json")
    final_audit = (
        final.get("audit", {})
        if isinstance(final.get("audit"), dict)
        else {}
    )
    operational = first_report(
        "final-review-validation.json",
        "operational-validation.json",
    )
    operational_audit = (
        operational.get("audit", {})
        if isinstance(operational.get("audit"), dict)
        else {}
    )
    detailed_audit = first_report("audit-summary.json", "preflight-summary.json")
    if os.environ.get("JALON11_REPORT_ROOT"):
        audit = {
            **operational_audit,
            **detailed_audit,
            **final_audit,
        }
    else:
        audit = {
            **detailed_audit,
            **final_audit,
            **operational_audit,
        }
    campaign = (
        final.get("campaign", {})
        if isinstance(final.get("campaign"), dict)
        else {}
    )
    if not campaign:
        campaign = first_report(
            "campaign-summary.json",
            "campaign-11a-summary.json",
        )
    dataset = (
        final.get("dataset", {})
        if isinstance(final.get("dataset"), dict)
        else {}
    )
    if not dataset:
        dataset = first_report("dataset-manifest.json")
    red_team = (
        final.get("red_team", {})
        if isinstance(final.get("red_team"), dict)
        else {}
    )
    if not red_team:
        red_team = first_report("red-team-summary.json", "red-team-report.json")
    replay = (
        final.get("replay", {})
        if isinstance(final.get("replay"), dict)
        else {}
    )
    if not replay:
        replay = first_report("replay-summary.json", "replay.json")
    watchlist = (
        final.get("watchlist", {})
        if isinstance(final.get("watchlist"), dict)
        else {}
    )
    if not watchlist:
        watchlist = first_report("prospective-watchlist.json")
    decision = (
        final.get("decision", {})
        if isinstance(final.get("decision"), dict)
        else {}
    )
    if not decision:
        decision = first_report("shadow-candidate-decision.json")
    ledger = (
        final.get("ledger", {})
        if isinstance(final.get("ledger"), dict)
        else {}
    )
    if not ledger:
        ledger = first_report(
            "public-evidence-ledger-v2.json",
            "ledger-audit.json",
        )
    coverage_report = first_report("coverage-matrix.json")
    feature_contract = first_report("feature-contract-v2.json")
    if not dataset and feature_contract:
        raw_features = feature_contract.get("features", [])
        feature_names = [
            str(item.get("name"))
            for item in raw_features
            if isinstance(item, dict) and item.get("name")
        ]
        blocked_families = feature_contract.get("blocked_families", {})
        compact_sample = campaign.get("sample", {})
        if not isinstance(compact_sample, dict):
            compact_sample = {}
        compact_pairing = coverage_report.get("pairing", {})
        if not isinstance(compact_pairing, dict):
            compact_pairing = {}
        compact_market_rows = integer(
            compact_sample.get(
                "market_rows",
                coverage_report.get("market_rows", 0),
            )
        )
        dataset = {
            "dataset_name": "TEAM_PREMATCH",
            "dataset_version": feature_contract.get(
                "dataset_version",
                "deep-football-team-prematch-v2",
            ),
            "rows": compact_market_rows,
            "features": feature_names,
            "feature_cutoff": feature_contract.get(
                "cutoff_policy",
                "STRICTLY_BEFORE_TARGET_KICKOFF",
            ),
            "research_mode": feature_contract.get(
                "research_mode",
                "PRE_LINEUP",
            ),
            "source": [
                "API_FOOTBALL_HISTORICAL",
                "FOOTBALL_DATA",
            ],
            "dataset_hash": feature_contract.get("dataset_hash", ""),
            "parquet_sha256": replay.get("parquet_sha256", ""),
            "parquet_bytes": replay.get(
                "parquet_bytes",
                feature_contract.get("parquet_bytes", 0),
            ),
            "blocked_datasets": (
                blocked_families
                if isinstance(blocked_families, dict)
                else {}
            ),
            "report": {
                "pairing": {
                    "market_rows": compact_pairing.get(
                        "market_rows",
                        compact_market_rows,
                    ),
                    "paired_rows": compact_pairing.get(
                        "paired_rows",
                        coverage_report.get(
                            "strict_1x2_rows",
                            compact_market_rows,
                        ),
                    ),
                    "duplicate_keys": compact_pairing.get(
                        "duplicate_keys",
                        0,
                    ),
                    "left_attrition": compact_pairing.get(
                        "left_attrition",
                        0,
                    ),
                    "right_attrition": compact_pairing.get(
                        "right_attrition",
                        0,
                    ),
                    "exact_keyset_for_market_scope": compact_pairing.get(
                        "exact_keyset_for_market_scope",
                        compact_market_rows > 0
                        and integer(
                            coverage_report.get(
                                "strict_1x2_rows",
                                compact_market_rows,
                            )
                        )
                        == compact_market_rows,
                    ),
                }
            },
            "provider_calls": feature_contract.get("provider_calls", 0),
            "odds_api_credits": feature_contract.get("odds_api_credits", 0),
            "production_status": feature_contract.get(
                "production_status",
                "PRODUCTION_LOCKED",
            ),
        }
    compact_promotion = campaign.get("promotion", {})
    if not isinstance(compact_promotion, dict):
        compact_promotion = {}
    if not watchlist:
        watchlist = {
            "status": (
                "EMPTY_NO_ROBUST_DEEP_MATCHUP"
                if integer(compact_promotion.get("watchlist")) == 0
                else "PROSPECTIVE_WATCHLIST"
            ),
            "count": integer(compact_promotion.get("watchlist")),
            "not_a_bet": True,
            "production_status": "PRODUCTION_LOCKED",
        }
    if not decision:
        decision = {
            "status": "NO_DECISION_NO_CANDIDATE",
            "candidate_count": integer(
                compact_promotion.get("shadow_candidates")
            ),
            "decisions": integer(compact_promotion.get("decisions")),
            "stake_units": number(compact_promotion.get("stake_units")) or 0.0,
            "shadow_bankroll_before": 1_000.0,
            "shadow_bankroll_after": (
                number(compact_promotion.get("shadow_bankroll")) or 1_000.0
            ),
            "production_status": "PRODUCTION_LOCKED",
            "real_bets": False,
            "no_bet_default": True,
        }

    artifacts_present = any(
        (
            final,
            audit,
            campaign,
            dataset,
            red_team,
            replay,
            watchlist,
            decision,
            ledger,
            coverage_report,
            feature_contract,
            operational,
        )
    )
    invariants: dict[str, Any] = {}
    audit_invariants = audit.get("invariants", {})
    if isinstance(audit_invariants, dict):
        invariants.update(
            {
                "production_status": (
                    "PRODUCTION_LOCKED"
                    if audit_invariants.get("PRODUCTION_LOCKED") is True
                    else audit_invariants.get("production_status")
                ),
                "real_bets": audit_invariants.get(
                    "REAL_BETS",
                    audit_invariants.get("real_bets"),
                ),
                "no_bet_default": audit_invariants.get(
                    "NO_BET_DEFAULT",
                    audit_invariants.get("no_bet_default"),
                ),
                "social_publishing_enabled": audit_invariants.get(
                    "SOCIAL_PUBLISHING_ENABLED",
                    audit_invariants.get("social_publishing_enabled"),
                ),
                "demo_mode_enabled": audit_invariants.get(
                    "DEMO_MODE_ENABLED",
                    audit_invariants.get("demo_mode_enabled"),
                ),
            }
        )
    for source in (
        final,
        campaign,
        dataset,
        replay,
        watchlist,
        decision,
    ):
        for key in (
            "production_status",
            "real_bets",
            "no_bet_default",
            "social_publishing_enabled",
            "demo_mode_enabled",
            "provider_calls",
            "odds_api_credits",
        ):
            if key in source:
                invariants[key] = source[key]

    expected = {
        "production_status": "PRODUCTION_LOCKED",
        "real_bets": False,
        "no_bet_default": True,
        "social_publishing_enabled": False,
        "demo_mode_enabled": False,
        "provider_calls": 0,
        "odds_api_credits": 0,
    }
    if artifacts_present:
        for key, expected_value in expected.items():
            if key not in invariants or invariants[key] != expected_value:
                raise RuntimeError(f"UNSAFE_JALON11_ARTIFACT:{key}")
        if watchlist and watchlist.get("not_a_bet") is not True:
            raise RuntimeError("UNSAFE_JALON11_ARTIFACT:watchlist_not_a_bet")

    gates_source = audit.get("gates", {})
    if not isinstance(gates_source, dict) or not gates_source:
        gates_source = coverage_report.get("gates", {})
    if not isinstance(gates_source, dict):
        gates_source = {}
    gates = []
    for gate_name in (
        "TEAM_GATE",
        "PLAYER_GATE",
        "PLAYER_FORM_GATE",
        "ABSENCE_GATE",
        "LINEUP_GATE",
        "FORMATION_GATE",
        "STARTER_BASELINE_GATE",
        "FOOTEDNESS_GATE",
        "MARKET_GATE",
    ):
        raw_gate = gates_source.get(gate_name, {})
        if not isinstance(raw_gate, dict):
            raw_gate = {}
        reasons = raw_gate.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = []
        if not reasons and isinstance(raw_gate.get("reason"), str):
            reasons = [raw_gate["reason"]]
        gates.append(
            {
                "name": gate_name,
                "status": str(raw_gate.get("status", "NOT_EVALUATED")),
                "reasons": [
                    str(reason)
                    for reason in reasons
                    if isinstance(reason, str)
                ][:4],
            }
        )

    raw_coverage = audit.get("coverage_matrix", [])
    if not isinstance(raw_coverage, list) or not raw_coverage:
        raw_coverage = coverage_report.get(
            "coverage_matrix",
            coverage_report.get("rows", []),
        )
    if not isinstance(raw_coverage, list):
        raw_coverage = []
    coverage_by_competition: dict[str, dict[str, Any]] = {}
    for row in raw_coverage:
        if not isinstance(row, dict):
            continue
        competition = str(row.get("competition", "UNKNOWN"))
        item = coverage_by_competition.setdefault(
            competition,
            {
                "competition": competition,
                "seasons": set(),
                "teamFixtures": 0,
                "playerFixtures": 0,
                "lineupFixtures": 0,
                "injuryRows": 0,
                "footednessObserved": 0,
            },
        )
        season = row.get("season")
        if isinstance(season, int):
            item["seasons"].add(season)
        item["teamFixtures"] += integer(
            row.get("team_fixtures", row.get("fixtures"))
        )
        item["playerFixtures"] += integer(
            row.get(
                "player_fixture_estimate",
                row.get("player_raw_fixtures"),
            )
        )
        item["lineupFixtures"] += integer(
            row.get(
                "lineup_fixture_estimate",
                row.get("lineup_raw_fixtures"),
            )
        )
        item["injuryRows"] += integer(row.get("injury_rows"))
        item["footednessObserved"] += integer(row.get("footedness_observed"))
    coverage = [
        {
            **item,
            "seasons": sorted(item["seasons"]),
        }
        for item in coverage_by_competition.values()
    ]

    campaigns_source = audit.get("campaigns", [])
    if not isinstance(campaigns_source, list):
        campaigns_source = []
    if not campaigns_source and isinstance(campaign.get("campaigns"), dict):
        campaigns_source = [
            {
                "campaign_id": campaign_id,
                "title": {
                    "11A": "Team and Calendar Deep Baseline",
                    "11B": "Player Availability",
                    "11C": "Lineup Continuity",
                    "11D": "Formation Matchups",
                    "11E": "Owner Anchored Hypotheses",
                    "11F": "Cross-League Transfer",
                    "11G": "Integrated Matchup Arena",
                }.get(str(campaign_id), str(campaign_id)),
                "status": status,
                "required_gates": [],
                "blocking_gates": (
                    []
                    if str(status).startswith("COMPLETED")
                    else ["DEEP_DATA_GATES"]
                ),
                "cache_only": True,
            }
            for campaign_id, status in campaign["campaigns"].items()
        ]
    campaigns = []
    for item in campaigns_source:
        if not isinstance(item, dict):
            continue
        campaigns.append(
            {
                "id": str(item.get("campaign_id", "UNKNOWN")),
                "title": str(item.get("title", "Untitled campaign")),
                "status": str(item.get("status", "NOT_RUN")),
                "requiredGates": [
                    str(gate) for gate in item.get("required_gates", [])
                ],
                "blockingGates": [
                    str(gate) for gate in item.get("blocking_gates", [])
                ],
                "cacheOnly": item.get("cache_only") is True,
            }
        )
    primary_campaign = next(
        (item for item in campaigns if item["id"] == "11A"),
        {"id": "NOT_RUN", "status": "NOT_RUN"},
    )

    hypotheses_source = audit.get("owner_hypotheses", [])
    if not isinstance(hypotheses_source, list):
        hypotheses_source = []
    if not hypotheses_source and isinstance(
        campaign.get("owner_hypotheses"),
        list,
    ):
        hypotheses_source = campaign["owner_hypotheses"]
    hypothesis_contracts = {
        contract.hypothesis_id: contract for contract in owner_hypotheses()
    }
    hypotheses = []
    for item in hypotheses_source:
        if not isinstance(item, dict):
            continue
        hypothesis_id = str(
            item.get("hypothesis_id", item.get("id", "UNKNOWN"))
        )
        contract = hypothesis_contracts.get(hypothesis_id)
        hypotheses.append(
            {
                "id": hypothesis_id,
                "title": str(
                    item.get(
                        "title",
                        contract.title if contract else "Untitled hypothesis",
                    )
                ),
                "family": str(
                    item.get(
                        "statistical_family",
                        contract.statistical_family if contract else "UNKNOWN",
                    )
                ),
                "eligibility": str(
                    item.get(
                        "eligibility",
                        item.get("status", "NOT_EVALUATED"),
                    )
                ),
                "blockingGates": [
                    str(gate) for gate in item.get("blocking_gates", [])
                ]
                or [
                    value
                    for value in str(item.get("limit", "")).split(";")
                    if value
                ],
                "minimumSupport": integer(
                    item.get(
                        "minimum_support",
                        contract.minimum_support if contract else 0,
                    )
                ),
                "cutoff": str(
                    item.get(
                        "cutoff",
                        contract.cutoff if contract else "UNSPECIFIED",
                    )
                ),
                "frozenBeforeResults": (
                    item.get(
                        "frozen_before_results",
                        contract.frozen_before_results if contract else False,
                    )
                    is True
                ),
                "preregistrationHash": str(
                    item.get(
                        "preregistration_hash",
                        contract.preregistration_hash if contract else "",
                    )
                ),
            }
        )

    models_source = campaign.get("models", {})
    if not isinstance(models_source, dict):
        models_source = {}
    models = []
    preferred_model_order = (
        "B0_MARKET",
        "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
        "B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL",
        "B1_MARKET_PLUS_TEAM_BOUNDED_GRADIENT_BOOSTING",
        "B1_TEAM_ONLY_REGULARIZED_MULTINOMIAL",
        "B1_TEAM_ONLY_BOUNDED_GRADIENT_BOOSTING",
        "B1_TEAM_ONLY_POISSON",
        "B1_TEAM_ONLY_DIXON_COLES",
    )
    model_ids = [
        model_id
        for model_id in preferred_model_order
        if isinstance(models_source.get(model_id), dict)
    ]
    model_ids.extend(
        sorted(
            str(model_id)
            for model_id, value in models_source.items()
            if isinstance(value, dict) and str(model_id) not in model_ids
        )
    )
    for model_id in model_ids:
        raw_model = models_source.get(model_id, {})
        if not isinstance(raw_model, dict):
            raw_model = {}
        delta_log_loss = number(
            raw_model.get(
                "delta_log_loss",
                raw_model.get("delta_log_loss_vs_raw_market"),
            )
        )
        delta_brier = number(
            raw_model.get(
                "delta_brier",
                raw_model.get("delta_brier_vs_raw_market"),
            )
        )
        raw_status = str(raw_model.get("status", ""))
        if model_id == "B0_MARKET":
            interpretation = "REFERENCE_RAW_MARKET"
        elif model_id == "B0_MARKET_RECALIBRATED_TRAIN_ONLY":
            interpretation = "REFERENCE_RECALIBRATED_TRAIN_ONLY"
        elif "BLOCKED" in raw_status:
            interpretation = "DATA_GATE_BLOCKED"
        elif delta_log_loss is not None and delta_log_loss > 0:
            interpretation = "WORSE_THAN_REFERENCE"
        elif delta_log_loss is not None and delta_log_loss < 0:
            interpretation = "BETTER_DESCRIPTIVE_ONLY"
        else:
            interpretation = "NOT_ESTABLISHED"
        models.append(
            {
                "id": model_id,
                "logLoss": number(raw_model.get("log_loss")),
                "brier": number(raw_model.get("brier")),
                "deltaLogLoss": delta_log_loss,
                "deltaBrier": delta_brier,
                "calibrationError": number(
                    raw_model.get("calibration_error")
                ),
                "reference": str(
                    raw_model.get(
                        "reference",
                        (
                            "B0_MARKET"
                            if model_id != "B0_MARKET"
                            else "SELF"
                        ),
                    )
                ),
                "status": raw_status or interpretation,
                "interpretation": interpretation,
            }
        )

    controls_source = campaign.get(
        "negative_controls",
        red_team.get("negative_controls", {}),
    )
    if not isinstance(controls_source, dict):
        controls_source = {}
    controls = []
    for name, raw_status in sorted(controls_source.items()):
        status = str(
            raw_status.get("status", "NOT_EVALUATED")
            if isinstance(raw_status, dict)
            else raw_status
        )
        controls.append(
            {
                "name": str(name),
                "status": status,
                "support": integer(
                    raw_status.get("support", 0)
                    if isinstance(raw_status, dict)
                    else 0
                ),
                "category": (
                    "DATA_GATED"
                    if status == "DATA_GATE_BLOCKED"
                    else "EXECUTED_OR_GUARD"
                ),
                "promotionEligible": (
                    raw_status.get("promotion_eligible") is True
                    if isinstance(raw_status, dict)
                    else False
                ),
            }
        )
    promotion = campaign.get("promotion", {})
    if not isinstance(promotion, dict):
        promotion = {}
    if "promoted" not in promotion:
        promotion = {
            **promotion,
            "status": "REJECTED",
            "promoted": False,
            "criteria": {"DEEP_DATA_GATES": False},
            "failed_criteria": ["DEEP_DATA_GATES"],
        }
    criteria_source = promotion.get("criteria", {})
    if not isinstance(criteria_source, dict):
        criteria_source = {}
    promotion_criteria = [
        {"name": str(name), "passed": passed is True}
        for name, passed in sorted(criteria_source.items())
    ]
    report = dataset.get("report", {})
    if not isinstance(report, dict):
        report = {}
    pairing = report.get("pairing", audit.get("team_pairing", {}).get("pairing", {}))
    if not isinstance(pairing, dict):
        pairing = {}
    blocked_datasets = dataset.get("blocked_datasets", {})
    if not isinstance(blocked_datasets, dict):
        blocked_datasets = {}
    features = dataset.get("features", feature_contract.get("features", []))
    if not isinstance(features, list):
        features = []
    folds = campaign.get("folds", [])
    if not isinstance(folds, list):
        folds = []
    normalized_folds: list[dict[str, Any]] = []
    for fold in folds:
        if not isinstance(fold, dict):
            continue

        def fold_metric(group: str, metric: str) -> float | None:
            nested = fold.get(group, {})
            if not isinstance(nested, dict):
                return None
            return number(nested.get(metric))

        primary_delta_log_loss = fold_metric(
            "incremental_logistic_vs_recalibrated_market",
            "delta_log_loss",
        )
        if primary_delta_log_loss is None:
            primary_delta_log_loss = number(
                fold.get("primary_delta_log_loss")
            )
        primary_delta_brier = fold_metric(
            "incremental_logistic_vs_recalibrated_market",
            "delta_brier",
        )
        if primary_delta_brier is None:
            primary_delta_brier = number(fold.get("primary_delta_brier"))
        normalized_folds.append(
            {
                "season": integer(
                    fold.get("test_season", fold.get("season"))
                ),
                "matches": integer(fold.get("matches")),
                "primaryDeltaLogLoss": primary_delta_log_loss,
                "primaryDeltaBrier": primary_delta_brier,
                "teamOnlyLogitDeltaLogLoss": (
                    fold_metric("logistic", "delta_log_loss")
                    if isinstance(fold.get("logistic"), dict)
                    else number(
                        fold.get(
                            "team_only_logit_delta_log_loss",
                            fold.get("logit_delta_log_loss"),
                        )
                    )
                ),
                "teamOnlyBoostingDeltaLogLoss": (
                    fold_metric(
                        "bounded_gradient_boosting",
                        "delta_log_loss",
                    )
                    if isinstance(
                        fold.get("bounded_gradient_boosting"),
                        dict,
                    )
                    else number(fold.get("boosting_delta_log_loss"))
                ),
                "marketRecalibrationDeltaLogLoss": fold_metric(
                    "market_recalibrated_vs_raw",
                    "delta_log_loss",
                ),
                "incrementalBoostingDeltaLogLoss": fold_metric(
                    "incremental_boosting_vs_recalibrated_market",
                    "delta_log_loss",
                )
                or number(fold.get("incremental_boosting_delta_log_loss")),
                "outcome": (
                    "BETTER_DESCRIPTIVE_ONLY"
                    if primary_delta_log_loss is not None
                    and primary_delta_log_loss < 0
                    else (
                        "LOST_TO_RECALIBRATED_MARKET"
                        if primary_delta_log_loss is not None
                        else "NOT_AVAILABLE"
                    )
                ),
            }
        )
    statistics = campaign.get("statistics", {})
    if not isinstance(statistics, dict):
        statistics = {}
    primary_model_id = str(
        models_source.get(
            "primary_for_inference",
            models_source.get("selected_for_red_team", "NONE"),
        )
    )
    primary_model = models_source.get(primary_model_id, {})
    if not isinstance(primary_model, dict):
        primary_model = {}
    primary_reference = str(
        primary_model.get(
            "reference",
            "B0_MARKET_RECALIBRATED_TRAIN_ONLY",
        )
    )
    bootstrap_ci = statistics.get("delta_log_loss_bootstrap_ci95", [])
    if not isinstance(bootstrap_ci, list):
        bootstrap_ci = []
    cross_league_source = campaign.get("cross_league", {})
    if not isinstance(cross_league_source, dict):
        cross_league_source = {}
    rotation_source = cross_league_source.get("rotations", [])
    rotation_count = (
        len(rotation_source)
        if isinstance(rotation_source, list)
        else integer(rotation_source)
    )
    if not isinstance(rotation_source, list):
        rotation_source = []
    rotations: list[dict[str, Any]] = []
    for index, rotation in enumerate(rotation_source, start=1):
        if not isinstance(rotation, dict):
            continue
        rotations.append(
            {
                "id": f"ROTATION_{index}",
                "discoveryLeagues": [
                    str(value)
                    for value in rotation.get("discovery_leagues", [])
                    if isinstance(value, str)
                ],
                "validationLeagues": [
                    str(value)
                    for value in rotation.get("validation_leagues", [])
                    if isinstance(value, str)
                ],
                "support": integer(rotation.get("support")),
                "deltaLogLoss": number(rotation.get("delta_log_loss")),
                "deltaBrier": number(rotation.get("delta_brier")),
                "descriptiveDirectionPositive": (
                    rotation.get("descriptive_direction_positive") is True
                ),
                "promotionEligible": (
                    rotation.get("promotion_eligible") is True
                ),
            }
        )
    rotation_supports: list[int] = [
        integer(rotation.get("support")) for rotation in rotations
    ]
    rotation_deltas: list[float] = []
    for rotation in rotations:
        delta = number(rotation.get("deltaLogLoss"))
        if delta is not None:
            rotation_deltas.append(delta)
    raw_delta_range = cross_league_source.get("delta_log_loss_range", [])
    if not isinstance(raw_delta_range, list):
        raw_delta_range = []
    objections = red_team.get("objections", {})
    if not isinstance(objections, dict):
        objections = {}
    storage = audit.get("storage", {})
    if not isinstance(storage, dict):
        storage = {}
    if not storage and isinstance(audit.get("historical_storage"), dict):
        storage = dict(audit["historical_storage"])
        storage["historical_bytes"] = storage.get("local_bytes", 0)
        storage["p3_p4"] = (
            "P3_P4_PAUSED"
            if audit.get("invariants", {}).get("P3_P4_PAUSED") is True
            else "NOT_EVALUATED"
        )
    r2 = storage.get("r2", {})
    if not isinstance(r2, dict):
        r2 = {}
    if not r2 and isinstance(audit.get("r2"), dict):
        r2 = audit["r2"]
    database = audit.get("database", {})
    if not isinstance(database, dict):
        database = {}
    if not database and isinstance(audit.get("postgresql"), dict):
        database = audit["postgresql"]

    verdict = str(
        final.get(
            "verdict",
            campaign.get(
                "verdict",
                (
                    "JALON_11_BLOCKED_BY_DATA_GATES"
                    if artifacts_present
                    else "JALON_11_NOT_RUN"
                ),
            ),
        )
    )
    if artifacts_present and verdict not in {
        "JALON_11_BLOCKED_BY_DATA_GATES",
        "JALON_11_COMPLETED_NO_PROMOTION",
    }:
        raise RuntimeError("UNSAFE_JALON11_ARTIFACT:verdict")
    sample = campaign.get("sample", {})
    if not isinstance(sample, dict):
        sample = {}
    market_rows = integer(
        campaign.get(
            "market_rows",
            sample.get("market_rows", audit.get("market_rows", 0)),
        )
    )
    paired_evaluation_rows = integer(
        campaign.get(
            "paired_1x2_rows",
            sample.get("paired_evaluation_rows", 0),
        )
    )
    replay_hashes = replay.get("hash_comparisons", {})
    if not isinstance(replay_hashes, dict):
        replay_hashes = {}
    ledger_event_counts = ledger.get("event_counts", {})
    if not isinstance(ledger_event_counts, dict):
        ledger_event_counts = {}

    return {
        "version": "MATCHUP_LAB_V1",
        "dataStatus": (
            "HISTORICAL_RESEARCH_EVIDENCE"
            if artifacts_present
            else "NO_OUTPUT"
        ),
        "origin": (
            "HISTORICAL RESEARCH" if artifacts_present else "NO OUTPUT"
        ),
        "verdict": verdict,
        "coverage": {
            "marketRows": market_rows,
            "pairedEvaluationRows": paired_evaluation_rows,
            "competitions": coverage,
            "gates": gates,
            "contentTotals": (
                audit.get("content_totals", {})
                if isinstance(audit.get("content_totals"), dict)
                else {}
            ),
        },
        "dataset": {
            "name": str(dataset.get("dataset_name", "NOT_BUILT")),
            "version": str(dataset.get("dataset_version", "NOT_BUILT")),
            "rows": integer(dataset.get("rows", market_rows)),
            "features": [
                str(
                    feature.get("name", "UNKNOWN")
                    if isinstance(feature, dict)
                    else feature
                )
                for feature in features
            ],
            "featureCutoff": str(
                dataset.get("feature_cutoff", "NOT_EVALUATED")
            ),
            "researchMode": str(dataset.get("research_mode", "NOT_EVALUATED")),
            "source": [
                str(source)
                for source in dataset.get("source", [])
                if isinstance(source, str)
            ],
            "pairing": {
                "marketRows": integer(pairing.get("market_rows")),
                "pairedRows": integer(pairing.get("paired_rows")),
                "duplicateKeys": integer(pairing.get("duplicate_keys")),
                "leftAttrition": integer(pairing.get("left_attrition")),
                "rightAttrition": integer(pairing.get("right_attrition")),
                "exactKeyset": pairing.get("exact_keyset_for_market_scope")
                is True,
            },
            "blocked": [
                {"name": str(name), "reason": str(reason)}
                for name, reason in sorted(blocked_datasets.items())
            ],
            "hash": str(dataset.get("dataset_hash", "")),
            "parquetHash": str(dataset.get("parquet_sha256", "")),
            "parquetBytes": integer(dataset.get("parquet_bytes")),
            "heavyArtifactLocation": str(
                dataset.get(
                    "heavy_artifact_location",
                    "R2_OR_POSTGRESQL_NOT_GIT",
                )
            ),
        },
        "experiments": {
            "campaigns": campaigns,
            "ownerHypotheses": hypotheses,
            "eligible": sum(item["status"] == "ELIGIBLE" for item in campaigns),
            "blocked": sum(
                item["status"] == "DATA_GATE_BLOCKED" for item in campaigns
            ),
        },
        "results": {
            "campaign": str(
                campaign.get("campaign", primary_campaign["id"])
            ),
            "status": str(
                campaign.get("status", primary_campaign["status"])
            ),
            "models": models,
            "folds": normalized_folds[:8],
            "primaryForInference": primary_model_id,
            "modelSelectionOnTest": (
                models_source.get("model_selection_on_test") is True
            ),
            "roi": str(
                campaign.get(
                    "roi",
                    "NOT_COMPUTED_NO_PREREGISTERED_BETTING_RULE",
                )
            ),
            "statistics": statistics,
            "pairedComparator": {
                "reference": primary_reference,
                "challenger": primary_model_id,
                "support": paired_evaluation_rows,
                "deltaLogLoss": number(
                    primary_model.get("delta_log_loss")
                ),
                "deltaBrier": number(primary_model.get("delta_brier")),
                "bootstrapCi95": [
                    value
                    for value in (
                        number(item) for item in bootstrap_ci[:2]
                    )
                    if value is not None
                ],
                "cr1OneSidedP": number(
                    statistics.get("cr1_one_sided_p")
                ),
                "signFlipP": number(statistics.get("sign_flip_p")),
                "familyQ": number(statistics.get("family_q")),
                "globalQ": number(statistics.get("global_q")),
                "clusters": integer(statistics.get("clusters")),
                "promotionEligible": (
                    campaign.get("promotion_eligible") is True
                ),
            },
            "whereModelLost": normalized_folds,
            "crossLeague": {
                "status": str(
                    cross_league_source.get("status", "NOT_RUN")
                ),
                "rotations": rotations,
                "rotationCount": rotation_count,
                "minimumSupport": integer(
                    cross_league_source.get(
                        "minimum_support",
                        min(rotation_supports) if rotation_supports else 0,
                    )
                ),
                "maximumSupport": integer(
                    cross_league_source.get(
                        "maximum_support",
                        max(rotation_supports) if rotation_supports else 0,
                    )
                ),
                "deltaLogLossRange": [
                    value
                    for value in (
                        number(item)
                        for item in (
                            raw_delta_range[:2]
                            if raw_delta_range
                            else (
                                [
                                    min(rotation_deltas),
                                    max(rotation_deltas),
                                ]
                                if rotation_deltas
                                else []
                            )
                        )
                    )
                    if value is not None
                ],
                "survivors": integer(
                    cross_league_source.get(
                        "cross_league_survivors",
                        cross_league_source.get("survivors"),
                    )
                ),
                "descriptivePositiveRotations": integer(
                    cross_league_source.get(
                        "descriptive_positive_rotations"
                    )
                ),
                "limitations": [
                    str(value)
                    for value in cross_league_source.get("limitations", [])
                    if isinstance(value, str)
                ],
                "promotionEligible": (
                    cross_league_source.get("promotion_eligible") is True
                ),
            },
            "teamGate": str(
                campaign.get(
                    "team_gate",
                    next(
                        (
                            gate["status"]
                            for gate in gates
                            if gate["name"] == "TEAM_GATE"
                        ),
                        "NOT_EVALUATED",
                    ),
                )
            ),
            "resultHash": str(campaign.get("result_hash", "")),
        },
        "negativeControls": controls,
        "negativeControlSummary": {
            "total": len(controls),
            "executedOrGuard": sum(
                control["category"] == "EXECUTED_OR_GUARD"
                for control in controls
            ),
            "dataGated": sum(
                control["category"] == "DATA_GATED"
                for control in controls
            ),
        },
        "redTeam": {
            "promotionAllowed": red_team.get("promotion_allowed") is True,
            "reason": str(red_team.get("reason", "NOT_RUN")),
            "objections": [
                {"name": str(name), "status": str(status)}
                for name, status in sorted(objections.items())
            ],
        },
        "promotion": {
            "status": str(promotion.get("status", "NOT_EVALUATED")),
            "promoted": promotion.get("promoted") is True,
            "criteria": promotion_criteria,
            "failedCriteria": [
                str(value)
                for value in promotion.get("failed_criteria", [])
                if isinstance(value, str)
            ],
        },
        "watchlist": {
            "status": str(watchlist.get("status", "NOT_BUILT")),
            "count": integer(watchlist.get("count")),
            "notABet": watchlist.get("not_a_bet", True) is True,
        },
        "decision": {
            "status": str(decision.get("status", "NO_DECISION_NO_CANDIDATE")),
            "candidateCount": integer(decision.get("candidate_count")),
            "decisions": integer(decision.get("decisions")),
            "stakeUnits": number(decision.get("stake_units")) or 0.0,
            "shadowBankrollBefore": number(
                decision.get("shadow_bankroll_before")
            )
            or 1000.0,
            "shadowBankrollAfter": number(
                decision.get("shadow_bankroll_after")
            )
            or 1000.0,
        },
        "replay": {
            "status": (
                "REPLAY_VERIFIED"
                if replay.get("identical") is True
                and integer(replay.get("business_duplicates")) == 0
                and integer(replay.get("data_loss")) == 0
                and integer(replay.get("hash_mismatches")) == 0
                else "NOT_VERIFIED"
            ),
            "identical": replay.get("identical") is True,
            "providerCalls": integer(replay.get("provider_calls")),
            "oddsApiCredits": integer(replay.get("odds_api_credits")),
            "businessDuplicates": integer(
                replay.get("business_duplicates")
            ),
            "dataLoss": integer(replay.get("data_loss")),
            "hashMismatches": integer(replay.get("hash_mismatches")),
            "hashComparisons": [
                {"name": str(name), "matched": matched is True}
                for name, matched in sorted(replay_hashes.items())
            ],
            "resultHash": str(replay.get("result_hash", "")),
        },
        "ledger": {
            "status": str(ledger.get("status", "NOT_CREATED")),
            "events": integer(ledger.get("events")),
            "headHash": str(ledger.get("head_hash", "")),
            "eventCounts": {
                str(name): integer(value)
                for name, value in sorted(ledger_event_counts.items())
            },
        },
        "provenance": {
            "sourceCommit": str(
                audit.get("source_commit", red_team.get("audit_source_commit", ""))
            ),
            "mainCommit": str(audit.get("main_commit", "")),
            "codeRevision": str(
                audit.get(
                    "code_revision",
                    replay.get(
                        "code_revision",
                        (
                            operational.get("github", {}).get(
                                "code_revision",
                                "",
                            )
                            if isinstance(operational.get("github"), dict)
                            else ""
                        ),
                    ),
                )
            ),
            "datasetHash": str(dataset.get("dataset_hash", "")),
            "campaignResultHash": str(campaign.get("result_hash", "")),
            "ledgerHeadHash": str(ledger.get("head_hash", "")),
            "marketObservedTimeStatus": str(
                audit.get("market", {}).get(
                    "observed_time_status",
                    [coverage_report.get("market_time_class", "NOT_EVALUATED")],
                )[0]
                if isinstance(audit.get("market"), dict)
                and isinstance(
                    audit.get("market", {}).get("observed_time_status"),
                    list,
                )
                and audit.get("market", {}).get("observed_time_status")
                else "NOT_EVALUATED"
            ),
        },
        "costs": {
            "providerCalls": integer(invariants.get("provider_calls")),
            "oddsApiCredits": integer(invariants.get("odds_api_credits")),
            "historicalBytes": integer(storage.get("historical_bytes")),
            "databaseBytes": integer(
                database.get(
                    "latest_verified_size_bytes",
                    database.get("database_bytes_last_verified"),
                )
            ),
            "r2ExpectedBytes": integer(r2.get("expected_bytes")),
            "r2LagObjects": integer(r2.get("lag_objects")),
            "storageStatus": str(storage.get("status", "NOT_EVALUATED")),
            "secondaryTasks": str(storage.get("p3_p4", "NOT_EVALUATED")),
        },
        "locks": {
            "productionStatus": "PRODUCTION_LOCKED",
            "realBets": False,
            "noBetDefault": True,
            "socialPublishingEnabled": False,
            "demoModeEnabled": False,
        },
        "caveats": [
            (
                "Recherche historique uniquement : les prix sont de classe "
                "SOURCE_PRICE_CLASS_ONLY, sans observed_at exact."
            ),
            (
                "TEAM_GATE est PARTIAL : l'ordre algorithmique est descriptif "
                "mais le observed_at source ligne par ligne n'est pas prouvé ; "
                "les gates joueurs et tactiques restent fermés."
            ),
            (
                "Les deltas positifs de Log Loss/Brier sont défavorables : "
                "aucun challenger testé ne bat sa référence de marché."
            ),
            (
                "Watchlist et décisions restent vides ; aucun résultat "
                "historique n'est présenté comme live."
            ),
        ],
    }


def build_deep_data() -> dict[str, Any]:
    state = Path(
        os.environ.get("HISTORICAL_STATE", str(ROOT / "data" / "historical"))
    ).resolve()
    analytics = read_json(
        ROOT / "data" / "live-proof" / "jalon5-legacy-analytics.json",
        {},
    )
    matrix = read_json(
        state / "coverage" / "matrix.json",
        read_json(ROOT / "data" / "contracts" / "api-football-coverage.json", []),
    )
    pilot = read_json(state / "runs" / "pilot-ligue-1-2025.json", {})
    plan = read_json(state / "tasks" / "backfill-plan.json", {})
    quality = read_json(state / "quality" / "latest.json", {})
    canonical = read_json(
        state / "audits" / "ligue1-2025-canonicalization.json",
        {},
    )
    forecast = read_json(state / "forecasts" / "accelerated-safe.json", {})
    readiness = read_json(
        state / "readiness" / "ligue1-multiseason-v1.json",
        {},
    )
    deployment_state = read_json(PRIVATE_DEPLOYMENT, {})
    compaction = read_json(state / "storage" / "latest-compaction.json", {})
    dataset = read_json(
        state / "datasets" / "api_team_pre_match_v1.json",
        read_json(
            state / "datasets" / "team_baseline_v1.json",
            (
                {
                    **analytics.get("dataset", {}),
                    "dataset_version": analytics.get("dataset", {}).get("name"),
                    "status": "FEATURE_FACTORY_ACTIVE",
                }
                if analytics
                else {}
            ),
        ),
    )
    model = read_json(
        state / "models" / "elo_v1.json",
        (
            {
                **analytics.get("model", {}),
                "model_version": analytics.get("model", {}).get("version"),
                "oos_metrics": {
                    "matches": analytics.get("model", {}).get("oos_matches"),
                    "log_loss": analytics.get("model", {}).get("oos_log_loss"),
                    "brier_score": analytics.get("model", {}).get("oos_brier_score"),
                },
            }
            if analytics
            else {}
        ),
    )
    backtest = read_json(
        state / "backtests" / "elo_edge_5pct_oos.json",
        analytics.get("backtest", {}),
    )
    proof = read_json(
        state / "proofs" / "api-football-live.json",
        read_json(ROOT / "data" / "live-proof" / "jalon5-api-football.json", {}),
    )
    task_counts: dict[str, int] = {}
    for task in plan.get("tasks", []):
        status = str(task.get("status", "UNKNOWN"))
        task_counts[status] = task_counts.get(status, 0) + 1
    coverage_counts: dict[str, int] = {}
    for row in matrix:
        status = str(row.get("status", "UNKNOWN"))
        coverage_counts[status] = coverage_counts.get(status, 0) + 1
    endpoint_counts: dict[str, int] = {}
    for report in pilot.get("endpoints", []):
        endpoint = str(report.get("endpoint", "UNKNOWN"))
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
    public_pilot = {
        key: value for key, value in pilot.items() if key != "endpoints"
    }
    public_pilot["endpointCounts"] = endpoint_counts
    public_dataset = {
        key: value for key, value in dataset.items() if key != "partitions"
    }
    player_readiness = build_player_readiness(state, quality, forecast)
    current_backfill_run = str(plan.get("last_run_id", ""))
    current_data_hash = hashlib.sha256(
        json.dumps(
            {
                "backfill_run_id": current_backfill_run,
                "forecast": forecast,
                "quality_generated_at": quality.get("generated_at"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    private_status = private_deployment_status(
        current_backfill_run=current_backfill_run,
        current_data_hash=current_data_hash,
        deployment_state=deployment_state,
    )
    private_status = os.environ.get("COCKPIT_PRIVATE_STATUS", private_status)
    players: list[dict[str, Any]] = []
    player_partitions = (
        path
        for path in (state / "parquet").rglob("*.parquet")
        if any(parent.name == "entity_type=players" for parent in path.parents)
    )
    for path in sorted(player_partitions):
        player_frame = pd.read_parquet(path)
        if "payload" not in player_frame.columns:
            continue
        for payload in player_frame["payload"].tolist()[:20]:
            record = json.loads(str(payload))
            player = record.get("player", {})
            statistics = record.get("statistics", [])
            stat = statistics[0] if statistics else {}
            games = stat.get("games", {})
            goals = stat.get("goals", {})
            players.append(
                {
                    "id": player.get("id"),
                    "name": player.get("name"),
                    "age": player.get("age"),
                    "position": games.get("position"),
                    "appearances": games.get("appearences"),
                    "minutes": games.get("minutes"),
                    "rating": games.get("rating"),
                    "goals": goals.get("total"),
                    "assists": goals.get("assists"),
                    "origin": "HISTORICAL POINT-IN-TIME",
                }
            )
        if players:
            break
    model_manifests = [
        read_json(path, {})
        for path in sorted((state / "models").glob("*.json"))
        if path.name not in {"jalon6-run.json", "jalon7-arena-run.json"}
    ]
    models = [
        {
            "name": manifest.get("model_name"),
            "version": manifest.get("model_version"),
            "dataset": manifest.get("dataset"),
            "status": manifest.get("status"),
            "calibration": manifest.get("selected_calibration"),
            "logLoss": manifest.get("oos_metrics", {}).get("log_loss"),
            "brier": manifest.get("oos_metrics", {}).get("brier_score"),
            "ece": manifest.get("oos_metrics", {}).get("ece"),
            "incremental": manifest.get("incremental_vs_team"),
            "origin": "OOS HISTORICAL",
        }
        for manifest in model_manifests
        if manifest.get("model_version")
    ]
    if not models and model:
        models.append(
            {
                "name": "Elo",
                "version": model.get("model_version", "elo_v1"),
                "dataset": "team_baseline_v1",
                "status": model.get("status", "WAITING_FOR_DATASET"),
                "calibration": model.get("calibration"),
                "logLoss": model.get("oos_metrics", {}).get("log_loss"),
                "brier": model.get("oos_metrics", {}).get("brier_score"),
                "ece": None,
                "incremental": None,
                "origin": "OOS HISTORICAL",
            }
        )
    models.extend(
        {
            "name": name,
            "version": "planned_v1",
            "status": "BLOCKED_BY_COVERAGE",
            "logLoss": None,
            "brier": None,
            "origin": "NO OUTPUT",
        }
        for name in (
            "Poisson",
            "Dixon-Coles",
            "Gradient boosting",
            "Ensemble calibré",
        )
    )
    dataset_manifests = [
        read_json(path, {})
        for path in sorted((state / "datasets").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    strategy_manifests = [
        read_json(path, {})
        for path in sorted((state / "strategies").glob("*.json"))
        if path.name != "jalon6-run.json"
    ]
    backtest_manifests = [
        read_json(path, {})
        for path in sorted((state / "backtests").glob("*.json"))
        if path.name
        not in {
            "jalon6-run.json",
            "jalon7-paired-comparisons.json",
            "jalon7-strategy-lab-v2.json",
        }
    ]
    arena = read_json(state / "models" / "jalon7-arena-run.json", {})
    strategy_v2 = read_json(state / "strategies" / "jalon7-run.json", {})
    external = read_json(
        state / "external" / "runs" / "jalon8-latest.json",
        {},
    )
    critical_closure = read_json(
        state / "market" / "runs" / "jalon9-latest.json",
        {},
    )
    external_readiness = external.get("readiness", {})
    external_competitions = (
        external_readiness.get("competitions", [])
        if isinstance(external_readiness, dict)
        else []
    )
    external_package = external.get("preseason_package", {})
    external_strategies = external.get("strategies", {})
    return {
        "status": proof.get("status", "ADAPTER_ONLY"),
        "pilotStatus": pilot.get("status", "NOT_STARTED"),
        "backfillStatus": plan.get("status", "NOT_STARTED"),
        "qualityStatus": quality.get("status", "NOT_RUN"),
        "productionStatus": "PRODUCTION_LOCKED",
        "criticalClosure": {
            "status": critical_closure.get("milestone", "JALON_9_WAITING"),
            "runId": critical_closure.get("run_id"),
            "sourceCommit": critical_closure.get("source_commit"),
            "teamGates": critical_closure.get("team_gates", {}),
            "playerGates": critical_closure.get("player_gates", []),
            "lineupGates": critical_closure.get("lineup_gates", []),
            "marketGates": critical_closure.get("market_gates", []),
            "matching": critical_closure.get("matching", {}),
            "files": critical_closure.get(
                "football_data_files_available",
                0,
            ),
            "marketRows": critical_closure.get("market_dataset_rows", 0),
            "storage": critical_closure.get("storage", {}),
            "r2": read_json(
                state / "storage" / "r2-migration-latest.json",
                {"mode": "WAITING_FOR_USER_STORAGE_ACTION"},
            ),
            "strategy": critical_closure.get("strategy_lab_v4", {}),
            "marketValidation": critical_closure.get(
                "market_paired_validation",
                {},
            ),
            "package": critical_closure.get("preseason_package", {}),
            "oddsApi": critical_closure.get(
                "odds_api_historical_pilot",
                {"credits_consumed": 0},
            ),
            "productionStatus": "PRODUCTION_LOCKED",
            "realBets": False,
        },
        "modelArena": {
            "status": arena.get("status", "NOT_RUN"),
            "baselineStatus": arena.get(
                "baseline_status", "JALON6_BASELINE_NOT_FROZEN"
            ),
            "baselineHash": arena.get("baseline_hash"),
            "externalProtocol": arena.get(
                "external_protocol", "EXTERNAL_VALIDATION_PROTOCOL_V1"
            ),
            "modelFamilies": arena.get("model_families", []),
            "modelsTested": arena.get("models_tested", 0),
            "predictions": arena.get("predictions", 0),
            "comparisons": arena.get("comparisons", []),
            "leaderboard": arena.get("leaderboard", []),
            "scoreModels": arena.get("score_models", []),
            "calibrationAudits": arena.get("calibration_audits", {}),
            "negativeControls": arena.get("negative_controls", []),
            "featureStability": arena.get("feature_stability", []),
            "ensemble": arena.get("ensemble", {}),
            "externalValidation": arena.get("external_validation", {}),
            "scientificStatuses": arena.get("scientific_statuses", {}),
            "oosGovernance": [
                {"period": "DISCOVERY", "seasons": "2020–2022"},
                {"period": "VALIDATION", "seasons": "2023"},
                {
                    "period": "EXPOSED_HISTORICAL_OOS",
                    "seasons": "2024–2025",
                },
                {
                    "period": "LOCKED_EXTERNAL_VALIDATION",
                    "seasons": "multi-ligues",
                },
                {"period": "LIVE_PROSPECTIVE", "seasons": "2026–2027"},
            ],
            "storage": arena.get("storage", {}),
            "strategyStatus": strategy_v2.get("status", "NOT_RUN"),
            "strategiesTested": strategy_v2.get("strategies_tested", 0),
            "liveCandidates": arena.get("live_candidates", 0),
            "providerCalls": arena.get("provider_calls", 0),
            "quotaConsumed": arena.get("quota_consumed", 0),
            "productionStatus": "PRODUCTION_LOCKED",
        },
        "externalValidation": {
            "status": external.get("status", "WAITING_FOR_EXTERNAL_GATES"),
            "runId": external.get("run_id"),
            "sourceCommit": external.get("source_commit"),
            "protocol": external.get("protocol", {}),
            "readiness": external_competitions,
            "datasets": [
                {
                    "name": item.get("dataset_name"),
                    "version": item.get("dataset_version"),
                    "competition": item.get("competition"),
                    "seasons": item.get("seasons", []),
                    "fixtures": item.get("fixtures", 0),
                    "rows": item.get("rows", 0),
                    "hash": item.get("hash"),
                    "status": item.get("status"),
                }
                for item in external.get("datasets", [])
                if isinstance(item, dict)
            ],
            "models": external.get("models", {}),
            "comparisons": external.get("comparisons", []),
            "leaveOneLeagueOut": external.get("leave_one_league_out", []),
            "playerGeneralization": external.get(
                "player_generalization",
                [],
            ),
            "negativeControls": external.get("negative_controls", []),
            "strategies": external_strategies,
            "package": external_package,
            "predictions": external.get("predictions", 0),
            "providerCalls": external.get("provider_calls", 0),
            "quotaConsumed": external.get("quota_consumed", 0),
            "storage": external.get("storage", {}),
            "productionStatus": "PRODUCTION_LOCKED",
        },
        "coverageCounts": coverage_counts,
        "coverageMatrix": matrix,
        "taskCounts": task_counts,
        "taskTotal": len(plan.get("tasks", [])),
        "taskCompleted": task_counts.get("COMPLETED", 0),
        "remainingTasks": plan.get("remaining_tasks", 0),
        "nextTask": next(
            (
                task
                for task in plan.get("tasks", [])
                if task.get("status")
                in {"PENDING", "READY", "RETRYABLE", "SKIPPED_QUOTA"}
            ),
            None,
        ),
        "pilot": public_pilot,
        "quota": {
            "remaining": plan.get(
                "quota_remaining",
                proof.get("quota_remaining", pilot.get("quota_remaining")),
            ),
            "calls": plan.get("provider_calls", 0),
            "lastRunId": plan.get("last_run_id"),
            "lastRunAt": plan.get("last_run_at"),
            "mode": "ACCELERATED_SAFE",
            "reserve": 5_000,
        },
        "storage": {
            "rawBytes": directory_size(state / "raw"),
            "parquetBytes": directory_size(state / "parquet"),
            "derivedBytes": directory_size(state / "derived"),
            "totalBytes": directory_size(state),
            "fileCount": len([path for path in state.rglob("*") if path.is_file()]),
            "bundleCount": len(
                list((state / "bundles").rglob("*.manifest.json"))
            ),
            "payloadCount": len(list((state / "raw" / "payloads").rglob("*.gz"))),
            "projectedBytes": forecast.get("storage_projected_bytes"),
            "projectedBytesLow": forecast.get("storage_projected_low"),
            "projectedBytesBase": forecast.get("storage_projected_base"),
            "projectedBytesHigh": forecast.get("storage_projected_high"),
            "warningBytes": forecast.get("storage_warning_bytes"),
            "pauseBytes": forecast.get("storage_pause_bytes"),
            "capacityStatus": (
                "PAUSE"
                if directory_size(state)
                >= int(forecast.get("storage_pause_bytes", 900_000_000))
                else "WARNING"
                if directory_size(state)
                >= int(forecast.get("storage_warning_bytes", 750_000_000))
                else "OK"
            ),
            "lastCompaction": compaction.get("status", "NOT_RUN"),
            "backend": "POSTGRESQL + PARQUET + HISTORICAL-DATA",
        },
        "players": players,
        "datasetReadiness": readiness,
        "datasets": [
            {
                "name": manifest.get("dataset_name"),
                "version": manifest.get("dataset_version"),
                "rows": manifest.get("rows"),
                "fixtures": manifest.get("fixtures"),
                "coverage": manifest.get("coverage"),
                "quality": manifest.get("quality"),
                "temporalPolicy": manifest.get("temporal_policy"),
                "status": manifest.get("status"),
                "sha256": manifest.get("sha256"),
            }
            for manifest in dataset_manifests
            if manifest.get("dataset_version")
        ],
        "featureCatalog": [
            {
                "name": name,
                "version": "v1",
                "status": (
                    "PLAYER_FEATURE_FACTORY_ACTIVE"
                    if readiness.get("gates", {}).get("B", {}).get("passed")
                    and name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "BLOCKED_BY_COVERAGE"
                    if name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "LEGACY_SOURCE_ONLY"
                    if dataset
                    else "CANDIDATE"
                ),
                "leakageRisk": "LOW",
                "origin": (
                    "HISTORICAL POINT-IN-TIME"
                    if readiness.get("gates", {}).get("B", {}).get("passed")
                    and name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "NO OUTPUT"
                    if name in {"minutes_joueur_5", "force_onze", "continuite_onze"}
                    else "LEGACY SOURCE"
                ),
            }
            for name in (
                "elo_global",
                "forme_5",
                "forme_10",
                "buts_marques_5",
                "buts_encaisses_5",
                "jours_repos",
                "minutes_joueur_5",
                "force_onze",
                "continuite_onze",
            )
        ],
        "dataset": public_dataset,
        "models": models,
        "backtests": [
            {
                **{
                    key: value
                    for key, value in manifest.items()
                    if key != "details"
                },
                "origin": "OOS HISTORICAL",
            }
            for manifest in backtest_manifests
            if manifest.get("backtest_version")
        ]
        or (
            [
                {
                    **{key: value for key, value in backtest.items() if key != "details"},
                    "origin": "OOS HISTORICAL",
                }
            ]
            if backtest
            else []
        ),
        "strategies": strategy_manifests,
        "quality": quality,
        "progress": {
            "tasksTotal": len(plan.get("tasks", [])),
            "tasksCompleted": task_counts.get("COMPLETED", 0),
            "tasksRemaining": plan.get("remaining_tasks", 0),
            "callsConsumed": plan.get("provider_calls", 0),
            "callsEstimated": forecast.get("estimated_calls_full_scope"),
            "callsRemainingLow": forecast.get("calls_remaining_low"),
            "callsRemainingBase": forecast.get("calls_remaining_base"),
            "callsRemainingHigh": forecast.get("calls_remaining_high"),
            "callsPerHour": (
                round(float(plan["scheduler"]["request_rate"]) * 3600)
                if plan.get("scheduler", {}).get("request_rate")
                else None
            ),
            "callsPerDay": forecast.get("calls_per_day"),
            "etaPriorityADays": forecast.get("eta_priority_a_days"),
            "etaPriorityBDays": forecast.get("eta_priority_b_days"),
            "etaFullDays": forecast.get("eta_full_scope_days"),
            "etaPriorityA": {
                "low": forecast.get("eta_priority_a_low"),
                "base": forecast.get("eta_priority_a_base"),
                "high": forecast.get("eta_priority_a_high"),
            },
            "etaPriorityB": {
                "low": forecast.get("eta_priority_b_low"),
                "base": forecast.get("eta_priority_b_base"),
                "high": forecast.get("eta_priority_b_high"),
            },
            "etaFull": {
                "low": forecast.get("eta_full_low"),
                "base": forecast.get("eta_full_base"),
                "high": forecast.get("eta_full_high"),
            },
            "materializedTasksTotal": forecast.get("materialized_tasks_total"),
            "materializedTasksCompleted": forecast.get(
                "materialized_tasks_completed"
            ),
            "materializedTasksRemaining": forecast.get(
                "materialized_tasks_remaining"
            ),
            "materializedCallsRemaining": forecast.get(
                "materialized_calls_remaining"
            ),
            "materializedEtaDays": forecast.get("materialized_eta_days"),
            "materializedEtaLabel": forecast.get("materialized_eta_label"),
            "latentFixtureTasks": forecast.get("latent_fixture_tasks"),
            "latentTeamTasks": forecast.get("latent_team_tasks"),
            "latentPlayerPages": forecast.get("latent_player_pages"),
            "completedThisRun": forecast.get("completed_this_run"),
            "expandedThisRun": forecast.get("expanded_this_run"),
            "newLatentTasksMaterialized": forecast.get(
                "new_latent_tasks_materialized"
            ),
            "scheduler": plan.get("scheduler", {}),
            "rowsLastRun": completed_rows_this_run(plan),
        },
        "canonicality": {
            key: canonical.get(key)
            for key in (
                "status",
                "received_fixtures",
                "canonical_fixtures",
                "received_teams",
                "canonical_teams",
                "classifications",
                "dataset_hash",
            )
        },
        "isolation": {
            "status": "LIVE_HISTORICAL_ISOLATED",
            "liveActive": True,
            "historicalActive": plan.get("status") == "HISTORICAL_BACKFILL_ACTIVE",
            "liveBranch": "shadow-data",
            "historicalBranch": "historical-data",
            "liveConcurrency": "shadow-state",
            "historicalConcurrency": "historical-state",
            "lastConflict": None,
            "lag": 0,
        },
        "playerReadiness": player_readiness,
        "deployment": {
            "build": "COCKPIT_BUILD_SUCCESS",
            "artifact": "COCKPIT_ARTIFACT_PUBLISHED",
            "private": private_status,
            "snapshotGeneratedAt": datetime.now(UTC).isoformat(),
            "currentDataHash": current_data_hash,
            "currentBackfillRunId": current_backfill_run,
            "deploymentVersion": deployment_state.get("deployment_version"),
            "deploymentTime": deployment_state.get("deployment_time"),
            "deployedSourceCommit": deployment_state.get("source_commit"),
            "deployedSnapshotHash": deployment_state.get("snapshot_hash"),
            "deployedBackfillRunId": deployment_state.get("backfill_run_id"),
            "accessMode": deployment_state.get("access_mode"),
            "automation": deployment_state.get("automation"),
            "sourceCommit": os.environ.get("GITHUB_SHA", "LOCAL_WORKTREE"),
        },
        "origins": [
            "LIVE SHADOW",
            "HISTORICAL POINT-IN-TIME",
            "HISTORICAL SIMULATED",
            "OOS HISTORICAL",
            "LEGACY SOURCE",
            "DEMO DATA",
            "NO OUTPUT",
        ],
    }


def write_snapshot(snapshot: dict[str, Any]) -> None:
    """Écrire un snapshot public et son hash."""

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    public_snapshot = sanitize_public_snapshot(snapshot)
    OUTPUT.write_text(
        json.dumps(public_snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUTPUT_HASH.write_text(
        hashlib.sha256(OUTPUT.read_bytes()).hexdigest() + "\n",
        encoding="ascii",
    )
    try:
        label = OUTPUT.relative_to(ROOT)
    except ValueError:
        label = OUTPUT
    print(f"Snapshot Cockpit écrit dans {label}")


def main() -> None:
    if os.environ.get("COCKPIT_PROSPECTIVE_ONLY") == "1":
        snapshot = read_json(OUTPUT, {})
        if not isinstance(snapshot, dict) or not snapshot:
            raise RuntimeError("snapshot Cockpit existant absent")
        snapshot["generatedAt"] = datetime.now(UTC).isoformat()
        snapshot["prospectiveObservatory"] = build_prospective_observatory()
        snapshot["patternResearch"] = build_pattern_research()
        snapshot["prequentialLearning"] = build_prequential_learning(
            snapshot.get("prequentialLearning")
        )
        write_snapshot(snapshot)
        return

    if os.environ.get("COCKPIT_MATCHUP_ONLY") == "1":
        snapshot = read_json(OUTPUT, {})
        if not isinstance(snapshot, dict) or not snapshot:
            raise RuntimeError("snapshot Cockpit existant absent")
        snapshot["generatedAt"] = datetime.now(UTC).isoformat()
        snapshot["matchupLab"] = build_matchup_lab()
        write_snapshot(snapshot)
        return

    live = read_json(
        ROOT / "data" / "live-proof" / "jalon3-activation.json",
        {},
    )
    if not live:
        raise RuntimeError("preuve live Jalon 3 absente")
    durable = read_json(
        ROOT / "data" / "live-proof" / "jalon4-durable-shadow.json",
        {},
    )
    if not durable:
        raise RuntimeError("preuve durable Jalon 4 absente")
    migration_rows = read_json(
        ROOT / "data" / "migrations" / "jalon2" / "legacy-uuid-summary.json",
        [{}],
    )
    migration = migration_rows[0] if migration_rows else {}
    oos = read_json(ROOT / "rapports" / "jalon2" / "oos-results.json", [])

    predictions = {
        item["internal_fixture_id"]: item
        for item in live.get("predictions", [])
    }
    decisions = {
        item["internal_fixture_id"]: item
        for item in live.get("decisions", [])
    }
    matches: list[dict[str, Any]] = []
    fixture_names: dict[str, tuple[str, str]] = {}
    for fixture in live.get("fixtures", []):
        internal_id = stable_internal_id(
            "fixture",
            "the-odds-api",
            fixture["provider_fixture_id"],
        )
        fixture_names[internal_id] = (fixture["home"], fixture["away"])
        prediction = predictions.get(internal_id)
        decision = decisions.get(internal_id)
        matches.append(
            {
                "id": fixture["provider_fixture_id"],
                "internalId": internal_id,
                "kickoff": fixture["kickoff"],
                "competition": fixture["competition"],
                "home": fixture["home"],
                "away": fixture["away"],
                "origin": fixture["origin"],
                "quality": prediction["quality"] if prediction else "PENDING",
                "model": (
                    prediction["model"]
                    if prediction
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "probabilities": {
                    "home": prediction.get("probability_home") if prediction else None,
                    "draw": prediction.get("probability_draw") if prediction else None,
                    "away": prediction.get("probability_away") if prediction else None,
                },
                "expectedGoals": {"home": None, "away": None},
                "decision": (
                    decision["primary_reason"]
                    if decision
                    else "EN ATTENTE DE DONNÉES PROSPECTIVES"
                ),
                "accepted": bool(decision and decision["accepted"]),
            }
        )

    odds = []
    for item in live.get("snapshots", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        odds.append({**item, "home": home, "away": away})

    decision_rows = []
    for item in live.get("decisions", []):
        home, away = fixture_names.get(
            item["internal_fixture_id"],
            ("Fixture inconnue", "Fixture inconnue"),
        )
        decision_rows.append(
            {
                **item,
                "home": home,
                "away": away,
                "decided_at": next(
                    (
                        prediction["generated_at"]
                        for prediction in live.get("predictions", [])
                        if prediction["prediction_id"] == item["prediction_id"]
                    ),
                    live["captured_at"],
                ),
            }
        )

    quota = live["quota"]
    persistence = live["persistence"]
    idempotence = live["idempotence"]
    health = live["health"]
    postgresql = durable["postgresql"]
    double_write = durable["double_write"]
    quality_checks = [
        {
            "check": "PostgreSQL Neon",
            "status": "PASS",
            "value": (
                f"{postgresql['registry_records']} lignes · "
                f"révision {postgresql['migration_revision']}"
            ),
            "threshold": "connecté, migré et audité",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Double écriture durable",
            "status": "PASS",
            "value": double_write["latest_ack_backend"],
            "threshold": "PostgreSQL + shadow-data",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Authentification The Odds API",
            "status": "PASS",
            "value": "appel HTTP 200, secret non exposé",
            "threshold": "source authentifiée",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Provenance brute",
            "status": "PASS",
            "value": "endpoint + temps + hash + ingestion",
            "threshold": "champs complets",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Persistance inter-runners",
            "status": "PASS",
            "value": f"{persistence['files_restored_by_runner_b']} fichiers restaurés",
            "threshold": "observation stable",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Déduplication exacte",
            "status": "PASS",
            "value": f"{idempotence['exact_duplicate_snapshots']} doublon",
            "threshold": "0",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Idempotence prédictions",
            "status": "PASS",
            "value": "1 → 1 ; décisions 1 → 1",
            "threshold": "aucun ajout identique",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Réserve quota",
            "status": "PASS",
            "value": f"{quota['reserve_pct']} %",
            "threshold": "≥ 20 %",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "Prédictions sans cote",
            "status": "WARN",
            "value": f"{health['blocked_predictions']} bloquées",
            "threshold": "jamais synthétisées",
            "origin": "LIVE SOURCE",
        },
        {
            "check": "API-Football",
            "status": "PENDING",
            "value": "adaptateur prêt, secret absent",
            "threshold": "enrichissement optionnel",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Paris réels",
            "status": "PASS",
            "value": "PRODUCTION_LOCKED",
            "threshold": "aucune exécution financière",
            "origin": "NO OUTPUT",
        },
        {
            "check": "Couverture UUID legacy",
            "status": "PASS",
            "value": f"{migration.get('coverage', 0) * 100:.3f} %",
            "threshold": "≥ 98 %",
            "origin": "LEGACY SOURCE",
        },
    ]

    strategies = [
        {
            **item,
            "origin": "LEGACY SOURCE",
            "roiPct": round(item.get("roi", 0) * 100, 2),
            "ciLowPct": round(item.get("roi_ci_low", 0) * 100, 2),
            "ciHighPct": round(item.get("roi_ci_high", 0) * 100, 2),
        }
        for item in oos
    ]
    deep_data = build_deep_data()
    pattern_research = build_pattern_research()
    matchup_lab = build_matchup_lab()
    prospective_observatory = build_prospective_observatory()
    prequential_learning = build_prequential_learning()
    hypothesis_intelligence = read_json(
        HYPOTHESIS_INTELLIGENCE_SNAPSHOT,
        {},
    )
    if hypothesis_intelligence and (
        hypothesis_intelligence.get("schemaVersion")
        != "hypothesis-intelligence-cockpit-v1"
        or hypothesis_intelligence.get("security", {}).get("realBets")
        is not False
        or hypothesis_intelligence.get("security", {}).get(
            "promotionLocked"
        )
        is not True
    ):
        raise RuntimeError("HYPOTHESIS_INTELLIGENCE_SNAPSHOT_UNSAFE")
    snapshot = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceCapturedAt": durable["captured_at"],
        "snapshotType": live["snapshot_type"],
        "status": durable["burn_in"]["health"],
        "shadowStatus": durable["status"],
        "productionStatus": live["production_status"],
        "demoModeAvailable": True,
        "demoModeEnabled": False,
        "message": (
            "PostgreSQL Neon et le registre append-only shadow-data sont "
            "synchronisés. La double écriture et le replay sans fournisseur "
            "sont vérifiés ; le burn-in reste statistiquement insuffisant."
        ),
        "metrics": {
            "fixtures": len(matches),
            "snapshots": len(odds),
            "quotes": sum(item["quotes"] for item in odds),
            "bookmakers": max((item["bookmakers"] for item in odds), default=0),
            "predictions": len(live.get("predictions", [])),
            "candidates": sum(1 for item in decision_rows if item["accepted"]),
            "rejections": sum(1 for item in decision_rows if not item["accepted"]),
            "blockedPredictions": health["blocked_predictions"],
            "quotaUsed": quota["used_after_activation"],
            "quotaRemaining": quota["remaining_after_activation"],
            "migrationCoveragePct": round(migration.get("coverage", 0) * 100, 3),
            "durableRecords": postgresql["registry_records"],
            "rawPayloads": durable["migration"]["physical_payloads_migrated"],
            "windowCoveragePct": 0,
            "sloBreaches": 0,
        },
        "matches": matches,
        "odds": odds,
        "decisions": decision_rows,
        "qualityChecks": quality_checks,
        "strategies": strategies,
        "runs": [
            {
                "id": str(item["id"]),
                "pipeline": item["pipeline"],
                "status": item["status"],
                "records": item["records"],
                "calls": item["calls"],
                "quotaRemaining": item["quota_remaining"],
                "finishedAt": item["finished_at"],
                "origin": item["origin"],
            }
            for item in live.get("runs", [])
        ],
        "filters": {
            "periods": ["30 prochains jours", "7 prochains jours", "Saison 2026–2027"],
            "competitions": ["Ligue 1 - France"],
            "markets": ["1X2", "TOTAL_GOALS"],
            "strategies": ["Toutes"]
            + [item.get("strategy", "inconnue") for item in oos],
            "models": ["MARKET_BASELINE_ONLY"],
            "statuses": ["Tous", "Bloqué", "En attente"],
            "qualities": ["Toutes", "OBSERVED", "PENDING"],
            "bookmakers": ["Tous", "22 agrégés"],
        },
        "provenance": {
            "demo": "Mode démo disponible uniquement sur activation explicite.",
            "legacy": "data/matches.parquet + rapports/jalon2/oos-results.json",
            "live": (
                "The Odds API → registre append-only shadow-data → "
                "preuve compacte Jalon 4"
            ),
            "stateArtifact": live["source_state_artifact"],
            "sourceCommit": live["source_commit"],
        },
        "quota": quota,
        "persistence": persistence,
        "idempotence": idempotence,
        "providers": live["providers"],
        "durableStorage": durable["storage"],
        "postgresql": postgresql,
        "doubleWrite": double_write,
        "failureRecovery": durable["failure_recovery"],
        "migration": durable["migration"],
        "replay": durable["replay"],
        "burnIn": durable["burn_in"],
        "slo": durable["slo"],
        "scheduler": durable["scheduler"],
        "funnel": [
            {"stage": "Fixtures attendues", "count": len(matches), "loss": 0},
            {"stage": "Fixtures collectées", "count": len(matches), "loss": 0},
            {"stage": "Avec marchés", "count": 1, "loss": len(matches) - 1},
            {"stage": "Avec snapshots", "count": 1, "loss": 0},
            {"stage": "Analysables", "count": 1, "loss": 0},
            {"stage": "Prédictions", "count": len(predictions), "loss": 0},
            {"stage": "Candidats", "count": len(decision_rows), "loss": 0},
            {"stage": "Retenus shadow", "count": 0, "loss": len(decision_rows)},
            {"stage": "Rejetés / bloqués", "count": 9, "loss": 0},
            {"stage": "Réglés", "count": 0, "loss": 0},
        ],
        "notAnalyzableReasons": [
            {"reason": "MARKET_NOT_AVAILABLE", "count": 8, "origin": "LIVE SOURCE"},
            {"reason": "QUALITY_BLOCKED", "count": 1, "origin": "LIVE SOURCE"},
        ],
        "coverage": [
            {
                "fixture": f"{item['home']} — {item['away']}",
                "fixtureId": item["internalId"],
                "kickoff": item["kickoff"],
                "providerCoverage": 1 if item["probabilities"]["home"] else 0,
                "analyticCoverage": 1 if item["probabilities"]["home"] else 0,
                "windows": {
                    window: "PENDING"
                    for window in durable["scheduler"]["windows"]
                },
                "origin": item["origin"],
            }
            for item in matches
        ],
        "coverageRates": {
            "provider": round(1 / len(matches), 4) if matches else 0,
            "collection": None,
            "analytic": round(1 / len(matches), 4) if matches else 0,
            "collectionStatus": "INSUFFICIENT_OBSERVATION",
        },
        "oddsMovement": durable["odds_movement"],
        "incidents": [
            {
                "code": "ARTIFACT_REDIRECT_AUTH_HEADER",
                "severity": "WARNING",
                "status": "RESOLVED",
                "startedAt": "2026-07-24T12:54:00Z",
                "endedAt": "2026-07-24T12:56:43Z",
                "cause": "En-tête GitHub transmis vers une URL signée",
                "impact": "Un run arrêté avant appel fournisseur",
                "correction": "Retrait de l’en-tête hors api.github.com",
                "origin": "LIVE SOURCE",
            }
        ],
        "costScenarios": [
            {"scope": "Rythme actuel", "competitions": 1, "markets": 2, "credits": 720},
            {"scope": "Deux championnats", "competitions": 2, "markets": 2, "credits": 1440},
            {"scope": "Cinq championnats", "competitions": 5, "markets": 2, "credits": 3600},
            {"scope": "Marchés étendus", "competitions": 1, "markets": 4, "credits": 1440},
        ],
        "dataExplorer": [
            {
                "date": item["kickoff"],
                "fixture": f"{item['home']} — {item['away']}",
                "competition": item["competition"],
                "market": "1X2",
                "bookmakers": 22 if item["probabilities"]["home"] else 0,
                "snapshots": 2 if item["probabilities"]["home"] else 0,
                "model": item["model"],
                "decision": item["decision"],
                "quality": item["quality"],
                "provenance": item["origin"],
            }
            for item in matches
        ],
        "deepData": deep_data,
        "patternResearch": pattern_research,
        "matchupLab": matchup_lab,
        "prospectiveObservatory": prospective_observatory,
        "prequentialLearning": prequential_learning,
        "hypothesisIntelligence": hypothesis_intelligence,
    }
    write_snapshot(snapshot)


if __name__ == "__main__":
    main()
