"""The cockpit receives plan metadata and audited counts, never the raw journal."""

import json
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from runpy import run_path

import pytest

from robin.source_observatory.collector import Fixture, build_plan, load_sources, parse_instant
from robin.source_observatory.models import (
    Publication,
    PublicationVersion,
    Source,
    Visit,
    VisitReceipt,
)
from robin.source_observatory.store import AppendOnlyStore

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'cockpit/scripts/build-source-observatory-snapshot.py'
PLAN_CLAIM = 'GOV.SOURCE_OBSERVATORY.DOSSIER_FIDELE.PLAN_V4.20261026'


@pytest.fixture
def export():
    return run_path(str(SCRIPT))['build_snapshot']


def test_real_v4_is_historical_plan_only(export):
    snapshot = export(
        ROOT / 'data/source_observatory/pilot_sources.csv',
        ROOT / 'data/source_observatory/visit_plan_20261031_v4.json',
        ROOT / 'reports/evidence/evidence-graph.json',
        PLAN_CLAIM,
    )
    assert snapshot['plan']['claimId'] == PLAN_CLAIM
    assert snapshot['plan']['sha256'] == '7f85aff07705634bce4c326ab5450e575cbd51905da191be71cfc86a79aebbb1'
    assert snapshot['plan']['plannedVisits'] == sum(source['plannedVisits'] for source in snapshot['sources'])
    assert snapshot['observations'] is None
    assert snapshot == json.loads((ROOT / 'cockpit/app/source-observatory-snapshot.json').read_bytes())
    assert any(source['access'] == 'manuel' for source in snapshot['sources'])


@pytest.fixture
def small_pilot(tmp_path):
    registry = tmp_path / 'registry.csv'
    registry.write_text(
        'source_id,nom,adresse,etat_connecteur,mode_acces,cgu_connues,competitions,categorie_audience\n'
        's1,Source pilote,https://example.invalid/feed,a_construire,rss_public,Test,Ligue 1,petit_auteur_inconnu\n',
        encoding='utf-8',
        newline='\r\n',
    )
    starts = parse_instant('2026-11-01T12:00:00Z')
    kickoff = starts + timedelta(hours=14)
    raw = registry.read_bytes().replace(b'\r\n', b'\n')
    plan = build_plan(load_sources(registry), (Fixture('match', kickoff, 'https://example.invalid/l1'),),
                      starts_at=starts, registry_sha256=sha256(raw).hexdigest())
    plan_path = tmp_path / 'plan.json'
    plan_bytes = (json.dumps(plan) + '\n').encode()
    plan_path.write_bytes(plan_bytes)
    plan_sha = sha256(plan_bytes).hexdigest()
    graph = tmp_path / 'graph.json'
    journal = tmp_path / 'journal.jsonl'
    store = AppendOnlyStore(journal)
    source = Source('s1', 'Source pilote', 'https://example.invalid/feed')
    post = Publication('post1', 's1', 'https://example.invalid/secret-post')
    version = PublicationVersion('version1', 'post1', 'a' * 64, None, starts, None, starts)
    store.append_batch((source, post, version))
    for spec, state in zip(plan['visits'], ('ok', 'echec', 'bloque_robots'), strict=False):
        at = parse_instant(spec['planned_at'])
        visit = Visit(spec['visit_id'], 's1', at, None, False)
        receipt = VisitReceipt('receipt:' + spec['visit_id'], spec['visit_id'], at, state,
                               ('post1',) if state == 'ok' else (),
                               None if state == 'ok' else 'trace qui doit rester locale')
        stored = store.append_batch((visit, receipt))

    receipt_path = tmp_path / 'receipt.json'
    anchor_journal(graph, receipt_path, plan_sha, stored[-1].hash)
    return registry, plan_path, graph, journal, receipt_path


def anchor_journal(graph, receipt_path, plan_sha, head):
    receipt = {'schema_version': 'source-observatory-journal-receipt-v1',
               'claim_id': 'TEST.RESULT', 'plan_sha256': plan_sha, 'journal_head': head}
    receipt_path.write_bytes(json.dumps(receipt).encode())
    graph.write_text(json.dumps({'claims': [
        {'claim_id': 'TEST.PLAN', 'claim': 'Plan ' + plan_sha},
        {'claim_id': 'TEST.RESULT', 'status': 'VERIFIED', 'scope': 'SOURCE_OBSERVATORY_PILOT_JOURNAL',
         'dataset_lineage_id': plan_sha, 'artifact': 'reports/ux/receipt.json',
         'verified_by': ['C3', 'A3'], 'hash': sha256(receipt_path.read_bytes()).hexdigest()},
    ]}), encoding='utf-8')


def test_pilot_projection_scopes_counts_and_withholds_raw_details(export, small_pilot):
    registry, plan_path, graph, journal, receipt_path = small_pilot
    before = journal.read_bytes()
    output = export(registry, plan_path, graph, 'TEST.PLAN',
                    journal_path=journal, journal_claim_id='TEST.RESULT', receipt_path=receipt_path)
    assert output['plan']['plannedVisits'] == 4
    assert output['observations']['totals'] == {
        'succeeded': 1, 'failed': 1, 'blockedRobots': 1, 'withoutReceipt': 1,
    }
    assert output['observations']['publications'] == 1
    assert output['observations']['bySource']['s1'] == output['observations']['totals']
    assert output['observations']['claimId'] == 'TEST.RESULT'
    projected = json.dumps(output)
    assert 'example.invalid' not in projected
    assert 'trace qui doit rester locale' not in projected
    assert journal.read_bytes() == before


def test_pilot_refuses_changed_journal(export, small_pilot):
    registry, plan_path, graph, journal, receipt_path = small_pilot
    journal.write_bytes(journal.read_bytes()[:-1])
    with pytest.raises(ValueError, match='journal'):
        export(registry, plan_path, graph, 'TEST.PLAN',
               journal_path=journal, journal_claim_id='TEST.RESULT', receipt_path=receipt_path)


def test_pilot_refuses_receipt_without_confirmed_plan_lineage(export, small_pilot):
    registry, plan_path, graph, journal, receipt_path = small_pilot
    evidence = json.loads(graph.read_bytes())
    evidence['claims'][1]['dataset_lineage_id'] = 'a' * 64
    graph.write_text(json.dumps(evidence), encoding='utf-8')
    with pytest.raises(ValueError, match='plan'):
        export(registry, plan_path, graph, 'TEST.PLAN',
               journal_path=journal, journal_claim_id='TEST.RESULT', receipt_path=receipt_path)

@pytest.mark.parametrize('defect', ['wrong-source', 'late-receipt'])
def test_refuses_anchored_proof_that_cannot_be_attributed_to_plan(export, small_pilot, tmp_path, defect):
    registry, plan_path, graph, _, receipt_path = small_pilot
    plan = json.loads(plan_path.read_bytes())
    visit = plan['visits'][-1]
    at = parse_instant(visit['planned_at'])
    kickoff = parse_instant(plan['fixtures'][0]['kickoff'])
    journal = tmp_path / 'other.jsonl'
    source_url = 'https://example.invalid/other' if defect == 'wrong-source' else 'https://example.invalid/feed'
    recorded = AppendOnlyStore(journal).append_batch((
        Source('s1', 'Source pilote', source_url),
        Visit(visit['visit_id'], 's1', at, None, False),
        VisitReceipt('receipt', visit['visit_id'], kickoff if defect == 'late-receipt' else at, 'ok', (), None),
    ))
    anchor_journal(graph, receipt_path, sha256(plan_path.read_bytes()).hexdigest(), recorded[-1].hash)
    with pytest.raises(ValueError, match='source|kickoff'):
        export(registry, plan_path, graph, 'TEST.PLAN',
               journal_path=journal, journal_claim_id='TEST.RESULT', receipt_path=receipt_path)
