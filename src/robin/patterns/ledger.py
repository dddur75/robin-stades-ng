"""Public Evidence Ledger append-only, hashé et shadow-only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

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
    fixture_id: int
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
    def __init__(self, path: Path, *, initial_bankroll: float = 1000.0) -> None:
        if initial_bankroll <= 0:
            raise ValueError("SHADOW_BANKROLL_MUST_BE_POSITIVE")
        self.path = path
        self.initial_bankroll = float(initial_bankroll)

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text("utf-8").splitlines()
            if line.strip()
        ]

    def _append(self, payload: dict[str, object], *, identity: str) -> dict[str, object]:
        records = self._records()
        for existing in records:
            if existing.get("decision_id") == identity or existing.get(
                "settlement_id"
            ) == identity:
                if existing == payload:
                    return payload
                raise ValueError(f"IMMUTABLE_LEDGER_RECORD_CONFLICT:{identity}")
        expected_previous = (
            str(records[-1]["record_hash"]) if records else GENESIS_HASH
        )
        if payload["previous_record_hash"] != expected_previous:
            raise ValueError("LEDGER_PREVIOUS_HASH_MISMATCH")
        expected_hash = record_hash(payload)
        if payload["record_hash"] != expected_hash:
            raise ValueError("LEDGER_RECORD_HASH_MISMATCH")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
        return payload

    def bankroll(self) -> float:
        value = self.initial_bankroll
        for record in self._records():
            if record.get("record_type") == "SETTLEMENT":
                value = float(record["shadow_bankroll_after"])
        return value

    @staticmethod
    def _decision_record(record: dict[str, Any]) -> DecisionRecord:
        return DecisionRecord(
            decision_id=str(record["decision_id"]),
            published_at=str(record["published_at"]),
            cutoff_at=str(record["cutoff_at"]),
            fixture_id=int(record["fixture_id"]),
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
        fixture_id: int,
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
        if not (published_at <= cutoff_at < kickoff_at):
            raise ValueError("DECISION_NOT_FROZEN_BEFORE_KICKOFF")
        if decision not in {"BET", "NO_BET", "NO_BET_DATA_UNAVAILABLE"}:
            raise ValueError("INVALID_SHADOW_DECISION")
        if decision == "BET" and (odds is None or odds <= 1.0 or pattern_id is None):
            raise ValueError("BET_REQUIRES_OBSERVED_ODDS_AND_PATTERN")
        stake = 1.0 if decision == "BET" else 0.0
        records = self._records()
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
                and candidate.fixture_id == fixture_id
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
            raise ValueError(f"IMMUTABLE_LEDGER_RECORD_CONFLICT:{decision_id}")
        previous = str(records[-1]["record_hash"]) if records else GENESIS_HASH
        payload: dict[str, object] = {
            "record_type": "DECISION",
            "decision_id": decision_id,
            "published_at": _iso(published_at),
            "cutoff_at": _iso(cutoff_at),
            "fixture_id": fixture_id,
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
            "shadow_bankroll_before": self.bankroll(),
            "status": "LIVE_SHADOW",
            "code_revision": code_revision,
            "dataset_hash": dataset_hash,
            "previous_record_hash": previous,
            "record_hash": "",
            "simulation": True,
        }
        payload["record_hash"] = record_hash(payload)
        stored = self._append(payload, identity=decision_id)
        return self._decision_record(cast(dict[str, Any], stored))

    def append_settlement(
        self,
        *,
        settlement_id: str,
        decision_id: str,
        settled_at: datetime,
        result: str,
        profit_units: float,
    ) -> SettlementRecord:
        if result not in {"WIN", "LOSS", "VOID"}:
            raise ValueError("INVALID_SETTLEMENT_RESULT")
        records = self._records()
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
            raise ValueError(f"IMMUTABLE_LEDGER_RECORD_CONFLICT:{settlement_id}")
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
        kickoff_at = datetime.fromisoformat(str(decision["kickoff_at"]))
        if settled_at <= kickoff_at:
            raise ValueError("SETTLEMENT_BEFORE_KICKOFF")
        expected_profit = {
            "WIN": float(decision["odds"]) - float(decision["stake_units"]),
            "LOSS": -float(decision["stake_units"]),
            "VOID": 0.0,
        }[result]
        if abs(float(profit_units) - expected_profit) > 1e-9:
            raise ValueError("SETTLEMENT_PROFIT_MISMATCH")
        existing_for_decision = next(
            (
                record
                for record in records
                if record.get("record_type") == "SETTLEMENT"
                and record.get("decision_id") == decision_id
            ),
            None,
        )
        if existing_for_decision is not None:
            raise ValueError("DECISION_ALREADY_SETTLED")
        if any(
            record.get("record_type") == "SETTLEMENT"
            and record.get("decision_id") == decision_id
            for record in records
        ):
            raise ValueError("DECISION_ALREADY_SETTLED")
        previous = str(records[-1]["record_hash"]) if records else GENESIS_HASH
        bankroll_after = self.bankroll() + float(profit_units)
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
        stored = self._append(payload, identity=settlement_id)
        return self._settlement_record(cast(dict[str, Any], stored))

    def audit(self) -> dict[str, object]:
        records = self._records()
        previous = GENESIS_HASH
        decisions: set[str] = set()
        settlements: set[str] = set()
        decision_records: dict[str, dict[str, Any]] = {}
        settlement_records: list[dict[str, Any]] = []
        for record in records:
            if record.get("previous_record_hash") != previous:
                raise ValueError("LEDGER_CHAIN_BROKEN")
            if record.get("record_hash") != record_hash(record):
                raise ValueError("LEDGER_HASH_MISMATCH")
            if record.get("simulation") is not True:
                raise ValueError("REAL_BET_RECORD_FORBIDDEN")
            if record.get("record_type") == "DECISION":
                identity = str(record["decision_id"])
                if identity in decisions:
                    raise ValueError("DUPLICATE_DECISION")
                decisions.add(identity)
                decision_records[identity] = record
            elif record.get("record_type") == "SETTLEMENT":
                identity = str(record["settlement_id"])
                if identity in settlements:
                    raise ValueError("DUPLICATE_SETTLEMENT")
                if str(record["decision_id"]) not in decisions:
                    raise ValueError("ORPHAN_SETTLEMENT")
                settlements.add(identity)
                settlement_records.append(record)
            else:
                raise ValueError("UNKNOWN_LEDGER_RECORD")
            previous = str(record["record_hash"])
        bankroll_curve = [self.initial_bankroll]
        peak = self.initial_bankroll
        maximum_drawdown = 0.0
        for settlement in settlement_records:
            balance = float(settlement["shadow_bankroll_after"])
            bankroll_curve.append(balance)
            peak = max(peak, balance)
            maximum_drawdown = max(maximum_drawdown, peak - balance)
        settled_stake = sum(
            float(decision_records[str(settlement["decision_id"])]["stake_units"])
            for settlement in settlement_records
        )
        profit = sum(
            float(settlement["profit_units"]) for settlement in settlement_records
        )
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
            "won": sum(record.get("result") == "WIN" for record in settlement_records),
            "lost": sum(
                record.get("result") == "LOSS" for record in settlement_records
            ),
            "void": sum(
                record.get("result") == "VOID" for record in settlement_records
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
            "shadow_bankroll": self.bankroll(),
            "production_status": PRODUCTION_STATUS,
            "real_bets": REAL_BETS,
            "social_publishing_enabled": SOCIAL_PUBLISHING_ENABLED,
        }


def records_to_dict(records: Iterable[DecisionRecord | SettlementRecord]) -> list[dict[str, object]]:
    return [asdict(record) for record in records]
