"""Public Evidence Ledger append-only, hashé et shadow-only."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, cast
from uuid import uuid4

GENESIS_HASH = "0" * 64
PRODUCTION_STATUS = "PRODUCTION_LOCKED"
REAL_BETS = False
NO_BET_DEFAULT = True
SOCIAL_PUBLISHING_ENABLED = False


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("UTC_TIMESTAMP_REQUIRED")
    return value.astimezone(UTC).isoformat()


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def record_hash(payload: dict[str, object]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "record_hash"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    published_at: str
    cutoff_at: str
    fixture_id: str
    competition: str
    kickoff_at: str
    market: str
    selection: str
    odds: float | None
    odds_source: str
    pattern_id: str | None
    pattern_version: str | None
    decision: str
    stake_units: float
    shadow_bankroll_before: float
    status: str
    code_revision: str
    dataset_hash: str
    previous_record_hash: str
    record_hash: str
    simulation: bool = True


@dataclass(frozen=True)
class SettlementRecord:
    settlement_id: str
    decision_id: str
    settled_at: str
    result: str
    profit_units: float
    shadow_bankroll_after: float
    previous_record_hash: str
    record_hash: str
    simulation: bool = True


class EvidenceLedger:
    def __init__(
        self,
        path: Path,
        *,
        initial_bankroll: float = 1000.0,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        if initial_bankroll <= 0:
            raise ValueError("SHADOW_BANKROLL_MUST_BE_POSITIVE")
        if lock_timeout_seconds <= 0:
            raise ValueError("LEDGER_LOCK_TIMEOUT_MUST_BE_POSITIVE")
        self.path = path
        self.initial_bankroll = float(initial_bankroll)
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self.lock_path = path.with_name(f"{path.name}.lock")

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Verrou inter-processus borné avec récupération prudente d'un verrou mort."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid4().hex
        deadline = time.monotonic() + self.lock_timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(descriptor, token.encode("ascii"))
                os.fsync(descriptor)
            except (FileExistsError, PermissionError):
                try:
                    age_seconds = time.time() - self.lock_path.stat().st_mtime
                    if age_seconds > 300.0:
                        self.lock_path.unlink()
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("LEDGER_EXCLUSIVE_LOCK_TIMEOUT") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                if self.lock_path.read_text("ascii") == token:
                    self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _records_unlocked(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.path.read_text("utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"LEDGER_RECORD_NOT_OBJECT:{line_number}")
            records.append(value)
        return records

    def _atomic_append_unlocked(self, payload: dict[str, object]) -> None:
        existing = self.path.read_bytes() if self.path.exists() else b""
        separator = b"" if not existing or existing.endswith(b"\n") else b"\n"
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(existing)
                stream.write(separator)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _timestamp(value: object, *, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"LEDGER_TIMESTAMP_INVALID:{field}") from None
        if parsed.tzinfo is None:
            raise ValueError(f"LEDGER_UTC_TIMESTAMP_REQUIRED:{field}")
        return parsed.astimezone(UTC)

    @staticmethod
    def _finite_number(value: object, *, field: str) -> float:
        try:
            converted = float(str(value))
        except (TypeError, ValueError):
            raise ValueError(f"LEDGER_NUMBER_INVALID:{field}") from None
        if not math.isfinite(converted):
            raise ValueError(f"LEDGER_NUMBER_INVALID:{field}")
        return converted

    def _audit_records(self, records: list[dict[str, Any]]) -> dict[str, object]:
        previous = GENESIS_HASH
        decisions: set[str] = set()
        settlements: set[str] = set()
        settled_decisions: set[str] = set()
        decision_records: dict[str, dict[str, Any]] = {}
        settlement_records: list[dict[str, Any]] = []
        current_bankroll = self.initial_bankroll
        bankroll_curve = [current_bankroll]
        maximum_drawdown = 0.0
        peak = current_bankroll

        for record in records:
            if record.get("previous_record_hash") != previous:
                raise ValueError("LEDGER_CHAIN_BROKEN")
            if record.get("record_hash") != record_hash(record):
                raise ValueError("LEDGER_HASH_MISMATCH")
            if record.get("simulation") is not True:
                raise ValueError("REAL_BET_RECORD_FORBIDDEN")
            record_type = record.get("record_type")
            if record_type == "DECISION":
                identity = str(record["decision_id"])
                if identity in decisions:
                    raise ValueError("DUPLICATE_DECISION")
                published_at = self._timestamp(
                    record.get("published_at"),
                    field="published_at",
                )
                cutoff_at = self._timestamp(
                    record.get("cutoff_at"),
                    field="cutoff_at",
                )
                kickoff_at = self._timestamp(
                    record.get("kickoff_at"),
                    field="kickoff_at",
                )
                if not published_at <= cutoff_at < kickoff_at:
                    raise ValueError("DECISION_NOT_FROZEN_BEFORE_KICKOFF")
                decision = str(record.get("decision"))
                if decision not in {"BET", "NO_BET", "NO_BET_DATA_UNAVAILABLE"}:
                    raise ValueError("INVALID_SHADOW_DECISION")
                stake = self._finite_number(
                    record.get("stake_units"),
                    field="stake_units",
                )
                expected_stake = 1.0 if decision == "BET" else 0.0
                if not math.isclose(stake, expected_stake, abs_tol=1e-9):
                    raise ValueError("LEDGER_STAKE_MISMATCH")
                if decision == "BET":
                    odds = self._finite_number(record.get("odds"), field="odds")
                    if odds <= 1.0 or record.get("pattern_id") in (None, ""):
                        raise ValueError("BET_REQUIRES_OBSERVED_ODDS_AND_PATTERN")
                bankroll_before = self._finite_number(
                    record.get("shadow_bankroll_before"),
                    field="shadow_bankroll_before",
                )
                if not math.isclose(
                    bankroll_before,
                    current_bankroll,
                    abs_tol=1e-9,
                ):
                    raise ValueError("LEDGER_BANKROLL_BEFORE_MISMATCH")
                if record.get("status") != "LIVE_SHADOW":
                    raise ValueError("LEDGER_DECISION_STATUS_INVALID")
                decisions.add(identity)
                decision_records[identity] = record
            elif record_type == "SETTLEMENT":
                identity = str(record["settlement_id"])
                decision_id = str(record["decision_id"])
                if identity in settlements:
                    raise ValueError("DUPLICATE_SETTLEMENT")
                if decision_id not in decisions:
                    raise ValueError("ORPHAN_SETTLEMENT")
                if decision_id in settled_decisions:
                    raise ValueError("DECISION_ALREADY_SETTLED")
                decision_record = decision_records[decision_id]
                if decision_record.get("decision") != "BET":
                    raise ValueError("NO_BET_CANNOT_BE_SETTLED")
                settled_at = self._timestamp(
                    record.get("settled_at"),
                    field="settled_at",
                )
                kickoff_at = self._timestamp(
                    decision_record.get("kickoff_at"),
                    field="kickoff_at",
                )
                if settled_at <= kickoff_at:
                    raise ValueError("SETTLEMENT_BEFORE_KICKOFF")
                result = str(record.get("result"))
                if result not in {"WIN", "LOSS", "VOID"}:
                    raise ValueError("INVALID_SETTLEMENT_RESULT")
                stake = self._finite_number(
                    decision_record.get("stake_units"),
                    field="stake_units",
                )
                odds = self._finite_number(
                    decision_record.get("odds"),
                    field="odds",
                )
                expected_profit = {
                    "WIN": odds - stake,
                    "LOSS": -stake,
                    "VOID": 0.0,
                }[result]
                profit = self._finite_number(
                    record.get("profit_units"),
                    field="profit_units",
                )
                if not math.isclose(profit, expected_profit, abs_tol=1e-9):
                    raise ValueError("SETTLEMENT_PROFIT_MISMATCH")
                expected_bankroll = current_bankroll + expected_profit
                bankroll_after = self._finite_number(
                    record.get("shadow_bankroll_after"),
                    field="shadow_bankroll_after",
                )
                if not math.isclose(
                    bankroll_after,
                    expected_bankroll,
                    abs_tol=1e-9,
                ):
                    raise ValueError("LEDGER_BANKROLL_AFTER_MISMATCH")
                current_bankroll = expected_bankroll
                bankroll_curve.append(current_bankroll)
                peak = max(peak, current_bankroll)
                maximum_drawdown = max(
                    maximum_drawdown,
                    peak - current_bankroll,
                )
                settlements.add(identity)
                settled_decisions.add(decision_id)
                settlement_records.append(record)
            else:
                raise ValueError("UNKNOWN_LEDGER_RECORD")
            previous = str(record["record_hash"])

        settled_stake = sum(
            self._finite_number(
                decision_records[str(settlement["decision_id"])].get(
                    "stake_units"
                ),
                field="stake_units",
            )
            for settlement in settlement_records
        )
        profit = current_bankroll - self.initial_bankroll
        return {
            "status": "LEDGER_VERIFIED",
            "records": len(records),
            "decisions": len(decisions),
            "settlements": len(settlements),
            "shadow_bets": sum(
                record.get("decision") == "BET"
                for record in decision_records.values()
            ),
            "no_bets": sum(
                record.get("decision") in {"NO_BET", "NO_BET_DATA_UNAVAILABLE"}
                for record in decision_records.values()
            ),
            "matches_analyzed": len(
                {
                    str(record["fixture_id"])
                    for record in decision_records.values()
                }
            ),
            "won": sum(
                record.get("result") == "WIN"
                for record in settlement_records
            ),
            "lost": sum(
                record.get("result") == "LOSS"
                for record in settlement_records
            ),
            "void": sum(
                record.get("result") == "VOID"
                for record in settlement_records
            ),
            "profit_units": profit,
            "settled_stake_units": settled_stake,
            "roi": profit / settled_stake if settled_stake else 0.0,
            "max_drawdown_units": maximum_drawdown,
            "bankroll_curve": bankroll_curve,
            "published_at": (
                max(
                    str(record["published_at"])
                    for record in decision_records.values()
                )
                if decision_records
                else None
            ),
            "last_record_hash": previous,
            "shadow_bankroll": current_bankroll,
            "production_status": PRODUCTION_STATUS,
            "real_bets": REAL_BETS,
            "no_bet_default": NO_BET_DEFAULT,
            "social_publishing_enabled": SOCIAL_PUBLISHING_ENABLED,
        }

    @staticmethod
    def _decision_record(record: dict[str, Any]) -> DecisionRecord:
        return DecisionRecord(
            decision_id=str(record["decision_id"]),
            published_at=str(record["published_at"]),
            cutoff_at=str(record["cutoff_at"]),
            fixture_id=str(record["fixture_id"]),
            competition=str(record["competition"]),
            kickoff_at=str(record["kickoff_at"]),
            market=str(record["market"]),
            selection=str(record["selection"]),
            odds=cast(float | None, record["odds"]),
            odds_source=str(record["odds_source"]),
            pattern_id=cast(str | None, record["pattern_id"]),
            pattern_version=cast(str | None, record["pattern_version"]),
            decision=str(record["decision"]),
            stake_units=float(record["stake_units"]),
            shadow_bankroll_before=float(record["shadow_bankroll_before"]),
            status=str(record["status"]),
            code_revision=str(record["code_revision"]),
            dataset_hash=str(record["dataset_hash"]),
            previous_record_hash=str(record["previous_record_hash"]),
            record_hash=str(record["record_hash"]),
            simulation=bool(record["simulation"]),
        )

    @staticmethod
    def _settlement_record(record: dict[str, Any]) -> SettlementRecord:
        return SettlementRecord(
            settlement_id=str(record["settlement_id"]),
            decision_id=str(record["decision_id"]),
            settled_at=str(record["settled_at"]),
            result=str(record["result"]),
            profit_units=float(record["profit_units"]),
            shadow_bankroll_after=float(record["shadow_bankroll_after"]),
            previous_record_hash=str(record["previous_record_hash"]),
            record_hash=str(record["record_hash"]),
            simulation=bool(record["simulation"]),
        )

    def append_decision(
        self,
        *,
        decision_id: str,
        published_at: datetime,
        cutoff_at: datetime,
        fixture_id: str,
        competition: str,
        kickoff_at: datetime,
        market: str,
        selection: str,
        odds: float | None,
        odds_source: str,
        pattern_id: str | None,
        pattern_version: str | None,
        decision: str,
        code_revision: str,
        dataset_hash: str,
    ) -> DecisionRecord:
        with self._exclusive_lock():
            records = self._records_unlocked()
            audit = self._audit_records(records)
            existing = next(
                (
                    record
                    for record in records
                    if record.get("decision_id") == decision_id
                ),
                None,
            )
            if existing is not None:
                candidate = self._decision_record(existing)
                replay_fields = (
                    candidate.published_at == _iso(published_at)
                    and candidate.cutoff_at == _iso(cutoff_at)
                    and candidate.fixture_id == str(fixture_id)
                    and candidate.competition == competition
                    and candidate.kickoff_at == _iso(kickoff_at)
                    and candidate.market == market
                    and candidate.selection == selection
                    and candidate.odds == odds
                    and candidate.odds_source == odds_source
                    and candidate.pattern_id == pattern_id
                    and candidate.pattern_version == pattern_version
                    and candidate.decision == decision
                    and candidate.code_revision == code_revision
                    and candidate.dataset_hash == dataset_hash
                )
                if replay_fields:
                    return candidate
                raise ValueError(
                    f"IMMUTABLE_LEDGER_RECORD_CONFLICT:{decision_id}"
                )
            stake = 1.0 if decision == "BET" else 0.0
            previous = str(audit["last_record_hash"])
            payload: dict[str, object] = {
                "record_type": "DECISION",
                "decision_id": decision_id,
                "published_at": _iso(published_at),
                "cutoff_at": _iso(cutoff_at),
                "fixture_id": str(fixture_id),
                "competition": competition,
                "kickoff_at": _iso(kickoff_at),
                "market": market,
                "selection": selection,
                "odds": odds,
                "odds_source": odds_source,
                "pattern_id": pattern_id,
                "pattern_version": pattern_version,
                "decision": decision,
                "stake_units": stake,
                "shadow_bankroll_before": float(
                    cast(float, audit["shadow_bankroll"])
                ),
                "status": "LIVE_SHADOW",
                "code_revision": code_revision,
                "dataset_hash": dataset_hash,
                "previous_record_hash": previous,
                "record_hash": "",
                "simulation": True,
            }
            payload["record_hash"] = record_hash(payload)
            self._audit_records(
                [*records, cast(dict[str, Any], payload)]
            )
            self._atomic_append_unlocked(payload)
            return self._decision_record(cast(dict[str, Any], payload))

    def append_settlement(
        self,
        *,
        settlement_id: str,
        decision_id: str,
        settled_at: datetime,
        result: str,
        profit_units: float,
    ) -> SettlementRecord:
        with self._exclusive_lock():
            records = self._records_unlocked()
            audit = self._audit_records(records)
            existing = next(
                (
                    record
                    for record in records
                    if record.get("settlement_id") == settlement_id
                ),
                None,
            )
            if existing is not None:
                candidate = self._settlement_record(existing)
                if (
                    candidate.decision_id == decision_id
                    and candidate.settled_at == _iso(settled_at)
                    and candidate.result == result
                    and candidate.profit_units == float(profit_units)
                ):
                    return candidate
                raise ValueError(
                    f"IMMUTABLE_LEDGER_RECORD_CONFLICT:{settlement_id}"
                )
            decisions = {
                str(record["decision_id"]): record
                for record in records
                if record.get("record_type") == "DECISION"
            }
            decision = decisions.get(decision_id)
            if decision is None:
                raise ValueError("SETTLEMENT_DECISION_NOT_FOUND")
            if decision["decision"] != "BET":
                raise ValueError("NO_BET_CANNOT_BE_SETTLED")
            if result not in {"WIN", "LOSS", "VOID"}:
                raise ValueError("INVALID_SETTLEMENT_RESULT")
            kickoff_at = self._timestamp(
                decision["kickoff_at"],
                field="kickoff_at",
            )
            if settled_at <= kickoff_at:
                raise ValueError("SETTLEMENT_BEFORE_KICKOFF")
            expected_profit = {
                "WIN": float(decision["odds"]) - float(decision["stake_units"]),
                "LOSS": -float(decision["stake_units"]),
                "VOID": 0.0,
            }[result]
            if not math.isclose(
                float(profit_units),
                expected_profit,
                abs_tol=1e-9,
            ):
                raise ValueError("SETTLEMENT_PROFIT_MISMATCH")
            if any(
                record.get("record_type") == "SETTLEMENT"
                and record.get("decision_id") == decision_id
                for record in records
            ):
                raise ValueError("DECISION_ALREADY_SETTLED")
            previous = str(audit["last_record_hash"])
            bankroll_after = float(
                cast(float, audit["shadow_bankroll"])
            ) + float(profit_units)
            payload: dict[str, object] = {
                "record_type": "SETTLEMENT",
                "settlement_id": settlement_id,
                "decision_id": decision_id,
                "settled_at": _iso(settled_at),
                "result": result,
                "profit_units": float(profit_units),
                "shadow_bankroll_after": bankroll_after,
                "previous_record_hash": previous,
                "record_hash": "",
                "simulation": True,
            }
            payload["record_hash"] = record_hash(payload)
            self._audit_records(
                [*records, cast(dict[str, Any], payload)]
            )
            self._atomic_append_unlocked(payload)
            return self._settlement_record(cast(dict[str, Any], payload))

    def audit(self) -> dict[str, object]:
        with self._exclusive_lock():
            return self._audit_records(self._records_unlocked())

    def bankroll(self) -> float:
        return float(cast(float, self.audit()["shadow_bankroll"]))


def records_to_dict(records: Iterable[DecisionRecord | SettlementRecord]) -> list[dict[str, object]]:
    return [asdict(record) for record in records]
