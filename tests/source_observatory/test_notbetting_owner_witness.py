"""Closed owner diagnostics must never change NotBetting qualification."""
import copy
from datetime import datetime, timezone

import pytest

from robin.source_observatory import notbetting_prospective as qualifier


@pytest.mark.parametrize('variant,expected_reason', [
    ('unresolved_owner', 'unresolved_data_reference'),
    ('malformed_owner', 'UNCLASSIFIED_REFERENCE_FAILURE'),
])
def test_owner_witness_preserves_qualification_and_contains_sink(variant, expected_reason):
    uid = '11111111-1111-1111-1111-111111111111'
    label = 'SYNTHETIC_OWNER'
    poison = 'SYNTHETIC_OWNER_POISON_NEVER_DIAGNOSTIC'
    row = dict(id='22222222-2222-2222-2222-222222222222',
               event='Synthetic Home - Synthetic Away', pick='SYNTHETIC_OPAQUE',
               competition='Bundesliga', date='2026-11-27T19:30:00+00:00',
               tipsterId=uid, tipster={'user': {'id': uid, 'username': label,
                         'tipster': {'id': uid, 'userId': uid}}})
    fixture = dict(id='synthetic', home='Synthetic Home', away='Synthetic Away',
                   kickoff=row['date'], competition='Bundesliga',
                   calendarSHA='a' * 64, calendarClaim='SYNTHETIC.CALENDAR')
    options = dict(ownerSpec=dict(uid=uid, label=label), competition='Bundesliga',
                   responseSHA='a' * 64, parserSHA='b' * 64,
                   calendarSHA='a' * 64, calendarClaim='SYNTHETIC.CALENDAR')
    if variant == 'unresolved_owner':
        row['tipster'] = '$f'
        row[poison] = False
    else:
        row['tipster'] = {'user': 42, poison: False}
    documents = {'0': row}
    original = copy.deepcopy((documents, [fixture], options))
    projections, observed = [], []
    for mode in ('OFF', 'ON', 'THROWING_SINK'):
        witnesses = []

        def observe(item):
            witnesses.append(item)
            if mode == 'THROWING_SINK':
                raise RuntimeError(poison)

        result = qualifier.qualify_documents(
            documents, [fixture], datetime(2026, 11, 23, tzinfo=timezone.utc),
            _observer=None if mode == 'OFF' else observe, **options,
        )
        assert (documents, [fixture], options) == original
        assert result['status'] == 'partial' and result['picks'] == []
        assert result['traversalComplete'] is False
        assert 'owner_backlinks_unproven' in result['reasons']
        if mode == 'OFF':
            assert witnesses == []
        else:
            assert len(witnesses) == 1
            assert witnesses[0] == dict(reason=expected_reason, referenceSHA256=None,
                                        depth=None, referenceCount=None)
            assert len(qualifier.canonical(witnesses)) <= 4096
        encoded = qualifier.canonical(witnesses)
        for forbidden in (poison, label, uid, 'SYNTHETIC_OPAQUE', '$f', 'tipster', 'user'):
            assert forbidden.encode() not in encoded
        projections.append(result)
        observed.append(witnesses)
    assert projections[0] == projections[1] == projections[2]
    assert observed[1] == observed[2]
