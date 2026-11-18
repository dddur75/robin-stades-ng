"""Local explicit execution/readback of the owner's bounded 57-source mission."""
import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from robin.source_observatory.connectors import (
    Journal,
    build_profiles,
    canonical,
    collect_source,
    read_events,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / 'data/source_observatory/pilot_sources.csv'
CODE = ROOT / 'src/robin/source_observatory/connectors.py'
PINNED = [CODE, Path(__file__), *(ROOT / 'src/robin/source_observatory' / name
          for name in ['collector.py', 'public_formats.py', 'extractor.py', 'schema_validation.py', 'models.py'])]


def code_pins() -> dict[str, str]:
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for p in PINNED}


def html_witness(directory: Path, profile: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    prior = next((r for r in events if r['kind'] == 'SOURCE_FINISHED'
                  and r['sourceId'] == profile['id'] and r['status'] == 'permission_required'), None)
    responses = [r for r in events if r['kind'] == 'REQUEST_FINISHED' and r['sourceId'] == profile['id']]
    reservations = [r for r in events if r['kind'] == 'REQUEST_RESERVED' and r['sourceId'] == profile['id']]
    if (not prior or len(reservations) != 2 or len(responses) != 2
            or any(r['httpStatus'] != 200 for r in responses)
            or [r['url'] for r in responses] != [profile['robotsUrl'], profile['termsUrl']]
            or (datetime.now(UTC) - datetime.fromisoformat(responses[0]['at'])).total_seconds() > 3600):
        raise ValueError('same-day robots witness unavailable')
    old_plan = json.loads((directory / 'plan.json').read_bytes())
    for relative, expected in old_plan['codePins'].items():
        original = directory / 'executed-tooling' / relative
        if sha256(original.read_bytes()).hexdigest() != expected:
            raise ValueError('executed historical tooling witness missing')
    return dict(sourceId=profile['id'], allowedUrls=[profile['endpoint'], profile['termsUrl']],
                robotsReceiptHash=responses[0]['hash'], termsReceiptHash=responses[1]['hash'],
                priorFinishedHash=prior['hash'], userAgent='RobinSourceObservatory/1.0',
                robotsSha256=responses[0]['responseSha256'], checkedAt=responses[0]['at'],
                expiresAt=(datetime.fromisoformat(responses[0]['at']) + timedelta(hours=1)).isoformat(),
                maximumCrawlDelaySeconds=60, historicalCodePins=old_plan['codePins'])


def phase_authorized(phase: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    decisions = [r for r in events if r['kind'] == 'DECISION' and r.get('decisionId') == phase['decisionId']]
    if not decisions:
        return False
    decision = decisions[-1]
    return bool(phase['predecessorHead'] in {r['hash'] for r in events}
        and decision.get('decision') in {'PASS_AND_HOLD', 'PASS_AND_SCALE'}
        and decision.get('responsible') == 'C0'
        and decision.get('predecessorHead') == phase['predecessorHead']
        and decision.get('phaseSha256') == sha256(canonical(phase)).hexdigest())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--init', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--prepare-html-phase', action='store_true')
    parser.add_argument('--run-html-phase', action='store_true')
    parser.add_argument('--source-id', action='append', default=[])
    args = parser.parse_args()
    phase: dict[str, Any] | None = None
    directory = args.directory.resolve()
    profiles = build_profiles(REGISTRY)
    digest = sha256(canonical(profiles)).hexdigest()
    if args.prepare_html_phase:
        events = read_events(directory / 'events.jsonl')
        wanted = set(args.source_id)
        if not wanted or not wanted <= {p['id'] for p in profiles if p['adapter'] in {'html_public', 'forum_html'}}:
            raise ValueError('explicit HTML phase source ids required')
        witnesses = {p['id']: html_witness(directory, p, events) for p in profiles if p['id'] in wanted}
        phase = dict(phaseId='HTML-FACTS-CORRECTION-20261118', predecessorHead=events[-1]['hash'],
            codePins=code_pins(), sourceHash=digest, sourceIds=sorted(wanted), witnesses=witnesses,
            decisionId='RCV3-20261118-CONNECTORS57-HTML-CORRECTION',
            changes='Lift the unsupported categorical HTML refusal. Preserve all other gates and original cumulative budgets.')
        with (directory / 'html-phase.json').open('xb') as stream:
            stream.write(canonical(phase) + b'\n')
    if args.init:
        directory.mkdir(parents=True, exist_ok=True)
        mission = dict(mission_id='TIPSTERS57-20261118-V1', authorized_stages=['E1', 'E2'],
            maximum_stage='E2', external_effects=dict(https_get_max=228, per_source_max=4,
                redirects=0, retries=0, api_football=0, purchases=0, raw_payload_storage=0),
            compute_budget=dict(max_bytes=2_000_000, max_sources=57),
            time_budget=dict(seconds=2700), source_hash=digest,
            expires_at=(datetime.now(UTC) + timedelta(hours=24)).isoformat())
        Journal(directory, mission)
        plan = dict(profiles=profiles, codePins=code_pins(),
                    authority='Owner request: develop and validate the 57 connectors, 2026-11-18')
        with (directory / 'plan.json').open('xb') as stream:
            stream.write(canonical(plan) + b'\n')
    if args.run or args.run_html_phase:
        mission = json.loads((directory / 'mission.json').read_bytes())
        plan = json.loads((directory / 'plan.json').read_bytes())
        phase = json.loads((directory / 'html-phase.json').read_bytes()) if args.run_html_phase else None
        pins = phase['codePins'] if phase else plan['codePins']
        if (mission['source_hash'] != digest or plan['profiles'] != profiles or pins != code_pins()
                or phase and phase['sourceHash'] != digest):
            raise ValueError('pinned source/code mismatch; new plan required')
        permitted = set(phase['sourceIds']) if phase else {p['id'] for p in profiles}
        requested = set(args.source_id) or permitted
        if not requested <= permitted:
            raise ValueError('source outside authorized 57')
        lock_path = directory / 'run.lock'
        # A crash leaves this lock in place: inspect receipts before manual recovery.
        with lock_path.open('x', encoding='utf-8') as lock:
            lock.write(str(os.getpid()))
            lock.flush()
            os.fsync(lock.fileno())
        try:
            journal = Journal(directory, mission)
            if phase:
                if not phase_authorized(phase, journal.events):
                    raise ValueError('HTML phase lacks predecessor/decision witness')
                journal.phase_id = phase['phaseId']
            done = {r['sourceId'] for r in journal.events if r['kind'] == 'SOURCE_FINISHED'
                    and (not phase or r.get('phaseId') == journal.phase_id)}
            reserved = {r['sourceId'] for r in journal.events if r['kind'] == 'REQUEST_RESERVED'
                        and (not phase or r.get('phaseId') == journal.phase_id)}
            journal.append('RUN_STARTED', sourceIds=sorted(requested))
            start = datetime.now(UTC)
            for profile in profiles:
                if profile['id'] not in requested or profile['id'] in done:
                    continue
                # Unknown in-flight request is never retried after an interrupted run.
                if profile['id'] in reserved:
                    journal.append('SOURCE_FINISHED', sourceId=profile['id'],
                        endpoint=profile['endpoint'], adapter=profile['adapter'],
                        status='interrupted_no_retry', permission='not_verified',
                        publications=[], candidates=[])
                    continue
                if (datetime.now(UTC) - start).total_seconds() >= mission['time_budget']['seconds']:
                    journal.append('RUN_STOPPED', reason='time_budget')
                    break
                witness = phase['witnesses'][profile['id']] if phase else None
                if witness and datetime.now(UTC) >= datetime.fromisoformat(witness['expiresAt']):
                    raise ValueError('robots witness expired')
                collect_source(profile, journal, robots_witness=witness)
            journal.append('RUN_FINISHED', verdict='PARTIAL', verifiedPreMatch=0)
        finally:
            lock_path.unlink()
    view = snapshot(directory)
    view['profiles'] = profiles
    view['running'] = (directory / 'run.lock').exists()
    view['mission'] = json.loads((directory / 'mission.json').read_bytes()) if (directory / 'mission.json').exists() else None
    observed_plan = json.loads((directory / 'plan.json').read_bytes()) if (directory / 'plan.json').exists() else None
    pins_valid = bool(observed_plan and observed_plan['codePins'] == code_pins())
    view['canRun'] = bool(pins_valid and view['mission'] and datetime.now(UTC) < datetime.fromisoformat(view['mission']['expires_at']))
    view['launchBlockReason'] = ('Mission locale absente.' if not view['mission'] else
        'Cette qualification est close. Un nouveau plan validé est requis pour la renouveler.' if not pins_valid else
        'Mission expirée. Un nouveau plan est requis.' if not view['canRun'] else None)
    print(json.dumps(view, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps(dict(status='unavailable', errorType=type(exc).__name__,
                             message='Mission locale indisponible : vérifier le plan et les reçus.'), ensure_ascii=False))
        sys.exit(1)
