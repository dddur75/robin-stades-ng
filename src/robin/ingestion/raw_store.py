"""Stockage local brut, immuable et compatible avec un futur backend objet."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from robin.domain.raw import RawObservation
from robin.providers.base import PayloadBackend

_SECRET_FRAGMENTS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "authorization",
    "password",
)


def redact_secrets(value: object, key: str = "") -> object:
    """Supprimer les secrets des paramètres conservés, y compris imbriqués."""
    normalized = key.lower().replace("-", "_")
    if any(fragment in normalized for fragment in _SECRET_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_secrets(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


class LocalPayloadBackend(PayloadBackend):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("object_key sort du stockage autorisé")
        return candidate

    def put_if_absent(self, object_key: str, payload: bytes) -> str:
        path = self._path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(payload)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise RuntimeError("collision de hash ou objet brut altéré") from None
        return object_key.replace("\\", "/")

    def read(self, object_key: str) -> bytes:
        return self._path(object_key).read_bytes()


class LocalRawStore:
    """Une observation est nouvelle, un payload identique est dédupliqué par hash."""

    def __init__(self, root: Path, backend: PayloadBackend | None = None) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = backend or LocalPayloadBackend(self.root / "payloads")
        self.observations = self.root / "observations"
        self.observations.mkdir(parents=True, exist_ok=True)

    def store(
        self,
        *,
        provider: str,
        endpoint: str,
        request_parameters: Mapping[str, object],
        requested_at: datetime,
        received_at: datetime,
        http_status: int,
        payload: bytes,
        schema_version: str,
        ingestion_run_id: str,
    ) -> RawObservation:
        payload_hash = hashlib.sha256(payload).hexdigest()
        object_key = f"{payload_hash[:2]}/{payload_hash}.bin"
        location = self.backend.put_if_absent(object_key, payload)
        observation_id = str(uuid4())
        sanitized = cast(
            dict[str, object],
            redact_secrets(dict(request_parameters)),
        )
        observation = RawObservation(
            observation_id=observation_id,
            provider=provider,
            endpoint=endpoint,
            request_parameters=sanitized,
            requested_at=requested_at,
            received_at=received_at,
            http_status=http_status,
            payload_hash=payload_hash,
            schema_version=schema_version,
            ingestion_run_id=ingestion_run_id,
            raw_payload_location=location,
        )
        partition = self.observations / observation.received_at.strftime("%Y/%m/%d")
        partition.mkdir(parents=True, exist_ok=True)
        metadata_path = partition / f"{observation_id}.json"
        with metadata_path.open("x", encoding="utf-8") as stream:
            stream.write(observation.model_dump_json(indent=2))
            stream.write("\n")
        return observation

    def load_payload(self, observation: RawObservation) -> bytes:
        payload = self.backend.read(observation.raw_payload_location)
        if hashlib.sha256(payload).hexdigest() != observation.payload_hash:
            raise RuntimeError("le payload brut ne correspond plus à son hash")
        return payload

    def iter_observations(self) -> list[RawObservation]:
        records = []
        for path in sorted(self.observations.rglob("*.json")):
            records.append(RawObservation.model_validate(json.loads(path.read_text("utf-8"))))
        return records
