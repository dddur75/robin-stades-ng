"""Local configuration must preserve archived sources and frozen collection authority."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cockpit/scripts/tipsters_source_settings.py"
SPEC = importlib.util.spec_from_file_location("source_settings", SCRIPT)
assert SPEC and SPEC.loader
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)
REGISTRY = ROOT / "data/source_observatory/pilot_sources.csv"


def payload(tmp_path, identifier="SRC_002"):
    value = settings.catalogue(REGISTRY, tmp_path)
    source = next(s for s in value["sources"] if s["id"] == identifier)
    return {"sourceId": identifier, "expectedRevision": value["revision"],
            "config": source["config"] | {"notes": "Préparation synthétique"}}


def test_every_registered_source_is_visible_with_a_valid_proposed_configuration(tmp_path):
    original = REGISTRY.read_bytes()
    value = settings.catalogue(REGISTRY, tmp_path / "uncreated")
    assert value["total"] == 74
    assert value["counts"] == {"a_construire": 57, "manuel": 14, "bloque": 3}
    assert value["prepared"] == 0 and len(value["sources"]) == 74
    assert value["pilotProvider"]["id"] not in {s["id"] for s in value["sources"]}
    assert all(not s["includedInPilot"] for s in value["sources"])
    assert all(settings.validate_config(s["config"], s) for s in value["sources"])
    assert REGISTRY.read_bytes() == original
    assert not (tmp_path / "uncreated").exists()


def test_settings_are_persistent_and_append_only_and_do_not_activate_sources(tmp_path):
    original = REGISTRY.read_bytes()
    request = payload(tmp_path)
    first = settings.save(REGISTRY, tmp_path, request)
    journal = tmp_path / "preparations.jsonl"
    prefix = journal.read_bytes()
    current = settings.catalogue(REGISTRY, tmp_path)
    assert current["revision"] == first["revision"]
    assert current["prepared"] == 1
    row = next(s for s in current["sources"] if s["id"] == request["sourceId"])
    assert row["config"]["notes"] == "Préparation synthétique"
    assert row["historicalState"] == "a_construire" and not row["includedInPilot"]
    second = request | {"expectedRevision": first["revision"],
                        "config": request["config"] | {"notes": "Deuxième version"}}
    settings.save(REGISTRY, tmp_path, second)
    assert journal.read_bytes().startswith(prefix)
    assert len(journal.read_bytes().splitlines()) == 2
    assert REGISTRY.read_bytes() == original


def test_concurrent_writers_produce_one_save_and_one_conflict(tmp_path):
    request = payload(tmp_path)
    def attempt():
        try:
            return settings.save(REGISTRY, tmp_path, request)["status"]
        except settings.ConflictError:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ["conflict", "saved"]
    assert len((tmp_path / "preparations.jsonl").read_bytes().splitlines()) == 1
    assert settings.catalogue(REGISTRY, tmp_path)["prepared"] == 1
    assert not (tmp_path / "preparations.lock").exists()


@pytest.mark.parametrize("change", [
    {"endpoint": "https://example.invalid/feed"},
    {"endpoint": "http://www.coteur.com/feed"},
    {"endpoint": "https://www.coteur.com:8443/feed"},
    {"endpoint": "https://user:password@www.coteur.com/feed"},
    {"endpoint": "https://www.coteur.com/feed?%74oken=secret"},
    {"endpoint": "https://www.coteur.com/feed#private"},
    {"adapter": "unknown"}, {"intervalMinutes": 29}, {"intervalMinutes": 1441},
    {"requestsPerVisit": 0}, {"requestsPerVisit": 11}, {"requestsPerVisit": True},
    {"notes": "x" * 2001}, {"notes": "invalid\x00note"},
])
def test_invalid_configuration_cannot_write_history(tmp_path, change):
    request = payload(tmp_path)
    with pytest.raises(ValueError):
        settings.save(REGISTRY, tmp_path, request | {"config": request["config"] | change})
    assert not (tmp_path / "preparations.jsonl").exists()


def test_authority_fields_and_unknown_sources_are_refused(tmp_path):
    request = payload(tmp_path)
    for invalid in [request | {"activate": True}, request | {"sourceId": "FORECAST_RECORD_J12"},
                    request | {"sourceId": "SRC_999"}, request | {"expectedRevision": "invalid"}]:
        with pytest.raises(ValueError):
            settings.save(REGISTRY, tmp_path, invalid)


def test_write_limit_is_checked_before_append_and_preserves_a_readable_journal(tmp_path, monkeypatch):
    first = settings.save(REGISTRY, tmp_path, payload(tmp_path))
    journal = tmp_path / "preparations.jsonl"
    prefix = journal.read_bytes()
    monkeypatch.setattr(settings, "MAX_SETTINGS_BYTES", len(prefix) + 1)
    request = payload(tmp_path) | {"expectedRevision": first["revision"]}
    with pytest.raises(ValueError, match="limite locale"):
        settings.save(REGISTRY, tmp_path, request)
    assert journal.read_bytes() == prefix
    assert settings.catalogue(REGISTRY, tmp_path)["revision"] == first["revision"]
    assert not (tmp_path / "preparations.lock").exists()


@pytest.mark.parametrize("partial", [False, True])
def test_invalid_journal_is_not_rewritten_or_reported_as_saved(tmp_path, partial):
    first = settings.save(REGISTRY, tmp_path, payload(tmp_path))
    journal = tmp_path / "preparations.jsonl"
    original = journal.read_bytes()
    bad = original[:-1] if partial else original.replace(b"SOURCE_PREPARATION", b"SOURCE_CORRUPTION")
    journal.write_bytes(bad)
    with pytest.raises(ValueError):
        settings.catalogue(REGISTRY, tmp_path)
    request = {"sourceId": "SRC_002", "expectedRevision": first["revision"],
               "config": settings.registry(REGISTRY)[0][1]["defaults"]}
    with pytest.raises(ValueError):
        settings.save(REGISTRY, tmp_path, request)
    assert journal.read_bytes() == bad
