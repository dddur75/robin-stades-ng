from hashlib import sha256
import pytest
from robin.source_observatory import legacy_bridge


def test_bridge_is_optional_and_never_falls_back_to_arbitrary_script(monkeypatch):
    monkeypatch.delenv('ROBIN_LEGACY_READ_ROOT',raising=False)
    assert legacy_bridge.read_legacy_snapshot('read-public-tipsters.py',[]) is None
    with pytest.raises(ValueError):legacy_bridge.read_legacy_snapshot('collect-profile-tipsters.py',[])


def test_bridge_never_accepts_execution_flags_for_the_pinned_admin_reader(tmp_path,monkeypatch):
    monkeypatch.setenv('ROBIN_LEGACY_READ_ROOT',str(tmp_path))
    with pytest.raises(ValueError):
        legacy_bridge.read_legacy_snapshot('run-tipster-connectors.py',['--run','all'])


def test_bridge_runs_only_pinned_reader_with_its_own_import_root(tmp_path,monkeypatch):
    scripts=tmp_path/'cockpit/scripts';scripts.mkdir(parents=True)
    script=scripts/'read-public-tipsters.py'
    script.write_text("import json, os\nprint(json.dumps({'status':'ok','root':os.environ['PYTHONPATH']}))\n",encoding='utf-8',newline='\n')
    monkeypatch.setenv('ROBIN_LEGACY_READ_ROOT',str(tmp_path))
    monkeypatch.setitem(legacy_bridge.APPROVED_LEGACY_READERS,script.name,sha256(script.read_bytes()).hexdigest())
    result=legacy_bridge.read_legacy_snapshot(script.name,[])
    assert result=={'status':'ok','root':str(tmp_path/'src')}


def test_changed_reader_is_rejected_before_any_script_side_effect(tmp_path,monkeypatch):
    scripts=tmp_path/'cockpit/scripts';scripts.mkdir(parents=True)
    script=scripts/'read-public-tipsters.py';sentinel=tmp_path/'executed'
    script.write_text('from pathlib import Path\nPath('+repr(str(sentinel))+').touch()\n',encoding='utf-8')
    monkeypatch.setenv('ROBIN_LEGACY_READ_ROOT',str(tmp_path))
    with pytest.raises(ValueError):legacy_bridge.read_legacy_snapshot(script.name,[])
    assert not sentinel.exists()
