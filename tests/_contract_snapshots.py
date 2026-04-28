from __future__ import annotations

import json
from pathlib import Path

_CONTRACT_SNAPSHOT_ROOT = (
    Path(__file__).resolve().parent / "fixtures" / "contract_snapshots"
)


def load_json_snapshot(name: str) -> object:
    path = _CONTRACT_SNAPSHOT_ROOT / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_text_snapshot(name: str) -> str:
    path = _CONTRACT_SNAPSHOT_ROOT / name
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")
