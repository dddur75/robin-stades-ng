"""Deterministic immutable archives and local sanitized artifact emission."""

from __future__ import annotations

import csv
import gzip
import io
import re
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from robin.data_torrent.contracts import canonical_json_bytes

_SAFE_MEMBER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,511}$")


def _validated_member(name: str) -> str:
    path = PurePosixPath(name)
    if (
        _SAFE_MEMBER.fullmatch(name) is None
        or path.is_absolute()
        or ".." in path.parts
        or "//" in name
    ):
        raise ValueError("DATA_TORRENT_ARCHIVE_MEMBER_INVALID")
    return name


def deterministic_tar_gz(members: Mapping[str, bytes]) -> bytes:
    """Build byte-identical gzip/tar bytes for the same member mapping."""

    if not members:
        raise ValueError("DATA_TORRENT_ARCHIVE_EMPTY")
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=output,
        mtime=0,
    ) as compressed:
        with tarfile.open(
            fileobj=compressed,
            mode="w",
            format=tarfile.USTAR_FORMAT,
        ) as archive:
            for name in sorted(members):
                validated = _validated_member(name)
                payload = members[name]
                if not isinstance(payload, bytes):
                    raise TypeError("DATA_TORRENT_ARCHIVE_BYTES_REQUIRED")
                member = tarfile.TarInfo(validated)
                member.size = len(payload)
                member.mtime = 0
                member.mode = 0o444
                member.uid = 0
                member.gid = 0
                member.uname = ""
                member.gname = ""
                archive.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def coverage_csv(rows: Sequence[Mapping[str, object]]) -> bytes:
    fields = (
        "league",
        "sport_key",
        "market",
        "fixtures_available",
        "fixtures_captured",
        "markets_requested",
        "markets_returned",
        "records_normalized",
        "records_rejected",
        "coverage_percentage",
        "absence_reason",
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fields,
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return output.getvalue().encode("utf-8")


def json_artifact(document: object) -> bytes:
    return canonical_json_bytes(document) + b"\n"


def write_artifacts(output_dir: Path, members: Mapping[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_dir.is_dir():
        raise ValueError("DATA_TORRENT_OUTPUT_DIRECTORY_INVALID")
    for name in sorted(members):
        validated = _validated_member(name)
        if "/" in validated:
            raise ValueError("DATA_TORRENT_OUTPUT_NESTING_FORBIDDEN")
        destination = output_dir / validated
        with destination.open("xb") as handle:
            handle.write(members[name])


def artifact_index(members: Mapping[str, bytes]) -> list[dict[str, Any]]:
    import hashlib

    return [
        {
            "name": name,
            "bytes": len(members[name]),
            "sha256": hashlib.sha256(members[name]).hexdigest(),
        }
        for name in sorted(members)
    ]


__all__ = [
    "artifact_index",
    "coverage_csv",
    "deterministic_tar_gz",
    "json_artifact",
    "write_artifacts",
]
