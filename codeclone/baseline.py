"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class Baseline:
    __slots__ = ("blocks", "functions", "path", "python_version")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.functions: set[str] = set()
        self.blocks: set[str] = set()
        self.python_version: str | None = None

    def load(self) -> None:
        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text("utf-8"))
            self.functions = set(data.get("functions", []))
            self.blocks = set(data.get("blocks", []))
            python_version = data.get("python_version")
            self.python_version = (
                python_version if isinstance(python_version, str) else None
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupted baseline file at {self.path}: {e}") from e

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                _baseline_payload(self.functions, self.blocks, self.python_version),
                indent=2,
                ensure_ascii=False,
            ),
            "utf-8",
        )

    @staticmethod
    def from_groups(
        func_groups: Mapping[str, object],
        block_groups: Mapping[str, object],
        path: str | Path = "",
        python_version: str | None = None,
    ) -> Baseline:
        bl = Baseline(path)
        bl.functions = set(func_groups.keys())
        bl.blocks = set(block_groups.keys())
        bl.python_version = python_version
        return bl

    def diff(
        self, func_groups: Mapping[str, object], block_groups: Mapping[str, object]
    ) -> tuple[set[str], set[str]]:
        new_funcs = set(func_groups.keys()) - self.functions
        new_blocks = set(block_groups.keys()) - self.blocks
        return new_funcs, new_blocks


def _baseline_payload(
    functions: set[str],
    blocks: set[str],
    python_version: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "functions": sorted(functions),
        "blocks": sorted(blocks),
    }
    if python_version:
        payload["python_version"] = python_version
    return payload
