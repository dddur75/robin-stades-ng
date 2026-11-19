import csv
from hashlib import sha256

import pytest

from robin.source_observatory.candidate_registry import import_candidates, load_registry

FIELDS = "candidate_id name platform source_url evidence_url source_sheet source_row declared_last_date historical_lot l1_flag_reported qualification_status collection_enabled".split()


def source(tmp_path, **override):
    url = "https://example.org/profile/alice"
    row = dict(
        zip(
            FIELDS,
            [
                "catalogue:" + sha256(url.encode()).hexdigest(),
                "Alice",
                "Forum test",
                url,
                "https://example.org/post/123",
                "Catalogue",
                "5",
                "2026-10-30",
                "A",
                "Oui",
                "UNVERIFIED_FROM_WORKBOOK",
                "false",
            ],
        )
    )
    row.update(override)
    path = tmp_path / "input.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerow(row)
    return path


def test_import_keeps_declared_date_and_disables_collection(tmp_path):
    path = source(tmp_path)
    target = tmp_path / "registry"
    import_candidates(path, target, source_workbook_sha256="a" * 64, expected_count=1)
    data = load_registry(target, expected_count=1)
    row = data["candidates"][0]
    assert row["collectionEnabled"] is False
    assert row["status"] == "pending_qualification"
    assert row["declaredLastDate"] == "2026-10-30"
    assert row["origin"]["row"] == 5
    assert "publishedAt" not in row and "picks" not in row
    before = (target / "registry.json").read_bytes()
    import_candidates(path, target, source_workbook_sha256="a" * 64, expected_count=1)
    assert (target / "registry.json").read_bytes() == before


@pytest.mark.parametrize(
    "override",
    [
        {"collection_enabled": "true"},
        {"source_url": "http://127.0.0.1/private"},
        {"evidence_url": "https://example.org/?token=secret"},
        {"declared_last_date": "yesterday"},
    ],
)
def test_unsafe_or_implicitly_active_input_refused(tmp_path, override):
    with pytest.raises(ValueError):
        import_candidates(
            source(tmp_path, **override),
            tmp_path / "registry",
            source_workbook_sha256="a" * 64,
            expected_count=1,
        )


def test_wrong_count_or_tampered_file_is_not_an_empty_registry(tmp_path):
    path = source(tmp_path)
    target = tmp_path / "registry"
    with pytest.raises(ValueError):
        import_candidates(path, target, source_workbook_sha256="a" * 64, expected_count=317)
    import_candidates(path, target, source_workbook_sha256="a" * 64, expected_count=1)
    (target / "registry.json").write_bytes(b"[]")
    with pytest.raises(ValueError):
        load_registry(target, expected_count=1)


def test_receipt_cannot_relabel_provenance(tmp_path):
    import json

    path = source(tmp_path)
    target = tmp_path / "registry"
    import_candidates(path, target, source_workbook_sha256="a" * 64, expected_count=1)
    receipt = json.loads((target / "receipt.json").read_bytes())
    receipt["sourceWorkbookSha256"] = "b" * 64
    (target / "receipt.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        load_registry(target, expected_count=1)
