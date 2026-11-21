import json
import sys
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from robin.source_observatory import roster_successor_view as view


def observation():
    pick = dict(
        id="olbg-tip:1",
        authorId="olbg:13000",
        authorUrl="https://www.olbg.com/tipsters/tips/13000",
        sourceTipId="1",
        fixtureId="f1",
        observedAt="2026-11-21T11:00:00Z",
        firstSeenAt="2026-11-21T11:00:00Z",
    )
    return dict(
        picks=[pick],
        claimId="TEST.NEXT",
        generatedAt="2026-11-21T12:00:00Z",
        rosterCampaign=dict(
            campaignId=view.CAMPAIGN_ID,
            state="scheduled",
            authorIds=["olbg:13000"],
            poolAuthorIds=["olbg:13000"],
            requests=0,
            requestsMax=129,
            successfulSlots=0,
            slots=3,
            lastObservedAt=None,
        ),
    )


def test_successor_preserves_old_campaign_and_exact_existing_choice(monkeypatch):
    observed = observation()
    base = dict(
        picks=deepcopy(observed["picks"]),
        claimId="TEST.OLD",
        generatedAt="2026-11-21T11:00:00Z",
        rosterCampaign=dict(state="completed", requests=133),
    )
    original = deepcopy(base)
    monkeypatch.setattr(view, "_read", lambda root: (observed, True))
    result = view.add_next_public(base, Path("unused"))
    assert base == original
    assert result["picks"] == original["picks"]
    assert result["rosterCampaign"] == original["rosterCampaign"]
    assert result["rosterNextCampaign"]["requests"] == 0
    assert result["rosterNextCampaign"]["successfulSlots"] == 0


def test_invalid_successor_keeps_facts_and_revokes_its_flags(monkeypatch):
    def invalid(root):
        raise ValueError("invalid authority")

    monkeypatch.setattr(view, "_read", invalid)
    base = dict(
        candidates=[
            dict(
                collectionEnabled=True,
                qualification=dict(rosterCampaignId=view.CAMPAIGN_ID, picks=[dict(id="old")]),
            )
        ],
        qualification=dict(status="ok"),
    )
    result = view.add_next_candidates(base, Path("unused"))
    assert result["candidates"][0]["collectionEnabled"] is False
    assert result["candidates"][0]["qualification"]["picks"] == [dict(id="old")]
    assert result["qualification"]["rosterNextState"] == "unavailable"
    assert base["candidates"][0]["collectionEnabled"] is True


def test_missing_successor_does_not_claim_an_installed_campaign(monkeypatch):
    monkeypatch.setattr(view, "_read", lambda root: None)
    base = dict(picks=[], rosterCampaign=dict(requests=133))
    assert view.add_next_public(base, Path("unused")) == base


def test_conflicting_successor_cannot_replace_historical_choice(monkeypatch):
    observed = observation()
    base = dict(
        picks=[{**observed["picks"][0], "authorId": "olbg:999"}],
        claimId="TEST.OLD",
        generatedAt="2026-11-21T11:00:00Z",
    )
    monkeypatch.setattr(view, "_read", lambda root: (observed, True))
    result = view.add_next_public(base, Path("unused"))
    assert result["picks"] == base["picks"]
    assert result["rosterNextCampaign"]["state"] == "unavailable"


def test_unavailable_base_cannot_be_reported_as_accepted_next(monkeypatch):
    monkeypatch.setattr(view, "_read", lambda root: (observation(), True))
    result = view.add_next_candidates(
        dict(candidates=[], qualification=dict(status="unavailable")), Path("unused")
    )
    assert result["qualification"]["rosterNextState"] == "unavailable"


def test_candidate_summaries_keep_the_old_campaign_separate(monkeypatch):
    monkeypatch.setattr(view, "_read", lambda root: (observation(), True))
    base = dict(
        candidates=[],
        qualification=dict(status="ok", rosterRecurringState="historical", rosterCampaignId="OLD"),
    )
    result = view.add_next_candidates(base, Path("unused"))
    assert result["qualification"]["rosterRecurringState"] == "historical"
    assert result["qualification"]["rosterCampaignId"] == "OLD"
    assert result["qualification"]["rosterNextCampaignId"] == view.CAMPAIGN_ID


def test_new_campaign_cannot_reassign_a_later_admitted_outside_author(monkeypatch):
    observed = observation()
    observed["rosterCampaign"]["profileCount"] = 1
    monkeypatch.setattr(view, "_read", lambda root: (observed, True))
    source_url = "https://www.olbg.com/tipsters/tips/13000"
    old = {**observed["picks"][0], "authorId": "olbg:669088"}
    base = dict(
        candidates=[
            dict(
                id="other",
                collectionEnabled=False,
                qualification=dict(picks=[old]),
                sourceUrl="https://www.olbg.com/tipsters/tips/669088",
                origin=dict(sheet="Catalogue", row=70),
            ),
            dict(
                id="member",
                collectionEnabled=False,
                qualification=dict(picks=[]),
                sourceUrl=source_url,
                origin=dict(sheet="Catalogue", row=2),
            ),
        ],
        rosterAssessments=[
            dict(
                candidateId="member",
                recordId="r",
                sourceUrl=source_url,
                sheet="Catalogue",
                row=2,
                collectionEnabled=False,
                qualification=dict(picks=[]),
            )
        ],
        qualification=dict(status="ok"),
    )
    result = view.add_next_candidates(base, Path("unused"))
    assert result["qualification"]["rosterNextState"] == "unavailable"
    assert result["candidates"][0]["qualification"]["picks"] == [old]
    assert result["candidates"][1]["qualification"]["picks"] == []


def test_slow_next_reader_uses_only_the_remaining_parent_budget(tmp_path, monkeypatch):
    packet = tmp_path / "packet"
    packet.mkdir()
    (packet / "runtime").mkdir()
    reader = packet / "read.py"
    reader.write_text("import time; time.sleep(10)", encoding="utf-8")
    config = tmp_path / view.CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            dict(
                directory=str(packet / "runtime"),
                readerSha256=sha256(reader.read_bytes()).hexdigest(),
                sourceDecisionSha256="1" * 64,
                taskDecisionSha256="2" * 64,
                nativeXmlSha256="3" * 64,
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(view, "PACKET", packet)
    monkeypatch.setattr(view, "READER_SHA256", sha256(reader.read_bytes()).hexdigest(), raising=False)
    monkeypatch.setattr(view, "PYTHON", Path(sys.executable))
    base = dict(picks=[dict(id="preserved")])
    original_run = view.subprocess.run
    timeouts = []

    def record_run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return original_run(*args, **kwargs)

    monkeypatch.setattr(view.subprocess, "run", record_run)
    started = time.monotonic()
    result = view.add_next_public(base, tmp_path, deadline=started + 0.35)
    assert time.monotonic() - started < 1.5
    assert result["picks"] == base["picks"]
    assert result["rosterNextCampaign"]["state"] == "unavailable"
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 0.05


def test_configured_matching_hash_does_not_authorize_a_different_reader(tmp_path, monkeypatch):
    packet = tmp_path / 'packet'
    (packet / 'runtime').mkdir(parents=True)
    reader = packet / 'read.py'
    reader.write_text('# arbitrary replacement')
    config = tmp_path / view.CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(dict(directory=str(packet / 'runtime'), readerSha256=sha256(reader.read_bytes()).hexdigest(), sourceDecisionSha256='1'*64, taskDecisionSha256='2'*64, nativeXmlSha256='3'*64)))
    monkeypatch.setattr(view, 'PACKET', packet)
    monkeypatch.setattr(view, 'READER_SHA256', 'f'*64, raising=False)
    monkeypatch.setattr(view.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('replacement executed')))
    import pytest
    with pytest.raises(ValueError):
        view._read(tmp_path)


def test_same_named_roster_clone_is_refused_before_import(tmp_path, monkeypatch):
    import pytest
    packet = tmp_path / 'trusted' / 'packet'
    (packet / 'runtime').mkdir(parents=True)
    reader = packet / 'read.py'
    reader.write_text('# legitimate pinned reader bytes')
    clone = tmp_path / 'foreign' / packet.name
    (clone / 'runtime').mkdir(parents=True)
    (clone / 'read.py').write_bytes(reader.read_bytes())
    (clone / 'successor.py').write_text('raise RuntimeError("untrusted sibling import")')
    path = tmp_path / view.CONFIG
    path.parent.mkdir(parents=True)
    pin = sha256(reader.read_bytes()).hexdigest()
    path.write_text(json.dumps(dict(directory=str(clone / 'runtime'), readerSha256=pin, sourceDecisionSha256='1'*64, taskDecisionSha256='2'*64, nativeXmlSha256='3'*64)))
    monkeypatch.setattr(view, 'PACKET', packet)
    monkeypatch.setattr(view, 'READER_SHA256', pin)
    monkeypatch.setattr(view.subprocess, 'run', lambda *a, **k: pytest.fail('foreign sibling import started'))
    with pytest.raises(ValueError):
        view._read(tmp_path)


def test_missing_private_config_survives_a_shallow_checkout(tmp_path):
    from types import ModuleType
    shallow = Path(Path(view.__file__).anchor) / 'portable-reader-fixture'
    module = ModuleType('robin.source_observatory.portability_fixture')
    module.__package__ = 'robin.source_observatory'
    module.__file__ = str(shallow / 'src' / 'robin' / 'source_observatory' / Path(view.__file__).name)
    source = Path(view.__file__).read_text(encoding='utf-8')
    exec(compile(source, module.__file__, 'exec'), vars(module))
    assert module._read(tmp_path) is None
