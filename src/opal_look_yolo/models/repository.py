from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from opal_look_yolo.schemas.models import Model

MODEL_EXTENSIONS = {".pt", ".onnx", ".engine", ".torchscript", ".tflite"}


@dataclass(frozen=True)
class ModelRecord:
    model_id: str
    path: Path
    tasks: tuple[str, ...] = ("detect",)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_model(self, loaded: bool = False) -> Model:
        return Model(
            model_id=self.model_id,
            engine_id="yolo",
            tasks=list(self.tasks),
            loaded=loaded,
            available=True,
            metadata=dict(self.metadata),
        )


class ModelRepository(Protocol):
    def list_records(self) -> list[ModelRecord]: ...

    def get_record(self, model_id: str) -> ModelRecord | None: ...


class LocalModelRepository:
    def __init__(
        self,
        roots: Iterable[Path],
        extensions: set[str] | None = None,
    ) -> None:
        self.roots = list(roots)
        self.extensions = extensions or MODEL_EXTENSIONS

    def list_records(self) -> list[ModelRecord]:
        records: list[ModelRecord] = []
        used_ids: set[str] = set()
        for path in self._iter_model_files():
            model_id = self._model_id(path, used_ids)
            used_ids.add(model_id)
            records.append(
                ModelRecord(
                    model_id=model_id,
                    path=path,
                    metadata={
                        "format": path.suffix.lstrip(".").lower(),
                        "size_bytes": path.stat().st_size,
                    },
                )
            )
        return records

    def get_record(self, model_id: str) -> ModelRecord | None:
        for record in self.list_records():
            if record.model_id == model_id:
                return record
        return None

    def _iter_model_files(self) -> Iterable[Path]:
        for root in self.roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                if path.suffix.lower() in self.extensions:
                    yield path

    def _model_id(self, path: Path, used_ids: set[str]) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip(".-_") or "model"
        if base not in used_ids:
            return base
        fingerprint = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
        return f"{base}-{fingerprint}"
