from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional


class Cache:
    def __init__(self, path: str):
        self.path = Path(path)
        self.data: dict = {"files": {}}

    def load(self) -> None:
        if self.path.exists():
            self.data = json.loads(self.path.read_text("utf-8"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            "utf-8",
        )

    def get_file_entry(self, filepath: str) -> Optional[dict]:
        return self.data.get("files", {}).get(filepath)

    def put_file_entry(self, filepath: str, stat_sig: dict, units, blocks) -> None:
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
