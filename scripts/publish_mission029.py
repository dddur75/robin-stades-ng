"""Append only normalized Parquet and sanitized receipts; never checkout data blobs."""
import hashlib
import os
import subprocess
import time
from pathlib import Path

from robin.historical_deep.adapters import R2ObjectStore
from scripts.run_mission029 import OUTPUT, PREFIX


def git(repo, *args, data=None):
    return subprocess.check_output(['git', '--git-dir', str(repo), *args], input=data).strip()


def append_tree(repo, files):
    for path in files:
        if 'season=2025' in path or '..' in Path(path).parts or not path.startswith(
            ('historical/parquet/', 'reports/evidence/mission029/')):
            raise ValueError('MISSION029_PUBLICATION_HOLDOUT_OR_PATH')
    head = git(repo, 'rev-parse', 'refs/heads/historical-data').decode()
    existing = {line.split(b'\t', 1)[1].decode(): line.split(b' ', 2)[2].split(b'\t')[0].decode()
        for line in git(repo, 'ls-tree', '-r', '-z', head).split(b'\0') if line}
    git(repo, 'read-tree', head)
    changed = False
    for path, body in files.items():
        digest = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body, usedforsecurity=False).hexdigest()
        if path in existing:
            if existing[path] != digest:
                raise ValueError('MISSION029_PUBLICATION_CONFLICT')
            continue
        sha = git(repo, 'hash-object', '-w', '--stdin', data=body).decode()
        git(repo, 'update-index', '--add', '--cacheinfo', '100644', sha, path)
        changed = True
    if not changed:
        return None
    tree = git(repo, 'write-tree').decode()
    commit = git(repo, 'commit-tree', tree, '-p', head, data=b'029: append normalized data and receipts\n').decode()
    git(repo, 'update-ref', 'refs/heads/historical-data', commit, head)
    return commit


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('MISSION029_ACTIONS_REQUIRED')
    repo = OUTPUT / '.publication.git'
    subprocess.run(['git', '-c', 'credential.helper=!gh auth git-credential', 'clone', '--bare',
        '--depth=1', '--filter=blob:none', '--single-branch', '--branch', 'historical-data',
        'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '.git', str(repo)], check=True)
    existing = set(git(repo, 'ls-tree', '-r', '--name-only', 'historical-data').decode().splitlines())
    store, files, deadline = R2ObjectStore(os.environ), {}, time.monotonic() + 300
    for prefix in (f'{PREFIX}/runs/', f'{PREFIX}/projection/'):
        for key in store.iter_keys(prefix):
            path = (key.removeprefix(prefix) if '/projection/' in prefix else
                'reports/evidence/mission029/runs/' + key.removeprefix(prefix))
            if path in existing:
                continue
            if time.monotonic() >= deadline or len(files) >= 1000:
                break
            if 'season=2025' in path:
                raise ValueError('MISSION029_PUBLICATION_HOLDOUT')
            files[path] = store.get_object(key)
    for name in ('AUTHOR', 'COMMITTER'):
        os.environ[f'GIT_{name}_NAME'] = 'Codex data collector'
        os.environ[f'GIT_{name}_EMAIL'] = 'codex-data@users.noreply.github.com'
    if append_tree(repo, files):
        git(repo, '-c', 'credential.helper=!gh auth git-credential', 'push', 'origin',
            'refs/heads/historical-data:refs/heads/historical-data')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
