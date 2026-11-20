import json
from hashlib import sha256

import pytest

from robin.source_observatory.workbook_inventory import (
    build_inventory,
    load_inventory,
    query_inventory,
)


def sample():
    return {
        "Catalogue": {
            "rows": [
                {"row": 4, "cells": {"A4": "Nom"}},
                {
                    "row": 5,
                    "cells": {
                        "A5": "Alice",
                        "B5": "Forum",
                        "C5": "auteur",
                        "G5": "https://example.com/alice",
                        "D5": "A",
                        "E5": "Oui",
                    },
                },
            ]
        },
        "Profils FR": {
            "rows": [
                {
                    "row": 5,
                    "cells": {"A5": "Bob", "B5": "Forum FR", "F5": "https://example.com/bob"},
                }
            ]
        },
        "Dépôts": {
            "rows": [{"row": 5, "cells": {"A5": "Outil", "D5": "https://example.com/tool"}}]
        },
    }


def test_all_sheets_keep_distinct_grains_and_do_not_activate():
    data = build_inventory(sample(), "a" * 64, "b" * 64)
    assert data["addressCount"] == 2
    assert len(data["records"]) == 3
    assert all(not r["collectionEnabled"] for r in data["records"])
    assert query_inventory(data)["total"] == 2
    bob = query_inventory(data, q="bob")["records"][0]
    assert bob["sheet"] == "Profils FR" and bob["row"] == 5
    assert bob["historicalL1"] is None
    assert "fields" not in bob
    assert query_inventory(data, sheet="Dépôts")["total"] == 1


def test_query_pagination_and_lookup_are_independent():
    data = build_inventory(sample(), "a" * 64, "b" * 64)
    first = query_inventory(data, limit=1)
    second = query_inventory(data, page=1, limit=1)
    assert first["records"][0]["label"] == "Alice"
    assert second["records"][0]["label"] == "Bob"
    assert query_inventory(data, q="bob")["total"] == 1
    assert (
        query_inventory(data, record_id=second["records"][0]["recordId"])["records"][0]["fields"][
            "A"
        ]
        == "Bob"
    )
    assert query_inventory(data, record_id="missing")["total"] == 0
    for kwargs in ({"page": -1}, {"limit": 51}, {"q": "x" * 121}, {"sheet": "inconnu"}):
        with pytest.raises(ValueError):
            query_inventory(data, **kwargs)


def test_unsafe_links_are_not_clickable_and_duplicate_identity_is_preserved():
    source = sample()
    source["Profils FR"]["rows"].append(
        {"row": 6, "cells": {"A6": "Alice aussi", "F6": "https://example.com/alice"}}
    )
    source["Profils FR"]["rows"].append(
        {"row": 7, "cells": {"A7": "URL privée", "F7": "http://127.0.0.1/admin"}}
    )
    data = build_inventory(source, "a" * 64, "b" * 64)
    assert data["addressCount"] == 2
    assert len({r["recordId"] for r in data["records"]}) == 5
    assert query_inventory(data, q="URL privée")["records"][0]["sourceUrl"] is None


def test_missing_or_tampered_index_fails_closed(tmp_path):
    with pytest.raises(OSError):
        load_inventory(tmp_path, expected_sha256="0" * 64)
    data = build_inventory(sample(), "a" * 64, "b" * 64)
    raw = json.dumps(data).encode()
    (tmp_path / "index.json").write_bytes(raw)
    assert load_inventory(tmp_path, expected_sha256=sha256(raw).hexdigest())["addressCount"] == 2
    with pytest.raises(ValueError):
        load_inventory(tmp_path, expected_sha256="0" * 64)


def test_archive_formula_target_is_preserved_without_replacing_original_label():
    source = sample()
    source["Sujets et archives"] = {
        "rows": [
            {"row": 5, "cells": {"A5": "Octobre", "B5": "Archive", "E5": "Ouvrir le document"}}
        ]
    }
    formulas = [
        {"part": "xl/worksheets/sheet4.xml", "cell": "E5", "target": "https://example.org/archive"}
    ]
    data = build_inventory(source, "a" * 64, "b" * 64, formulas)
    row = query_inventory(data, sheet="Sujets et archives")["records"][0]
    assert row["sourceUrl"] == "https://example.org/archive"
    detail = query_inventory(data, record_id=row["recordId"])["records"][0]
    assert detail["fields"]["E"] == "Ouvrir le document"
    assert detail["documentaryLinkRejected"] is False
    assert data["addressCount"] == 2
