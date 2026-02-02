"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional


class Cache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data: dict[str, Any] = {"files": {}}

    def load(self) -> None:
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
            except json.JSONDecodeError:
                # If cache is corrupted, start fresh
                self.data = {"files": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            "utf-8",
        )

    def get_file_entry(self, filepath: str) -> Optional[dict[str, Any]]:
        return self.data.get("files", {}).get(filepath)

    def put_file_entry(
        self, filepath: str, stat_sig: dict[str, Any], units: list, blocks: list
    ) -> None:
        self.data.setdefault("files", {})[filepath] = {
            "stat": stat_sig,
            "units": [asdict(u) for u in units],
            "blocks": [asdict(b) for b in blocks],
        }


def file_stat_signature(path: str) -> dict:
    st = os.stat(path)
    return {
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
    }
