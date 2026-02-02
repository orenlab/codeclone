"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from typing import Any


def build_groups(units: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for u in units:
        key = f"{u['fingerprint']}|{u['loc_bucket']}"
        groups.setdefault(key, []).append(u)
    return {k: v for k, v in groups.items() if len(v) > 1}


def build_block_groups(
    blocks: list[dict[str, Any]], min_functions: int = 2
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for b in blocks:
        groups.setdefault(b["block_hash"], []).append(b)

    filtered: dict[str, list[dict[str, Any]]] = {}
    for h, items in groups.items():
        functions = {i["qualname"] for i in items}
        if len(functions) >= min_functions:
            filtered[h] = items

    return filtered


def to_json(groups: dict) -> str:
    return json.dumps(
        {
            "group_count": len(groups),
            "groups": [
                {"key": k, "count": len(v), "items": v}
                for k, v in sorted(
                    groups.items(), key=lambda kv: len(kv[1]), reverse=True
                )
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: dict) -> str:
    lines: list[str] = []
    for i, (_, v) in enumerate(
        sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    ):
        lines.append(f"\n=== Clone group #{i + 1} (count={len(v)}) ===")
        for item in v:
            lines.append(
                f"- {item['qualname']} "
                f"{item['filepath']}:{item['start_line']}-{item['end_line']} "
                f"loc={item.get('loc', item.get('size'))}"
            )
    return "\n".join(lines).strip() + "\n"
