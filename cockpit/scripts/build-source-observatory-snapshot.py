"""Project the source observatory plan and audited journal into cockpit metadata."""

import argparse
import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from robin.source_observatory.collector import Fixture, build_plan, load_sources, parse_instant
from robin.source_observatory.models import Source, Visit, VisitReceipt
from robin.source_observatory.store import AppendOnlyStore

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/source_observatory'
PLAN_CLAIM = 'GOV.SOURCE_OBSERVATORY.DOSSIER_FIDELE.PLAN_V4.20261026'
JOURNAL_SCOPE = 'SOURCE_OBSERVATORY_PILOT_JOURNAL'
RECEIPT_VERSION = 'source-observatory-journal-receipt-v1'
OUTCOMES = {'ok': 'succeeded', 'echec': 'failed', 'bloque_robots': 'blockedRobots'}


def _versioned_bytes(path: Path) -> bytes:
    # Git stores these inputs with LF. Windows may check out identical text with CRLF.
    return path.read_bytes().replace(b'\r\n', b'\n')


def _get_claim(graph: dict[str, Any], claim_id: str) -> dict[str, Any]:
    claims: list[dict[str, Any]] = graph['claims']
    matches = [claim for claim in claims if claim['claim_id'] == claim_id]
    if len(matches) != 1:
        raise ValueError(f'expected one evidence claim for {claim_id}')
    return matches[0]


def _observations(
    plan: dict[str, Any], journal_path: Path, receipt_path: Path, claim: dict[str, Any], plan_hash: str,
    counts_by_source: Counter[str],
) -> dict[str, Any]:
    review = json.loads((ROOT / 'configs/agents/agent-registry-v3.json').read_bytes())
    reviewers = set(claim.get('verified_by', []))
    registered = {agent['agent_id'] for agent in review['agents']}
    if (claim.get('status') != 'VERIFIED' or claim.get('scope') != JOURNAL_SCOPE
            or claim.get('dataset_lineage_id') != plan_hash or not claim.get('artifact')
            or len(reviewers) < 2 or not reviewers <= registered):
        raise ValueError('journal evidence must verify this exact plan with two registered reviewers')
    receipt_bytes = _versioned_bytes(receipt_path)
    if sha256(receipt_bytes).hexdigest() != claim.get('hash'):
        raise ValueError('journal receipt artifact does not match the evidence claim')
    receipt = json.loads(receipt_bytes)
    head = receipt.get('journal_head')
    if (receipt != {'schema_version': RECEIPT_VERSION, 'claim_id': claim['claim_id'],
                    'plan_sha256': plan_hash, 'journal_head': head}
            or not isinstance(head, str) or re.fullmatch(r'[0-9a-f]{64}', head) is None):
        raise ValueError('journal receipt binds a different claim, plan or head')
    if not journal_path.is_file():
        raise ValueError('journal proof file is missing')
    records = AppendOnlyStore(journal_path, expected_head=head).read()
    if not records or records[-1].hash != head:
        raise ValueError('journal does not match the evidence claim')

    planned = {visit['visit_id']: visit for visit in plan['visits']}
    sources = {source['source_id']: Source(source['source_id'], source['name'], source['url'])
               for source in plan['sources']}
    kickoffs = {fixture['fixture_id']: parse_instant(fixture['kickoff']) for fixture in plan['fixtures']}
    by_source = {
        source_id: dict.fromkeys(OUTCOMES.values(), 0) | {'withoutReceipt': count}
        for source_id, count in counts_by_source.items()
    }
    publications: set[str] = set()
    for record in records:
        entity = record.entity
        if isinstance(entity, Source) and entity != sources.get(entity.source_id):
            raise ValueError('journal source does not match the exact plan')
        if isinstance(entity, Visit):
            expected = planned.get(entity.visit_id)
            if (expected is None or entity.source_id != expected['source_id']
                    or entity.planned_at != parse_instant(expected['planned_at'])
                    or entity.completed_at is not None or entity.succeeded):
                raise ValueError('journal visit does not match the exact plan')
        elif isinstance(entity, VisitReceipt):
            visit_plan = planned[entity.visit_id]
            if entity.status == 'ok':
                if not any(entity.completed_at < kickoffs[fixture_id]
                           for fixture_id in visit_plan['fixture_ids']):
                    raise ValueError('successful journal visit ended at or after kickoff')
                publications.update(entity.publication_ids)
            source_counts = by_source[visit_plan['source_id']]
            source_counts[OUTCOMES[entity.status]] += 1
            source_counts['withoutReceipt'] -= 1
    return {
        'claimId': claim['claim_id'],
        'journalHead': head,
        'bySource': by_source,
        'totals': {key: sum(row[key] for row in by_source.values())
                   for key in (*OUTCOMES.values(), 'withoutReceipt')},
        'publications': len(publications),
    }


def build_snapshot(
    registry_path: Path, plan_path: Path, graph_path: Path, plan_claim_id: str, *,
    journal_path: Path | None = None, journal_claim_id: str | None = None,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    plan_bytes = _versioned_bytes(plan_path)
    plan_hash = sha256(plan_bytes).hexdigest()
    plan = json.loads(plan_bytes)
    graph = json.loads(graph_path.read_bytes())
    plan_claim = _get_claim(graph, plan_claim_id)
    if re.search(rf'\b{plan_hash}\b', plan_claim.get('claim', '')) is None:
        raise ValueError('plan hash does not match evidence claim')

    source_registry_hash = sha256(_versioned_bytes(registry_path)).hexdigest()
    sources = load_sources(registry_path)
    fixtures = tuple(Fixture(item['fixture_id'], parse_instant(item['kickoff']),
                             item['evidence_url']) for item in plan['fixtures'])
    if build_plan(sources, fixtures, starts_at=parse_instant(plan['starts_at']),
                  registry_sha256=source_registry_hash) != plan:
        raise ValueError('plan cannot be reproduced from its registry and fixtures')

    if sum(item is None for item in (journal_path, journal_claim_id, receipt_path)) not in (0, 3):
        raise ValueError('journal, receipt artifact and evidence claim must be supplied together')
    counts_by_source = Counter(visit['source_id'] for visit in plan['visits'])
    observations = None
    if journal_path is not None and journal_claim_id is not None and receipt_path is not None:
        observations = _observations(
            plan, journal_path, receipt_path, _get_claim(graph, journal_claim_id), plan_hash, counts_by_source,
        )
    return {
        'plan': {
            'claimId': plan_claim_id,
            'sha256': plan_hash,
            'registrySha256': source_registry_hash,
            'startsAt': plan['starts_at'],
            'lastVisitAt': plan['visits'][-1]['planned_at'],
            'fixtureCount': len(fixtures),
            'plannedVisits': len(plan['visits']),
        },
        'sources': [{'id': source.source_id, 'name': source.name, 'audience': source.audience,
                     'access': source.state, 'plannedVisits': counts_by_source[source.source_id]}
                    for source in sources],
        'observations': observations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=DATA / 'pilot_sources.csv')
    parser.add_argument('--plan', type=Path, default=DATA / 'visit_plan_20261031_v4.json')
    parser.add_argument('--evidence-graph', type=Path, default=ROOT / 'reports/evidence/evidence-graph.json')
    parser.add_argument('--plan-claim-id', default=PLAN_CLAIM)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--journal-claim-id')
    parser.add_argument('--journal-receipt', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inputs = (args.registry, args.plan, args.evidence_graph, args.journal, args.journal_receipt)
    if any(path is not None and path.resolve() == args.output.resolve() for path in inputs):
        parser.error('output cannot overwrite an input')
    snapshot = build_snapshot(
        args.registry, args.plan, args.evidence_graph, args.plan_claim_id,
        journal_path=args.journal, journal_claim_id=args.journal_claim_id,
        receipt_path=args.journal_receipt,
    )
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n',
    )


if __name__ == '__main__':
    main()
