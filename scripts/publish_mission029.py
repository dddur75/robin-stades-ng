"""Reconcile immutable receipt references, without importing any collector.

Subprocesses invoke fixed Git subcommands via argv, never a shell. Only explicit
clone/fetch/push calls allow HTTPS; local object reads forbid every protocol.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config

from robin.historical_deep.adapters import R2ObjectStore

PREFIX = 'historical-deep-data/schema-v1/_control/mission-029'
OUTPUT = Path('artifacts/historical-deep/mission029')
PREFIXES = (PREFIX, PREFIX.replace('029', '027'))
PHASES = ('B_calendars', 'compositions', 'B_events', 'C_players')


class PublicationR2(R2ObjectStore):
    """Read-only adapter with bounded retries; collector defaults stay untouched."""

    def __init__(self, environment):
        names = ('R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME')
        if any(not environment.get(name) for name in names):
            raise RuntimeError('PUBLICATION_R2_CREDENTIALS_MISSING')
        self.bucket = environment['R2_BUCKET_NAME']
        self.client = boto3.client('s3', region_name='auto',
            endpoint_url=f'https://{environment["R2_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
            aws_access_key_id=environment['R2_ACCESS_KEY_ID'],
            aws_secret_access_key=environment['R2_SECRET_ACCESS_KEY'],
            config=Config(connect_timeout=10, read_timeout=30,
                          retries={'mode': 'standard', 'total_max_attempts': 2}))

    def put_if_absent(self, key, data):
        raise RuntimeError('PUBLICATION_R2_WRITE_FORBIDDEN')


def git(repo, *args, data=None, network=False):
    argv = ['git', '-c', 'protocol.allow=never', '-c',
        f'protocol.https.allow={"always" if network else "never"}',
        '-c', 'credential.helper=!gh auth git-credential', '--git-dir', str(repo), *args]
    return subprocess.check_output(argv, input=data, stderr=subprocess.PIPE,  # nosec B603
        env=dict(os.environ, GIT_NO_LAZY_FETCH='1')).strip()


def append_tree(repo, files):
    for path in files:
        if 'season=2025' in path or '..' in Path(path).parts or not path.startswith(
            ('historical/parquet/', 'reports/evidence/mission029/', 'reports/evidence/mission027/')):
            raise ValueError('MISSION029_PUBLICATION_HOLDOUT_OR_PATH')
    head = git(repo, 'rev-parse', 'refs/heads/historical-data').decode()
    existing = {line.split(b'\t', 1)[1].decode(): line.split(b' ', 2)[2].split(b'\t')[0].decode()
        for line in git(repo, 'ls-tree', '-r', '-z', head).split(b'\0') if line}
    git(repo, 'read-tree', head)
    updates = []
    for path, body in files.items():
        digest = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body, usedforsecurity=False).hexdigest()
        if path in existing:
            if existing[path] != digest:
                raise ValueError('MISSION029_PUBLICATION_CONFLICT')
            continue
        sha = git(repo, 'hash-object', '-w', '--stdin', data=body).decode()
        updates.append(f'100644 {sha}\t{path}\0'.encode())
    if not updates:
        return None
    # One index rewrite per batch, rather than once per object in a growing tree.
    git(repo, 'update-index', '-z', '--index-info', data=b''.join(updates))
    # Existing entries come from the remote parent tree; do not hydrate unrelated
    # (including holdout) blobs merely to preserve their unchanged object IDs.
    tree = git(repo, 'write-tree', '--missing-ok').decode()
    commit = git(repo, 'commit-tree', tree, '-p', head, data=b'029: append normalized data and receipts\n').decode()
    git(repo, 'update-ref', 'refs/heads/historical-data', commit, head)
    return commit


def load_references(store):
    """Freeze public receipts, deduplicate references, reject contradictory proofs."""
    expected, receipts = {}, {}
    for prefix in PREFIXES:
        for key in sorted(store.iter_keys(f'{prefix}/runs/')):
            if not key.endswith('public-receipt.json'):
                continue
            suffix = key.removeprefix(f'{prefix}/runs/')
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.json', suffix):
                raise ValueError('REFERENCE_SCOPE')
            body = store.get_object(key)
            if body is None:
                raise ValueError('RECEIPT_MISSING')
            receipts[key] = body
            mission = prefix.rsplit('-', 1)[1]
            path = f'reports/evidence/mission{mission}/runs/{suffix}'
            expected[path] = dict(sha256=hashlib.sha256(body).hexdigest(), r2_key=key, phase='receipts')
            receipt = json.loads(body)
            for spec in receipt.get('partitions', []):
                path = spec['path']
                # Pre-48a93765 mission027 receipts retained the producer's absolute
                # runner path. Only this exact historical root is an alias; the
                # canonical path must still equal the immutable R2 projection key.
                legacy = '/'.join(('', 'home', 'runner', 'work', 'robin-stades-ng',
                                   'robin-stades-ng', 'artifacts', 'historical-deep', 'mission027', ''))
                if mission == '027' and path.startswith(legacy):
                    path = path.removeprefix(legacy)
                # Holdout exclusion is metadata-only and precedes every object read.
                if 'season=2025/' in path:
                    continue
                if (not re.fullmatch(r'historical/parquet/competition=[\w-]+/season=\d{4}/'
                    r'entity_type=[a-z_]+/dataset_version=[\w.-]+/[\w.-]+\.parquet', path)
                    or spec['r2_key'] != f'{prefix}/projection/{path}'
                    or not re.fullmatch('[a-f0-9]{64}', spec['sha256'])):
                    raise ValueError('REFERENCE_SCOPE')
                family = re.search(r'/entity_type=([^/]+)/', path)[1]
                phase = ('compositions' if family == 'lineups' else
                    {'B-calendars': 'B_calendars', 'B': 'B_events', 'C': 'C_players'}.get(
                        receipt.get('phase'), f'{receipt.get("phase", mission)}_{family}'))
                value = dict(sha256=spec['sha256'], r2_key=spec['r2_key'], phase=phase)
                if path in expected and expected[path]['sha256'] != value['sha256']:
                    raise ValueError('RECEIPT_CONFLICT')
                expected.setdefault(path, value)
    if not receipts:
        raise ValueError('RECEIPTS_EMPTY')
    return expected, receipts


def inventory(repo):
    return {line.split(b'\t', 1)[1].decode(): line.split(b' ', 2)[2].split(b'\t')[0].decode()
        for line in git(repo, 'ls-tree', '-r', '-z', 'historical-data').split(b'\0') if line}


def hydrate(repo, expected):
    """Fetch only referenced, non-holdout blobs explicitly, never lazy-fetch a tree."""
    present = inventory(repo)
    ids = sorted({present[p] for p in expected if p in present})
    if not ids:
        return
    check = git(repo, 'cat-file', '--batch-check', data=('\n'.join(ids)+'\n').encode())
    missing = [line.split()[0].decode() for line in check.splitlines() if line.endswith(b' missing')]
    for start in range(0, len(missing), 500):
        git(repo, 'fetch', '--refetch', '--no-filter', '--no-tags', '--no-write-fetch-head', 'origin', '--stdin',
            data=('\n'.join(missing[start:start+500])+'\n').encode(), network=True)


def blob_hashes(repo, ids, cache):
    argv = ['git', '-c', 'protocol.allow=never', '--git-dir', str(repo), 'cat-file', '--batch']
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # nosec B603
            env=dict(os.environ, GIT_NO_LAZY_FETCH='1')) as child:
        for oid in sorted(ids - cache.keys()):
            child.stdin.write((oid+'\n').encode())
            child.stdin.flush()
            header = child.stdout.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise ValueError('PUBLISHED_BLOB_UNAVAILABLE')
            left, digest = int(header[2]), hashlib.sha256()
            while left:
                chunk = child.stdout.read(min(left, 1024 * 1024))
                if not chunk:
                    raise ValueError('PUBLISHED_BLOB_TRUNCATED')
                digest.update(chunk)
                left -= len(chunk)
            if child.stdout.read(1) != b'\n':
                raise ValueError('PUBLISHED_BLOB_DELIMITER')
            cache[oid] = digest.hexdigest()
        child.stdin.close()
        if child.wait() != 0:
            raise ValueError('PUBLISHED_BLOB_READ_FAILED')


def reconcile(repo, expected, cache, failures):
    published = inventory(repo)
    blob_hashes(repo, {published[p] for p in expected if p in published}, cache)
    phases = {p: dict(expected=0, published=0, missing=0, mismatched=0) for p in PHASES}
    pending, issues = [], []
    for path, spec in sorted(expected.items()):
        counts = phases.setdefault(spec['phase'], dict(expected=0, published=0, missing=0, mismatched=0))
        counts['expected'] += 1
        actual = cache.get(published.get(path))
        if actual is not None:
            field = 'published' if actual == spec['sha256'] else 'mismatched'
            if field == 'mismatched':
                issues.append(dict(path=path, reason='PUBLISHED_SHA256_MISMATCH',
                                   expected=spec['sha256'], actual=actual))
        else:
            field = 'mismatched' if failures.get(path) == 'R2_SHA256_MISMATCH' else 'missing'
            if path in failures:
                issues.append(dict(path=path, reason=failures[path]))
            else:
                pending.append(path)
        counts[field] += 1
    report = dict(status='BLOCKED' if issues else 'PARTIAL' if pending else 'COMPLETE',
        phases=phases, issues=issues, published_revision=git(repo, 'rev-parse', 'historical-data').decode(),
        provider_calls=0, neon_writes=0, r2_writes=0,
        expected_manifest_sha256=hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest())
    report['totals'] = {field: sum(p[field] for p in phases.values())
                        for field in ('expected', 'published', 'missing', 'mismatched')}
    return report, pending


def catch_up(repo, store, expected, receipts, *, batch_size=1000, max_batches=1,
             max_seconds=9600, publish=lambda: None, checkpoint=lambda report: None):
    if min(batch_size, max_batches, max_seconds) <= 0:
        raise ValueError('PUBLICATION_BOUNDS')
    deadline, cache, failures = time.monotonic()+max_seconds, {}, {}
    def read(path):
        if time.monotonic() >= deadline:
            return path, None, 'TIME_BUDGET'
        spec = expected[path]
        try:
            body = receipts.get(spec['r2_key'])
            if body is None:
                body = store.get_object(spec['r2_key'])
            reason = ('R2_OBJECT_MISSING' if body is None else 'R2_SHA256_MISMATCH'
                      if hashlib.sha256(body).hexdigest() != spec['sha256'] else None)
        except Exception:
            body, reason = None, 'R2_READ_FAILED'
        return path, body, reason
    for number in range(max_batches):
        report, pending = reconcile(repo, expected, cache, failures)
        report['batches'] = number
        checkpoint(report)
        if (not pending or time.monotonic() >= deadline or
                any(i['reason'] == 'PUBLISHED_SHA256_MISMATCH' for i in report['issues'])):
            return report
        pending.sort(key=lambda p: (PHASES.index(expected[p]['phase'])
            if expected[p]['phase'] in PHASES else len(PHASES), p))
        files = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for path, body, reason in pool.map(read, pending[:batch_size]):
                if reason == 'TIME_BUDGET':
                    continue  # Not an object failure: the next pass resumes this path.
                if reason:
                    failures[path] = reason
                else:
                    files[path] = body
        if files and append_tree(repo, files):
            publish()  # A rejected push raises; no remote-success checkpoint is written.
        checkpoint(dict(batch=number+1, objects=len(files), failures=len(failures)))
    report, _ = reconcile(repo, expected, cache, failures)
    report['batches'] = max_batches
    checkpoint(report)
    return report


def drain(repo, store, *, until_complete=False, batch_size=1000, max_seconds=9600,
          publish=lambda: None, checkpoint=lambda report: None, manifest=lambda expected: None):
    deadline, before = time.monotonic()+max_seconds, None
    while True:
        expected, receipts = load_references(store)
        manifest(expected)
        hydrate(repo, expected)
        if before is None:
            before = reconcile(repo, expected, {}, {})[0]['phases']
        report = catch_up(repo, store, expected, receipts, batch_size=batch_size,
            max_batches=100000 if until_complete else 1,
            max_seconds=max(0.001, deadline-time.monotonic()), publish=publish, checkpoint=checkpoint)
        report['before_phases'] = before
        if not until_complete or report['status'] != 'COMPLETE':
            return report
        refreshed, _ = load_references(store)
        if refreshed == expected:
            return report
        if time.monotonic() >= deadline:
            report, _ = reconcile(repo, refreshed, {}, {})
            report.update(before_phases=before, reason='TIME_BUDGET_RECEIPT_INVENTORY_CHANGED')
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catchup', action='store_true')
    parser.add_argument('--batch-size', type=int, default=1000)
    parser.add_argument('--max-seconds', type=int, default=9600)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or not 1 <= args.max_seconds <= 9600:
        parser.error('PUBLICATION_BOUNDS')
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('MISSION029_ACTIONS_REQUIRED')
    repo = OUTPUT / '.publication.git'
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('PUBLICATION_REPOSITORY')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT / 'publication-report.json'
    def checkpoint(report):
        if 'status' in report:
            report_path.write_text(json.dumps(report, indent=2)+'\n')
        with (OUTPUT / 'publication-batches.jsonl').open('a') as stream:
            stream.write(json.dumps(report)+'\n')
        print(json.dumps({k: v for k, v in report.items() if k != 'issues'}), flush=True)
    for name in ('AUTHOR', 'COMMITTER'):
        os.environ[f'GIT_{name}_NAME'] = 'Codex data collector'
        os.environ[f'GIT_{name}_EMAIL'] = 'codex-data@users.noreply.github.com'
    try:
        if not repo.exists():
            git_binary = shutil.which('git')
            if git_binary is None:
                raise RuntimeError('GIT_UNAVAILABLE')
            subprocess.run([git_binary, '-c', 'credential.helper=!gh auth git-credential',  # nosec B603
                'clone', '--bare', '--depth=1', '--filter=blob:none', '--single-branch',
                '--branch', 'historical-data', 'https://github.com/'+repository+'.git', str(repo)], check=True)
        else:
            # Resume from the remote checkpoint, including after an ambiguous push.
            git(repo, 'fetch', '--filter=blob:none', '--no-tags', 'origin',
                '+refs/heads/historical-data:refs/remotes/origin/historical-data', network=True)
            head = git(repo, 'rev-parse', 'refs/remotes/origin/historical-data').decode()
            git(repo, 'update-ref', 'refs/heads/historical-data', head)
        def publish():
            git(repo, 'push', 'origin', 'refs/heads/historical-data:refs/heads/historical-data', network=True)
        report = drain(repo, PublicationR2(os.environ), until_complete=args.catchup,
            batch_size=args.batch_size, max_seconds=args.max_seconds if args.catchup else 300,
            publish=publish, checkpoint=checkpoint,
            manifest=lambda expected: (OUTPUT / 'publication-expected.json').write_text(
                json.dumps(expected, sort_keys=True)+'\n'))
        report['code_revision'] = os.environ.get('GITHUB_SHA')
        checkpoint(report)
        run = os.environ['GITHUB_RUN_ID']+'-'+os.environ.get('GITHUB_RUN_ATTEMPT', '1')
        if append_tree(repo, {f'reports/evidence/mission029/publication/{run}/report.json': report_path.read_bytes()}):
            publish()
        print(json.dumps(dict(status=report['status'], historical_data_revision=
            git(repo, 'rev-parse', 'historical-data').decode())), flush=True)
        return 0 if report['status'] == 'COMPLETE' or not args.catchup else 2
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch('[A-Z_]+', str(error)) else type(error).__name__
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        report.update(status='BLOCKED', reason=code, provider_calls=0, neon_writes=0, r2_writes=0)
        if isinstance(error, subprocess.CalledProcessError):
            report['failed_git_operation'] = (error.cmd[error.cmd.index('--git-dir')+2]
                                             if '--git-dir' in error.cmd else 'clone')
            report['git_returncode'] = error.returncode
        checkpoint(report)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
