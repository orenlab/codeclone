from __future__ import annotations

import json
from pathlib import Path
from typing import Set


class Baseline:
    def __init__(self, path: str):
        self.path = Path(path)
        self.functions: Set[str] = set()
        self.blocks: Set[str] = set()

    def load(self) -> None:
        if not self.path.exists():
            return

        data = json.loads(self.path.read_text("utf-8"))
        self.functions = set(data.get("functions", []))
        self.blocks = set(data.get("blocks", []))

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
    def from_groups(func_groups: dict, block_groups: dict) -> "Baseline":
        bl = Baseline("")
        bl.functions = set(func_groups.keys())
        bl.blocks = set(block_groups.keys())
        return bl

    def diff(self, func_groups: dict, block_groups: dict) -> tuple[set, set]:
        new_funcs = set(func_groups.keys()) - self.functions
        new_blocks = set(block_groups.keys()) - self.blocks
        return new_funcs, new_blocks
