"""Read normalized Git blobs locally. No lazy fetch, provider or database access."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from robin.prematch.criteria import Fixture, PlayerStat

POPULATION_SHA256 = "0f652e40d430f4670436318858161d90fa8ebebe85cd3fcb6d6e77178f56833f"
FAMILIES = {"fixtures", "lineups", "events", "fixture_events", "fixture_player_statistics"}


@dataclass(frozen=True)
class Target:
    fixture_id: int
    competition: str
    season: int
    date: str | None = None
    home_name: str | None = None
    away_name: str | None = None


def load_targets(root: Path) -> list[Target]:
    folder = root / "configs/execution"
    targets: list[Target] = []
    for g in json.loads((folder / "mission027-targets.json").read_text())["groups"]:
        targets.extend(Target(i, g["competition"], g["season"]) for i in g["fixture_ids"])
    with (folder / "mission028-mapping.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["reason"] == "MATCHED":
                targets.append(Target(int(row["fixture_id"]), row["ligue_fd"], int(row["season"]),
                                      row["date"], row["equipe_dom_fd"], row["equipe_ext_fd"]))
    for g in json.loads((folder / "mission029-l1-targets.json").read_text())["groups"]:
        targets.extend(Target(row[0], "Ligue-1", g["season"]) for row in g["fixtures"])
    ids = sorted(t.fixture_id for t in targets)
    digest = hashlib.sha256("".join(f"{i}\n" for i in ids).encode()).hexdigest()
    if (len(ids) != len(set(ids)) or digest != POPULATION_SHA256 or
            any(t.season == 2025 for t in targets)):
        raise ValueError("frozen mission036 population changed or holdout")
    return sorted(targets, key=lambda t: t.fixture_id)


@dataclass
class Snapshot:
    revision: str
    fixtures: list[Fixture] = field(default_factory=list)
    players: dict[tuple[int, int], list[PlayerStat]] = field(default_factory=dict)
    lineups: dict[tuple[int, int], tuple[int, ...]] = field(default_factory=dict)
    events: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    inventory: list[dict[str, Any]] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


def _git(repo: Path, *args: str) -> list[str]:
    # Protocol denial is a second guard if an older Git ignores GIT_NO_LAZY_FETCH.
    return ["git", "-c", "protocol.allow=never", "-C", str(repo), *args]


def _fixture(payload: dict[str, Any], competition: str, season: int) -> Fixture:
    if payload.get("league", {}).get("season", season) != season:
        raise ValueError("fixture season mismatch")
    fixture, teams = payload["fixture"], payload["teams"]
    score = payload.get("score", {}).get("fulltime", {})
    return Fixture(fixture["id"], competition, season,
                   datetime.fromisoformat(fixture["date"].replace("Z", "+00:00")),
                   teams["home"]["id"], teams["away"]["id"], score.get("home"), score.get("away"),
                   fixture["status"]["short"], teams["home"].get("name", ""),
                   teams["away"].get("name", ""))


def _player_block(payload: dict[str, Any]) -> list[PlayerStat]:
    result = []
    for item in payload["players"]:
        if type(item["player"]["id"]) is not int:
            raise ValueError("invalid player identity")
        statistics = item["statistics"]
        if len(statistics) != 1:
            raise ValueError("ambiguous player statistics")
        games = statistics[0]["games"]
        rating = games.get("rating")
        rating = float(rating) if rating is not None else None
        if rating is not None and (not math.isfinite(rating) or not 0 <= rating <= 10):
            raise ValueError("invalid rating")
        result.append(PlayerStat(item["player"]["id"], games.get("minutes"), rating))
    return result


def load_snapshot(repo: Path, ref: str) -> Snapshot:
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1")
    revision = subprocess.check_output(
        _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}"), env=env, text=True).strip()
    tree = subprocess.check_output(
        _git(repo, "ls-tree", "-r", revision, "historical/parquet"), env=env, text=True)
    selected = []
    for line in tree.splitlines():
        meta, path = line.split("\t", 1)
        parts = dict(s.split("=", 1) for s in path.split("/") if "=" in s)
        # Decide holdout and family solely from the path, before reading any blob.
        if parts.get("season") == "2025" or not path.endswith(".parquet"):
            continue
        family = parts.get("entity_type")
        if family not in FAMILIES and not (family == "players" and
                                          re.search(r"/fixture-\d+\.parquet$", path)):
            continue
        selected.append((meta.split()[2], path, parts))
    snapshot = Snapshot(revision)
    fixtures: dict[int, Fixture] = {}
    conflicts: dict[str, set[Any]] = {k: set() for k in ("fixtures", "lineups", "players", "events")}
    audit: Counter[str] = Counter()

    def put(kind: str, key: Any, value: Any, dest: dict[Any, Any]) -> None:
        if key in conflicts[kind]:
            return
        if key in dest and dest[key] != value:
            conflicts[kind].add(key)
            dest.pop(key)
        else:
            dest[key] = value

    with subprocess.Popen(_git(repo, "cat-file", "--batch"), env=env,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as process:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("local Git pipes unavailable")
        for sha, path, parts in selected:
            process.stdin.write((sha + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().strip().split()
            if len(header) != 3 or header[1] != "blob":
                raise ValueError(f"source blob unavailable locally: {path}; fetch from GitHub first")
            body = process.stdout.read(int(header[2]))
            if process.stdout.read(1) != b"\n":
                raise ValueError("invalid git batch framing")
            rows = pq.ParquetFile(io.BytesIO(body)).read(use_threads=False).to_pylist()
            family, season = parts["entity_type"], int(parts["season"])
            file_fixture = re.search(r"/fixture-(\d+)\.parquet$", path)
            per_fixture = int(file_fixture[1]) if file_fixture else None
            entry: dict[str, Any] = dict(path=path, blob_sha1=sha, sha256=hashlib.sha256(body).hexdigest(),
                                        competition=parts["competition"], season=season,
                                        family=family, rows=len(rows), linked_rows=0)
            snapshot.inventory.append(entry)
            grouped_events: dict[int, list[dict[str, Any]]] = {}
            if family in {"events", "fixture_events"} and per_fixture is not None:
                grouped_events[per_fixture] = []
            for row in rows:
                if row.get("season", season) != season:
                    raise ValueError("row/path season mismatch or holdout")
                payload = row.get("payload")
                payload = json.loads(payload) if isinstance(payload, str) else payload
                if not isinstance(payload, dict):
                    audit["invalid_payload_rows"] += 1
                    continue
                if family == "fixtures":
                    try:
                        f = _fixture(payload, parts["competition"], season)
                        put("fixtures", f.fixture_id, f, fixtures)
                        entry["linked_rows"] += 1
                    except (KeyError, TypeError, ValueError):
                        audit["invalid_fixture_rows"] += 1
                    continue
                fid = row.get("provider_fixture_id")
                fid = fid if type(fid) is int else per_fixture
                if fid is None:
                    audit["unlinked_rows"] += 1
                    continue
                if per_fixture is not None and fid != per_fixture:
                    raise ValueError("fixture identity conflicts with source path")
                try:
                    if family in {"events", "fixture_events"}:
                        grouped_events.setdefault(fid, []).append(payload)
                    elif family == "lineups":
                        xi = tuple(p["player"]["id"] for p in payload["startXI"])
                        if len(xi) != len(set(xi)) or len(xi) != 11 or any(type(p) is not int for p in xi):
                            raise ValueError("invalid official XI")
                        put("lineups", (fid, payload["team"]["id"]), xi, snapshot.lineups)
                    else:
                        put("players", (fid, payload["team"]["id"]),
                            _player_block(payload), snapshot.players)
                    entry["linked_rows"] += 1
                except (KeyError, TypeError, ValueError):
                    audit["invalid_detail_rows"] += 1
            for fid, events in grouped_events.items():
                put("events", fid, events, snapshot.events)
        process.stdin.close()
        if process.wait() != 0:
            raise ValueError("local Git source reader failed")
    snapshot.fixtures = sorted(fixtures.values(), key=lambda f: f.fixture_id)
    snapshot.audit = dict(audit)
    snapshot.audit.update({f"conflicting_{k}": sorted(v) for k, v in conflicts.items()})
    return snapshot
