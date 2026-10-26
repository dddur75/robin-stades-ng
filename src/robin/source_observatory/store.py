"""Single-writer append-only, canonical hash-chained metadata journal."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import TypeVar, cast
from zoneinfo import ZoneInfo

from .models import (
    AccountAssignment,
    Cohort,
    Contribution,
    Entity,
    Evaluation,
    EvidenceExcerpt,
    IdentityRevision,
    MatchMarket,
    Publication,
    PublicationVersion,
    RepriseLink,
    Result,
    SettlementLeg,
    SettlementRule,
    Source,
    Visit,
    VisitReceipt,
    Withdrawal,
    decimal_text,
    instant_text,
)
from .ranking import observation_time
from .service import combined_legs_proven, evaluate

GENESIS = '0' * 64
_TYPES = (Source, Publication, PublicationVersion, Contribution, MatchMarket, Result, Evaluation,
          IdentityRevision, Withdrawal, Visit, Cohort, VisitReceipt)
_REGISTRY = {cls.__name__: cls for cls in _TYPES}
_IDS = ('source_id', 'publication_id', 'version_id', 'contribution_id',
        'match_market_id', 'result_id', 'evaluation_id', 'revision_id', 'withdrawal_id', 'visit_id',
        'cohort_id', 'receipt_id')
_ID_FIELDS = dict(zip(_TYPES, _IDS, strict=True))
_DATES = frozenset(('announced_by_platform_at', 'first_observed_by_robin_at',
                    'modification_observed_at', 'usable_at', 'contribution_usable_at',
                    'match_usable_at', 'observed_at', 'planned_at', 'completed_at',
                    'cote_declaree_at', 'cote_observee_at', 'defined_at', 'evaluation_starts_at',
                    'evaluation_ends_at', 'prospective_starts_at', 'prospective_ends_at'))
_DECIMALS = frozenset(('cote_declaree', 'cote_observee', 'odds_used', 'unit_profit',
                       'ligne', 'probabilite', 'odds', 'brier', 'log_loss', 'factual_accuracy',
                       'anteriority_seconds', 'binary_outcome', 'minimum_visit_coverage'))
T = TypeVar('T', bound=Entity)


class AppendOnlyViolation(ValueError):
    """An existing observation cannot be replaced or removed."""


class IntegrityError(ValueError):
    """The journal or its previously observed prefix has changed."""


@dataclass(frozen=True, slots=True)
class StoredRecord:
    sequence: int
    kind: str
    entity: Entity
    previous_hash: str
    hash: str


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode('utf-8')


def _wire(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is None:
            raise ValueError('datetime sans fuseau')
        return {'utc': instant_text(value),
                'origin_timezone': getattr(value.tzinfo, 'key', None) or value.tzname(),
                'origin_offset_seconds': int(offset.total_seconds())}
    if isinstance(value, Decimal):
        return decimal_text(value)
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    raise TypeError('only typed metadata may be persisted; raw payloads are forbidden')


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise IntegrityError('JSON object expected')
    return cast(dict[str, object], value)


def _timestamp(raw: object) -> datetime:
    data = _object(raw)
    if set(data) != {'utc', 'origin_timezone', 'origin_offset_seconds'}:
        raise IntegrityError('UTC and original timezone required')
    utc, zone, offset = data['utc'], data['origin_timezone'], data['origin_offset_seconds']
    if not isinstance(utc, str) or not isinstance(zone, str) or type(offset) is not int:
        raise IntegrityError('invalid timestamp metadata')
    instant = datetime.fromisoformat(utc)
    if instant.utcoffset() != timedelta(0):
        raise IntegrityError('UTC timestamp required')
    try:
        tz = ZoneInfo(zone)
        restored = instant.astimezone(tz)
    except (KeyError, ValueError):
        restored = instant.astimezone(timezone(timedelta(seconds=offset), zone))
    if int(restored.utcoffset().total_seconds()) != offset:  # type: ignore[union-attr]
        raise IntegrityError('origin timezone offset mismatch')
    return restored


def _decode_data(cls: type[object], raw: object) -> dict[str, object]:
    if not is_dataclass(cls):
        raise TypeError('registered dataclass required')
    data = _object(raw).copy()
    if set(data) != {field.name for field in fields(cls)}:
        raise IntegrityError('unknown or missing metadata fields')
    for name, value in data.items():
        if name in _DATES and value is not None:
            data[name] = _timestamp(value)
        elif name in _DECIMALS and value is not None:
            if not isinstance(value, str):
                raise IntegrityError('exact decimal string required')
            data[name] = Decimal(value)
        elif name == 'reglement' and value is not None:
            factory = cast(Callable[..., object], SettlementRule)
            data[name] = factory(**_decode_data(SettlementRule, value))
        elif name in ('extraits_preuve', 'liens_reprise', 'assignments', 'legs'):
            if not isinstance(value, list):
                raise IntegrityError('typed metadata list required')
            nested = {'extraits_preuve': EvidenceExcerpt, 'liens_reprise': RepriseLink,
                      'assignments': AccountAssignment, 'legs': SettlementLeg}[name]
            decoded = []
            for item in value:
                factory = cast(Callable[..., object], nested)
                decoded.append(factory(**_decode_data(nested, item)))
            data[name] = tuple(decoded)
        elif name in ('author_ids', 'publication_ids'):
            if not isinstance(value, list):
                raise IntegrityError('explicit cohort membership required')
            data[name] = tuple(value)
    return data


def _decode(kind: str, raw: object) -> Entity:
    if kind not in _REGISTRY:
        raise IntegrityError('unknown entity kind')
    cls = _REGISTRY[kind]
    # Closed registry + exact field set + dataclass validation form the decoding boundary.
    constructor = cast(Callable[..., Entity], cls)
    return constructor(**_decode_data(cls, raw))


def _key(entity: Entity) -> tuple[str, str]:
    return type(entity).__name__, cast(str, getattr(entity, _ID_FIELDS[type(entity)]))


def _get(known: dict[tuple[str, str], Entity], cls: type[T], identifier: str) -> T:
    entity = known.get((cls.__name__, identifier))
    if not isinstance(entity, cls):
        raise ValueError(f'missing {cls.__name__} predecessor: {identifier}')
    return entity


def _validate_lineage(entity: Entity, known: dict[tuple[str, str], Entity]) -> None:
    if _key(entity) in known:
        raise AppendOnlyViolation('identity already recorded: append a new observation instead')
    observed = observation_time(entity)
    if observed is not None:
        observations = [t for e in known.values() if (t := observation_time(e)) is not None]
        if observations and observed < max(observations):
            raise ValueError('observation cannot be backdated in the journal')
    if isinstance(entity, Publication):
        _get(known, Source, entity.source_id)
    elif isinstance(entity, PublicationVersion):
        _get(known, Publication, entity.publication_id)
        previous = [e for e in known.values() if isinstance(e, PublicationVersion)
                    and e.publication_id == entity.publication_id]
        if previous:
            last = previous[-1]
            if entity.previous_version_id != last.version_id:
                raise ValueError('correction requires previous version')
            if (entity.first_observed_by_robin_at != last.first_observed_by_robin_at
                    or entity.modification_observed_at is None
                    or entity.usable_at <= last.usable_at
                    or entity.modification_observed_at <= last.usable_at):
                raise ValueError('correction must retain first observation and advance time')
        elif entity.previous_version_id is not None:
            raise ValueError('first version cannot reference a missing predecessor')
    elif isinstance(entity, Contribution):
        version = _get(known, PublicationVersion, entity.version_id)
        publication = _get(known, Publication, version.publication_id)
        if (entity.publication_id != publication.publication_id
                or entity.source_id != publication.source_id
                or entity.publication_url != publication.publication_url
                or entity.text_sha256 != version.text_sha256):
            raise ValueError('contribution lineage metadata mismatch')
        if entity.observed_at < version.usable_at:
            raise ValueError('contribution observation precedes usable version')
        if (entity.cote_observee_at is not None
                and entity.cote_observee_at < version.first_observed_by_robin_at):
            raise ValueError('observed odds precede first observation')
        if any(isinstance(previous, Contribution) and previous.version_id == entity.version_id
               and previous.selection_key == entity.selection_key for previous in known.values()):
            raise ValueError('one contribution per selection slot and version')
    elif isinstance(entity, MatchMarket):
        contribution = _get(known, Contribution, entity.contribution_id)
        version = _get(known, PublicationVersion, contribution.version_id)
        if any(isinstance(e, MatchMarket) and e.contribution_id == entity.contribution_id
               for e in known.values()):
            raise AppendOnlyViolation('one match market per contribution; append a corrected contribution')
        if (entity.version_id != version.version_id or entity.contribution_usable_at != max(
                version.usable_at, contribution.observed_at)):
            raise ValueError('match/contribution temporal lineage mismatch')
        if entity.statut == 'resolu' and contribution.match_id != entity.match_id:
            raise ValueError('contribution match identity mismatch')
    elif isinstance(entity, Result):
        match = _get(known, MatchMarket, entity.match_market_id)
        contribution = _get(known, Contribution, match.contribution_id)
        if entity.legs and entity.outcome != 'en_attente' and not any(
                combined_legs_proven(contribution, match, entity, known.values(), basis)
                for basis in ('cote_declaree', 'cote_observee')):
            raise ValueError('combined legs require pre-match contributions and result evidence')
        if match.match_usable_at is not None and entity.observed_at < match.match_usable_at:
            raise ValueError('result observation precedes kickoff')
        settlements = [e for e in known.values() if isinstance(e, Result)
                       and e.match_market_id == entity.match_market_id]
        if settlements:
            last_result = settlements[-1]
            if (entity.previous_result_id != last_result.result_id
                    or entity.observed_at < last_result.observed_at
                    or (last_result.outcome != 'en_attente'
                        and entity.audit_evidence_sha256 is None)):
                raise AppendOnlyViolation('settlement already recorded; unaudited correction forbidden')
        elif entity.previous_result_id is not None:
            raise ValueError('first result cannot reference a missing predecessor')
    elif isinstance(entity, Evaluation):
        contribution = _get(known, Contribution, entity.contribution_id)
        match = _get(known, MatchMarket, entity.match_market_id)
        result = _get(known, Result, entity.result_id)
        if entity != evaluate(contribution, match, result, odds_basis=entity.odds_basis,
                              leg_evidence=known.values()):
            raise ValueError('evaluation must reproduce the evidence-backed unit calculation')
    elif isinstance(entity, IdentityRevision):
        previous_revisions = [e for e in known.values() if isinstance(e, IdentityRevision)]
        previous_id = previous_revisions[-1].revision_id if previous_revisions else None
        if entity.previous_revision_id != previous_id:
            raise ValueError('identity revision must extend the current revision')
        if previous_revisions and entity.observed_at < previous_revisions[-1].observed_at:
            raise ValueError('identity revision observation cannot move backwards')
        authors = {e.author_id for e in known.values() if isinstance(e, Contribution)}
        if any(a.author_id not in authors for a in entity.assignments):
            raise ValueError('identity revision references an unknown account')
    elif isinstance(entity, Withdrawal):
        c = _get(known, Contribution, entity.contribution_id)
        v = _get(known, PublicationVersion, c.version_id)
        if entity.observed_at < v.usable_at:
            raise ValueError('withdrawal precedes observation')
    elif isinstance(entity, Visit):
        _get(known, Source, entity.source_id)
    elif isinstance(entity, VisitReceipt):
        visit = _get(known, Visit, entity.visit_id)
        if visit.completed_at is not None or any(isinstance(e, VisitReceipt)
                and e.visit_id == entity.visit_id for e in known.values()):
            raise AppendOnlyViolation('visit already completed; no second receipt allowed')
        if entity.completed_at < visit.planned_at:
            raise ValueError('visit receipt precedes planned time')
        for identifier in entity.publication_ids:
            publication = _get(known, Publication, identifier)
            if publication.source_id != visit.source_id:
                raise ValueError('visit publication belongs to another source')
            if not any(isinstance(e, PublicationVersion) and e.publication_id == identifier
                       for e in known.values()):
                raise ValueError('visit publication requires observed version')
    elif isinstance(entity, Cohort):
        for existing in known.values():
            if isinstance(existing, (PublicationVersion, Contribution, Result)):
                observed = (existing.modification_observed_at or existing.first_observed_by_robin_at
                            if isinstance(existing, PublicationVersion) else existing.observed_at)
                if observed > entity.defined_at:
                    raise ValueError('cohort must be recorded before observations and results')
            if isinstance(existing, Evaluation):
                c = _get(known, Contribution, existing.contribution_id)
                if c.author_id in entity.author_ids:
                    raise ValueError('cohort must be recorded before evaluations')


class AppendOnlyStore:
    """Only append and read are allowed; no payload ingestion or history repair.

    Single-writer contract. Retain ``expected_head`` outside the file between
    processes if detection of whole-file replacement/truncation is required.
    """

    def __init__(self, path: Path, *, expected_head: str | None = None) -> None:
        self.path = path
        self._anchor = (0, GENESIS)
        records = self.read()
        head = records[-1].hash if records else GENESIS
        if expected_head is not None and head != expected_head:
            raise IntegrityError('journal does not match expected head')

    def read(self) -> tuple[StoredRecord, ...]:
        raw = self.path.read_bytes() if self.path.exists() else b''
        records: list[StoredRecord] = []
        known: dict[tuple[str, str], Entity] = {}
        previous = GENESIS
        try:
            for index, line in enumerate(raw.splitlines(keepends=True), 1):
                if not line.endswith(b'\n'):
                    raise IntegrityError('incomplete journal line')
                record = _object(json.loads(line))
                if set(record) != {'sequence', 'kind', 'data', 'previous_hash', 'hash'}:
                    raise IntegrityError('unknown record fields')
                if type(record['sequence']) is not int or record['sequence'] != index:
                    raise IntegrityError('sequence mismatch')
                if record['previous_hash'] != previous or not isinstance(record['kind'], str):
                    raise IntegrityError('broken hash chain or kind')
                body = {name: value for name, value in record.items() if name != 'hash'}
                digest = sha256(_canonical(body)).hexdigest()
                if record['hash'] != digest or _canonical(record) + b'\n' != line:
                    raise IntegrityError('hash mismatch or noncanonical JSONL')
                entity = _decode(record['kind'], record['data'])
                if _wire(entity) != record['data']:
                    raise IntegrityError('noncanonical metadata representation')
                _validate_lineage(entity, known)
                known[_key(entity)] = entity
                records.append(StoredRecord(index, record['kind'], entity, previous, digest))
                previous = digest
        except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
            raise IntegrityError(f'invalid journal: {exc}') from exc
        anchor_sequence, anchor_hash = self._anchor
        if anchor_sequence and (len(records) < anchor_sequence
                                or records[anchor_sequence - 1].hash != anchor_hash):
            raise IntegrityError('previously observed history changed or disappeared')
        self._anchor = (len(records), previous)
        return tuple(records)

    def entities(self) -> tuple[Entity, ...]:
        return tuple(record.entity for record in self.read())

    def append(self, entity: Entity) -> StoredRecord:
        if type(entity) not in _TYPES:
            raise TypeError('only observatory metadata dataclasses are accepted')
        records = self.read()
        known = {_key(record.entity): record.entity for record in records}
        _validate_lineage(entity, known)
        previous = records[-1].hash if records else GENESIS
        body = {'sequence': len(records) + 1, 'kind': type(entity).__name__,
                'data': _wire(entity), 'previous_hash': previous}
        digest = sha256(_canonical(body)).hexdigest()
        line = _canonical(body | {'hash': digest}) + b'\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Binary append cannot truncate an existing file. A partial I/O error is
        # fail-closed on the next read; never truncate or repair the previous bytes.
        with self.path.open('ab') as stream:
            written = stream.write(line)
            if written != len(line):
                raise OSError('incomplete append; journal must remain quarantined')
            stream.flush()
            os.fsync(stream.fileno())
        self._anchor = (len(records) + 1, digest)
        return StoredRecord(len(records) + 1, type(entity).__name__, entity, previous, digest)

    def update(self, identifier: str, entity: Entity) -> None:
        raise AppendOnlyViolation('updates forbidden; append a new version')

    def delete(self, identifier: str) -> None:
        raise AppendOnlyViolation('deletions forbidden')
