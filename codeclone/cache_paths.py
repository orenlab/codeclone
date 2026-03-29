# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path


def wire_filepath_from_runtime(
    runtime_filepath: str,
    *,
    root: Path | None,
) -> str:
    runtime_path = Path(runtime_filepath)
    if root is None:
        return runtime_path.as_posix()

    try:
        relative = runtime_path.relative_to(root)
        return relative.as_posix()
    except ValueError:
        pass

    try:
        relative = runtime_path.resolve().relative_to(root.resolve())
        return relative.as_posix()
    except OSError:
        return runtime_path.as_posix()
    except ValueError:
        return runtime_path.as_posix()


def runtime_filepath_from_wire(
    wire_filepath: str,
    *,
    root: Path | None,
) -> str:
    wire_path = Path(wire_filepath)
    if root is None or wire_path.is_absolute():
        return str(wire_path)

    combined = root / wire_path
    try:
        return str(combined.resolve(strict=False))
    except OSError:
        return str(combined)
