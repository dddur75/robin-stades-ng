import pytest
from datetime import UTC, datetime

from robin.source_observatory import campaign_view as view


def base():
    return {
        "status": "ok",
        "picks": [
            {
                "id": "one",
                "authorId": "public:a",
                "selection": "1-0",
                "observedAt": "2026-11-19T09:00:00Z",
                "firstSeenAt": "2026-11-19T09:00:00Z",
                "versions": [{"selection": "1-0", "observedAt": "2026-11-19T09:00:00Z"}],
            }
        ],
        "distinctPicks": 1,
        "authorCount": 1,
        "recurring": False,
        "claimId": "DATA.SEED",
    }


def test_scheduled_campaign_keeps_seed_before_first_run(monkeypatch, tmp_path):
    monkeypatch.setattr(view, "read_collection", lambda d: base())
    monkeypatch.setattr(
        view,
        "validate_campaign",
        lambda d: (
            {
                "taskName": "ForumTask",
                "startsAt": "2026-11-20T07:00:00Z",
                "slots": ["2026-11-20T07:00:00Z"],
            },
            {"expires_at": "2026-11-21T07:00:00Z", "external_effects": {"https_get_max": 72}},
        ),
    )
    result = view.read_public_view(
        tmp_path / "seed", tmp_path / "campaign", now=datetime(2026, 11, 19, tzinfo=UTC)
    )
    assert result["distinctPicks"] == 1 and result["recurring"] is False
    assert result["campaign"]["requests"] == 0
    assert result["campaign"]["state"] == "scheduled"


def test_invalid_campaign_does_not_remove_existing_facts(monkeypatch, tmp_path):
    monkeypatch.setattr(view, "read_collection", lambda d: base())

    def invalid(d):
        raise ValueError("pins changed")

    monkeypatch.setattr(view, "validate_campaign", invalid)
    result = view.read_public_view(tmp_path / "seed", tmp_path / "campaign")
    assert result["distinctPicks"] == 1
    assert result["campaign"]["state"] == "invalid_package"


def test_first_campaign_bundle_keeps_seed_and_versions(monkeypatch, tmp_path):
    seed = base()
    active = {
        "picks": [
            {
                "id": "one",
                "authorId": "public:a",
                "selection": "2-0",
                "observedAt": "2026-11-20T07:00:00Z",
                "versions": [{"selection": "2-0", "observedAt": "2026-11-20T07:00:00Z"}],
            },
            {
                "id": "two",
                "authorId": "public:b",
                "selection": "1-1",
                "observedAt": "2026-11-20T07:00:00Z",
                "versions": [{"selection": "1-1", "observedAt": "2026-11-20T07:00:00Z"}],
            },
        ],
        "claimId": "ENG.CAMPAIGN",
        "generatedAt": "2026-11-20T07:01:00Z",
    }
    monkeypatch.setattr(view, "read_collection", lambda d: seed if d.name == "seed" else active)
    monkeypatch.setattr(
        view,
        "validate_campaign",
        lambda d: (
            {
                "taskName": "ForumTask",
                "startsAt": "2026-11-20T07:00:00Z",
                "slots": ["2026-11-20T07:00:00Z"],
            },
            {"expires_at": "2026-11-21T07:00:00Z", "external_effects": {"https_get_max": 72}},
        ),
    )
    monkeypatch.setattr(
        view, "read_events", lambda p: [{"kind": "PUBLIC_COLLECTION_ACCEPTED", "hash": "a" * 64}]
    )
    result = view.read_public_view(
        tmp_path / "seed", tmp_path / "campaign", now=datetime(2026, 11, 20, 8, tzinfo=UTC)
    )
    assert result["distinctPicks"] == 2
    assert result["picks"][0]["versionCount"] == 2
    assert result["picks"][0]["firstSeenAt"] == "2026-11-19T09:00:00Z"
    assert result["claimIds"] == ["DATA.SEED", "ENG.CAMPAIGN"]
    assert result["generatedAt"] == "2026-11-20T07:01:00Z"


@pytest.mark.parametrize("failure", ["truncated_journal", "missing_bundle"])
def test_corrupt_campaign_keeps_valid_seed(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(
        view,
        "read_collection",
        lambda d: (
            base()
            if d.name == "seed"
            else (_ for _ in ()).throw(FileNotFoundError("missing bundle"))
        ),
    )
    monkeypatch.setattr(
        view,
        "validate_campaign",
        lambda d: (
            {
                "taskName": "ForumTask",
                "startsAt": "2026-11-20T07:00:00Z",
                "slots": ["2026-11-20T07:00:00Z"],
            },
            {"expires_at": "2026-11-21T07:00:00Z", "external_effects": {"https_get_max": 72}},
        ),
    )

    def events(path):
        if failure == "truncated_journal":
            raise ValueError("truncated")
        return [{"kind": "PUBLIC_COLLECTION_ACCEPTED", "hash": "a" * 64}]

    monkeypatch.setattr(view, "read_events", events)
    result = view.read_public_view(
        tmp_path / "seed", tmp_path / "campaign", now=datetime(2026, 11, 20, 8, tzinfo=UTC)
    )
    assert result["distinctPicks"] == 1
    assert result["campaign"]["state"] == "invalid_package"
