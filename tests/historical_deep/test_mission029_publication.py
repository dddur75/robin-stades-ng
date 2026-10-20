"""Receipt reconciliation must prove content, resume, and never recollect."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from robin.historical_deep.storage import InMemoryObjectStore
from scripts import publish_mission029 as publication

PREFIX = 'historical-deep-data/schema-v1/_control/mission-029'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for name in ('GIT_AUTHOR_NAME', 'GIT_COMMITTER_NAME'):
        monkeypatch.setenv(name, 'Synthetic')
    for name in ('GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_EMAIL'):
        monkeypatch.setenv(name, 'synthetic@example.invalid')
    subprocess.run(['git', 'init', '--bare', str(tmp_path)], check=True, capture_output=True)
    tree = publication.git(tmp_path, 'mktree', data=b'').decode()
    head = publication.git(tmp_path, 'commit-tree', tree, data=b'Initial\n').decode()
    publication.git(tmp_path, 'update-ref', 'refs/heads/historical-data', head)
    return tmp_path


def partition(number, family='events', season=2020, prefix=PREFIX):
    path = (f'historical/parquet/competition=E0/season={season}/entity_type={family}/'
            f'dataset_version=api-football-v3/fixture-{number}.parquet')
    body = f'synthetic normalized fixture {number}'.encode()
    return dict(path=path, sha256=hashlib.sha256(body).hexdigest(),
                r2_key=f'{prefix}/projection/{path}'), body


def store_with_receipt(parts, phase='B', prefix=PREFIX):
    store = InMemoryObjectStore()
    receipt = json.dumps(dict(phase=phase, partitions=[p for p, _ in parts])).encode()
    store.put_if_absent(f'{prefix}/runs/1-1/{phase}-public-receipt.json', receipt)
    for spec, body in parts:
        store.put_if_absent(spec['r2_key'], body)
    return store


def test_old_receipt_objects_are_drained_across_batches_and_second_run_is_noop(repo):
    parts = [partition(i) for i in range(5)]
    store = store_with_receipt(parts)
    expected, receipts = publication.load_references(store)
    pushed = []
    first = publication.catch_up(repo, store, expected, receipts, batch_size=2,
                                 max_batches=1, publish=lambda: pushed.append(True))
    assert first['status'] == 'PARTIAL'
    assert first['phases']['B_events']['missing'] > 0
    final = publication.catch_up(repo, store, expected, receipts, batch_size=2,
                                 max_batches=10, publish=lambda: pushed.append(True))
    assert final['status'] == 'COMPLETE'
    assert final['phases']['B_events'] == dict(expected=5, published=5, missing=0, mismatched=0)
    for spec, body in parts:
        assert publication.git(repo, 'show', 'historical-data:' + spec['path']) == body
    head = publication.git(repo, 'rev-parse', 'historical-data')
    count = len(pushed)
    assert publication.catch_up(repo, store, expected, receipts)['status'] == 'COMPLETE'
    assert publication.git(repo, 'rev-parse', 'historical-data') == head
    assert len(pushed) == count


def test_existing_path_with_wrong_content_is_not_counted_as_published_or_overwritten(repo):
    spec, body = partition(1)
    publication.append_tree(repo, {spec['path']: b'previous immutable bytes'})
    store = store_with_receipt([(spec, body)])
    expected, receipts = publication.load_references(store)
    report = publication.catch_up(repo, store, expected, receipts)
    assert report['status'] == 'BLOCKED'
    assert report['phases']['B_events'] == dict(expected=1, published=0, missing=0, mismatched=1)
    assert report['issues'][0]['reason'] == 'PUBLISHED_SHA256_MISMATCH'
    assert publication.git(repo, 'show', 'historical-data:' + spec['path']) == b'previous immutable bytes'


@pytest.mark.parametrize('bad_body,reason', [(None, 'R2_OBJECT_MISSING'), (b'corrupt', 'R2_SHA256_MISMATCH')])
def test_missing_or_corrupt_r2_object_stops_without_false_completion(repo, bad_body, reason):
    spec, body = partition(1)
    store = store_with_receipt([(spec, body)])
    original = store.get_object
    store.get_object = lambda key: bad_body if key == spec['r2_key'] else original(key)
    expected, receipts = publication.load_references(store)
    report = publication.catch_up(repo, store, expected, receipts, max_batches=10)
    assert report['status'] == 'BLOCKED'
    assert any(i['reason'] == reason for i in report['issues'])
    assert report['phases']['B_events']['published'] == 0


def test_holdout_is_excluded_from_metadata_before_any_payload_read(repo):
    spec, body = partition(1, season=2025)
    store = store_with_receipt([(spec, body)])
    original = store.get_object
    def guarded(key):
        assert 'season=2025/' not in key
        return original(key)
    store.get_object = guarded
    expected, receipts = publication.load_references(store)
    assert not any('season=2025/' in p for p in expected)
    assert publication.catch_up(repo, store, expected, receipts)['status'] == 'COMPLETE'


def test_conflicting_receipts_and_foreign_r2_keys_fail_closed():
    spec, body = partition(1)
    store = store_with_receipt([(spec, body)])
    bad = dict(spec, sha256='f' * 64)
    store.put_if_absent(f'{PREFIX}/runs/2-1/B-public-receipt.json',
                        json.dumps(dict(phase='B', partitions=[bad])).encode())
    with pytest.raises(ValueError, match='RECEIPT_CONFLICT'):
        publication.load_references(store)
    store = store_with_receipt([(dict(spec, r2_key='raw/private'), body)])
    with pytest.raises(ValueError, match='REFERENCE_SCOPE'):
        publication.load_references(store)


def test_compositions_from_027_have_their_own_verified_phase(repo):
    prefix = PREFIX.replace('029', '027')
    spec, body = partition(1, family='lineups', prefix=prefix)
    store = store_with_receipt([(spec, body)], phase='lineups', prefix=prefix)
    expected, receipts = publication.load_references(store)
    report = publication.catch_up(repo, store, expected, receipts, max_batches=10)
    assert report['phases']['compositions']['published'] == 1
    assert report['status'] == 'COMPLETE'


def test_same_content_referenced_by_several_phases_is_not_a_conflict():
    spec, body = partition(1)
    store = store_with_receipt([(spec, body)])
    store.put_if_absent(f'{PREFIX}/runs/2-1/D-public-receipt.json',
                        json.dumps(dict(phase='D', partitions=[spec])).encode())
    expected, _ = publication.load_references(store)
    assert expected[spec['path']]['phase'] == 'B_events'


def test_new_receipt_appearing_during_publication_is_drained_before_completion(repo):
    first, second = partition(1), partition(2)
    store = store_with_receipt([first])
    def publish():
        spec, body = second
        store.put_if_absent(spec['r2_key'], body)
        store.put_if_absent(f'{PREFIX}/runs/2-1/B-public-receipt.json',
                            json.dumps(dict(phase='B', partitions=[spec])).encode())
    report = publication.drain(repo, store, until_complete=True, publish=publish)
    assert report['status'] == 'COMPLETE'
    assert report['phases']['B_events']['published'] == 2
    assert report['before_phases']['B_events']['published'] == 0


def test_deadline_stops_queued_reads_and_leaves_resumable_partial_checkpoint(repo, monkeypatch):
    store = store_with_receipt([partition(i) for i in range(20)])
    expected, receipts = publication.load_references(store)
    clock, reads, checkpoints = [0.0], [], []
    original = store.get_object
    def get(key):
        reads.append(key)
        clock[0] += 10
        return original(key)
    store.get_object = get
    monkeypatch.setattr(publication.time, 'monotonic', lambda: clock[0])
    report = publication.catch_up(repo, store, expected, receipts, batch_size=1000,
        max_batches=10, max_seconds=1, checkpoint=checkpoints.append)
    assert report['status'] == 'PARTIAL'
    assert len(reads) == 1
    assert checkpoints[-1]['status'] == 'PARTIAL'
    assert report['phases']['B_events']['published'] == 1


def test_manual_catchup_isolated_from_all_provider_jobs_and_secrets():
    source = Path('.github/workflows/71-historical-deep-fixture-bundle-harvest.yml').read_text()
    workflow = yaml.safe_load(source)
    triggers = workflow.get('on', workflow.get(True))
    assert triggers['workflow_dispatch']['inputs']['publication_catchup']['default'] is False
    assert '!inputs.publication_catchup' in workflow['jobs']['fixture-bundles']['if']
    job = workflow['jobs']['publication-catchup']
    assert 'workflow_dispatch' in job['if'] and 'inputs.publication_catchup' in job['if']
    assert 'API_FOOTBALL' not in json.dumps(job)
    assert 'NEON' not in json.dumps(job)
    assert '--catchup' in json.dumps(job)
    assert 'run_mission029' not in Path('scripts/publish_mission029.py').read_text()


def test_publication_r2_adapter_bounds_inflight_requests_and_denies_writes(monkeypatch):
    configuration = []
    def client(service, **kwargs):
        configuration.append(kwargs['config'])
        return object()
    monkeypatch.setattr('boto3.client', client)
    env = {name: 'synthetic' for name in ('R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID',
                                         'R2_SECRET_ACCESS_KEY', 'R2_BUCKET_NAME')}
    store = publication.PublicationR2(env)
    assert configuration[0].connect_timeout <= 10
    assert configuration[0].read_timeout <= 30
    assert configuration[0].retries['total_max_attempts'] == 2
    with pytest.raises(RuntimeError, match='WRITE_FORBIDDEN'):
        store.put_if_absent('normalized/object', b'value')


def test_partial_git_clone_hydrates_only_selected_blobs(repo, tmp_path_factory, monkeypatch):
    first, second = partition(1), partition(2)
    publication.append_tree(repo, {first[0]['path']: first[1], second[0]['path']: second[1]})
    publication.git(repo, 'config', 'uploadpack.allowFilter', 'true')
    publication.git(repo, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    clone = tmp_path_factory.mktemp('partial-git') / 'data.git'
    subprocess.run(['git', 'clone', '--no-local', '--bare', '--filter=blob:none',
                    '--single-branch', '--branch', 'historical-data', repo.as_uri(), str(clone)],
                   check=True, capture_output=True)
    original = publication.git
    def local_transport(repo, *args, data=None, network=False):
        if network:  # Real local upload-pack; no HTTP or credentials in synthetic tests.
            return subprocess.check_output(['git', '-c', 'protocol.file.allow=always',
                '--git-dir', str(repo), *args], input=data, stderr=subprocess.PIPE,
                env=dict(os.environ, GIT_NO_LAZY_FETCH='1')).strip()
        return original(repo, *args, data=data)
    monkeypatch.setattr(publication, 'git', local_transport)
    publication.hydrate(clone, {first[0]['path']: {}})
    published = publication.inventory(clone)
    cache = {}
    publication.blob_hashes(clone, {published[first[0]['path']]}, cache)
    assert cache[published[first[0]['path']]] == first[0]['sha256']
    excluded = published[second[0]['path']]
    assert original(clone, 'cat-file', '--batch-check', data=(excluded+'\n').encode()).endswith(b' missing')
