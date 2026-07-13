from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol


class JsonWriter(Protocol):
    def __call__(self, path: Path, payload: Mapping[str, object]) -> None: ...


def update_clone_baseline(
    *,
    update_baseline: bool,
    path: Path,
    payload: Mapping[str, object],
    writer: JsonWriter,
) -> Path | None:
    if not update_baseline:
        return None
    writer(path, payload)
    return path


def update_metrics_baseline(
    *,
    update_metrics_baseline: bool,
    clone_baseline_updated_path: Path | None,
    path: Path,
    payload: Mapping[str, object],
    writer: JsonWriter,
) -> None:
    if not update_metrics_baseline:
        return
    writer(path, payload)
    if clone_baseline_updated_path != path:
        publish_baseline_updated(path)


def publish_baseline_updated(path: Path) -> None:
    _ = path
