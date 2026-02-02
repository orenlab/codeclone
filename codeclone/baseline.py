"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from pathlib import Path


class Baseline:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.functions: set[str] = set()
        self.blocks: set[str] = set()

    def load(self) -> None:
        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text("utf-8"))
            self.functions = set(data.get("functions", []))
            self.blocks = set(data.get("blocks", []))
        except json.JSONDecodeError as e:
            raise ValueError(f"Corrupted baseline file at {self.path}: {e}") from e

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "functions": sorted(self.functions),
                    "blocks": sorted(self.blocks),
                },
                indent=2,
                ensure_ascii=False,
            ),
            "utf-8",
        )

    @staticmethod
    def from_groups(
        func_groups: dict, block_groups: dict, path: str | Path = ""
    ) -> "Baseline":
        bl = Baseline(path)
        bl.functions = set(func_groups.keys())
        bl.blocks = set(block_groups.keys())
        return bl

    def diff(self, func_groups: dict, block_groups: dict) -> tuple[set, set]:
        new_funcs = set(func_groups.keys()) - self.functions
        new_blocks = set(block_groups.keys()) - self.blocks
        return new_funcs, new_blocks
