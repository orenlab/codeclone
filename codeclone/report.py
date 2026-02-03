"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from typing import Any

GroupItem = dict[str, Any]
GroupMap = dict[str, list[GroupItem]]


def build_groups(units: list[GroupItem]) -> GroupMap:
    groups: GroupMap = {}
    for u in units:
        key = f"{u['fingerprint']}|{u['loc_bucket']}"
        groups.setdefault(key, []).append(u)
    return {k: v for k, v in groups.items() if len(v) > 1}


def build_block_groups(blocks: list[GroupItem], min_functions: int = 2) -> GroupMap:
    groups: GroupMap = {}
    for b in blocks:
        groups.setdefault(b["block_hash"], []).append(b)

    filtered: GroupMap = {}
    for h, items in groups.items():
        functions = {i["qualname"] for i in items}
        if len(functions) >= min_functions:
            filtered[h] = items

    return filtered


def to_json(groups: GroupMap) -> str:
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


def to_json_report(func_groups: GroupMap, block_groups: GroupMap) -> str:
    return json.dumps(
        {"functions": func_groups, "blocks": block_groups},
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: GroupMap) -> str:
    lines: list[str] = []
    for i, (_, v) in enumerate(
        sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    ):
        lines.append(f"\n=== Clone group #{i + 1} (count={len(v)}) ===")
        lines.extend(
            [
                f"- {item['qualname']} "
                f"{item['filepath']}:{item['start_line']}-{item['end_line']} "
                f"loc={item.get('loc', item.get('size'))}"
                for item in v
            ]
        )
    return "\n".join(lines).strip() + "\n"
