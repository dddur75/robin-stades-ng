from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from robin.domain.enums import EntityType
from robin.domain.identity import ProviderIdentity
from robin.identity.service import IdentityService
from robin.source_observatory import (
    AppendOnlyStore,
    AppendOnlyViolation,
    Contribution,
    EvidenceExcerpt,
    IntegrityError,
    Publication,
    PublicationVersion,
    Result,
    Source,
    evaluate,
    resolve_match_market,
    text_fingerprint,
)
from robin.source_observatory.models import SettlementRule
from robin.storage.models import InternalEntity, ProviderMapping

T = datetime(2026, 10, 25, 10, tzinfo=UTC)
TEXT_HASH = 'a' * 64


def settlement_rule():
    return SettlementRule('rule1', '1', 'https://example.invalid/rules', TEXT_HASH,
                          '1X2', 'reglementaire')


def recorded_result(identifier, match_market_id, outcome, observed_at, evidence_sha256):
    return Result(identifier, match_market_id, outcome, observed_at, evidence_sha256,
                  reglement=settlement_rule())


def version(**changes: object) -> PublicationVersion:
    values = dict(
        version_id='v1', publication_id='p1', text_sha256=TEXT_HASH,
        announced_by_platform_at=T - timedelta(hours=1),
        first_observed_by_robin_at=T, modification_observed_at=T + timedelta(minutes=1),
        usable_at=T + timedelta(minutes=2),
    )
    return PublicationVersion(**(values | changes))


def contribution(**changes: object) -> Contribution:
    values = dict(
        contribution_id='c1', version_id='v1', source_id='s1',
        publication_url='https://example.invalid/post/1', text_sha256=TEXT_HASH,
        langue='fr', marche='1X2', selection='home',
        cote_declaree=Decimal('2.40'), cote_observee=Decimal('2.15'),
        statut='non_resolu', raison_non_resolu='identite_en_attente',
        extraits_preuve=(EvidenceExcerpt(TEXT_HASH, 2, 12),),
        author_id='author1', publication_id='p1', preuve_permise=None, liens_reprise=(),
        match_id='fixture', certitude_rapprochement='certaine', ligne=None,
        periode='reglementaire', reglement=settlement_rule(),
        cote_declaree_provenance='auteur', cote_declaree_at=T,
        cote_observee_provenance='observation Robin', cote_observee_at=T, bookmaker=None,
        categorie='selection_avec_cote', probabilite=None,
    )
    for basis in ('cote_declaree', 'cote_observee'):
        if basis in changes and changes[basis] is None:
            values[basis + '_provenance'] = None
            values[basis + '_at'] = None
    return Contribution(**(values | changes))


@pytest.fixture
def identity() -> IdentityService:
    engine = create_engine('sqlite://')
    InternalEntity.__table__.create(engine)
    ProviderMapping.__table__.create(engine)
    with Session(engine) as session:
        yield IdentityService(session)
    engine.dispose()


def reference(entity_type: EntityType) -> ProviderIdentity:
    return ProviderIdentity(entity_type=entity_type, provider_name='synthetic',
                            provider_entity_id=entity_type.value, valid_from=version().usable_at)


def link(identity: IdentityService, entity_type: EntityType, suffix: str = '') -> str:
    ref = reference(entity_type)
    if suffix:
        ref = ref.model_copy(update={'valid_from': ref.valid_from - timedelta(seconds=1)})
    internal_id = entity_type.value + suffix
    identity.session.add(InternalEntity(id=internal_id, entity_type=entity_type.value,
                                        display_name=None, attributes={}, created_at=T))
    identity.session.add(ProviderMapping(
        id=internal_id, internal_entity_id=internal_id, entity_type=entity_type.value,
        provider_name=ref.provider_name, provider_entity_id=ref.provider_entity_id,
        observed_name=None, valid_from=ref.valid_from, valid_to=None,
        mapping_status='CONFIRMED', mapping_confidence=1., mapping_method='provider_id',
        review_status='NOT_REQUIRED',
    ))
    identity.session.flush()
    return internal_id


def resolved(identity: IdentityService, *, kickoff: datetime | None = T + timedelta(hours=2)):
    return resolve_match_market(
        identity, contribution(), version(), fixture=reference(EntityType.FIXTURE),
        market=reference(EntityType.MARKET), selection=reference(EntityType.SELECTION),
        match_usable_at=kickoff,
    )


def complete_identity(identity: IdentityService) -> None:
    for entity_type in (EntityType.FIXTURE, EntityType.MARKET, EntityType.SELECTION):
        link(identity, entity_type)


def test_four_instants_are_preserved_and_frozen():
    v = version()
    assert (v.announced_by_platform_at, v.first_observed_by_robin_at,
            v.modification_observed_at, v.usable_at) == (
                T - timedelta(hours=1), T, T + timedelta(minutes=1), T + timedelta(minutes=2))
    with pytest.raises(FrozenInstanceError):
        v.usable_at = T
    unknown = version(announced_by_platform_at=None, modification_observed_at=None)
    assert unknown.announced_by_platform_at is None
    assert unknown.modification_observed_at is None
    assert version(modification_observed_at=None, usable_at=T).usable_at == T


@pytest.mark.parametrize('changes', [
    {'usable_at': T - timedelta(seconds=1)},
    {'usable_at': T},  # modification is only observed one minute later
    {'modification_observed_at': T - timedelta(seconds=1)},
    {'first_observed_by_robin_at': T.replace(tzinfo=None)},
    {'announced_by_platform_at': T.replace(tzinfo=None)},
])
def test_invalid_temporal_evidence_is_rejected(changes):
    with pytest.raises(ValueError):
        version(**changes)


def test_fingerprint_never_keeps_text():
    raw = 'SYNTHETIC publication, not a provider payload.'
    assert text_fingerprint(raw) == sha256(raw.encode('utf-8')).hexdigest()
    assert text_fingerprint('abc') == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'


@pytest.mark.parametrize('field', ['cote_declaree', 'cote_observee'])
@pytest.mark.parametrize('bad', [Decimal('NaN'), Decimal('Infinity'), Decimal('0.9'), 2.4])
def test_invalid_or_inexact_odds_rejected(field, bad):
    with pytest.raises((TypeError, ValueError)):
        contribution(**{field: bad})


def test_cotes_absent_never_completed():
    assert contribution(cote_declaree=None).cote_declaree is None
    assert contribution(cote_observee=None).cote_observee is None
    assert contribution(cote_declaree=None).cote_observee == Decimal('2.15')
    with pytest.raises((TypeError, ValueError)):
        contribution(extraits_preuve=['raw publication'])


def test_identity_resolution_is_read_only(identity):
    complete_identity(identity)
    count = identity.session.scalar(select(func.count()).select_from(InternalEntity))
    match = resolved(identity)
    assert (match.statut, match.match_id, match.market_id, match.selection_id) == (
        'resolu', 'fixture', 'market', 'selection')
    assert match.pre_match_valid is True
    assert identity.session.scalar(select(func.count()).select_from(InternalEntity)) == count


@pytest.mark.parametrize('entity_type', [EntityType.FIXTURE, EntityType.MARKET, EntityType.SELECTION])
def test_ambiguous_identity_is_unresolved(identity, entity_type):
    complete_identity(identity)
    link(identity, entity_type, '-conflict')
    match = resolved(identity)
    assert match.statut == 'non_resolu'
    assert match.raison_non_resolu == 'identite_ambigue'
    assert match.match_id is match.market_id is match.selection_id is None


def test_missing_identity_is_not_created(identity):
    match = resolved(identity)
    assert match.statut == 'non_resolu'
    assert match.raison_non_resolu == 'identite_absente'
    assert identity.session.scalar(select(func.count()).select_from(InternalEntity)) == 0


@pytest.mark.parametrize('kickoff,valid', [
    (T + timedelta(hours=2), True),
    (T + timedelta(minutes=2), False),
    (T + timedelta(minutes=1), False),
    (None, False),
])
def test_pre_match_uses_observed_usability_not_announced_time(identity, kickoff, valid):
    complete_identity(identity)
    match = resolved(identity, kickoff=kickoff)
    assert match.pre_match_valid is valid
    observed = recorded_result('r1', match.match_market_id, 'gagne', T + timedelta(hours=3), TEXT_HASH)
    evaluation = evaluate(contribution(), match, observed, odds_basis='cote_declaree')
    assert evaluation.evaluable is valid
    if not valid:
        assert evaluation.unit_profit is None


@pytest.mark.parametrize('outcome,expected', [
    ('gagne', Decimal('1.40')), ('perdu', Decimal('-1')),
    ('rembourse', Decimal('0')), ('void', Decimal('0')),
])
def test_unit_stake_evaluation(identity, outcome, expected):
    complete_identity(identity)
    match = resolved(identity)
    result = recorded_result('r1', match.match_market_id, outcome, T + timedelta(hours=3), TEXT_HASH)
    evaluation = evaluate(contribution(), match, result, odds_basis='cote_declaree')
    assert evaluation.unit_profit == expected
    assert evaluation.unit_stake == Decimal('1')
    assert evaluation.odds_used == Decimal('2.40')


@pytest.mark.parametrize('outcome', ['gagne', 'perdu', 'rembourse', 'void'])
def test_missing_selected_odds_always_unevaluable(identity, outcome):
    complete_identity(identity)
    match = resolved(identity)
    result = recorded_result('r1', match.match_market_id, outcome, T + timedelta(hours=3), TEXT_HASH)
    evaluation = evaluate(contribution(cote_declaree=None), match, result,
                          odds_basis='cote_declaree')
    assert evaluation.evaluable is False
    assert evaluation.unit_profit is evaluation.odds_used is None
    assert evaluation.reason == 'cote_absente'
    observed = evaluate(contribution(cote_declaree=None), match, result,
                        odds_basis='cote_observee')
    assert observed.odds_used == Decimal('2.15')


def test_result_cannot_settle_another_contribution(identity):
    complete_identity(identity)
    match = resolved(identity)
    result = recorded_result('r1', 'other-match-market', 'gagne', T + timedelta(hours=3), TEXT_HASH)
    with pytest.raises(ValueError):
        evaluate(contribution(), match, result, odds_basis='cote_declaree')


def populate(store):
    store.append(Source('s1', 'synthetic', 'https://example.invalid'))
    store.append(Publication('p1', 's1', 'https://example.invalid/post/1'))
    store.append(version())
    store.append(contribution())


def test_append_only_restart_hashes_and_no_payload(tmp_path):
    path = tmp_path / 'journal.jsonl'
    store = AppendOnlyStore(path)
    populate(store)
    before = path.read_bytes()
    head = store.read()[-1].hash
    with pytest.raises(AppendOnlyViolation):
        store.append(replace(contribution(), selection='away'))
    with pytest.raises(AppendOnlyViolation):
        store.update('c1', contribution())
    with pytest.raises(AppendOnlyViolation):
        store.delete('c1')
    with pytest.raises(TypeError):
        store.append({'payload': 'raw text'})
    assert path.read_bytes() == before
    reopened = AppendOnlyStore(path, expected_head=head)
    reopened.append(version(version_id='v2', text_sha256='b' * 64,
                            previous_version_id='v1',
                            modification_observed_at=T + timedelta(minutes=3),
                            usable_at=T + timedelta(minutes=3)))
    assert path.read_bytes().startswith(before)
    records = reopened.read()
    assert records[-1].previous_hash == head
    assert isinstance(records[3].entity, Contribution)
    assert records[3].entity.cote_declaree == Decimal('2.40')
    wire = json.loads(before.splitlines()[3])
    assert wire['data']['extraits_preuve'] == [
        {'text_sha256': TEXT_HASH, 'start': 2, 'end': 12, 'text': None}]
    assert 'payload' not in wire['data']
    assert 'text' not in wire['data']


@pytest.mark.parametrize('damage', ['edit', 'truncate', 'remove', 'partial'])
def test_store_refuses_damaged_history(tmp_path, damage):
    path = tmp_path / 'history.jsonl'
    store = AppendOnlyStore(path)
    populate(store)
    before = path.read_bytes()
    head = store.read()[-1].hash
    if damage == 'edit':
        path.write_bytes(before.replace(b'synthetic', b'corrupted'))
    elif damage == 'truncate':
        path.write_bytes(b'\n'.join(before.splitlines()[:-1]) + b'\n')
    elif damage == 'remove':
        path.unlink()
    else:
        path.write_bytes(before + b'{')
    damaged = path.read_bytes() if path.exists() else None
    with pytest.raises(IntegrityError):
        store.append(Source('s2', 'second', 'https://example.invalid/second'))
    assert (path.read_bytes() if path.exists() else None) == damaged
    with pytest.raises(IntegrityError):
        AppendOnlyStore(path, expected_head=head)


def test_deterministic_serialization(tmp_path):
    first, second = tmp_path / 'a.jsonl', tmp_path / 'b.jsonl'
    populate(AppendOnlyStore(first))
    populate(AppendOnlyStore(second))
    assert first.read_bytes() == second.read_bytes()


def test_valid_hash_cannot_smuggle_raw_payload_into_history(tmp_path):
    path = tmp_path / 'closed-metadata.jsonl'
    populate(AppendOnlyStore(path))
    lines = path.read_bytes().splitlines()
    record = json.loads(lines[-1])
    record['data']['raw_text'] = 'SYNTHETIC forbidden text'
    body = {key: value for key, value in record.items() if key != 'hash'}
    record['hash'] = sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':')).encode('utf-8')).hexdigest()
    lines[-1] = json.dumps(record, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
    path.write_bytes(b'\n'.join(lines) + b'\n')
    with pytest.raises(IntegrityError, match='unknown or missing metadata fields'):
        AppendOnlyStore(path)


def test_orphan_and_inconsistent_lineage_rejected(tmp_path):
    store = AppendOnlyStore(tmp_path / 'orphan.jsonl')
    with pytest.raises(ValueError):
        store.append(contribution())
    populate(store)
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.append(contribution(contribution_id='c2', text_sha256='f' * 64))
    with pytest.raises(ValueError):
        store.append(contribution(contribution_id='c3', source_id='other'))
    assert store.path.read_bytes() == before


def test_full_chain_is_persisted_and_reloaded(tmp_path, identity):
    complete_identity(identity)
    store = AppendOnlyStore(tmp_path / 'chain.jsonl')
    populate(store)
    match = resolved(identity)
    store.append(match)
    result = recorded_result('r1', match.match_market_id, 'gagne', T + timedelta(hours=3), TEXT_HASH)
    store.append(result)
    evaluation = evaluate(contribution(), match, result, odds_basis='cote_declaree')
    store.append(evaluation)
    assert AppendOnlyStore(store.path).read()[-1].entity == evaluation


def test_schema_is_closed_and_matches_extraction_contract():
    schema = json.loads((Path(__file__).parents[2] / 'src/robin/source_observatory/schemas/'
                         'contribution.schema.json').read_text(encoding='utf-8'))
    data = contribution(cote_declaree=None).extraction_metadata()
    assert set(data) == set(schema['required']) == set(schema['properties'])
    assert schema['additionalProperties'] is False
    assert data['cote_declaree'] is None
    assert data['cote_observee'] == '2.15'
    assert schema['properties']['statut']['enum'] == ['resolu', 'non_resolu']
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(data)
    assert not validator.is_valid(data | {'raw_text': 'forbidden'})
    assert not validator.is_valid(data | {'cote_declaree': '0.9'})
    assert not validator.is_valid(data | {'statut': 'resolu'})
    assert not validator.is_valid(data | {'raison_non_resolu': None})
    assert not validator.is_valid(data | {'extraits_preuve': ['raw text']})
    assert not validator.is_valid(data | {'extraits_preuve': [
        {'text_sha256': TEXT_HASH, 'start': 0, 'end': 4, 'text': 'raw text'}]})
    validator.validate(data | {'statut': 'resolu', 'raison_non_resolu': None})


def test_unresolved_match_cannot_be_evaluated(identity):
    match = resolved(identity)
    result = recorded_result('r1', match.match_market_id, 'gagne', T + timedelta(hours=3), TEXT_HASH)
    evaluation = evaluate(contribution(), match, result, odds_basis='cote_declaree')
    assert evaluation.evaluable is False
    assert evaluation.unit_profit is None
    assert evaluation.reason == 'non_resolu'


@pytest.mark.parametrize('problem', ['wrong_type', 'wrong_asof', 'wrong_version'])
def test_identity_inputs_cannot_silently_change_temporal_context(identity, problem):
    fixture = reference(EntityType.FIXTURE)
    current_version = version()
    if problem == 'wrong_type':
        fixture = reference(EntityType.TEAM)
    elif problem == 'wrong_asof':
        fixture = fixture.model_copy(update={'valid_from': T})
    else:
        current_version = version(version_id='other')
    with pytest.raises(ValueError):
        resolve_match_market(identity, contribution(), current_version, fixture=fixture,
                             market=reference(EntityType.MARKET),
                             selection=reference(EntityType.SELECTION),
                             match_usable_at=T + timedelta(hours=2))


def test_store_refuses_forged_evaluation_and_result_correction(tmp_path, identity):
    complete_identity(identity)
    store = AppendOnlyStore(tmp_path / 'settlement.jsonl')
    populate(store)
    match = resolved(identity)
    store.append(match)
    result = recorded_result('r1', match.match_market_id, 'gagne', T + timedelta(hours=3), TEXT_HASH)
    store.append(result)
    evaluation = evaluate(contribution(), match, result, odds_basis='cote_declaree')
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.append(replace(evaluation, unit_profit=Decimal('9')))
    with pytest.raises(AppendOnlyViolation):
        store.append(replace(result, result_id='r2', outcome='perdu'))
    with pytest.raises(ValueError):
        store.append(replace(match, match_market_id='other', contribution_usable_at=T))
    assert store.path.read_bytes() == before


def test_result_before_kickoff_is_refused(identity):
    complete_identity(identity)
    match = resolved(identity)
    result = recorded_result('r1', match.match_market_id, 'gagne', T, TEXT_HASH)
    with pytest.raises(ValueError):
        evaluate(contribution(), match, result, odds_basis='cote_declaree')


def test_decimal_calculation_does_not_depend_on_callers_precision(identity):
    from decimal import localcontext

    complete_identity(identity)
    match = resolved(identity)
    result = recorded_result('r1', match.match_market_id, 'gagne', T + timedelta(hours=3), TEXT_HASH)
    quoted = contribution(cote_declaree=Decimal('2.12345678901234567890123456789'))
    with localcontext() as context:
        context.prec = 2
        evaluation = evaluate(quoted, match, result, odds_basis='cote_declaree')
    assert evaluation.unit_profit == Decimal('1.12345678901234567890123456789')
