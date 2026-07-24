"""Journal append-only et idempotent de snapshots et décisions shadow."""

from __future__ import annotations

import json
from pathlib import Path

from robin.domain.odds import OddsSnapshot


class JsonlSnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        snapshot: OddsSnapshot,
        *,
        source_payload_hash: str | None = None,
    ) -> bool:
        partition = self.root / snapshot.observed_at.strftime("%Y/%m/%d")
        partition.mkdir(parents=True, exist_ok=True)
        path = partition / "odds-snapshots.jsonl"
        existing = self.read_all()
        known = {
            str(record["snapshot_id"])
            for record in existing
            if "snapshot_id" in record
        }
        if snapshot.snapshot_id in known:
            return False
        if source_payload_hash and any(
            record.get("source_payload_hash") == source_payload_hash
            and record.get("provider_fixture_id") == snapshot.provider_fixture_id
            for record in existing
        ):
            return False
        record = snapshot.model_dump(mode="json")
        record["snapshot_id"] = snapshot.snapshot_id
        record["source_payload_hash"] = source_payload_hash
        record["time_to_kickoff_seconds"] = snapshot.time_to_kickoff_seconds
        record["is_live"] = snapshot.is_live
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            stream.write("\n")
        return True

    def read_all(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for path in sorted(self.root.rglob("odds-snapshots.jsonl")):
            for line in path.read_text("utf-8").splitlines():
                value = json.loads(line)
                if isinstance(value, dict):
                    records.append(value)
        return records
